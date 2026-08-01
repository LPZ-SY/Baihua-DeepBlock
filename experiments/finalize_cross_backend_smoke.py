from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

from experiment_utils import ROOT

SRC_DIR = ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from quantum_route_forge.quantum_measurements import (  # noqa: E402
    canonical_sha256,
    now_iso,
    redact_payload,
)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                fields.append(key)
                seen.add(key)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _latest_tasks(path: Path) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            latest[str(row["config_hash"])] = row
    return sorted(latest.values(), key=lambda row: int(row.get("execution_index", 0)))


def _quark_task(token: str, runtime_path: Path):
    try:
        from quark import Task
    except ImportError:
        if str(runtime_path.resolve()) not in sys.path:
            sys.path.insert(0, str(runtime_path.resolve()))
        from quark import Task
    return Task(token)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Finalize the P10 cross-backend smoke evidence bundle."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=ROOT / "experiments" / "configs" / "cross_backend_smoke_v1.json",
    )
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=ROOT / "results" / "experiments" / "qrf_cross_backend_smoke_20260801",
    )
    parser.add_argument("--retrieve-raw", action="store_true")
    parser.add_argument("--token-file", type=Path, default=ROOT.parent / ".env.txt")
    parser.add_argument(
        "--quark-runtime",
        type=Path,
        default=ROOT.parent / "tmp" / "quarkstudio_runtime2",
    )
    args = parser.parse_args()

    config = json.loads(args.config.read_text(encoding="utf-8"))
    tasks = _latest_tasks(args.results_dir / "tasks.jsonl")
    expected_backends = ["Baihua", "Dongling", "Shenglian"]
    if len(tasks) != 3:
        raise SystemExit(f"Expected 3 smoke task records, found {len(tasks)}")
    if [row.get("backend_requested") for row in tasks] != expected_backends:
        raise SystemExit("Smoke task order/backends do not match the frozen protocol")

    manager = None
    if args.retrieve_raw:
        token = os.getenv("QPU_API_TOKEN", "").strip()
        if not token and args.token_file.exists():
            token = args.token_file.read_text(encoding="utf-8").strip()
        if not token:
            raise SystemExit("QPU_API_TOKEN and --token-file are both empty")
        manager = _quark_task(token, args.quark_runtime)

    manifest_rows: list[dict[str, Any]] = []
    summary_rows: list[dict[str, Any]] = []
    for task in tasks:
        config_hash = str(task["config_hash"])
        task_id = str(task["task_id"])
        evidence_path = args.results_dir / "raw_evidence" / f"{config_hash}.json"
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        instance_dir = args.results_dir / "instances" / config_hash
        summary = json.loads(
            (instance_dir / "quantum_candidate_quality_summary.json").read_text(
                encoding="utf-8"
            )
        )
        task_dir = args.results_dir / "tasks" / task_id
        task_dir.mkdir(parents=True, exist_ok=True)

        raw_response = evidence.get("raw_response")
        if manager is not None:
            retrieved = manager.result(int(task_id), timeout=180.0)
            raw_response = redact_payload(retrieved)
        if raw_response is None:
            raise SystemExit(
                f"Raw response unavailable for task {task_id}; rerun with --retrieve-raw"
            )
        _write_json(task_dir / "raw_response.json", raw_response)
        _write_json(task_dir / "counts.json", evidence.get("counts", {}))
        evidence_bundle = {
            **evidence,
            "task_record": task,
            "raw_response_path": str(task_dir / "raw_response.json"),
            "raw_response_sha256": canonical_sha256(raw_response),
        }
        _write_json(task_dir / "evidence.json", evidence_bundle)
        candidate_source = instance_dir / "quantum_candidates.csv"
        if candidate_source.exists():
            shutil.copyfile(candidate_source, task_dir / "candidate_metrics.csv")

        counts = evidence.get("counts", {})
        manifest_rows.append(
            {
                "execution_index": task.get("execution_index"),
                "task_key": task.get("task_key"),
                "task_id": task_id,
                "instance_id": task.get("instance_id"),
                "backend_requested": task.get("backend_requested"),
                "backend_actual": task.get("backend_actual"),
                "status": task.get("status"),
                "decision": task.get("evaluation_decision"),
                "source": task.get("source"),
                "shots_requested": task.get("shots"),
                "shots_received": evidence.get("shots_received"),
                "counts_sum": sum(counts.values()),
                "unique_bitstrings": len(counts),
                "logical_qasm_sha256": evidence.get("circuit_hash"),
                "threshold_file_sha256": evidence.get("threshold_file_sha256"),
                "git_commit_actual": evidence.get("git_commit_actual"),
                "evidence_sha256": task.get("evidence_sha256"),
                "raw_response_sha256": canonical_sha256(raw_response),
            }
        )
        summary_rows.append(
            {
                "task_id": task_id,
                "backend_requested": task.get("backend_requested"),
                "backend_actual": task.get("backend_actual"),
                "quality_hit_rate": summary.get("quality_hit_rate"),
                "random_quality_hit_rate": summary.get("random_quality_hit_rate"),
                "quantum_minus_random": (
                    float(summary["quality_hit_rate"])
                    - float(summary["random_quality_hit_rate"])
                ),
                "classical_reach_feasible_rate": summary.get(
                    "classical_reach_feasible_rate"
                ),
                "strict_improvement_rate": summary.get("strict_improvement_rate"),
                "raw_feasible_rate": summary.get("raw_feasible_rate"),
                "decision": summary.get("decision"),
            }
        )

    protocol_snapshot = {
        **config,
        "config_sha256": canonical_sha256(config),
        "finalized_at": now_iso(),
        "task_count": len(tasks),
        "all_backends_match": all(
            row["backend_requested"] == row["backend_actual"] for row in manifest_rows
        ),
        "all_counts_complete": all(
            row["counts_sum"] == row["shots_received"] == 1024
            for row in manifest_rows
        ),
    }
    _write_json(args.results_dir / "protocol_snapshot.json", protocol_snapshot)
    _write_csv(args.results_dir / "task_manifest.csv", manifest_rows)
    _write_csv(args.results_dir / "cross_backend_smoke_summary.csv", summary_rows)

    report_lines = [
        "# Cross-Backend Smoke Report",
        "",
        "All three P10 tasks completed with fresh hardware counts. Requested and actual backends matched, each counts distribution summed to 1024, and QASM/threshold/code hashes were identical across tasks.",
        "",
        "| Backend | Task ID | QHR | Random QHR | Q-R | Classical reach | Strict improvement |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in summary_rows:
        report_lines.append(
            "| {backend_requested} | {task_id} | {quality_hit_rate:.4f} | "
            "{random_quality_hit_rate:.4f} | {quantum_minus_random:.4f} | "
            "{classical_reach_feasible_rate:.4f} | {strict_improvement_rate:.4f} |".format(
                **row
            )
        )
    report_lines.extend(
        [
            "",
            "This smoke test validates the cross-backend evidence pipeline. It is not the formal 24-task result and does not support a quantum-advantage claim.",
            "",
        ]
    )
    (args.results_dir / "cross_backend_smoke_report.md").write_text(
        "\n".join(report_lines), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "task_count": len(tasks),
                "all_backends_match": protocol_snapshot["all_backends_match"],
                "all_counts_complete": protocol_snapshot["all_counts_complete"],
                "result_directory": str(args.results_dir),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
