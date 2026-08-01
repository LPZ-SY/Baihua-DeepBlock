from __future__ import annotations

import math
import statistics
from datetime import datetime, timezone
from itertools import product
from typing import Any, Iterable, Mapping, Optional

import dimod

from .assignment_bqm import assignment_var, decode_assignment
from .models import (
    CandidateEvaluation,
    DispatchInstance,
    ExperimentSummary,
    QuantumMeasurementResult,
)
from .quantum_measurements import BIT_ORDER_OPENQASM, bitstring_to_customer_preferences


DEFAULT_ENERGY_TOLERANCE = 1e-9
DEFAULT_QUALITY_TAU = 0.20
DEFAULT_NEAR_QUALITY_TAU = 0.50


def _weighted_budget(rows: Iterable[Mapping[str, Any]], budget: int) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    remaining = max(0, int(budget))
    for raw in rows:
        if remaining <= 0:
            break
        weight = int(raw.get("weight", raw.get("count", raw.get("shots", 1))))
        if weight <= 0:
            continue
        take = min(weight, remaining)
        selected.append({**dict(raw), "weight": take})
        remaining -= take
    return selected


def freeze_thresholds(
    baseline: Mapping[str, Iterable[Mapping[str, Any]]],
    budget: int,
    *,
    exact_references: Optional[Mapping[str, Mapping[str, Any]]] = None,
    quality_tau: float = DEFAULT_QUALITY_TAU,
    near_quality_tau: float = DEFAULT_NEAR_QUALITY_TAU,
    energy_tolerance: float = DEFAULT_ENERGY_TOLERANCE,
    metadata: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    if budget <= 0:
        raise ValueError("budget must be positive")
    instances: dict[str, Any] = {}
    for instance_id, raw_rows in sorted(baseline.items()):
        rows = _weighted_budget(raw_rows, budget)
        observed = sum(int(row["weight"]) for row in rows)
        all_energies = [float(row["energy"]) for row in rows]
        feasible_rows = [
            row for row in rows if bool(row.get("raw_feasible", row.get("feasible", False)))
        ]
        all_threshold = min(all_energies) if observed == budget and all_energies else None
        feasible_threshold = (
            min(float(row["energy"]) for row in feasible_rows)
            if observed == budget and feasible_rows
            else None
        )
        ref = dict((exact_references or {}).get(instance_id, {}))
        instances[instance_id] = {
            # Compatibility alias now intentionally means the feasible primary threshold.
            "threshold": feasible_threshold,
            "best_classical_energy_all": all_threshold,
            "best_classical_energy_feasible": feasible_threshold,
            "observed_baseline_shots": observed,
            "feasible_baseline_shots": sum(int(row["weight"]) for row in feasible_rows),
            "status_all": "ready" if all_threshold is not None else "not_evaluable",
            "status_feasible": "ready" if feasible_threshold is not None else "not_evaluable",
            "reason_feasible": (
                "Best feasible classical energy frozen before result evaluation."
                if feasible_threshold is not None
                else (
                    "Classical calibration samples are below the fixed budget."
                    if observed < budget
                    else "No raw-feasible classical sample was observed within the fixed budget."
                )
            ),
            "exact_optimum_energy": ref.get("exact_optimum_energy"),
            "random_median_energy": ref.get("random_median_energy"),
            "random_quality_hit_rate": ref.get("random_quality_hit_rate"),
        }
    payload = {
        "schema_version": 2,
        "created_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "created_before_hardware_result": True,
        "criterion": "raw feasible and normalized_score <= absolute_quality_tau",
        "threshold_method": "same-budget best classical energies, stored separately for all and raw-feasible candidates",
        "energy_tolerance": float(energy_tolerance),
        "absolute_quality_tau": float(quality_tau),
        "near_quality_tau": float(near_quality_tau),
        "budget_shots_per_instance": int(budget),
        "instances": instances,
    }
    if metadata:
        payload["metadata"] = dict(metadata)
    return payload


def fixed_assignment_from_bitstring(
    bitstring: str,
    selected_customer_ids: Iterable[int],
    *,
    num_vehicles: int,
    bit_order: str = BIT_ORDER_OPENQASM,
) -> dict[str, int]:
    if num_vehicles != 2:
        raise ValueError("candidate quality bitstring evaluation currently requires two vehicles")
    preferences = bitstring_to_customer_preferences(
        bitstring,
        selected_customer_ids,
        bit_order=bit_order,
    )
    fixed: dict[str, int] = {}
    for customer_id, vehicle in preferences.items():
        fixed[assignment_var(customer_id, 0)] = 1 if vehicle == 0 else 0
        fixed[assignment_var(customer_id, 1)] = 1 if vehicle == 1 else 0
    return fixed


def complete_min_energy_sample(
    bqm: dimod.BinaryQuadraticModel,
    fixed_assignment: Mapping[str, int],
) -> tuple[dict[str, int], float]:
    residual = bqm.copy()
    residual.fix_variables({str(key): int(value) for key, value in fixed_assignment.items()})
    slack = dict(dimod.ExactSolver().sample(residual).first.sample) if residual.num_variables else {}
    completed = {str(variable): 0 for variable in bqm.variables}
    completed.update({str(key): int(value) for key, value in fixed_assignment.items()})
    completed.update({str(key): int(value) for key, value in slack.items()})
    return completed, float(bqm.energy(completed))


def raw_feasibility(
    sample: Mapping[str, int],
    instance: DispatchInstance,
) -> tuple[bool, int, int]:
    onehot = 0
    for customer in instance.customers:
        assigned = sum(
            int(sample.get(assignment_var(customer.customer_id, vehicle), 0))
            for vehicle in range(instance.num_vehicles)
        )
        if assigned != 1:
            onehot += 1
    assignments = decode_assignment(dict(sample), instance.customers, instance.num_vehicles)
    capacity = sum(
        1
        for customers in assignments.values()
        if sum(customer.demand for customer in customers) > instance.vehicle_capacity
    )
    return onehot == 0 and capacity == 0, onehot, capacity


def evaluate_bitstring(
    *,
    instance_id: str,
    source: str,
    bitstring: str,
    count: int,
    shots_received: int,
    instance: DispatchInstance,
    bqm: dimod.BinaryQuadraticModel,
    selected_customer_ids: Iterable[int],
    bit_order: str = BIT_ORDER_OPENQASM,
    exact_optimum_energy: Optional[float] = None,
    random_median_energy: Optional[float] = None,
    classical_threshold_all: Optional[float] = None,
    classical_threshold_feasible: Optional[float] = None,
    quality_tau: float = DEFAULT_QUALITY_TAU,
    near_quality_tau: float = DEFAULT_NEAR_QUALITY_TAU,
    tolerance: float = DEFAULT_ENERGY_TOLERANCE,
    task_id: Optional[str] = None,
    backend: Optional[str] = None,
) -> CandidateEvaluation:
    fixed = fixed_assignment_from_bitstring(
        bitstring,
        selected_customer_ids,
        num_vehicles=instance.num_vehicles,
        bit_order=bit_order,
    )
    completed, energy = complete_min_energy_sample(bqm, fixed)
    feasible, onehot, capacity = raw_feasibility(completed, instance)
    gap = None if exact_optimum_energy is None else energy - float(exact_optimum_energy)
    normalized = None
    if exact_optimum_energy is not None and random_median_energy is not None:
        denominator = float(random_median_energy) - float(exact_optimum_energy)
        if abs(denominator) > tolerance:
            normalized = (energy - float(exact_optimum_energy)) / denominator
    return CandidateEvaluation(
        instance_id=instance_id,
        source=source,
        bitstring=bitstring,
        count=int(count),
        probability=(int(count) / shots_received) if shots_received else 0.0,
        energy=energy,
        raw_feasible=feasible,
        onehot_violation_count=onehot,
        capacity_violation_count=capacity,
        task_id=task_id,
        backend=backend,
        exact_energy=exact_optimum_energy,
        energy_gap=gap,
        normalized_score=normalized,
        quality_gate_pass=(feasible and normalized <= quality_tau) if normalized is not None else None,
        near_quality_gate_pass=(feasible and normalized <= near_quality_tau) if normalized is not None else None,
        classical_reach_all_pass=(energy <= classical_threshold_all + tolerance)
        if classical_threshold_all is not None
        else None,
        classical_reach_feasible_pass=(feasible and energy <= classical_threshold_feasible + tolerance)
        if classical_threshold_feasible is not None
        else None,
        strict_improvement_all_pass=(energy < classical_threshold_all - tolerance)
        if classical_threshold_all is not None
        else None,
        strict_improvement_feasible_pass=(feasible and energy < classical_threshold_feasible - tolerance)
        if classical_threshold_feasible is not None
        else None,
    )


def exact_assignment_reference(
    instance: DispatchInstance,
    bqm: dimod.BinaryQuadraticModel,
    *,
    selected_customer_ids: Optional[Iterable[int]] = None,
    bit_order: str = BIT_ORDER_OPENQASM,
    quality_tau: float = DEFAULT_QUALITY_TAU,
    tolerance: float = DEFAULT_ENERGY_TOLERANCE,
) -> dict[str, Any]:
    selected = list(selected_customer_ids or [c.customer_id for c in instance.customers])
    if len(selected) != len(instance.customers):
        raise ValueError("exact assignment reference requires 100% customer coverage")
    energies: list[tuple[float, bool]] = []
    for bits in product("01", repeat=len(selected)):
        bitstring_qubit_order = "".join(bits)
        bitstring = bitstring_qubit_order[::-1] if bit_order == BIT_ORDER_OPENQASM else bitstring_qubit_order
        fixed = fixed_assignment_from_bitstring(
            bitstring,
            selected,
            num_vehicles=instance.num_vehicles,
            bit_order=bit_order,
        )
        completed, energy = complete_min_energy_sample(bqm, fixed)
        feasible, _onehot, _capacity = raw_feasibility(completed, instance)
        energies.append((energy, feasible))
    exact = min(energy for energy, _ in energies)
    random_median = statistics.median(energy for energy, _ in energies)
    denominator = random_median - exact
    if abs(denominator) <= tolerance:
        random_hit_rate = None
    else:
        qualifying = sum(
            1
            for energy, feasible in energies
            if feasible and (energy - exact) / denominator <= quality_tau
        )
        random_hit_rate = qualifying / len(energies)
    return {
        "exact_optimum_energy": exact,
        "random_median_energy": random_median,
        "random_quality_hit_rate": random_hit_rate,
        "enumerated_assignments": len(energies),
    }


def evaluate_measurement(
    measurement: QuantumMeasurementResult,
    *,
    instance_id: str,
    instance: DispatchInstance,
    bqm: dimod.BinaryQuadraticModel,
    threshold_info: Mapping[str, Any],
    quality_tau: float = DEFAULT_QUALITY_TAU,
    near_quality_tau: float = DEFAULT_NEAR_QUALITY_TAU,
    tolerance: float = DEFAULT_ENERGY_TOLERANCE,
) -> tuple[list[CandidateEvaluation], ExperimentSummary]:
    exact = threshold_info.get("exact_optimum_energy")
    random_median = threshold_info.get("random_median_energy")
    random_rate = threshold_info.get("random_quality_hit_rate")
    threshold_all = threshold_info.get("best_classical_energy_all")
    threshold_feasible = threshold_info.get("best_classical_energy_feasible")
    evaluations = [
        evaluate_bitstring(
            instance_id=instance_id,
            source=measurement.source,
            bitstring=bitstring,
            count=count,
            shots_received=measurement.shots_received,
            instance=instance,
            bqm=bqm,
            selected_customer_ids=measurement.selected_customer_ids,
            bit_order=measurement.bit_order,
            exact_optimum_energy=exact,
            random_median_energy=random_median,
            classical_threshold_all=threshold_all,
            classical_threshold_feasible=threshold_feasible,
            quality_tau=quality_tau,
            near_quality_tau=near_quality_tau,
            tolerance=tolerance,
            task_id=measurement.task_id,
            backend=measurement.backend,
        )
        for bitstring, count in sorted(measurement.counts.items(), key=lambda item: item[1], reverse=True)
    ]
    shots = measurement.shots_received

    def weighted_rate(field: str) -> Optional[float]:
        values = [getattr(row, field) for row in evaluations]
        if not evaluations or all(value is None for value in values) or shots <= 0:
            return None
        return sum(row.count for row in evaluations if getattr(row, field) is True) / shots

    quality_rate = weighted_rate("quality_gate_pass")
    raw_feasible_rate = (
        sum(row.count for row in evaluations if row.raw_feasible) / shots if shots else None
    )
    if not evaluations or shots <= 0 or quality_rate is None:
        decision = "NOT_EVALUABLE"
        conclusion = "NOT_EVALUABLE: evidence is insufficient to evaluate absolute quantum-candidate quality."
    elif quality_rate > 0:
        decision = "PASS"
        if random_rate is not None and quality_rate > float(random_rate):
            conclusion = "Sampling shows a higher hit rate than uniform random for the prespecified low-energy feasible region."
        else:
            conclusion = "At least one sample reached the prespecified low-energy feasible region; superiority to random was not established."
    else:
        decision = "FAIL"
        conclusion = "No sample reached the prespecified low-energy feasible region under the frozen criterion."
    gain = quality_rate - float(random_rate) if quality_rate is not None and random_rate is not None else None
    lift = (
        quality_rate / float(random_rate)
        if quality_rate is not None and random_rate not in {None, 0}
        else None
    )
    gaps = [row.energy_gap for row in evaluations if row.energy_gap is not None]
    summary = ExperimentSummary(
        instance_id=instance_id,
        source=measurement.source,
        decision=decision,
        shots_requested=measurement.shots_requested,
        shots_received=shots,
        unique_bitstrings=len(evaluations),
        qualified_unique=sum(row.quality_gate_pass is True for row in evaluations),
        raw_feasible_rate=raw_feasible_rate,
        quality_hit_rate=quality_rate,
        near_quality_hit_rate=weighted_rate("near_quality_gate_pass"),
        random_quality_hit_rate=random_rate,
        quality_hit_gain=gain,
        quality_lift=lift,
        classical_reach_all_rate=weighted_rate("classical_reach_all_pass"),
        classical_reach_feasible_rate=weighted_rate("classical_reach_feasible_pass"),
        strict_improvement_rate=weighted_rate("strict_improvement_feasible_pass"),
        best_gap=min(gaps) if gaps else None,
        conclusion=conclusion,
        task_id=measurement.task_id,
        backend=measurement.backend,
        warnings=list(measurement.warnings),
    )
    return evaluations, summary
