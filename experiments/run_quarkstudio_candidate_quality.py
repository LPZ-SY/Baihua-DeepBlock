from __future__ import annotations

import argparse
import csv
import json
import math
import os
import random
import sys
from pathlib import Path
from typing import Any

from experiment_utils import (
    ROOT,
    build_bqm_for_instance,
    compute_capacity_metrics,
    compute_onehot_violation_count,
    evaluate_sample,
    infer_capacity_from_seed,
)
from run_quantum_candidate_quality import DEFAULT_ENERGY_TOLERANCE, calibrate_thresholds

SRC_DIR = ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from quantum_route_forge import generate_dispatch_instance  # noqa: E402
from quantum_route_forge.assignment_bqm import assignment_var, decode_assignment  # noqa: E402
from quantum_route_forge.geometry import euclidean  # noqa: E402


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _selected_customers(customers: list, max_qubits: int) -> list:
    ranked = sorted(customers, key=lambda c: (-c.demand, c.customer_id))
    return ranked[: max(2, min(max_qubits, len(ranked)))]


def _business_qasm(selected: list) -> str:
    """Mirror the project's QAOA-style proximity circuit as OpenQASM 2.0."""
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
    lines.extend(f"h q[{i}];" for i in range(n))
    for i in range(n):
        for j in range(i + 1, n):
            distance = euclidean(selected[i].point, selected[j].point)
            proximity = 1.0 - min(1.0, distance / max_distance)
            weight = 0.25 + 0.75 * proximity
            lines.append(f"rzz({gamma * weight:.17g}) q[{i}],q[{j}];")
    lines.extend(f"rx({beta:.17g}) q[{i}];" for i in range(n))
    lines.extend(f"measure q[{i}] -> meas[{i}];" for i in range(n))
    return "\n".join(lines) + "\n"


def _assignment_from_bitstring(bitstring: str, selected: list, num_vehicles: int) -> dict[str, int]:
    if num_vehicles != 2:
        raise ValueError("当前单比特映射仅支持 2 辆车。")
    if len(bitstring) != len(selected) or set(bitstring) - {"0", "1"}:
        raise ValueError(f"无效 bitstring: {bitstring!r}")

    sample: dict[str, int] = {}
    for index, customer in enumerate(selected):
        # OpenQASM count strings use the highest classical bit on the left.
        bit = bitstring[len(bitstring) - 1 - index]
        vehicle = int(bit)
        sample[assignment_var(customer.customer_id, 0)] = 1 if vehicle == 0 else 0
        sample[assignment_var(customer.customer_id, 1)] = 1 if vehicle == 1 else 0
    return sample


def _complete_min_energy_sample(bqm, fixed_assignment: dict[str, int]) -> tuple[dict[str, int], float]:
    import dimod

    residual = bqm.copy()
    residual.fix_variables(fixed_assignment)
    if residual.num_variables:
        slack_sample = dict(dimod.ExactSolver().sample(residual).first.sample)
    else:
        slack_sample = {}
    completed = {str(v): 0 for v in bqm.variables}
    completed.update({str(k): int(v) for k, v in fixed_assignment.items()})
    completed.update({str(k): int(v) for k, v in slack_sample.items()})
    return completed, float(bqm.energy(completed))


def _raw_feasibility(sample: dict[str, int], instance) -> tuple[bool, int, int]:
    onehot = compute_onehot_violation_count(sample, instance.customers, instance.num_vehicles)
    assignments = decode_assignment(sample, instance.customers, instance.num_vehicles)
    capacity, _over, _loads = compute_capacity_metrics(assignments, instance.vehicle_capacity)
    return onehot == 0 and capacity == 0, onehot, capacity


def _choose_backend(status: Any, requested: str) -> tuple[str, dict[str, Any]]:
    candidates = ["Dongling", "Baihua", "Shenglian"]
    snapshot = {name: status.get(name) for name in candidates} if isinstance(status, dict) else {}
    if requested.lower() != "auto":
        if requested not in candidates:
            raise ValueError(f"backend 必须是 auto 或 {candidates}")
        return requested, snapshot

    online = []
    for preference, name in enumerate(candidates):
        queue = snapshot.get(name)
        if isinstance(queue, (int, float)) and math.isfinite(float(queue)):
            online.append((float(queue), preference, name))
    if not online:
        raise RuntimeError(f"候选芯片均不可用: {snapshot}")
    return min(online)[2], snapshot


def main() -> None:
    parser = argparse.ArgumentParser(description="QuarkStudio 真机量子候选质量门槛实验")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--customers", type=int, default=4)
    parser.add_argument("--vehicles", type=int, default=2)
    parser.add_argument("--shots", type=int, default=1024)
    parser.add_argument("--num-sweeps", type=int, default=40)
    parser.add_argument("--backend", default="auto")
    parser.add_argument("--token-file", type=Path, default=ROOT.parent / ".env.txt")
    parser.add_argument("--quark-runtime", type=Path, default=ROOT.parent / "tmp" / "quarkstudio_runtime2")
    parser.add_argument("--outdir", type=Path, default=ROOT / "results" / "quarkstudio_candidate_quality")
    parser.add_argument("--reuse-evidence", type=Path, default=None)
    args = parser.parse_args()

    if args.vehicles != 2:
        raise SystemExit("当前 bitstring 业务映射要求 --vehicles=2。")
    if args.customers < 4:
        raise SystemExit("--customers 必须至少为 4。")
    if args.shots <= 0 or args.shots % 1024 != 0:
        raise SystemExit("QuarkStudio shots 必须为 1024 的正整数倍。")

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
        raise SystemExit("QPU_API_TOKEN 和 token 文件均为空。")

    capacity = infer_capacity_from_seed(args.seed, args.customers, args.vehicles)
    instance = generate_dispatch_instance(
        seed=args.seed,
        num_customers=args.customers,
        num_vehicles=args.vehicles,
        vehicle_capacity=capacity,
    )
    selected = _selected_customers(instance.customers, args.customers)
    if len(selected) != len(instance.customers):
        raise RuntimeError("独立候选分析要求所有客户均映射到量子比特。")
    bqm = build_bqm_for_instance(instance)

    # Stage 1: classical calibration. Freeze this file before any quantum submission.
    import dimod

    sampler = dimod.SimulatedAnnealingSampler()
    classical_ss = sampler.sample(
        bqm,
        num_reads=args.shots,
        num_sweeps=args.num_sweeps,
    )
    instance_id = f"seed{args.seed}_c{args.customers}_v{args.vehicles}"
    baseline_rows = []
    for datum in classical_ss.data(fields=["sample", "energy"]):
        sample = {str(k): int(v) for k, v in dict(datum.sample).items()}
        feasible, _onehot, _capacity = _raw_feasibility(sample, instance)
        # Recompute with the same BQM evaluator used for quantum candidates. This avoids
        # tiny floating differences caused by sampler-side energy accumulation order.
        baseline_rows.append({"energy": float(bqm.energy(sample)), "feasible": feasible, "weight": 1})
    frozen = calibrate_thresholds({instance_id: baseline_rows}, budget=args.shots)
    threshold = float(frozen["instances"][instance_id]["threshold"])

    args.outdir.mkdir(parents=True, exist_ok=True)
    frozen_path = args.outdir / "frozen_thresholds.json"
    _write_json(frozen_path, frozen)
    print(json.dumps({"event": "threshold_frozen", "instance_id": instance_id, "threshold": threshold, "path": str(frozen_path)}, ensure_ascii=True), flush=True)

    # Stage 2: real-hardware submission. The frozen threshold is not modified afterwards.
    qasm = _business_qasm(selected)
    if args.reuse_evidence is not None:
        evidence = json.loads(args.reuse_evidence.read_text(encoding="utf-8"))
        task_id = int(evidence["task_id"])
        backend = str(evidence["backend"])
        backend_snapshot = {"reused_evidence": True}
        result = {
            "status": evidence.get("status"),
            "count": evidence.get("counts", {}),
            "error": evidence.get("error", ""),
        }
        qasm = str(evidence.get("circuit") or qasm)
        print(json.dumps({"event": "reused_evidence", "task_id": task_id, "backend": backend}, ensure_ascii=True), flush=True)
    else:
        manager = Task(token)
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
        task_id = manager.run(task)
        if not isinstance(task_id, int):
            raise RuntimeError(f"QuarkStudio submit failed: {task_id}")
        print(json.dumps({"event": "submitted", "task_id": task_id, "backend": backend, "shots": args.shots}, ensure_ascii=True), flush=True)
        result = manager.result(task_id, timeout=180.0)
        if not isinstance(result, dict):
            raise RuntimeError(f"Unexpected result type: {type(result).__name__}")
    counts_raw = result.get("count") or {}
    counts = {
        str(bitstring).replace(" ", ""): int(count)
        for bitstring, count in counts_raw.items()
        if len(str(bitstring).replace(" ", "")) == len(selected)
    }
    if not counts:
        raise RuntimeError(f"任务未返回 {len(selected)} 比特 measurement counts: {result.get('status')}")

    candidate_rows: list[dict[str, Any]] = []
    for bitstring, count in sorted(counts.items(), key=lambda item: item[1], reverse=True):
        fixed = _assignment_from_bitstring(bitstring, selected, args.vehicles)
        completed, energy = _complete_min_energy_sample(bqm, fixed)
        feasible, onehot_bad, capacity_bad = _raw_feasibility(completed, instance)
        candidate_rows.append(
            {
                "instance_id": instance_id,
                "task_id": task_id,
                "backend": backend,
                "bitstring": bitstring,
                "count": count,
                "probability": count / args.shots,
                "bqm_energy": energy,
                "threshold": threshold,
                "meets_quality_threshold": energy <= threshold + DEFAULT_ENERGY_TOLERANCE,
                "strictly_below_threshold": energy < threshold - DEFAULT_ENERGY_TOLERANCE,
                "raw_feasible": feasible,
                "onehot_violation_count": onehot_bad,
                "capacity_violation_count": capacity_bad,
            }
        )

    top = candidate_rows[0]
    best = min(candidate_rows, key=lambda row: float(row["bqm_energy"]))
    passing_shots = sum(int(row["count"]) for row in candidate_rows if row["meets_quality_threshold"])
    strictly_improving_shots = sum(
        int(row["count"]) for row in candidate_rows if row["strictly_below_threshold"]
    )
    decision = "PASS" if passing_shots > 0 else "FAIL"
    exact_optimum = None
    if bqm.num_variables <= 20:
        exact_optimum = float(dimod.ExactSolver().sample(bqm).first.energy)
    summary = {
        "instance_id": instance_id,
        "task_id": task_id,
        "backend": backend,
        "backend_queue_snapshot_before_submit": backend_snapshot,
        "status": result.get("status"),
        "shots": args.shots,
        "selected_customer_ids_in_qubit_order": [c.customer_id for c in selected],
        "customer_demands": {str(c.customer_id): c.demand for c in instance.customers},
        "vehicle_capacity": capacity,
        "threshold": threshold,
        "threshold_method": frozen["threshold_method"],
        "energy_tolerance": DEFAULT_ENERGY_TOLERANCE,
        "exact_optimum_energy": exact_optimum,
        "top_bitstring": top["bitstring"],
        "top_bitstring_count": top["count"],
        "top_bitstring_energy": top["bqm_energy"],
        "top_bitstring_meets_quality_threshold": top["meets_quality_threshold"],
        "quantum_best_bitstring": best["bitstring"],
        "quantum_best_energy": best["bqm_energy"],
        "quantum_best_count": best["count"],
        "passing_shots": passing_shots,
        "passing_rate": passing_shots / args.shots,
        "decision": decision,
        "strictly_improving_shots": strictly_improving_shots,
        "strict_improvement_rate": strictly_improving_shots / args.shots,
        "strict_improvement_decision": "PASS" if strictly_improving_shots > 0 else "FAIL",
        "claim_scope": "候选 BQM 能量层面的门槛判定，不等同于最终路径优势或广义量子优势。",
    }

    # Stage 3: measured bitstring -> assignment -> repair -> route refinement.
    quantum_fixed = _assignment_from_bitstring(str(best["bitstring"]), selected, args.vehicles)
    quantum_sample, _quantum_energy = _complete_min_energy_sample(bqm, quantum_fixed)
    quantum_eval = evaluate_sample(instance, bqm, quantum_sample, two_opt_rounds=2)

    classical_sample = {str(k): int(v) for k, v in dict(classical_ss.first.sample).items()}
    classical_eval = evaluate_sample(instance, bqm, classical_sample, two_opt_rounds=2)

    rng = random.Random(args.seed * 1000 + args.customers * 10 + args.vehicles)
    random_best_sample = None
    random_best_energy = None
    for _ in range(args.shots):
        sample = {str(v): int(rng.randint(0, 1)) for v in bqm.variables}
        energy = float(bqm.energy(sample))
        if random_best_energy is None or energy < random_best_energy:
            random_best_sample = sample
            random_best_energy = energy
    assert random_best_sample is not None
    random_eval = evaluate_sample(instance, bqm, random_best_sample, two_opt_rounds=2)

    def _pipeline_row(
        mode: str,
        source: str,
        eval_info: dict[str, Any],
        bitstring: str = "",
    ) -> dict[str, Any]:
        return {
            "instance_id": instance_id,
            "mode": mode,
            "candidate_source": source,
            "task_id": task_id if mode == "quantum" else "",
            "backend": backend if mode == "quantum" else "",
            "bitstring": bitstring,
            "bqm_energy": float(eval_info["assignment_energy"]),
            "raw_assignment_feasible": bool(eval_info["assignment_feasible"]),
            "onehot_violation_count": int(eval_info["onehot_violation_count"]),
            "capacity_violation_count_before_repair": int(
                eval_info["capacity_violation_count_before_repair"]
            ),
            "capacity_violation_count_after_repair": int(eval_info["capacity_violation_count"]),
            "repair_applied": bool(eval_info["repaired"]),
            "repair_summary": eval_info["repair_summary"],
            "route_distance_before_2opt": float(eval_info["route_distance_before_2opt"]),
            "route_distance_after_2opt": float(eval_info["route_distance_after_2opt"]),
            "improvement_after_2opt": float(eval_info["improvement_after_2opt"]),
            "route_feasible": bool(eval_info["route_feasible"]),
            "decoded_assignment": json.dumps(
                eval_info["decoded_assignment"], ensure_ascii=False, sort_keys=True
            ),
        }

    pipeline_rows = [
        _pipeline_row("random", "best_of_1024_random_bqm_samples", random_eval),
        _pipeline_row("classical", "best_of_1024_classical_sa_samples", classical_eval),
        _pipeline_row(
            "quantum",
            "best_energy_candidate_from_dongling_measurement_counts",
            quantum_eval,
            bitstring=str(best["bitstring"]),
        ),
    ]
    closed_loop_summary = {
        "instance_id": instance_id,
        "task_id": task_id,
        "backend": backend,
        "task_status": result.get("status"),
        "used_mode": "quarkstudio_quantum_bitstring_refine",
        "has_measurement_counts": True,
        "has_bitstrings": True,
        "quantum_bitstring_used_in_assignment": True,
        "quantum_bitstring_used_in_route_refinement": True,
        "quantum_candidate_selection_policy": "minimum BQM energy among measured bitstrings",
        "selected_quantum_bitstring": str(best["bitstring"]),
        "selected_quantum_bitstring_count": int(best["count"]),
        "selected_quantum_candidate_meets_quality_threshold": bool(
            best["meets_quality_threshold"]
        ),
        "modes": {
            row["mode"]: {
                key: value
                for key, value in row.items()
                if key not in {"instance_id", "mode"}
            }
            for row in pipeline_rows
        },
        "conclusion": (
            "真实 Dongling measured bitstring 已进入客户-车辆分配、约束检查/修复和 2-opt "
            "路径细化，量子-经典闭环已完成。"
        ),
    }
    _write_csv(args.outdir / "quantum_candidates.csv", candidate_rows)
    _write_json(args.outdir / "quantum_candidate_quality_summary.json", summary)
    _write_csv(args.outdir / "three_mode_closed_loop_comparison.csv", pipeline_rows)
    _write_json(args.outdir / "quantum_closed_loop_summary.json", closed_loop_summary)
    _write_json(
        args.outdir / "task_evidence.json",
        {
            "task_id": task_id,
            "backend": backend,
            "status": result.get("status"),
            "shots": args.shots,
            "counts": counts,
            "error": result.get("error", ""),
            "circuit": qasm,
        },
    )
    print(json.dumps(summary, ensure_ascii=True, indent=2), flush=True)


if __name__ == "__main__":
    main()
