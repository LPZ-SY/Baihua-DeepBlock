from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app_research as web_app  # noqa: E402


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
    assert {
        "main-tabs",
        "cq-load-btn",
        "batch-preview-btn",
        "history-refresh-btn",
        "history-instance-filter",
        "history-backend-filter",
        "history-status-filter",
        "history-source-filter",
    } <= ids
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


def test_candidate_quality_page_preserves_fresh_hardware_provenance():
    evidence = (
        ROOT
        / "results"
        / "experiments"
        / "qrf_cross_backend_smoke_20260801"
        / "raw_evidence"
        / "63bf003c200b1a23efbef71ad1810f5c3aa87ed71fe027da7718392ac9049d41.json"
    )
    thresholds = (
        ROOT
        / "experiments"
        / "configs"
        / "formal_hardware_matrix_v2_thresholds.json"
    )
    cards, _figure, conclusion, rows, _columns = web_app.load_candidate_quality(
        1,
        str(evidence),
        str(thresholds),
        2026,
        4,
        "medium",
    )
    assert len(cards) == 8
    assert len(rows) == 16
    assert conclusion.startswith("FRESH HARDWARE EVIDENCE")
    assert "backend=Baihua" in conclusion
    assert "task_id=2608012251527123036" in conclusion


def test_history_can_filter_task_level_hardware_rows_by_backend():
    rows, columns = web_app.refresh_history(
        1,
        str(ROOT / "results" / "experiments"),
        "seed2026_c4_v2_medium",
        "Dongling",
        "completed",
        "hardware",
    )
    assert columns
    assert rows
    assert all(row["backend_actual"] == "Dongling" for row in rows)
    assert all(row["source"] == "hardware" for row in rows)
