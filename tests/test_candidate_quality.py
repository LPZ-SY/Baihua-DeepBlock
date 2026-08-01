from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from quantum_route_forge import generate_dispatch_instance
from quantum_route_forge.assignment_bqm import build_assignment_bqm
from quantum_route_forge.candidate_quality import (
    evaluate_bitstring,
    evaluate_measurement,
    exact_assignment_reference,
)
from quantum_route_forge.models import QuantumMeasurementResult


def _fixture():
    instance = generate_dispatch_instance(
        seed=2026,
        num_customers=4,
        num_vehicles=2,
        vehicle_capacity=10,
    )
    return instance, build_assignment_bqm(instance)


def test_exact_reference_and_three_gate_evaluation_are_populated():
    instance, bqm = _fixture()
    selected = [customer.customer_id for customer in instance.customers]
    reference = exact_assignment_reference(instance, bqm, selected_customer_ids=selected)
    measurement = QuantumMeasurementResult(
        source="replay",
        platform="quarkstudio",
        status="completed",
        task_id="fake",
        shots_requested=10,
        shots_received=10,
        counts={"0000": 4, "1001": 6},
        selected_customer_ids=selected,
    )
    threshold_info = {
        **reference,
        "best_classical_energy_all": 1e9,
        "best_classical_energy_feasible": 1e9,
    }
    rows, summary = evaluate_measurement(
        measurement,
        instance_id="seed2026_c4_v2_medium",
        instance=instance,
        bqm=bqm,
        threshold_info=threshold_info,
    )
    assert len(rows) == 2
    assert all(row.energy_gap is not None for row in rows)
    assert all(row.classical_reach_all_pass is True for row in rows)
    assert summary.shots_received == 10
    assert summary.classical_reach_all_rate == 1.0
    assert summary.random_quality_hit_rate == reference["random_quality_hit_rate"]


def test_zero_normalization_denominator_is_not_silently_zero():
    instance, bqm = _fixture()
    selected = [customer.customer_id for customer in instance.customers]
    row = evaluate_bitstring(
        instance_id="case",
        source="simulator",
        bitstring="0000",
        count=1,
        shots_received=1,
        instance=instance,
        bqm=bqm,
        selected_customer_ids=selected,
        exact_optimum_energy=10.0,
        random_median_energy=10.0,
    )
    assert row.normalized_score is None
    assert row.quality_gate_pass is None
