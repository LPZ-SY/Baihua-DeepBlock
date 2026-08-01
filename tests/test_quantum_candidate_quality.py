from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
EXPERIMENTS_DIR = ROOT / "experiments"
if str(EXPERIMENTS_DIR) not in sys.path:
    sys.path.insert(0, str(EXPERIMENTS_DIR))

from run_quantum_candidate_quality import (  # noqa: E402
    calibrate_thresholds,
    evaluate_quantum_candidates,
)


def test_pass_requires_energy_strictly_below_frozen_threshold():
    baseline = {
        "case-a": [
            {"energy": 12.0, "feasible": True, "weight": 1},
            {"energy": 10.0, "feasible": True, "weight": 1},
        ]
    }
    thresholds = calibrate_thresholds(baseline, budget=2)
    assert thresholds["instances"]["case-a"]["threshold"] == 10.0

    quantum = {
        "case-a": [
            {"energy": 9.0, "feasible": False, "weight": 1},
            {"energy": 9.5, "feasible": True, "weight": 1},
        ]
    }
    rows, summary = evaluate_quantum_candidates(quantum, thresholds)
    assert rows[0]["decision"] == "PASS"
    assert rows[0]["passing_shots"] == 2
    assert rows[0]["feasible_quantum_shots"] == 1
    assert summary["conclusion"] == "positive_contribution_observed"


def test_equal_energy_passes_quality_gate_but_is_not_strict_improvement():
    thresholds = calibrate_thresholds(
        {"case-a": [{"energy": 10.0, "feasible": True, "weight": 1}]},
        budget=1,
    )
    rows, _ = evaluate_quantum_candidates(
        {"case-a": [{"energy": 10.0, "feasible": True, "weight": 1}]},
        thresholds,
    )
    assert rows[0]["decision"] == "PASS"
    assert rows[0]["strictly_improving_shots"] == 0


def test_missing_quantum_samples_is_not_evaluable():
    thresholds = calibrate_thresholds(
        {"case-a": [{"energy": 10.0, "feasible": True, "weight": 1}]},
        budget=1,
    )
    rows, summary = evaluate_quantum_candidates({}, thresholds)
    assert rows[0]["decision"] == "NOT_EVALUABLE"
    assert summary["conclusion"] == "not_evaluable"


def test_incomplete_fixed_budget_is_not_evaluable():
    thresholds = calibrate_thresholds(
        {"case-a": [{"energy": 10.0, "feasible": True, "weight": 1}]},
        budget=2,
    )
    assert thresholds["instances"]["case-a"]["threshold"] is None

    complete_thresholds = calibrate_thresholds(
        {"case-a": [{"energy": 10.0, "feasible": True, "weight": 2}]},
        budget=2,
    )
    rows, _ = evaluate_quantum_candidates(
        {"case-a": [{"energy": 9.0, "feasible": True, "weight": 1}]},
        complete_thresholds,
    )
    assert rows[0]["decision"] == "NOT_EVALUABLE"


def test_threshold_does_not_depend_on_baseline_feasibility():
    thresholds = calibrate_thresholds(
        {"case-a": [{"energy": 8.0, "feasible": False, "weight": 2}]},
        budget=2,
    )
    assert thresholds["instances"]["case-a"]["threshold"] == 8.0
    assert thresholds["instances"]["case-a"]["feasible_baseline_shots"] == 0
