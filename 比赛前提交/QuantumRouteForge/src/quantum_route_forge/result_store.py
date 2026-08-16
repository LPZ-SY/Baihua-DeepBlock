from __future__ import annotations

import csv
import io
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

from .quantum_measurements import canonical_sha256, redact_payload


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="") as stream:
            stream.write(text)
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def _immutable_text(path: Path, text: str) -> None:
    if path.exists():
        if path.read_bytes() != text.encode("utf-8"):
            raise ValueError(f"immutable artifact conflict: {path}")
        return
    _atomic_text(path, text)


class ResultStore:
    """Idempotent, auditable storage for one experiment id."""

    def __init__(self, root: Path | str, experiment_id: str):
        clean_id = str(experiment_id).strip()
        if not clean_id or any(char in clean_id for char in "\\/:"):
            raise ValueError("experiment_id must be a non-empty path-safe name")
        self.root = Path(root)
        self.experiment_id = clean_id
        self.path = self.root / clean_id
        self.raw_evidence_dir = self.path / "raw_evidence"
        self.tasks_dir = self.path / "tasks"
        self.figures_dir = self.path / "figures"
        self.logs_dir = self.path / "logs"
        for directory in (
            self.path,
            self.raw_evidence_dir,
            self.tasks_dir,
            self.figures_dir,
            self.logs_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)

    @property
    def config_path(self) -> Path:
        return self.path / "config.json"

    @property
    def tasks_path(self) -> Path:
        return self.path / "tasks.jsonl"

    @property
    def candidates_path(self) -> Path:
        return self.path / "candidates.jsonl"

    def initialize_config(self, config: Mapping[str, Any]) -> str:
        payload = dict(config)
        config_hash = canonical_sha256(payload)
        if self.config_path.exists():
            existing = json.loads(self.config_path.read_text(encoding="utf-8"))
            if canonical_sha256(existing) != config_hash:
                raise ValueError(
                    f"immutable config conflict for experiment_id={self.experiment_id}"
                )
        else:
            _atomic_text(
                self.config_path,
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            )
        return config_hash

    def write_manifest(self, manifest: Mapping[str, Any]) -> Path:
        payload = {
            "schema_version": 2,
            "experiment_id": self.experiment_id,
            "updated_at": _now_iso(),
            **dict(manifest),
        }
        path = self.path / "manifest.json"
        _atomic_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        return path

    def write_protocol_snapshot(self, payload: Mapping[str, Any]) -> Path:
        path = self.path / "protocol_snapshot.json"
        text = json.dumps(dict(payload), ensure_ascii=False, indent=2) + "\n"
        _immutable_text(path, text)
        return path

    def write_baseline_manifest(self, payload: Mapping[str, Any]) -> Path:
        path = self.path / "baseline_manifest.json"
        text = json.dumps(dict(payload), ensure_ascii=False, indent=2) + "\n"
        _immutable_text(path, text)
        return path

    def write_task_manifest(self, rows: Iterable[Mapping[str, Any]]) -> Path:
        path = self.path / "task_manifest.csv"
        records = [dict(row) for row in rows]
        fields = [
            "execution_index",
            "task_key",
            "task_id",
            "instance_id",
            "backend_requested",
            "backend_actual",
            "repeat_index",
            "status",
            "source",
            "shots",
            "shots_received",
            "evaluation_decision",
            "recorded_at",
            "error",
        ]
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)
        _atomic_text(path, stream.getvalue())
        return path

    def save_task_artifacts(
        self,
        task_id: str,
        *,
        evidence: Mapping[str, Any],
        candidates: Iterable[Mapping[str, Any]],
        summary: Mapping[str, Any],
    ) -> Path:
        clean_task_id = str(task_id).strip()
        if not re.fullmatch(r"[A-Za-z0-9._-]+", clean_task_id):
            raise ValueError("task_id must be a non-empty path-safe identifier")
        task_dir = self.tasks_dir / clean_task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        clean_evidence = redact_payload(dict(evidence))
        artifacts: dict[str, Any] = {
            "evidence.json": clean_evidence,
            "raw_response.json": clean_evidence.get("raw_response"),
            "counts.json": clean_evidence.get("counts", {}),
            "summary.json": redact_payload(dict(summary)),
        }
        for name, payload in artifacts.items():
            _immutable_text(
                task_dir / name,
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            )
        circuit = str(clean_evidence.get("circuit") or "")
        if circuit:
            _immutable_text(task_dir / "logical_qasm.qasm", circuit)
        candidate_rows = [dict(row) for row in candidates]
        candidate_stream = io.StringIO(newline="")
        if candidate_rows:
            fields: list[str] = []
            seen: set[str] = set()
            for row in candidate_rows:
                for field in row:
                    if field not in seen:
                        fields.append(field)
                        seen.add(field)
            writer = csv.DictWriter(candidate_stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(candidate_rows)
        _immutable_text(task_dir / "candidate_metrics.csv", candidate_stream.getvalue())
        return task_dir

    @staticmethod
    def _read_jsonl(path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        rows: list[dict[str, Any]] = []
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"corrupt JSONL at {path}:{line_no}") from exc
            if not isinstance(value, dict):
                raise ValueError(f"non-object JSONL row at {path}:{line_no}")
            rows.append(value)
        return rows

    def tasks(self) -> list[dict[str, Any]]:
        return self._read_jsonl(self.tasks_path)

    def latest_tasks_by_hash(self) -> dict[str, dict[str, Any]]:
        latest: dict[str, dict[str, Any]] = {}
        for row in self.tasks():
            task_hash = str(row.get("config_hash", ""))
            if task_hash:
                latest[task_hash] = row
        return latest

    def append_task(self, row: Mapping[str, Any], *, allow_status_update: bool = True) -> bool:
        payload = {**dict(row), "recorded_at": dict(row).get("recorded_at", _now_iso())}
        task_hash = str(payload.get("config_hash", ""))
        if not task_hash:
            raise ValueError("task row requires config_hash")
        latest = self.latest_tasks_by_hash().get(task_hash)
        if latest is not None:
            same_status = latest.get("status") == payload.get("status")
            same_evidence = latest.get("evidence_sha256") == payload.get("evidence_sha256")
            if same_status and same_evidence:
                return False
            if not allow_status_update:
                return False
            payload["attempt"] = int(latest.get("attempt", 1)) + 1
        else:
            payload.setdefault("attempt", 1)
        with self.tasks_path.open("a", encoding="utf-8", newline="") as stream:
            stream.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
        return True

    def append_candidates(self, rows: Iterable[Mapping[str, Any]]) -> int:
        existing_keys = {
            (
                str(row.get("config_hash", "")),
                str(row.get("source", "")),
                str(row.get("bitstring", "")),
            )
            for row in self._read_jsonl(self.candidates_path)
        }
        added = 0
        with self.candidates_path.open("a", encoding="utf-8", newline="") as stream:
            for raw in rows:
                row = dict(raw)
                key = (
                    str(row.get("config_hash", "")),
                    str(row.get("source", "")),
                    str(row.get("bitstring", "")),
                )
                if not all(key) or key in existing_keys:
                    continue
                stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
                existing_keys.add(key)
                added += 1
        return added

    def save_evidence(self, config_hash: str, payload: Any) -> tuple[Path, str]:
        clean = redact_payload(payload)
        evidence_hash = canonical_sha256(clean)
        path = self.raw_evidence_dir / f"{config_hash}.json"
        if path.exists():
            existing = json.loads(path.read_text(encoding="utf-8"))
            if canonical_sha256(existing) != evidence_hash:
                raise ValueError(f"evidence conflict for config_hash={config_hash}")
        else:
            _atomic_text(path, json.dumps(clean, ensure_ascii=False, indent=2) + "\n")
        return path, evidence_hash

    def write_thresholds(self, payload: Mapping[str, Any]) -> Path:
        path = self.path / "frozen_thresholds.json"
        if path.exists():
            existing = json.loads(path.read_text(encoding="utf-8"))
            if canonical_sha256(existing) != canonical_sha256(payload):
                raise ValueError("frozen thresholds are immutable once written")
        else:
            _atomic_text(path, json.dumps(dict(payload), ensure_ascii=False, indent=2) + "\n")
        return path

    def write_instance_summary(self, rows: list[Mapping[str, Any]]) -> Path:
        path = self.path / "instance_summary.csv"
        if not rows:
            _atomic_text(path, "")
            return path
        fieldnames: list[str] = []
        seen: set[str] = set()
        for row in rows:
            for key in row:
                if key not in seen:
                    fieldnames.append(key)
                    seen.add(key)
        handle, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(handle, "w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(dict(row) for row in rows)
            os.replace(temp_name, path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
        return path

    def write_aggregate_summary(self, payload: Mapping[str, Any]) -> Path:
        path = self.path / "aggregate_summary.json"
        _atomic_text(path, json.dumps(dict(payload), ensure_ascii=False, indent=2) + "\n")
        return path

    def integrity_report(self) -> dict[str, Any]:
        required = [
            "config.json",
            "manifest.json",
            "frozen_thresholds.json",
            "tasks.jsonl",
            "candidates.jsonl",
            "instance_summary.csv",
            "aggregate_summary.json",
        ]
        present = {name: (self.path / name).exists() for name in required}
        return {
            "experiment_id": self.experiment_id,
            "path": str(self.path),
            "required_files": present,
            "complete": all(present.values()),
            "task_records": len(self.tasks()),
            "candidate_records": len(self._read_jsonl(self.candidates_path)),
            "evidence_files": len(list(self.raw_evidence_dir.glob("*.json"))),
        }


def list_experiments(root: Path | str) -> list[dict[str, Any]]:
    base = Path(root)
    if not base.exists():
        return []
    experiments = []
    for path in sorted(item for item in base.iterdir() if item.is_dir()):
        try:
            experiments.append(ResultStore(base, path.name).integrity_report())
        except (OSError, ValueError):
            continue
    return experiments
