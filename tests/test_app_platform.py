from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app as web_app  # noqa: E402


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


def test_app_exposes_four_platform_tabs_and_hides_quantum_controls_in_classical_mode():
    ids = _component_ids(web_app.app.layout)
    assert {"main-tabs", "cq-load-btn", "batch-preview-btn", "history-refresh-btn"} <= ids
    assert web_app.toggle_quantum_connection("classical")["display"] == "none"
    assert "display" not in web_app.toggle_quantum_connection("quantum")


def test_classical_single_run_needs_no_token_and_labels_classical_energy():
    status, _figure, metrics, _table = web_app._generate_outputs(
        seed=2026,
        customers=8,
        vehicles=2,
        capacity=13,
        mode="classical",
        time_limit=8,
        quafu_token="",
        quafu_backend="",
        quafu_base_url="",
        quafu_shots=1024,
        quafu_max_qubits=8,
        quafu_wait="false",
        quafu_timeout_sec=25,
        quafu_proxy_url="",
        quafu_verify_ssl="true",
        quafu_result_task_id="",
        quafu_manual_bitstring="",
    )
    assert "Classical full-assignment energy" in status
    assert "total route distance" in metrics


def test_candidate_quality_page_can_replay_checked_in_evidence():
    cards, _figure, conclusion, rows, columns = web_app.load_candidate_quality(
        1,
        str(ROOT / "results" / "quarkstudio_candidate_quality_validated" / "task_evidence.json"),
        str(ROOT / "results" / "quarkstudio_candidate_quality_validated" / "frozen_thresholds.json"),
        2026,
        4,
        "medium",
    )
    assert len(cards) == 8
    assert len(rows) == 16
    assert columns
    assert conclusion.startswith("REPLAY")
