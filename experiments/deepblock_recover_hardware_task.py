from __future__ import annotations

from datetime import datetime, timezone
import argparse
import json
import os
from pathlib import Path
import time

from dotenv import load_dotenv

from deepblock_submit_first_hardware import HARDWARE_DIR, ROOT, _parse_counts


def recover(task_id: str, timeout_sec: int = 600) -> dict[str, object]:
    evidence_path = HARDWARE_DIR / "live_tasks" / f"{task_id}.json"
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    load_dotenv(ROOT / ".env", override=False)
    token = os.getenv("QUAFU_API_TOKEN", "").strip()
    if not token:
        raise RuntimeError("QUAFU_API_TOKEN is empty")
    from quark import Task
    manager = Task(token)
    deadline = time.monotonic() + timeout_sec
    counts = {}
    raw = None
    status = "unknown"
    while time.monotonic() < deadline:
        raw = manager.result(task_id)
        status, counts = _parse_counts(raw)
        print(f"RECOVER task_id={task_id} status={status} shots={sum(counts.values())}", flush=True)
        if counts or status.lower() in {"failed", "error", "cancelled"}:
            break
        time.sleep(3)
    if not counts:
        raise RuntimeError(f"Task {task_id} has no counts; status={status}")
    completed_at = datetime.now(timezone.utc).isoformat()
    evidence.update(status="COMPLETED", completed_at=completed_at,
                    shots_received=sum(counts.values()), counts=counts, raw_result=raw)
    evidence_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2, default=str),
                             encoding="utf-8")
    result_path = HARDWARE_DIR / "hardware_live_results.jsonl"
    rows = [json.loads(line) for line in result_path.read_text(encoding="utf-8").splitlines()
            if line.strip()]
    if not any(str(row.get("task_id")) == task_id for row in rows):
        rows.append({"instance_id": evidence["instance_id"], "seed": evidence["seed"],
                     "p": evidence["p"], "replicate": evidence.get("replicate", 1),
                     "task_id": task_id, "backend": "Baihua", "shots": sum(counts.values()),
                     "counts": counts, "submitted_at": evidence["submitted_at"],
                     "completed_at": completed_at, "physical_qubits": evidence["physical_qubits"],
                     "physical_qasm_sha256": evidence["physical_qasm_sha256"]})
        result_path.write_text("\n".join(json.dumps(row, ensure_ascii=False, separators=(",", ":"))
                                         for row in rows) + "\n", encoding="utf-8")
    return {"task_id": task_id, "status": "COMPLETED", "shots": sum(counts.values()),
            "unique_states": len(counts)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("task_id")
    parser.add_argument("--timeout-sec", type=int, default=600)
    args = parser.parse_args()
    print(json.dumps(recover(args.task_id, args.timeout_sec), ensure_ascii=False, indent=2))
