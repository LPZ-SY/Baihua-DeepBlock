from __future__ import annotations

import math
import re

from .assignment_bqm import build_assignment_bqm, decode_assignment
from .models import AssignmentMetadata, DispatchInstance, OptimizationResult
from .quafu_bridge import (
    QuafuJobResult,
    bitstring_to_vehicle_hints,
    fetch_quafu_task_bitstring,
    submit_quafu_partition_job,
)
from .quantum_measurements import measurement_from_payload
from .routing import build_route_plans
from .solvers import solve_bqm_classical


def _repair_capacity(assignments, vehicle_capacity: int) -> dict[int, list]:
    """Repair capacity violations by moving customers from overloaded routes."""
    assignments = {k: list(v) for k, v in assignments.items()}
    max_iters = 2000
    for _ in range(max_iters):
        loads = {v: sum(c.demand for c in clist) for v, clist in assignments.items()}
        overloaded = [v for v, load in loads.items() if load > vehicle_capacity]
        if not overloaded:
            return assignments

        moved = False
        for ov in sorted(overloaded, key=lambda v: loads[v], reverse=True):
            # Move higher-demand points first to reduce overload quickly.
            for customer in sorted(assignments[ov], key=lambda c: (-c.demand, c.customer_id)):
                candidates = [
                    v
                    for v in assignments.keys()
                    if v != ov and loads[v] + customer.demand <= vehicle_capacity
                ]
                if not candidates:
                    continue
                target = min(candidates, key=lambda v: loads[v])
                assignments[ov].remove(customer)
                assignments[target].append(customer)
                moved = True
                break
            if moved:
                break

        if not moved:
            # Feasibility should usually hold because global capacity is checked.
            break
    return assignments


def _normalize_bitstring(raw: str) -> tuple[str, str]:
    text = (raw or "").strip().replace(" ", "").replace("_", "")
    if not text:
        return "", ""
    if not re.fullmatch(r"[01]+", text):
        return "", "Manual bitstring ignored: only 0/1 are allowed."
    return text, ""


def run_optimization(
    instance: DispatchInstance,
    mode: str,
    time_limit: int = 8,
    num_reads: int = 300,
    num_sweeps: int = 40,
    compactness_weight: float = 1.0,
    assignment_penalty: float = 90.0,
    capacity_penalty: float = 45.0,
    balance_weight: float = 1.2,
    two_opt_rounds: int = 2,
    quafu_token: str = "",
    quafu_backend: str = "",
    quafu_base_url: str = "",
    quafu_shots: int = 1000,
    quafu_wait: bool = True,
    quafu_max_qubits: int = 8,
    quafu_timeout_sec: int = 25,
    quafu_proxy_url: str = "",
    quafu_verify_ssl: bool = True,
    quafu_result_task_id: str = "",
    quafu_manual_bitstring: str = "",
    auto_repair_capacity: bool = False,
    quantum_action: str = "auto",
) -> OptimizationResult:
    mode = (mode or "classical").lower().strip()
    use_quafu = mode in {"quantum", "quafu"}

    preferred_vehicle_by_customer: dict[int, int] = {}
    quafu_task_id = None
    quafu_backend_used = None
    quafu_bitstring = None
    quafu_endpoint = None
    quafu_msg = ""
    capacity_msg = ""
    used_mode = "classical"
    manual_bitstring, manual_bitstring_msg = _normalize_bitstring(quafu_manual_bitstring)
    requested_result_task_id = str(quafu_result_task_id or "").strip()
    lookup_task_msg = ""
    measurement_result = None

    if not instance.feasible_capacity:
        if not auto_repair_capacity:
            min_capacity = math.ceil(instance.total_demand / instance.num_vehicles)
            raise ValueError(
                "Total demand exceeds fleet capacity. "
                f"Required minimum capacity per vehicle is {min_capacity} "
                f"(demand={instance.total_demand}, vehicles={instance.num_vehicles})."
            )
        repaired_capacity = math.ceil(instance.total_demand / instance.num_vehicles)
        instance = DispatchInstance(
            depot=instance.depot,
            customers=instance.customers,
            num_vehicles=instance.num_vehicles,
            vehicle_capacity=repaired_capacity,
        )
        capacity_msg = (
            f"Capacity auto-repaired to {repaired_capacity} "
            f"(original capacity was infeasible for demand {instance.total_demand})."
        )

    if use_quafu:
        action = (quantum_action or "auto").lower().strip()
        ranked = sorted(instance.customers, key=lambda c: (-c.demand, c.customer_id))
        action_selected_ids = [
            customer.customer_id
            for customer in ranked[: max(2, min(quafu_max_qubits, len(ranked)))]
        ]
        if action == "manual":
            job = QuafuJobResult(
                ok=bool(manual_bitstring),
                message="Manual debug action selected; no hardware request was made.",
                selected_customer_ids=action_selected_ids,
                status="completed" if manual_bitstring else "failed",
                shots_requested=1 if manual_bitstring else 0,
            )
        elif action == "query":
            if not requested_result_task_id:
                job = QuafuJobResult(
                    ok=False,
                    message="Query action requires Result Task ID; no new task was submitted.",
                    selected_customer_ids=action_selected_ids,
                    status="failed",
                )
            else:
                job = fetch_quafu_task_bitstring(
                    task_id=requested_result_task_id,
                    api_token=quafu_token,
                    base_url=quafu_base_url or None,
                    timeout_sec=quafu_timeout_sec,
                    proxy_url=quafu_proxy_url,
                    verify_ssl=quafu_verify_ssl,
                )
        elif action == "submit":
            job = submit_quafu_partition_job(
                customers=instance.customers,
                api_token=quafu_token,
                backend=quafu_backend or None,
                base_url=quafu_base_url or None,
                shots=quafu_shots,
                wait=quafu_wait,
                max_qubits=quafu_max_qubits,
                timeout_sec=quafu_timeout_sec,
                proxy_url=quafu_proxy_url,
                verify_ssl=quafu_verify_ssl,
            )
        elif requested_result_task_id:
            job = fetch_quafu_task_bitstring(
                task_id=requested_result_task_id,
                api_token=quafu_token,
                base_url=quafu_base_url or None,
                timeout_sec=quafu_timeout_sec,
                proxy_url=quafu_proxy_url,
                verify_ssl=quafu_verify_ssl,
            )
            if not job.bitstring:
                lookup_task_msg = f"Task lookup ({requested_result_task_id}): {job.message}"
                job = submit_quafu_partition_job(
                    customers=instance.customers,
                    api_token=quafu_token,
                    backend=quafu_backend or None,
                    base_url=quafu_base_url or None,
                    shots=quafu_shots,
                    wait=quafu_wait,
                    max_qubits=quafu_max_qubits,
                    timeout_sec=quafu_timeout_sec,
                    proxy_url=quafu_proxy_url,
                    verify_ssl=quafu_verify_ssl,
                )
        else:
            job = submit_quafu_partition_job(
                customers=instance.customers,
                api_token=quafu_token,
                backend=quafu_backend or None,
                base_url=quafu_base_url or None,
                shots=quafu_shots,
                wait=quafu_wait,
                max_qubits=quafu_max_qubits,
                timeout_sec=quafu_timeout_sec,
                proxy_url=quafu_proxy_url,
                verify_ssl=quafu_verify_ssl,
            )
        quafu_task_id = job.task_id
        quafu_backend_used = job.backend
        quafu_bitstring = job.bitstring
        quafu_endpoint = job.endpoint
        quafu_msg = " | ".join(x for x in [lookup_task_msg, job.message] if x)
        measurement_result = job.measurement_result

        selected_by_id = {c.customer_id: c for c in instance.customers}
        if job.selected_customer_ids:
            ordered_selected = [selected_by_id[cid] for cid in job.selected_customer_ids if cid in selected_by_id]
        else:
            # Fallback selection when backend accepts submission but does not expose selected ids in response.
            ordered_selected = ranked[: max(2, min(quafu_max_qubits, len(ranked)))]

        if manual_bitstring and ordered_selected and instance.num_vehicles >= 2:
            preferred_vehicle_by_customer = bitstring_to_vehicle_hints(
                selected_customers=ordered_selected,
                bitstring=manual_bitstring,
                num_vehicles=instance.num_vehicles,
            )
            quafu_bitstring = manual_bitstring
            measurement_result = measurement_from_payload(
                {"counts": {manual_bitstring: 1}},
                source="manual_debug",
                platform="local",
                status="completed",
                task_id=quafu_task_id,
                backend=quafu_backend_used,
                endpoint=quafu_endpoint,
                shots_requested=1,
                selected_customer_ids=[customer.customer_id for customer in ordered_selected],
                message="Manual debug bitstring override; excluded from formal hardware statistics.",
            )
            used_mode = "quafu_quantum_hybrid"
            quafu_msg = " | ".join(x for x in [quafu_msg, "Manual bitstring override applied."] if x)
        elif job.ok and job.bitstring and ordered_selected and instance.num_vehicles >= 2:
            preferred_vehicle_by_customer = bitstring_to_vehicle_hints(
                selected_customers=ordered_selected,
                bitstring=job.bitstring,
                num_vehicles=instance.num_vehicles,
            )
            used_mode = "quafu_quantum_hybrid"
            if measurement_result is None:
                measurement_result = measurement_from_payload(
                    {"counts": {job.bitstring: 1}},
                    source="hardware",
                    platform="quafu",
                    status=job.status,
                    task_id=job.task_id,
                    backend=job.backend,
                    endpoint=job.endpoint,
                    shots_requested=job.shots_requested,
                    selected_customer_ids=[customer.customer_id for customer in ordered_selected],
                    message="Backend exposed a single sample through the compatibility path.",
                )
        elif job.ok:
            used_mode = "quafu_submitted_classical_refine"
        else:
            used_mode = "quafu_unavailable_classical_fallback"
            measurement_result = measurement_from_payload(
                {},
                source="fallback",
                platform="local",
                status="failed",
                task_id=job.task_id,
                backend=job.backend,
                endpoint=job.endpoint,
                shots_requested=job.shots_requested,
                selected_customer_ids=[customer.customer_id for customer in ordered_selected],
                message=job.message,
            )

        if manual_bitstring_msg:
            quafu_msg = " | ".join(x for x in [quafu_msg, manual_bitstring_msg] if x)

    bqm = build_assignment_bqm(
        instance=instance,
        compactness_weight=compactness_weight,
        assignment_penalty=assignment_penalty,
        capacity_penalty=capacity_penalty,
        balance_weight=balance_weight,
        preferred_vehicle_by_customer=preferred_vehicle_by_customer,
    )
    run = solve_bqm_classical(
        bqm=bqm,
        num_reads=num_reads,
        num_sweeps=num_sweeps,
    )
    assignments = decode_assignment(
        sample=run.sample,
        customers=instance.customers,
        num_vehicles=instance.num_vehicles,
    )
    assignments = _repair_capacity(assignments, vehicle_capacity=instance.vehicle_capacity)
    routes = build_route_plans(
        assignments=assignments,
        depot=instance.depot,
        two_opt_rounds=two_opt_rounds,
    )
    total_distance = sum(r.distance for r in routes)

    return OptimizationResult(
        instance=instance,
        assignments=assignments,
        routes=routes,
        total_distance=total_distance,
        metadata=AssignmentMetadata(
            requested_mode=mode,
            used_mode=used_mode if use_quafu else run.used_mode,
            energy=run.energy,
            message=(
                " | ".join(
                    x
                    for x in [
                        run.message,
                        quafu_msg if use_quafu else "",
                        capacity_msg,
                    ]
                    if x
                )
            ),
            quantum_task_id=quafu_task_id,
            quantum_backend=quafu_backend_used,
            quantum_bitstring=quafu_bitstring,
            quantum_endpoint=quafu_endpoint,
            quantum_measurement_summary=(
                measurement_result.to_dict() if measurement_result is not None else None
            ),
        ),
    )
