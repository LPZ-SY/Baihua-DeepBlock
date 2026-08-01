from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
EXPERIMENTS_DIR = ROOT / "experiments"
if str(EXPERIMENTS_DIR) not in sys.path:
    sys.path.insert(0, str(EXPERIMENTS_DIR))

from hybrid_contribution import build_fair_candidate_pools, evaluate_pools  # noqa: E402
from prepare_hybrid_input import build_hybrid_input  # noqa: E402


def test_candidate_pools_have_equal_total_budget_and_source_replacement():
    classical = [{"score": index} for index in range(20)]
    random = [{"score": 100 + index} for index in range(20)]
    quantum = [{"bitstring": f"{index:04b}", "count": index + 1, "score": 50 + index} for index in range(16)]
    pools = build_fair_candidate_pools(
        classical=classical,
        random_candidates=random,
        quantum=quantum,
        total_budget=10,
        seed=2026,
    )
    assert all(len(pool) == 10 for pool in pools.values())
    assert sum(row["source"] == "classical" for row in pools["C+R"]) == 5
    assert sum(row["source"] == "uniform_random" for row in pools["C+R"]) == 5
    assert sum(row["source"] == "classical" for row in pools["C+Q"]) == 5
    assert sum(row["source"] == "quantum" for row in pools["C+Q"]) == 5
    assert [row["score"] for row in pools["C+R"][:5]] == [
        row["score"] for row in pools["C+Q"][:5]
    ]


def test_pool_evaluation_reports_paired_cq_vs_cr_metrics():
    pools = {
        "C": [{"source": "classical", "score": 10.0}],
        "C+R": [{"source": "uniform_random", "score": 9.0}],
        "C+Q": [{"source": "quantum", "score": 7.0}],
        "Q-only": [{"source": "quantum", "score": 8.0}],
    }

    def evaluator(candidate):
        return {
            "assignment_energy": candidate["score"],
            "route_distance_after_2opt": candidate["score"],
            "route_feasible": True,
            "repair_moved_customers": 0,
        }

    _rows, summary = evaluate_pools(pools, evaluator)
    assert summary["delta_distance_C_to_CQ"] == 3.0
    assert summary["paired_gain_CQ_vs_CR_distance"] == 2.0
    assert summary["D_C"] == 10.0
    assert summary["D_C_plus_R"] == 9.0
    assert summary["D_C_plus_Q"] == 7.0
    assert summary["delta_QR"] == 2.0
    assert summary["delta_QC"] == 3.0
    assert summary["quantum_source_win"] is True
    assert summary["final_source"]["C+Q"] == "quantum"


def test_missing_quantum_candidates_cannot_degrade_to_classical_only_cq():
    try:
        build_fair_candidate_pools(
            classical=[{"score": index} for index in range(10)],
            random_candidates=[{"score": index} for index in range(10)],
            quantum=[],
            total_budget=10,
            seed=2026,
        )
    except ValueError as exc:
        assert "measured quantum candidates" in str(exc)
    else:
        raise AssertionError("C+Q accepted an empty measured candidate source")


def test_checked_in_smoke_hybrid_input_is_reproducible_and_task_level():
    import json

    config = json.loads(
        (ROOT / "experiments" / "configs" / "cross_backend_smoke_v1.json").read_text(
            encoding="utf-8"
        )
    )
    result_dir = ROOT / "results" / "experiments" / "qrf_cross_backend_smoke_20260801"
    first = build_hybrid_input(config, result_dir, candidate_budget=20)
    second = build_hybrid_input(config, result_dir, candidate_budget=20)
    assert first == second
    assert len(first["instances"]) == 3
    assert all(unit["measurement_source"] == "hardware" for unit in first["instances"])
    assert all(len(unit["classical"]) == 20 for unit in first["instances"])
    assert all(len(unit["random"]) == 20 for unit in first["instances"])
    assert first["instances"][0]["classical"] == first["instances"][1]["classical"]
    assert first["instances"][0]["random"] == first["instances"][1]["random"]
