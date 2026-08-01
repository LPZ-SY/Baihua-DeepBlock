from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

from experiment_utils import ROOT

SRC_DIR = ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from batch_candidate_quality import (  # noqa: E402
    _load_frozen_protocol_thresholds,
    expand_matrix,
)
from quantum_route_forge.quantum_measurements import canonical_sha256  # noqa: E402


TERMINAL_STATUSES = {"completed", "failed", "not_evaluable"}


def _resolve_git_tag(tag: str) -> str | None:
    if not tag:
        return None
    try:
        completed = subprocess.run(
            ["git", "rev-list", "-n", "1", tag],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = completed.stdout.strip().lower()
    return value if completed.returncode == 0 and re.fullmatch(r"[0-9a-f]{40}", value) else None


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _latest_by_config_hash(rows: list[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = str(row.get("config_hash", ""))
        if key:
            latest[key] = dict(row)
    return latest


def validate_result_store(
    config: Mapping[str, Any],
    experiment_dir: Path,
    *,
    allow_partial: bool = False,
) -> dict[str, Any]:
    specs = expand_matrix(config)
    _load_frozen_protocol_thresholds(config)
    expected = {spec.config_hash: spec for spec in specs}
    rows = _read_jsonl(experiment_dir / "tasks.jsonl")
    latest = _latest_by_config_hash(rows)
    errors: list[str] = []
    warnings: list[str] = []
    task_checks: list[dict[str, Any]] = []
    strict_formal_schema = str(config.get("protocol_version", "")).startswith(
        "formal-matrix"
    )
    execution_tag = str(config.get("execution_git_tag", ""))
    expected_execution_commit = _resolve_git_tag(execution_tag)
    if strict_formal_schema and not expected_execution_commit:
        errors.append(f"execution_git_tag cannot be resolved: {execution_tag!r}")

    duplicates = [key for key, count in Counter(row.get("task_id") for row in rows if row.get("task_id")).items() if count > 1]
    if duplicates:
        errors.append(f"duplicate task_id values: {duplicates}")
    extras = sorted(set(latest) - set(expected))
    if extras:
        errors.append(f"unexpected task keys in result store: {extras}")
    missing = [spec for spec in specs if spec.config_hash not in latest]
    if missing:
        message = f"missing {len(missing)} of {len(specs)} planned tasks"
        (warnings if allow_partial else errors).append(message)

    actual_git_commits: set[str] = set()
    for spec in specs:
        task = latest.get(spec.config_hash)
        if task is None:
            task_checks.append(
                {
                    "execution_index": spec.execution_index,
                    "task_key": spec.task_key,
                    "instance_id": spec.instance_id,
                    "backend_requested": spec.backend,
                    "repeat_index": spec.repeat,
                    "status": "missing",
                    "valid": False,
                }
            )
            continue
        task_errors: list[str] = []
        status = str(task.get("status", "")).lower()
        if status not in TERMINAL_STATUSES:
            task_errors.append(f"non-terminal status {status!r}")
        if task.get("backend_requested") != spec.backend:
            task_errors.append("task backend_requested differs from frozen schedule")
        if task.get("task_key") != spec.task_key:
            task_errors.append("stored task_key differs from recomputed task key")
        if task.get("protocol_config_sha256") != spec.protocol_config_sha256:
            task_errors.append("protocol config hash mismatch")

        evidence_path = experiment_dir / "raw_evidence" / f"{spec.config_hash}.json"
        evidence: dict[str, Any] | None = None
        if not evidence_path.exists():
            task_errors.append("normalized evidence file is missing")
        else:
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))

        if status == "completed" and evidence is not None:
            if task.get("source") != "hardware" or evidence.get("source") != "hardware":
                task_errors.append("completed formal task source is not hardware")
            backend_actual = evidence.get("backend_actual", evidence.get("backend"))
            if backend_actual != spec.backend or task.get("backend_actual") != spec.backend:
                task_errors.append("backend_requested does not equal backend_actual")
            counts = evidence.get("counts")
            if not isinstance(counts, dict) or not counts:
                task_errors.append("counts are missing or empty")
            else:
                invalid_keys = [
                    key
                    for key in counts
                    if not isinstance(key, str)
                    or len(key) != spec.customers
                    or set(key) - {"0", "1"}
                ]
                if invalid_keys:
                    task_errors.append("counts contain invalid bitstrings")
                shots_received = evidence.get("shots_received")
                if sum(counts.values()) != shots_received or shots_received != spec.shots:
                    task_errors.append("counts sum / shots_received / frozen shots mismatch")
            if evidence.get("circuit_hash") != spec.logical_qasm_sha256:
                task_errors.append("logical QASM hash mismatch")
            if evidence.get("threshold_file_sha256") != spec.threshold_sha256:
                task_errors.append("threshold file hash mismatch")
            if tuple(evidence.get("selected_customer_ids", [])) != tuple(
                spec.selected_customer_ids_in_qubit_order
            ):
                task_errors.append("selected customer order mismatch")
            if evidence.get("bit_order") != config.get("bit_order"):
                task_errors.append("bit order mismatch")
            git_commit_actual = str(evidence.get("git_commit_actual") or "")
            if not re.fullmatch(r"[0-9a-f]{40}", git_commit_actual):
                task_errors.append("actual git commit is missing or invalid")
            else:
                actual_git_commits.add(git_commit_actual)
                if expected_execution_commit and git_commit_actual != expected_execution_commit:
                    task_errors.append("actual git commit does not match execution_git_tag")
            raw_response_path = experiment_dir / "tasks" / str(task.get("task_id")) / "raw_response.json"
            if evidence.get("raw_response") is None and not raw_response_path.exists():
                task_errors.append("raw platform response is missing")
            if strict_formal_schema:
                if evidence.get("run_id") != config.get("experiment_id"):
                    task_errors.append("run_id mismatch")
                if evidence.get("instance_id") != spec.instance_id:
                    task_errors.append("evidence instance_id mismatch")
                if evidence.get("task_key") != spec.task_key:
                    task_errors.append("evidence task_key mismatch")
                if str(evidence.get("task_id")) != str(task.get("task_id")):
                    task_errors.append("evidence task_id mismatch")
                if evidence.get("raw_counts") != evidence.get("counts"):
                    task_errors.append("raw_counts and normalized counts differ")
                if evidence.get("unique_bitstrings") != len(evidence.get("counts", {})):
                    task_errors.append("unique_bitstrings mismatch")
                for field in (
                    "submitted_at",
                    "completed_at",
                    "threshold_method",
                    "dependency_snapshot",
                    "compile_options",
                    "hardware_metadata",
                    "backend_queue_snapshot_before_submit",
                    "poll_count",
                ):
                    if field not in evidence:
                        task_errors.append(f"required evidence field is missing: {field}")
                if not isinstance(evidence.get("random_reference"), dict):
                    task_errors.append("random_reference is missing")
                if not isinstance(evidence.get("classical_reference"), dict):
                    task_errors.append("classical_reference is missing")
                if evidence.get("qubit_count") != spec.customers:
                    task_errors.append("qubit_count mismatch")
                task_dir = experiment_dir / "tasks" / str(task.get("task_id"))
                required_task_artifacts = {
                    "evidence.json",
                    "raw_response.json",
                    "counts.json",
                    "summary.json",
                    "logical_qasm.qasm",
                    "candidate_metrics.csv",
                }
                missing_task_artifacts = sorted(
                    name for name in required_task_artifacts if not (task_dir / name).exists()
                )
                if missing_task_artifacts:
                    task_errors.append(
                        f"task-addressable artifacts are missing: {missing_task_artifacts}"
                    )

        if status in {"failed", "not_evaluable"} and not task.get("error") and evidence is None:
            task_errors.append("non-evaluable task lacks both error detail and evidence")
        if task_errors:
            errors.extend(f"task {spec.execution_index}: {message}" for message in task_errors)
        task_checks.append(
            {
                "execution_index": spec.execution_index,
                "task_key": spec.task_key,
                "task_id": task.get("task_id"),
                "instance_id": spec.instance_id,
                "backend_requested": spec.backend,
                "backend_actual": task.get("backend_actual"),
                "repeat_index": spec.repeat,
                "status": status,
                "source": task.get("source"),
                "valid": not task_errors,
                "errors": task_errors,
            }
        )

    if len(actual_git_commits) > 1:
        allowed = set(str(value) for value in config.get("allowed_actual_git_commits", []))
        if not actual_git_commits.issubset(allowed):
            errors.append(
                "multiple actual git commits are mixed without an allowed_actual_git_commits declaration"
            )
    required_files = [
        "config.json",
        "manifest.json",
        "frozen_thresholds.json",
        "tasks.jsonl",
        "candidates.jsonl",
        "instance_summary.csv",
        "aggregate_summary.json",
    ]
    if strict_formal_schema:
        required_files.extend(
            ["protocol_snapshot.json", "baseline_manifest.json", "task_manifest.csv"]
        )
    missing_files = [name for name in required_files if not (experiment_dir / name).exists()]
    if missing_files:
        errors.append(f"missing required result-store files: {missing_files}")

    complete = len(latest) == len(specs) and all(
        str(latest[spec.config_hash].get("status", "")).lower() in TERMINAL_STATUSES
        for spec in specs
        if spec.config_hash in latest
    )
    return {
        "schema_version": 1,
        "experiment_id": config.get("experiment_id"),
        "protocol_version": config.get("protocol_version"),
        "config_sha256": canonical_sha256(config),
        "experiment_dir": str(experiment_dir),
        "planned_task_count": len(specs),
        "observed_task_count": len(latest),
        "complete": complete,
        "valid": not errors and (complete or allow_partial),
        "allow_partial": allow_partial,
        "status_counts": dict(Counter(str(row.get("status", "")).lower() for row in latest.values())),
        "actual_git_commits": sorted(actual_git_commits),
        "errors": errors,
        "warnings": warnings,
        "tasks": task_checks,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate a formal QRF result store")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--experiment-dir", type=Path, required=True)
    parser.add_argument("--allow-partial", action="store_true")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    config = json.loads(args.config.read_text(encoding="utf-8"))
    report = validate_result_store(
        config,
        args.experiment_dir,
        allow_partial=args.allow_partial,
    )
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")
    if not report["valid"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
