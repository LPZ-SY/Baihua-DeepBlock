from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
EXPERIMENTS_DIR = ROOT / "experiments"
if str(EXPERIMENTS_DIR) not in sys.path:
    sys.path.insert(0, str(EXPERIMENTS_DIR))

from generate_paper_artifacts import _read_csv, _statistics  # noqa: E402


def test_smoke_statistics_use_tasks_and_preserve_backend_strata():
    result_dir = ROOT / "results" / "experiments" / "qrf_cross_backend_smoke_20260801"
    rows = _read_csv(result_dir / "instance_summary.csv")
    statistics, backend_rows, instance_rows = _statistics(rows)
    assert statistics["statistical_unit"] == "hardware task"
    assert statistics["shots_are_not_independent_replicates"] is True
    assert statistics["evaluable_tasks"] == 3
    assert set(statistics["by_backend"]) == {"Baihua", "Dongling", "Shenglian"}
    assert set(statistics["by_instance"]) == {"seed2026_c4_v2_medium"}
    assert backend_rows
    assert instance_rows


def test_generated_smoke_artifacts_keep_reach_and_strict_improvement_separate():
    result_dir = ROOT / "results" / "experiments" / "qrf_cross_backend_smoke_20260801"
    statistics = json.loads(
        (result_dir / "statistics_summary.json").read_text(encoding="utf-8")
    )
    assert "classical_reach_feasible_rate" in statistics["overall"]
    assert "strict_improvement_rate" in statistics["overall"]
    for name in (
        "quantum_vs_random_task.png",
        "backend_hit_rate_distribution.png",
        "classical_reach_vs_strict.png",
        "hybrid_cq_vs_cr_route_delta.png",
        "energy_cdf.png",
    ):
        path = result_dir / "figures" / name
        assert path.exists() and path.stat().st_size > 0
