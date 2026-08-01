from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
EXPERIMENTS_DIR = ROOT / "experiments"
for path in (SRC_DIR, EXPERIMENTS_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from batch_candidate_quality import BatchRunner, BatchTaskSpec, expand_matrix  # noqa: E402
from quantum_route_forge.result_store import ResultStore  # noqa: E402


def _spec() -> BatchTaskSpec:
    return BatchTaskSpec(
        experiment_id="test",
        seed=2026,
        customers=4,
        vehicles=2,
        capacity_pressure="medium",
        capacity=6,
        shots=1024,
        repeat=1,
        backend="auto",
        num_sweeps=10,
    )


def test_result_store_is_idempotent_and_rejects_config_conflicts(tmp_path):
    store = ResultStore(tmp_path, "experiment")
    assert store.initialize_config({"a": 1}) == store.initialize_config({"a": 1})
    try:
        store.initialize_config({"a": 2})
    except ValueError as exc:
        assert "immutable config conflict" in str(exc)
    else:
        raise AssertionError("config conflict was not rejected")
    task = {"config_hash": "abc", "status": "completed", "evidence_sha256": "sha"}
    assert store.append_task(task) is True
    assert store.append_task(task) is False
    assert len(store.tasks()) == 1


def test_batch_resume_does_not_repeat_completed_config_hash(tmp_path):
    store = ResultStore(tmp_path, "experiment")
    store.initialize_config({"experiment_id": "experiment"})
    calls = []

    def executor(spec):
        calls.append(spec.config_hash)
        return {
            "summary": {"decision": "PASS", "source": "replay", "task_id": "fake"},
            "evidence": {"counts": {"0000": 1024}},
            "candidates": [{"source": "replay", "bitstring": "0000"}],
        }

    runner = BatchRunner(store, executor)
    assert len(runner.run([_spec()])) == 1
    assert runner.run([_spec()], resume=True) == []
    assert len(calls) == 1
    assert len(store.tasks()) == 1


def test_batch_resume_does_not_implicitly_retry_failed_task(tmp_path):
    store = ResultStore(tmp_path, "experiment")
    store.initialize_config({"experiment_id": "experiment"})
    calls = []

    def failing_executor(spec):
        calls.append(spec.config_hash)
        raise RuntimeError("synthetic failure")

    runner = BatchRunner(store, failing_executor)
    assert runner.run([_spec()])[0]["decision"] == "NOT_EVALUABLE"
    assert runner.run([_spec()], resume=True) == []
    assert len(calls) == 1

    assert runner.run([_spec()], retry_failed=True) == []
    assert len(calls) == 2


def test_matrix_expansion_honors_repeated_selected_instances():
    config = {
        "experiment_id": "matrix",
        "customers": [4],
        "vehicles": [2],
        "capacity_pressure": ["medium", "tight"],
        "seeds": [2026],
        "shots": 1024,
        "repeats": 1,
        "repeat_selected_instances": 1,
        "repeat_count": 3,
    }
    specs = expand_matrix(config)
    assert len(specs) == 4
    assert sum(spec.repeat > 1 for spec in specs) == 2


def test_formal_matrix_v2_is_balanced_fixed_and_unique():
    config_path = ROOT / "experiments" / "configs" / "formal_hardware_matrix_v2.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    specs = expand_matrix(config)

    assert len(specs) == 24
    assert len({spec.task_key for spec in specs}) == 24
    assert all(spec.backend != "auto" for spec in specs)
    assert [spec.execution_index for spec in specs] == list(range(1, 25))

    instance_ids = {spec.instance_id for spec in specs}
    assert len(instance_ids) == 4
    for instance_id in instance_ids:
        instance_specs = [spec for spec in specs if spec.instance_id == instance_id]
        assert len(instance_specs) == 6
        assert {(spec.backend, spec.repeat) for spec in instance_specs} == {
            (backend, repeat)
            for backend in ("Baihua", "Dongling", "Shenglian")
            for repeat in (1, 2)
        }
        assert len({spec.logical_qasm_sha256 for spec in instance_specs}) == 1
        assert len({spec.threshold_sha256 for spec in instance_specs}) == 1
        assert len(
            {spec.selected_customer_ids_in_qubit_order for spec in instance_specs}
        ) == 1


def test_formal_matrix_rejects_backend_auto():
    config_path = ROOT / "experiments" / "configs" / "formal_hardware_matrix_v2.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["backends"][0] = "auto"
    try:
        expand_matrix(config)
    except ValueError as exc:
        assert "forbids backend=auto" in str(exc)
    else:
        raise AssertionError("formal matrix accepted backend=auto")
