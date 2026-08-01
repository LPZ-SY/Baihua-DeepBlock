from __future__ import annotations

import argparse
import csv
import importlib.metadata
import json
import math
import os
import platform
import random
import subprocess
import sys
from pathlib import Path
from typing import Any

from experiment_utils import (
    ROOT,
    build_bqm_for_instance,
    evaluate_sample,
    infer_capacity_from_seed,
)

SRC_DIR = ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from quantum_route_forge import generate_dispatch_instance  # noqa: E402
from quantum_route_forge.candidate_quality import (  # noqa: E402
    DEFAULT_ENERGY_TOLERANCE,
    complete_min_energy_sample,
    evaluate_measurement,
    exact_assignment_reference,
    fixed_assignment_from_bitstring,
    freeze_thresholds,
    raw_feasibility,
)
from quantum_route_forge.geometry import euclidean  # noqa: E402
from quantum_route_forge.quantum_measurements import (  # noqa: E402
    BIT_ORDER_OPENQASM,
    canonical_sha256,
    measurement_from_evidence,
    measurement_from_payload,
    now_iso,
    redact_payload,
)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        if rows:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)


def _current_git_commit() -> str | None:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = completed.stdout.strip().lower()
    return value if completed.returncode == 0 and len(value) == 40 else None


def _dependency_snapshot() -> dict[str, Any]:
    packages: dict[str, str | None] = {}
    for name in ("dimod", "numpy", "quarkstudio", "pyquafu"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    return {
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "packages": packages,
    }


def _find_metadata_value(payload: Any, names: set[str]) -> Any:
    pending = [payload]
    visited: set[int] = set()
    while pending:
        current = pending.pop(0)
        marker = id(current)
        if marker in visited:
            continue
        visited.add(marker)
        if isinstance(current, dict):
            for key, value in current.items():
                if str(key).lower() in names:
                    return value
                if isinstance(value, (dict, list, tuple)):
                    pending.append(value)
        elif isinstance(current, (list, tuple)):
            pending.extend(current)
    return None


def _selected_customers(customers: list, max_qubits: int) -> list:
    ranked = sorted(customers, key=lambda customer: (-customer.demand, customer.customer_id))
    return ranked[: max(2, min(max_qubits, len(ranked)))]


def _business_qasm(selected: list) -> str:
    """Mirror the project's frozen QAOA-style proximity seed circuit."""
    n = len(selected)
    distances = [
        euclidean(selected[i].point, selected[j].point)
        for i in range(n)
        for j in range(i + 1, n)
    ]
    max_distance = max(distances) if distances else 1.0
    gamma = 1.1
    beta = 0.8
    lines = [
        "OPENQASM 2.0;",
        'include "qelib1.inc";',
        f"qreg q[{n}];",
        f"creg meas[{n}];",
    ]
    lines.extend(f"h q[{index}];" for index in range(n))
    for i in range(n):
        for j in range(i + 1, n):
            distance = euclidean(selected[i].point, selected[j].point)
            proximity = 1.0 - min(1.0, distance / max_distance)
            weight = 0.25 + 0.75 * proximity
            lines.append(f"rzz({gamma * weight:.17g}) q[{i}],q[{j}];")
    lines.extend(f"rx({beta:.17g}) q[{index}];" for index in range(n))
    lines.extend(f"measure q[{index}] -> meas[{index}];" for index in range(n))
    return "\n".join(lines) + "\n"


def _choose_backend(status: Any, requested: str) -> tuple[str, dict[str, Any]]:
    candidates = ["Dongling", "Baihua", "Shenglian"]
    snapshot = {name: status.get(name) for name in candidates} if isinstance(status, dict) else {}
    if requested.lower() != "auto":
        if requested not in candidates:
            raise ValueError(f"backend must be auto or one of {candidates}")
        return requested, snapshot
    online = []
    for preference, name in enumerate(candidates):
        queue = snapshot.get(name)
        if isinstance(queue, (int, float)) and math.isfinite(float(queue)):
            online.append((float(queue), preference, name))
    if not online:
        raise RuntimeError(f"No candidate backend is available: {snapshot}")
    return min(online)[2], snapshot


def _pipeline_row(
    instance_id: str,
    mode: str,
    source: str,
    evaluation: dict[str, Any],
    *,
    task_id: str = "",
    backend: str = "",
    bitstring: str = "",
) -> dict[str, Any]:
    return {
        "instance_id": instance_id,
        "mode": mode,
        "candidate_source": source,
        "task_id": task_id if mode == "quantum" else "",
        "backend": backend if mode == "quantum" else "",
        "bitstring": bitstring,
        "bqm_energy": float(evaluation["assignment_energy"]),
        "raw_assignment_feasible": bool(evaluation["assignment_feasible"]),
        "onehot_violation_count": int(evaluation["onehot_violation_count"]),
        "capacity_violation_count_before_repair": int(
            evaluation["capacity_violation_count_before_repair"]
        ),
        "capacity_violation_count_after_repair": int(evaluation["capacity_violation_count"]),
        "repair_applied": bool(evaluation["repaired"]),
        "repair_summary": evaluation["repair_summary"],
        "route_distance_before_2opt": float(evaluation["route_distance_before_2opt"]),
        "route_distance_after_2opt": float(evaluation["route_distance_after_2opt"]),
        "improvement_after_2opt": float(evaluation["improvement_after_2opt"]),
        "route_feasible": bool(evaluation["route_feasible"]),
        "decoded_assignment": json.dumps(
            evaluation["decoded_assignment"], ensure_ascii=False, sort_keys=True
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="QuarkStudio quantum-candidate quality experiment")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--customers", type=int, default=4)
    parser.add_argument("--vehicles", type=int, default=2)
    parser.add_argument(
        "--capacity-pressure",
        choices=["legacy", "loose", "medium", "tight"],
        default="legacy",
    )
    parser.add_argument("--shots", type=int, default=1024)
    parser.add_argument("--num-sweeps", type=int, default=40)
    parser.add_argument("--backend", default="auto")
    parser.add_argument("--protocol-version", default="single-run-v1")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--frozen-git-commit", default="")
    parser.add_argument("--protocol-config-sha256", default="")
    parser.add_argument("--task-key", default="")
    parser.add_argument("--repeat-index", type=int, default=1)
    parser.add_argument("--capacity", type=int, default=0)
    parser.add_argument("--threshold-file-sha256", default="")
    parser.add_argument("--token-file", type=Path, default=ROOT.parent / ".env.txt")
    parser.add_argument("--quark-runtime", type=Path, default=ROOT.parent / "tmp" / "quarkstudio_runtime2")
    parser.add_argument("--outdir", type=Path, default=ROOT / "results" / "quarkstudio_candidate_quality")
    parser.add_argument("--reuse-evidence", type=Path, default=None)
    parser.add_argument("--frozen-thresholds", type=Path, default=None)
    parser.add_argument("--resume-task-id", default="")
    parser.add_argument("--resume-backend", default="")
    parser.add_argument("--resume-submitted-at", default="")
    args = parser.parse_args()

    if args.vehicles != 2:
        raise SystemExit("Candidate bitstring evaluation requires --vehicles=2.")
    if args.customers < 4:
        raise SystemExit("--customers must be at least 4.")
    if args.shots <= 0 or args.shots % 1024 != 0:
        raise SystemExit("QuarkStudio shots must be a positive multiple of 1024.")

    pressure_ratio = {"legacy": 1.15, "loose": 1.30, "medium": 1.15, "tight": 1.0}[
        args.capacity_pressure
    ]
    capacity = int(args.capacity) if args.capacity > 0 else infer_capacity_from_seed(
        args.seed,
        args.customers,
        args.vehicles,
        ratio=pressure_ratio,
    )
    instance = generate_dispatch_instance(
        seed=args.seed,
        num_customers=args.customers,
        num_vehicles=args.vehicles,
        vehicle_capacity=capacity,
    )
    selected = _selected_customers(instance.customers, args.customers)
    if len(selected) != len(instance.customers):
        raise RuntimeError("Formal candidate analysis requires 100% customer-to-qubit coverage.")
    selected_ids = [customer.customer_id for customer in selected]
    bqm = build_bqm_for_instance(instance)
    instance_id = f"seed{args.seed}_c{args.customers}_v{args.vehicles}"
    if args.capacity_pressure != "legacy":
        instance_id += f"_{args.capacity_pressure}"
    qasm = _business_qasm(selected)

    # Stage 1: same-budget classical calibration and exact absolute reference.
    import dimod

    sampler = dimod.SimulatedAnnealingSampler()
    random.seed(args.seed)
    classical_ss = sampler.sample(
        bqm,
        num_reads=args.shots,
        num_sweeps=args.num_sweeps,
    )
    baseline_rows = []
    for datum in classical_ss.data(fields=["sample", "energy"]):
        sample = {str(key): int(value) for key, value in dict(datum.sample).items()}
        feasible, _onehot, _capacity = raw_feasibility(sample, instance)
        baseline_rows.append(
            {"energy": float(bqm.energy(sample)), "feasible": feasible, "weight": 1}
        )
    reference = exact_assignment_reference(
        instance,
        bqm,
        selected_customer_ids=selected_ids,
        bit_order=BIT_ORDER_OPENQASM,
    )
    if args.frozen_thresholds is not None:
        frozen = json.loads(args.frozen_thresholds.read_text(encoding="utf-8"))
        if instance_id not in frozen.get("instances", {}):
            raise RuntimeError(f"Frozen threshold file has no entry for {instance_id}")
    else:
        frozen = freeze_thresholds(
            {instance_id: baseline_rows},
            budget=args.shots,
            exact_references={instance_id: reference},
            metadata={
                "instance_id": instance_id,
                "bqm_config_hash": canonical_sha256(
                    {"seed": args.seed, "customers": args.customers, "vehicles": args.vehicles, "capacity": capacity}
                ),
                "circuit_config_hash": canonical_sha256(qasm),
                "bit_order": BIT_ORDER_OPENQASM,
            },
        )
    threshold_info = frozen["instances"][instance_id]
    args.outdir.mkdir(parents=True, exist_ok=True)
    frozen_path = args.outdir / "frozen_thresholds.json"
    _write_json(frozen_path, frozen)
    print(
        json.dumps(
            {
                "event": "threshold_frozen",
                "instance_id": instance_id,
                "threshold_all": threshold_info["best_classical_energy_all"],
                "threshold_feasible": threshold_info["best_classical_energy_feasible"],
                "path": str(frozen_path),
            },
            ensure_ascii=True,
        ),
        flush=True,
    )

    # Stage 2: hardware result or offline evidence replay. Replay never needs a token.
    backend_snapshot: dict[str, Any]
    raw_response: Any
    if args.reuse_evidence is not None:
        measurement = measurement_from_evidence(
            args.reuse_evidence,
            source="replay",
            platform="quarkstudio",
            selected_customer_ids=selected_ids,
        )
        raw_evidence = json.loads(args.reuse_evidence.read_text(encoding="utf-8"))
        raw_response = raw_evidence
        qasm = str(raw_evidence.get("circuit") or qasm)
        backend_snapshot = {"reused_evidence": True}
        submission_time = raw_evidence.get("submitted_at")
        print(
            json.dumps(
                {"event": "reused_evidence", "task_id": measurement.task_id, "backend": measurement.backend},
                ensure_ascii=True,
            ),
            flush=True,
        )
    else:
        runtime_path = args.quark_runtime.resolve()
        try:
            from quark import Task
        except ImportError:
            if str(runtime_path) not in sys.path:
                sys.path.insert(0, str(runtime_path))
            from quark import Task
        token = os.getenv("QPU_API_TOKEN", "").strip()
        if not token and args.token_file.exists():
            token = args.token_file.read_text(encoding="utf-8").strip()
        if not token:
            raise SystemExit("QPU_API_TOKEN and --token-file are both empty.")
        manager = Task(token)
        if args.resume_task_id:
            backend = args.resume_backend or args.backend
            if backend != args.backend:
                raise RuntimeError("resume backend differs from frozen backend request")
            backend_snapshot = {"resumed_existing_task": True}
            task_id = (
                int(args.resume_task_id)
                if args.resume_task_id.isdigit()
                else args.resume_task_id
            )
            submission_time = args.resume_submitted_at or None
            print(
                json.dumps(
                    {"event": "resume_existing_task", "task_id": task_id, "backend": backend},
                    ensure_ascii=True,
                ),
                flush=True,
            )
        else:
            backend, backend_snapshot = _choose_backend(manager.status(), args.backend)
            task = {
                "chip": backend,
                "name": f"QRF_candidate_quality_{instance_id}",
                "circuit": qasm,
                "shots": args.shots,
                "compile": True,
                "options": {
                    "compiler": "quarkcircuit",
                    "correct": False,
                    "open_dd": None,
                    "target_qubits": [],
                },
            }
            submission_time = now_iso()
            task_id = manager.run(task)
            if not isinstance(task_id, int):
                raise RuntimeError(f"QuarkStudio submit failed: {task_id}")
            receipt = {
                "schema_version": 1,
                "run_id": args.run_id or None,
                "protocol_version": args.protocol_version,
                "protocol_config_sha256": args.protocol_config_sha256 or None,
                "task_key": args.task_key or None,
                "instance_id": instance_id,
                "repeat_index": args.repeat_index,
                "source": "hardware",
                "status": "submitted",
                "task_id": str(task_id),
                "backend_requested": args.backend,
                "backend_actual": backend,
                "shots": args.shots,
                "submitted_at": submission_time,
                "selected_customer_ids": selected_ids,
                "bit_order": BIT_ORDER_OPENQASM,
                "circuit": qasm,
                "circuit_hash": canonical_sha256(qasm),
                "threshold_file_sha256": args.threshold_file_sha256 or None,
                "compile_options": task["options"] | {"compile": True},
            }
            _write_json(
                args.outdir / "submission_receipt.json", redact_payload(receipt)
            )
            print(
                json.dumps(
                    {"event": "submitted", "task_id": task_id, "backend": backend, "shots": args.shots},
                    ensure_ascii=True,
                ),
                flush=True,
            )
        result = manager.result(task_id, timeout=180.0)
        if not isinstance(result, dict):
            result = {"status": "failed", "error": f"Unexpected result type: {type(result).__name__}"}
        raw_response = result
        measurement = measurement_from_payload(
            result,
            source="hardware",
            platform="quarkstudio",
            status=result.get("status", "unknown"),
            task_id=task_id,
            backend=backend,
            shots_requested=args.shots,
            selected_customer_ids=selected_ids,
            circuit=qasm,
            submitted_at=submission_time,
        )

    candidates, summary_model = evaluate_measurement(
        measurement,
        instance_id=instance_id,
        instance=instance,
        bqm=bqm,
        threshold_info=threshold_info,
        quality_tau=float(frozen["absolute_quality_tau"]),
        near_quality_tau=float(frozen["near_quality_tau"]),
        tolerance=DEFAULT_ENERGY_TOLERANCE,
    )
    candidate_rows = []
    for candidate in candidates:
        row = candidate.to_dict()
        row["bqm_energy"] = row["energy"]
        row["threshold_all"] = threshold_info["best_classical_energy_all"]
        row["threshold_feasible"] = threshold_info["best_classical_energy_feasible"]
        row["meets_quality_threshold"] = row["quality_gate_pass"]
        row["strictly_below_threshold"] = row["strict_improvement_feasible_pass"]
        candidate_rows.append(row)

    summary = summary_model.to_dict()
    summary.update(
        {
            "protocol_version": args.protocol_version,
            "run_id": args.run_id or None,
            "frozen_git_commit": args.frozen_git_commit or None,
            "git_commit_actual": _current_git_commit(),
            "protocol_config_sha256": args.protocol_config_sha256 or None,
            "task_key": args.task_key or None,
            "repeat_index": args.repeat_index,
            "backend_requested": args.backend,
            "backend_actual": measurement.backend,
            "backend_queue_snapshot_before_submit": backend_snapshot,
            "status": measurement.status,
            "shots": measurement.shots_requested,
            "selected_customer_ids_in_qubit_order": selected_ids,
            "customer_demands": {str(customer.customer_id): customer.demand for customer in instance.customers},
            "vehicle_capacity": capacity,
            "threshold": threshold_info["best_classical_energy_feasible"],
            "threshold_all": threshold_info["best_classical_energy_all"],
            "threshold_method": frozen["threshold_method"],
            "energy_tolerance": DEFAULT_ENERGY_TOLERANCE,
            "exact_optimum_energy": reference["exact_optimum_energy"],
            "random_median_energy": reference["random_median_energy"],
            "claim_scope": (
                "Results describe candidate quality and same-budget complementarity only; "
                "they do not establish universal quantum or speed advantage."
            ),
        }
    )
    if candidates:
        top = max(candidates, key=lambda row: row.count)
        best = min(candidates, key=lambda row: row.energy)
        summary.update(
            {
                "top_bitstring": top.bitstring,
                "top_bitstring_count": top.count,
                "top_bitstring_energy": top.energy,
                "top_bitstring_meets_quality_threshold": top.quality_gate_pass,
                "quantum_best_bitstring": best.bitstring,
                "quantum_best_energy": best.energy,
                "quantum_best_count": best.count,
            }
        )
    else:
        best = None

    evidence_payload = {
        "schema_version": 2,
        "run_id": args.run_id or None,
        "protocol_version": args.protocol_version,
        "frozen_git_commit": args.frozen_git_commit or None,
        "git_commit_actual": _current_git_commit(),
        "protocol_config_sha256": args.protocol_config_sha256 or None,
        "task_key": args.task_key or None,
        "instance_id": instance_id,
        "repeat_index": args.repeat_index,
        "source": measurement.source,
        "platform": measurement.platform,
        "task_id": measurement.task_id,
        "backend": measurement.backend,
        "backend_requested": args.backend,
        "backend_actual": measurement.backend,
        "status": measurement.status,
        "shots": measurement.shots_requested,
        "shots_received": measurement.shots_received,
        "unique_bitstrings": len(measurement.counts),
        "raw_counts": measurement.counts,
        "counts": measurement.counts,
        "raw_response": redact_payload(raw_response),
        "selected_customer_ids": selected_ids,
        "bit_order": measurement.bit_order,
        "circuit": qasm,
        "circuit_hash": canonical_sha256(qasm),
        "threshold_hash": canonical_sha256(frozen),
        "threshold_file_sha256": args.threshold_file_sha256 or None,
        "threshold_method": frozen.get("threshold_method"),
        "random_reference": {
            "median_energy": threshold_info.get("random_median_energy"),
            "quality_hit_rate": threshold_info.get("random_quality_hit_rate"),
        },
        "classical_reference": {
            "best_energy_all": threshold_info.get("best_classical_energy_all"),
            "best_energy_feasible": threshold_info.get("best_classical_energy_feasible"),
            "observed_baseline_shots": threshold_info.get("observed_baseline_shots"),
        },
        "raw_payload_sha256": measurement.raw_payload_sha256,
        "threshold_created_at": frozen.get("created_at"),
        "submitted_at": measurement.submitted_at or submission_time,
        "completed_at": measurement.completed_at,
        "poll_count": _find_metadata_value(
            raw_response, {"poll_count", "polls", "query_count"}
        ),
        "backend_queue_snapshot_before_submit": backend_snapshot,
        "compile_options": {
            "compile": True,
            "compiler": "quarkcircuit",
            "correct": False,
            "open_dd": None,
            "target_qubits": [],
        },
        "hardware_metadata": {
            "physical_mapping": _find_metadata_value(
                raw_response, {"physical_mapping", "qubit_mapping", "mapping"}
            ),
            "compiled_depth": _find_metadata_value(
                raw_response, {"compiled_depth", "circuit_depth", "depth"}
            ),
            "two_qubit_gate_count": _find_metadata_value(
                raw_response, {"two_qubit_gate_count", "2q_gates", "twoq_gates"}
            ),
            "swap_count": _find_metadata_value(raw_response, {"swap_count", "swaps"}),
            "calibration": _find_metadata_value(
                raw_response, {"calibration", "calibration_snapshot"}
            ),
        },
        "dependency_snapshot": _dependency_snapshot(),
        "qubit_count": len(selected_ids),
        "warnings": measurement.warnings,
    }
    _write_json(args.outdir / "task_evidence.json", redact_payload(evidence_payload))
    _write_csv(args.outdir / "quantum_candidates.csv", candidate_rows)
    _write_json(args.outdir / "quantum_candidate_quality_summary.json", summary)

    # Stage 3: closed-loop comparison. Missing counts remain NOT_EVALUABLE.
    pipeline_rows: list[dict[str, Any]] = []
    if best is not None:
        quantum_fixed = fixed_assignment_from_bitstring(
            best.bitstring,
            selected_ids,
            num_vehicles=args.vehicles,
            bit_order=measurement.bit_order,
        )
        quantum_sample, _ = complete_min_energy_sample(bqm, quantum_fixed)
        quantum_eval = evaluate_sample(instance, bqm, quantum_sample, two_opt_rounds=2)
        classical_sample = {str(key): int(value) for key, value in dict(classical_ss.first.sample).items()}
        classical_eval = evaluate_sample(instance, bqm, classical_sample, two_opt_rounds=2)
        rng = random.Random(args.seed * 1000 + args.customers * 10 + args.vehicles)
        random_sample = min(
            (
                {str(variable): rng.randint(0, 1) for variable in bqm.variables}
                for _ in range(args.shots)
            ),
            key=bqm.energy,
        )
        random_eval = evaluate_sample(instance, bqm, random_sample, two_opt_rounds=2)
        pipeline_rows = [
            _pipeline_row(instance_id, "random", f"best_of_{args.shots}_random_bqm_samples", random_eval),
            _pipeline_row(instance_id, "classical", f"best_of_{args.shots}_classical_sa_samples", classical_eval),
            _pipeline_row(
                instance_id,
                "quantum",
                f"best_energy_candidate_from_{measurement.source}_measurement_counts",
                quantum_eval,
                task_id=measurement.task_id or "",
                backend=measurement.backend or "",
                bitstring=best.bitstring,
            ),
        ]
    closed_loop_summary = {
        "instance_id": instance_id,
        "task_id": measurement.task_id,
        "backend": measurement.backend,
        "task_status": measurement.status,
        "source": measurement.source,
        "decision": "EVALUATED" if best is not None else "NOT_EVALUABLE",
        "has_measurement_counts": bool(measurement.counts),
        "quantum_candidate_selection_policy": "minimum BQM energy among measured bitstrings",
        "selected_quantum_bitstring": best.bitstring if best is not None else None,
        "modes": {
            row["mode"]: {key: value for key, value in row.items() if key not in {"instance_id", "mode"}}
            for row in pipeline_rows
        },
        "conclusion": (
            "The measured candidate entered the shared assignment, repair, and 2-opt pipeline."
            if best is not None
            else "NOT_EVALUABLE: no valid measurement counts were available for closed-loop refinement."
        ),
    }
    _write_csv(args.outdir / "three_mode_closed_loop_comparison.csv", pipeline_rows)
    _write_json(args.outdir / "quantum_closed_loop_summary.json", closed_loop_summary)
    print(json.dumps(summary, ensure_ascii=True, indent=2), flush=True)


if __name__ == "__main__":
    main()
