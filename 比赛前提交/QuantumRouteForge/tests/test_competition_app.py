from __future__ import annotations

import os
from pathlib import Path
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app as competition_app  # noqa: E402


def test_configure_quafu_token_loads_local_file_without_overwriting_environment(
    tmp_path, monkeypatch
):
    env_file = tmp_path / ".env"
    env_file.write_text("QUAFU_API_TOKEN=local-test-token\n", encoding="utf-8")
    monkeypatch.delenv("QUAFU_API_TOKEN", raising=False)

    assert competition_app._configure_quafu_token(env_file) == "project_env"
    assert os.environ["QUAFU_API_TOKEN"] == "local-test-token"

    monkeypatch.setenv("QUAFU_API_TOKEN", "environment-token")
    assert competition_app._configure_quafu_token(env_file) == "environment"
    assert os.environ["QUAFU_API_TOKEN"] == "environment-token"


def _component_ids(component):
    found = set()
    component_id = getattr(component, "id", None)
    if component_id:
        found.add(component_id)
    children = getattr(component, "children", None)
    if children is None:
        return found
    if not isinstance(children, (list, tuple)):
        children = [children]
    for child in children:
        if hasattr(child, "children") or getattr(child, "id", None):
            found.update(_component_ids(child))
    return found


def test_competition_app_has_four_pages_and_defaults_to_safe_selectable_mode():
    ids = _component_ids(competition_app.app.layout)
    assert {
        "tabs",
        "run-btn",
        "hardware-confirm",
        "initial-route",
        "final-route",
        "block-table",
        "candidate-table",
        "comparison-table",
        "history-table",
        "open-history-btn",
    } <= ids
    mode = competition_app.app.layout["mode"]
    confirmation = competition_app.app.layout["hardware-confirm"]
    history_table = competition_app.app.layout["history-table"]
    route_table = competition_app.app.layout["route-table"]
    candidate_table = competition_app.app.layout["candidate-table"]
    comparison_table = competition_app.app.layout["comparison-table"]
    assert mode.value == "deepblock_simulator"
    assert getattr(mode, "disabled", False) is False
    assert confirmation.value == []
    assert "disabled" not in confirmation.options[0]
    assert history_table.fill_width is False
    assert route_table.fill_width is True
    assert candidate_table.fill_width is True
    assert comparison_table.fill_width is True
    assert "min-width: 0 !important" in competition_app.app.index_string


def test_execute_uses_selected_mode_without_submitting_hardware(monkeypatch):
    captured = {}
    monkeypatch.setattr(competition_app, "ctx", SimpleNamespace(triggered_id="run-btn"))
    monkeypatch.setattr(
        competition_app,
        "generate_dispatch_instance",
        lambda **_kwargs: SimpleNamespace(),
    )

    def fake_run(**kwargs):
        captured.update(kwargs)
        return {
            "run_id": "test-run",
            "parameters": {"mode": "deepblock_simulator"},
            "selected": {
                "status": "COMPLETED",
                "source": "simulator",
                "baseline_distance": 10.0,
                "final_distance": 9.0,
                "accepted_moves": 1,
            },
        }

    monkeypatch.setattr(competition_app, "run_deepblock_optimization", fake_run)
    monkeypatch.delenv("QUAFU_API_TOKEN", raising=False)

    payload, status = competition_app.execute_or_open(
        1,
        0,
        None,
        16,
        3,
        24,
        2026,
        "deepblock_simulator",
        "Baihua",
        4096,
        64,
        1,
        [],
    )

    assert payload["run_id"] == "test-run"
    assert captured["mode"] == "deepblock_simulator"
    assert captured["submit_hardware"] is False
    assert captured["confirm_hardware_submit"] is False
    assert status == "运行结果 · Ideal Simulator · 已完成 · 路线距离 10.000 → 9.000 · 接受改进 1 次"


def test_competition_app_empty_state_renders_all_outputs():
    outputs = competition_app.render_run(None)
    assert len(outputs) == 17
    assert outputs[3] == []
    assert outputs[10] == "{}"


def test_history_option_label_is_compact_and_in_china_time():
    label = competition_app._history_option_label(
        {
            "time": "2026-08-02T04:29:57.617109+00:00",
            "run_id": "20260802T042957Z-a4cd72b9",
            "mode": "deepblock_hardware",
            "status": "FAILED",
        }
    )
    assert label == "08-02 12:29 | DeepBlock Hardware | FAILED | a4cd72b9"


def test_history_table_formats_time_for_expert_display(monkeypatch):
    monkeypatch.setattr(
        competition_app.HISTORY,
        "rows",
        lambda: [
            {
                "run_id": "20260802T042957Z-a4cd72b9",
                "time": "2026-08-02T04:29:57.617109+00:00",
                "mode": "deepblock_random",
                "task_id": "2608021234567890123",
            }
        ],
    )

    rows, columns, options = competition_app.refresh_history(1, None)

    assert rows[0]["time"] == "2026-08-02 12:29:57"
    assert rows[0]["mode"] == "Random Baseline"
    assert {column["id"]: column["name"] for column in columns}["time"] == "时间"
    assert options[0]["label"].startswith("08-02 12:29 |")


def test_overlapping_trajectories_reports_the_visible_overlap():
    overlaps = competition_app._overlapping_trajectories(
        [
            {"name": "DeepBlock Hardware", "xs": ["Initial", "B1"], "ys": [10.0, 9.0]},
            {"name": "Random Baseline", "xs": ["Initial", "B1"], "ys": [10.0, 9.0]},
            {"name": "Exact Baseline", "xs": ["Initial", "B1"], "ys": [10.0, 8.0]},
        ]
    )

    assert overlaps == [
        {
            "names": ["DeepBlock Hardware", "Random Baseline"],
            "x": "B1",
            "y": 9.0,
        }
    ]
