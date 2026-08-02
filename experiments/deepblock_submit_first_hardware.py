from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from typing import Mapping

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from dotenv import load_dotenv

from quantum_route_forge.deepblock.adapters import select_baihua_subgraph
from quantum_route_forge.deepblock.proxy_qubo import ProxyInteraction, SparseProxyQUBO
from quantum_route_forge.deepblock.qaoa_runner import (
    QAOAParameters,
    build_qaoa_qasm,
    compilation_audit,
    transpile_for_baihua,
)


HARDWARE_DIR = ROOT / "results" / "deepblock_final_study" / "hardware_gap"


def _proxy(payload: Mapping[str, object]) -> SparseProxyQUBO:
    return SparseProxyQUBO(
        customer_ids=tuple(int(value) for value in payload["customer_ids"]),  # type: ignore[arg-type]
        vehicle_pair=tuple(int(value) for value in payload["vehicle_pair"]),  # type: ignore[arg-type]
        linear=tuple(float(value) for value in payload["linear"]),  # type: ignore[arg-type]
        quadratic=tuple(ProxyInteraction(**row) for row in payload["quadratic"]),  # type: ignore[arg-type]
        constant=float(payload["constant"]),
        current_bitstring=str(payload["current_bitstring"]),
        scale=float(payload["scale"]),
    )


def _parameters(payload: Mapping[str, object]) -> QAOAParameters:
    return QAOAParameters(
        depth=int(payload["depth"]),
        gamma=tuple(float(value) for value in payload["gamma"]),  # type: ignore[arg-type]
        beta=tuple(float(value) for value in payload["beta"]),  # type: ignore[arg-type]
        optimizer=str(payload["optimizer"]),
        initial_value=float(payload["initial_value"]),
        final_value=float(payload["final_value"]),
        evaluations=int(payload["evaluations"]),
    )


def _parse_counts(raw_result: object) -> tuple[str, dict[str, int]]:
    status = "unknown"
    counts: dict[str, int] = {}
    if not isinstance(raw_result, Mapping):
        return status, counts
    status = str(raw_result.get("status") or "unknown")
    raw_counts = raw_result.get("corrected") or raw_result.get("count") or raw_result.get("counts") or {}
    if not isinstance(raw_counts, Mapping):
        return status, counts
    for key, raw_value in raw_counts.items():
        bitstring = str(key).replace(" ", "")
        if not bitstring or set(bitstring) - {"0", "1"}:
            continue
        try:
            value = int(raw_value)
        except (TypeError, ValueError):
            continue
        if value > 0:
            counts[bitstring] = value
    return status, counts


def submit_one(
    *,
    confirm: bool,
    instance_id: str,
    depth: int,
    timeout_sec: int = 600,
    allow_repeat: bool = False,
) -> dict[str, object]:
    if not confirm:
        raise PermissionError("Use --confirm-submit to authorize exactly one hardware task.")
    load_dotenv(ROOT / ".env", override=False)
    token = os.getenv("QUAFU_API_TOKEN", "").strip()
    if not token:
        raise RuntimeError("QUAFU_API_TOKEN is empty")

    from quark import Task
    from quark.circuit import Backend

    manifest_path = HARDWARE_DIR / "hardware_submission_manifest.jsonl"
    rows = [json.loads(line) for line in manifest_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    entry = next(
        row
        for row in rows
        if str(row["instance_id"]) == str(instance_id) and int(row["p"]) == int(depth)
    )
    result_path = HARDWARE_DIR / "hardware_live_results.jsonl"
    completed: list[dict[str, object]] = []
    if result_path.exists():
        completed = [
            json.loads(line)
            for line in result_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        matching = [
            row for row in completed
            if str(row.get("instance_id")) == str(instance_id)
            and int(row.get("p", -1)) == int(depth)
        ]
        if matching and not allow_repeat:
            raise RuntimeError(
                f"Hardware result already exists for {instance_id} p={depth}; "
                "refusing duplicate submission."
            )
    else:
        matching = []
    replicate = 1 + len(matching)
    proxy = _proxy(entry["qubo"])
    parameters = _parameters(entry["qaoa_parameters"])
    chip_info = dict(Backend("Baihua").chip_info)
    topology = select_baihua_subgraph(chip_info, width=proxy.width)
    logical_qasm = build_qaoa_qasm(proxy, parameters.depth, parameters.gamma, parameters.beta)
    physical_qasm, raw_audit = transpile_for_baihua(
        logical_qasm,
        backend_name="Baihua",
        target_qubits=list(topology.qubits),
    )
    audit = compilation_audit(
        physical_qasm,
        swap_count=raw_audit.swap_count,
        mapping_verified=raw_audit.mapping_verified,
        uncalibrated_couplings=topology.uncalibrated_couplings,
        max_cnot=96,
        max_depth=240,
    )
    if not audit.passed:
        raise RuntimeError("Compilation audit failed: " + "; ".join(audit.reasons))

    manager = Task(token)
    task_payload = {
        "chip": "Baihua",
        "name": f"QRF_Final_{entry['instance_id']}_p{depth}_r{replicate}",
        "circuit": physical_qasm,
        "shots": 1024,
        "compile": False,
        "options": {
            "compiler": None,
            "correct": False,
            "open_dd": None,
            "target_qubits": [],
        },
    }
    submitted_at = datetime.now(timezone.utc).isoformat()
    task_id = str(manager.run(task_payload, repeat=1))
    print(
        f"SUBMITTED task_id={task_id} instance_id={entry['instance_id']} "
        f"p={depth} replicate={replicate} repeat=1 expected_shots=1024",
        flush=True,
    )

    live_dir = HARDWARE_DIR / "live_tasks"
    live_dir.mkdir(parents=True, exist_ok=True)
    evidence_path = live_dir / f"{task_id}.json"
    evidence: dict[str, object] = {
        "schema": "qrf.deepblock.baihua.live.v1",
        "instance_id": entry["instance_id"],
        "seed": entry["seed"],
        "p": int(depth),
        "replicate": replicate,
        "task_id": task_id,
        "backend": "Baihua",
        "submitted_at": submitted_at,
        "completed_at": None,
        "status": "SUBMITTED",
        "shots_requested": 1024,
        "shots_received": 0,
        "counts": {},
        "physical_qubits": list(topology.qubits),
        "logical_edges": [list(edge) for edge in topology.logical_edges],
        "compilation": audit.payload(),
        "logical_qasm_sha256": hashlib.sha256(logical_qasm.encode("utf-8")).hexdigest(),
        "physical_qasm_sha256": hashlib.sha256(physical_qasm.encode("utf-8")).hexdigest(),
        "logical_qasm": logical_qasm,
        "physical_qasm": physical_qasm,
        "frozen_manifest": entry,
        "raw_result": None,
    }
    evidence_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")

    deadline = time.monotonic() + max(1, int(timeout_sec))
    last_status = ""
    counts: dict[str, int] = {}
    raw_result: object = None
    while time.monotonic() < deadline:
        raw_result = manager.result(task_id)
        status, counts = _parse_counts(raw_result)
        if status != last_status:
            print(
                f"POLL task_id={task_id} status={status} shots_received={sum(counts.values())}",
                flush=True,
            )
            last_status = status
        terminal = status.strip().lower() in {
            "finished", "completed", "done", "success", "failed", "error", "cancelled"
        }
        if counts or terminal:
            break
        time.sleep(3)

    completed_at = datetime.now(timezone.utc).isoformat()
    final_status = "COMPLETED" if counts else ("TIMEOUT" if time.monotonic() >= deadline else last_status.upper())
    evidence.update(
        {
            "completed_at": completed_at,
            "status": final_status,
            "shots_received": sum(counts.values()),
            "counts": counts,
            "raw_result": raw_result,
        }
    )
    evidence_path.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    if counts:
        existing = []
        if result_path.exists():
            existing = [
                json.loads(line)
                for line in result_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        existing = [row for row in existing if str(row.get("task_id")) != task_id]
        existing.append(
            {
                "instance_id": entry["instance_id"],
                "seed": entry["seed"],
                "p": int(depth),
                "replicate": replicate,
                "task_id": task_id,
                "backend": "Baihua",
                "shots": sum(counts.values()),
                "counts": counts,
                "submitted_at": submitted_at,
                "completed_at": completed_at,
                "physical_qubits": list(topology.qubits),
                "physical_qasm_sha256": evidence["physical_qasm_sha256"],
            }
        )
        result_path.write_text(
            "\n".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) for row in existing) + "\n",
            encoding="utf-8",
        )

    return {
        "task_id": task_id,
        "instance_id": entry["instance_id"],
        "p": int(depth),
        "replicate": replicate,
        "status": final_status,
        "shots_received": sum(counts.values()),
        "unique_states": len(counts),
        "evidence_path": str(evidence_path),
        "submission_count_this_run": 1,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Submit exactly one frozen Baihua DeepBlock task")
    parser.add_argument("--confirm-submit", action="store_true")
    parser.add_argument("--instance-id", default="seed002_pair1_B2_w8")
    parser.add_argument("--p", type=int, choices=(1, 2, 3), default=1)
    parser.add_argument("--timeout-sec", type=int, default=600)
    parser.add_argument("--allow-repeat", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            submit_one(
                confirm=args.confirm_submit,
                instance_id=args.instance_id,
                depth=args.p,
                timeout_sec=args.timeout_sec,
                allow_repeat=args.allow_repeat,
            ),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
