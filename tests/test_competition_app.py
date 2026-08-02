from __future__ import annotations

import os
from pathlib import Path
import sys

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


def test_competition_app_has_four_pages_and_forces_hardware_confirmation():
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
    assert mode.value == "deepblock_hardware"
    assert mode.disabled is True
    assert confirmation.value == ["confirm"]
    assert confirmation.options[0]["disabled"] is True


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
    assert label == "08-02 12:29 | Hardware | FAILED | a4cd72b9"
