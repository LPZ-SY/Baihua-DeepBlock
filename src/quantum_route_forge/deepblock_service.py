from __future__ import annotations

from datetime import datetime, timezone
import math
from pathlib import Path
from typing import Any
from uuid import uuid4

from .competition_history import CompetitionHistory
from .models import Customer, DispatchInstance
from .routing import build_route_plans
from .deepblock.clustering import capacity_constrained_kmeans
from .deepblock.solver import DeepBlockConfig, DeepBlockResult, run_deepblock


MODE_ORDER = (
    "deepblock_hardware",
    "deepblock_random",
    "deepblock_simulator",
    "deepblock_exact",
)


def low_energy_effect_from_payload(hardware: dict[str, Any]) -> dict[str, Any]:
    """Measure hardware mass in the pre-defined bottom-10% QUBO states."""
    rows: list[dict[str, Any]] = []
    for trace in hardware.get("traces", []):
        proxy = trace.get("proxy") or {}
        run = trace.get("run") or {}
        width = len(proxy.get("customer_ids") or [])
        if width < 1 or width > 8 or not run.get("counts"):
            continue
        ranked: list[tuple[float, str]] = []
        for value in range(1 << width):
            bitstring = format(value, f"0{width}b")
            bits = tuple(int(bit) for bit in reversed(bitstring))
            energy = float(proxy.get("constant", 0.0))
            energy += sum(
                float(coefficient) * bits[index]
                for index, coefficient in enumerate(proxy.get("linear") or [])
            )
            energy += sum(
                float(row["coefficient"])
                * bits[int(row["left"])]
                * bits[int(row["right"])]
                for row in proxy.get("quadratic") or []
                if row.get("kept")
            )
            ranked.append((energy, bitstring))
        ranked.sort(key=lambda item: (item[0], item[1]))
        tail_size = max(1, math.ceil(0.10 * (1 << width)))
        low_energy = {bitstring for _energy, bitstring in ranked[:tail_size]}
        counts: dict[str, int] = {}
        for key, value in (run.get("counts") or {}).items():
            canonical = str(key).replace(" ", "")[-width:].zfill(width)
            counts[canonical] = counts.get(canonical, 0) + int(value)
        shots = sum(counts.values())
        hits = sum(counts.get(bitstring, 0) for bitstring in low_energy)
        hardware_mass = hits / max(1, shots)
        uniform_mass = tail_size / (1 << width)
        rows.append(
            {
                "block_id": trace.get("block", {}).get("block_id"),
                "width": width,
                "low_energy_states": tail_size,
                "energy_threshold": ranked[tail_size - 1][0],
                "hits": hits,
                "shots": shots,
                "hardware_mass": hardware_mass,
                "uniform_mass": uniform_mass,
                "enrichment": hardware_mass / uniform_mass,
                "difference_percentage_points": 100.0
                * (hardware_mass - uniform_mass),
                "positive": hardware_mass > uniform_mass,
            }
        )
    if not rows:
        return {
            "evaluable": False,
            "definition": "exact bottom 10% proxy-QUBO energy rank",
            "blocks": [],
        }
    hardware_mean = sum(row["hardware_mass"] for row in rows) / len(rows)
    uniform_mean = sum(row["uniform_mass"] for row in rows) / len(rows)
    return {
        "evaluable": True,
        "definition": "exact bottom 10% proxy-QUBO energy rank",
        "blocks": rows,
        "mean_hardware_mass": hardware_mean,
        "mean_uniform_mass": uniform_mean,
        "enrichment": hardware_mean / uniform_mean,
        "difference_percentage_points": 100.0 * (hardware_mean - uniform_mean),
        "positive_blocks": sum(bool(row["positive"]) for row in rows),
        "total_blocks": len(rows),
        "interpretation": (
            "positive_low_energy_enrichment"
            if hardware_mean > uniform_mean
            else "no_positive_low_energy_enrichment"
        ),
    }


def _routes_payload(
    assignments: dict[int, list[Customer]],
    instance: DispatchInstance,
) -> list[dict[str, Any]]:
    plans = build_route_plans(assignments=assignments, depot=instance.depot, two_opt_rounds=2)
    return [
        {
            "vehicle_id": route.vehicle_id,
            "customer_ids": [customer.customer_id for customer in route.customers],
            "customers": [
                {
                    "customer_id": customer.customer_id,
                    "x": customer.x,
                    "y": customer.y,
                    "demand": customer.demand,
                }
                for customer in route.customers
            ],
            "load": route.load,
            "distance": route.distance,
        }
        for route in plans
    ]


def _instance_payload(instance: DispatchInstance) -> dict[str, Any]:
    return {
        "depot": list(instance.depot),
        "num_vehicles": instance.num_vehicles,
        "vehicle_capacity": instance.vehicle_capacity,
        "total_demand": instance.total_demand,
        "customers": [
            {
                "customer_id": customer.customer_id,
                "x": customer.x,
                "y": customer.y,
                "demand": customer.demand,
            }
            for customer in instance.customers
        ],
    }


def _result_payload(result: DeepBlockResult, instance: DispatchInstance) -> dict[str, Any]:
    raw = result.payload()
    raw["routes"] = _routes_payload(result.assignments, instance)
    raw["improvement_pct"] = (
        100.0 * result.improvement / result.baseline_distance
        if result.baseline_distance > 0
        else 0.0
    )
    raw["task_ids"] = [
        trace.run.task_id for trace in result.traces if trace.run.task_id
    ]
    raw["backend"] = next(
        (trace.run.backend for trace in result.traces if trace.run.backend),
        "",
    )
    raw["shots_received"] = sum(
        sum(trace.run.counts.values()) for trace in result.traces
    )
    return raw


def run_deepblock_optimization(
    *,
    instance: DispatchInstance,
    mode: str = "deepblock_simulator",
    backend: str = "Baihua",
    shots: int = 4096,
    candidate_k: int = 64,
    qaoa_depth: int = 1,
    pool_size: int = 16,
    block_size: int = 8,
    overlap: int = 3,
    seed: int = 2026,
    submit_hardware: bool = False,
    confirm_hardware_submit: bool = False,
    history_root: str | Path | None = None,
    save_history: bool = True,
) -> dict[str, Any]:
    """Run one fair DeepBlock comparison and return the UI's stable schema."""
    requested_mode = str(mode or "").strip().lower()
    if requested_mode not in MODE_ORDER:
        raise ValueError(f"unsupported mode: {mode}")
    if not instance.feasible_capacity:
        raise ValueError(
            "Total demand exceeds fleet capacity; increase capacity before running."
        )

    initial_result = capacity_constrained_kmeans(instance, seed=int(seed))
    initial_assignments = {
        vehicle: list(customers)
        for vehicle, customers in initial_result.assignments.items()
    }
    initial_routes = _routes_payload(initial_assignments, instance)
    initial_distance = float(sum(route["distance"] for route in initial_routes))
    config_base = dict(
        pool_size=int(pool_size),
        block_size=int(block_size),
        overlap=int(overlap),
        qaoa_depth=int(qaoa_depth),
        shots=int(shots),
        candidate_k=int(candidate_k),
        scan_order="forward",
        backend=str(backend or "Baihua"),
    )

    results: dict[str, DeepBlockResult] = {}
    chip_info: dict[str, Any] | None = None
    if submit_hardware:
        try:
            from quark.circuit import Backend
        except ImportError as exc:
            raise RuntimeError(
                "quarkcircuit==0.5.13 is required for Baihua calibration and compilation."
            ) from exc
        chip_info = dict(Backend(str(backend or "Baihua")).chip_info)
    # All arms receive the same immutable starting assignment and parameters.
    for arm_mode in MODE_ORDER:
        is_hardware = arm_mode == "deepblock_hardware"
        should_submit = bool(submit_hardware and requested_mode == arm_mode)
        config = DeepBlockConfig(
            **config_base,
            submit_hardware=should_submit,
            confirm_hardware_submit=bool(confirm_hardware_submit and should_submit),
        )
        results[arm_mode] = run_deepblock(
            instance=instance,
            initial_assignments=initial_assignments,
            mode=arm_mode,
            config=config,
            seed=int(seed),
            chip_info=chip_info if is_hardware else None,
        )

    selected = _result_payload(results[requested_mode], instance)
    comparisons: list[dict[str, Any]] = [
        {
            "method": "Initial",
            "mode": "classical_initial",
            "source": "classical",
            "status": "COMPLETED",
            "final_distance": initial_distance,
            "improvement": 0.0,
            "improvement_pct": 0.0,
            "accepted_moves": 0,
            "task_ids": [],
        }
    ]
    labels = {
        "deepblock_hardware": "Hardware",
        "deepblock_random": "Random",
        "deepblock_simulator": "Simulator",
        "deepblock_exact": "Exact",
    }
    for arm_mode in MODE_ORDER:
        item = _result_payload(results[arm_mode], instance)
        comparisons.append(
            {
                "method": labels[arm_mode],
                "mode": arm_mode,
                "source": item["source"],
                "status": item["status"],
                "final_distance": item["final_distance"],
                "improvement": item["improvement"],
                "improvement_pct": item["improvement_pct"],
                "accepted_moves": item["accepted_moves"],
                "task_ids": item["task_ids"],
                "backend": item["backend"],
                "shots_received": item["shots_received"],
            }
        )

    run_id = (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + "-"
        + uuid4().hex[:8]
    )
    arms_payload = {
        arm_mode: _result_payload(result, instance)
        for arm_mode, result in results.items()
    }
    payload: dict[str, Any] = {
        "schema_version": 1,
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "parameters": {
            "seed": int(seed),
            "num_customers": len(instance.customers),
            "num_vehicles": instance.num_vehicles,
            "vehicle_capacity": instance.vehicle_capacity,
            "mode": requested_mode,
            "backend": str(backend or "Baihua"),
            "shots": int(shots),
            "candidate_k": int(candidate_k),
            "qaoa_depth": int(qaoa_depth),
            "pool_size": int(pool_size),
            "block_size": int(block_size),
            "overlap": int(overlap),
        },
        "fairness": {
            "same_instance": True,
            "same_initial_assignment": True,
            "same_blocks": True,
            "same_shots": True,
            "same_candidate_k": True,
            "same_capacity_repair": True,
            "same_route_evaluator": True,
            "same_acceptance_rule": "strict_true_distance_improvement",
        },
        "instance": _instance_payload(instance),
        "initial": {
            "distance": initial_distance,
            "assignments": {
                str(vehicle): [customer.customer_id for customer in customers]
                for vehicle, customers in sorted(initial_assignments.items())
            },
            "routes": initial_routes,
        },
        "selected": selected,
        "arms": arms_payload,
        "quantum_effect": low_energy_effect_from_payload(
            arms_payload["deepblock_hardware"]
        ),
        "comparisons": comparisons,
        "warnings": (
            [
                "Hardware is a guarded dry-run and is NOT_EVALUABLE until explicit submission is confirmed."
            ]
            if not submit_hardware
            else []
        ),
    }
    if save_history:
        root = Path(history_root) if history_root else Path("results") / "competition_history"
        CompetitionHistory(root).save(payload)
    return payload
