from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from quantum_route_forge.models import QuantumMeasurementResult
from quantum_route_forge.quantum_measurements import (
    BIT_ORDER_OPENQASM,
    BIT_ORDER_QUBIT0_LEFT,
    bitstring_to_customer_preferences,
    formal_measurements,
    measurement_from_payload,
)


def test_nested_serialized_counts_are_cleaned_and_shots_are_verified():
    result = measurement_from_payload(
        {"result": {"res": '{"0011": 7, "1010": 3}'}},
        source="hardware",
        platform="sqc",
        status="Finished",
        shots_requested=10,
        selected_customer_ids=[1, 2, 3, 4],
    )
    assert result.status == "completed"
    assert result.counts == {"0011": 7, "1010": 3}
    assert result.shots_received == 10
    assert result.most_frequent_bitstring == "0011"
    assert result.warnings == []


def test_probabilities_are_converted_to_exact_integer_budget():
    result = measurement_from_payload(
        {"probabilities": {"00": 0.51, "11": 0.49}},
        source="simulator",
        platform="local",
        status="completed",
        shots_requested=10,
        selected_customer_ids=[1, 2],
    )
    assert result.counts == {"00": 5, "11": 5}
    assert result.shots_received == 10
    assert any("probabilities converted" in warning for warning in result.warnings)


def test_invalid_keys_and_shots_mismatch_are_explicit_warnings():
    result = measurement_from_payload(
        {"counts": {"0101": 3, "bad": 9, "01": 4}},
        source="replay",
        platform="quarkstudio",
        status="Finished",
        shots_requested=10,
        selected_customer_ids=[1, 2, 3, 4],
    )
    assert result.counts == {"0101": 3}
    assert result.shots_received == 3
    assert any("ignored 2" in warning for warning in result.warnings)
    assert any("shots mismatch" in warning for warning in result.warnings)


def test_bit_order_and_customer_order_are_deterministic():
    assert bitstring_to_customer_preferences(
        "1100", [10, 20, 30, 40], bit_order=BIT_ORDER_OPENQASM
    ) == {10: 0, 20: 0, 30: 1, 40: 1}
    assert bitstring_to_customer_preferences(
        "1100", [10, 20, 30, 40], bit_order=BIT_ORDER_QUBIT0_LEFT
    ) == {10: 1, 20: 1, 30: 0, 40: 0}


def test_only_completed_hardware_is_in_formal_statistics():
    def result(source: str, status: str = "completed") -> QuantumMeasurementResult:
        return QuantumMeasurementResult(
            source=source,
            platform="test",
            status=status,
            counts={"0": 1},
            shots_requested=1,
            shots_received=1,
        )

    values = [result("hardware"), result("replay"), result("manual_debug"), result("fallback")]
    assert formal_measurements(values) == [values[0]]
