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

from batch_candidate_quality import (  # noqa: E402
    BatchRunner,
    BatchTaskSpec,
    SubmittedTaskPendingError,
    build_dry_run_manifest,
    collect_stored_summaries,
    expand_matrix,
)
from quantum_route_forge.result_store import ResultStore  # noqa: E402
from quantum_route_forge.quantum_measurements import redact_text  # noqa: E402
from validate_formal_result_store import validate_result_store  # noqa: E402


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


def test_log_text_redaction_removes_common_credential_forms():
    fake_key = "sk-" + "a" * 22
    fake_bearer = "a" * 26
    fake_token = "b" * 21
    raw = (
        "Authorization" + ": Bearer " + fake_bearer + " "
        + "api_" + "token=" + fake_token + " " + fake_key
    )
    clean = redact_text(raw)
    assert fake_bearer not in clean
    assert fake_token not in clean
    assert fake_key not in clean
    assert clean.count("[REDACTED]") == 3


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
    task_dir = store.path / "tasks" / "fake"
    assert {
        "evidence.json",
        "raw_response.json",
        "counts.json",
        "summary.json",
        "candidate_metrics.csv",
    }.issubset({path.name for path in task_dir.iterdir()})


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
    failed = store.tasks()[0]
    evidence = json.loads(Path(failed["evidence_path"]).read_text(encoding="utf-8"))
    assert evidence["status"] == "failed"
    assert evidence["counts"] == {}
    assert "synthetic failure" in evidence["error"]


def test_submitted_receipt_remains_nonterminal_for_same_task_retrieval(tmp_path):
    store = ResultStore(tmp_path, "experiment")
    store.initialize_config({"experiment_id": "experiment"})
    receipt_path = store.path / "instances" / _spec().config_hash / "submission_receipt.json"
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt = {
        "task_key": _spec().task_key,
        "task_id": "2608019999999999999",
        "backend_requested": "auto",
        "backend_actual": "Baihua",
        "status": "submitted",
    }
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    def interrupted_after_submit(_task):
        raise SubmittedTaskPendingError("retrieve interrupted", receipt, receipt_path)

    runner = BatchRunner(store, interrupted_after_submit)
    summary = runner.run([_spec()])[0]
    assert summary["decision"] == "NOT_EVALUABLE"
    latest = store.latest_tasks_by_hash()[_spec().config_hash]
    assert latest["status"] == "submitted"
    assert latest["task_id"] == receipt["task_id"]
    assert not (store.raw_evidence_dir / f"{_spec().config_hash}.json").exists()


def test_cumulative_summary_rebuild_keeps_completed_tasks_after_resume(tmp_path):
    store = ResultStore(tmp_path, "experiment")
    store.initialize_config({"experiment_id": "experiment"})
    first = _spec()
    second = BatchTaskSpec(**{**first.__dict__, "backend": "Baihua"})
    for spec, rate in ((first, 0.25), (second, 0.5)):
        summary_dir = store.path / "instances" / spec.config_hash
        summary_dir.mkdir(parents=True, exist_ok=True)
        (summary_dir / "quantum_candidate_quality_summary.json").write_text(
            '{"decision": "PASS", "quality_hit_rate": ' + str(rate) + "}",
            encoding="utf-8",
        )
        store.append_task(
            {
                **spec.to_dict(),
                "status": "completed",
                "evidence_sha256": spec.config_hash,
            }
        )

    rows = collect_stored_summaries(store, [first, second])
    assert [row["quality_hit_rate"] for row in rows] == [0.25, 0.5]


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

    manifest = build_dry_run_manifest(config, specs)
    assert manifest["hardware_accessed"] is False
    assert manifest["task_count"] == manifest["unique_task_keys"] == 24
    assert manifest["total_requested_shots"] == 24576
    assert manifest["contains_backend_auto"] is False
    assert set(manifest["instance_task_counts"].values()) == {6}
    assert config["live_submission"]["max_tasks_per_invocation"] == 1
    assert config["live_submission"]["require_explicit_confirmation"] is True


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


def test_cross_backend_smoke_changes_only_the_requested_backend():
    config_path = ROOT / "experiments" / "configs" / "cross_backend_smoke_v1.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    specs = expand_matrix(config)

    assert len(specs) == 3
    assert [spec.backend for spec in specs] == ["Baihua", "Dongling", "Shenglian"]
    assert len({spec.task_key for spec in specs}) == 3
    assert len({spec.instance_id for spec in specs}) == 1
    assert len({spec.shots for spec in specs}) == 1
    assert len({spec.logical_qasm_sha256 for spec in specs}) == 1
    assert len({spec.threshold_sha256 for spec in specs}) == 1
    assert len({spec.selected_customer_ids_in_qubit_order for spec in specs}) == 1


def test_checked_in_cross_backend_smoke_store_passes_strict_validation():
    config_path = ROOT / "experiments" / "configs" / "cross_backend_smoke_v1.json"
    result_dir = ROOT / "results" / "experiments" / "qrf_cross_backend_smoke_20260801"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    report = validate_result_store(config, result_dir)
    assert report["valid"] is True
    assert report["complete"] is True
    assert report["planned_task_count"] == report["observed_task_count"] == 3
    assert report["errors"] == []
