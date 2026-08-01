from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
EXPERIMENTS_DIR = ROOT / "experiments"
for path in (SRC_DIR, EXPERIMENTS_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from batch_candidate_quality import (  # noqa: E402
    BatchRunner,
    aggregate_summaries,
    expand_matrix,
)
from experiment_utils import ROOT as EXPERIMENT_ROOT  # noqa: E402
from quantum_route_forge import generate_dispatch_instance  # noqa: E402
from quantum_route_forge.quantum_measurements import canonical_sha256  # noqa: E402
from quantum_route_forge.result_store import ResultStore  # noqa: E402
from run_quarkstudio_candidate_quality import (  # noqa: E402
    _business_qasm,
    _selected_customers,
)
from validate_formal_result_store import validate_result_store  # noqa: E402


def test_formal_schema_and_task_addressable_artifacts_validate(tmp_path):
    config = json.loads(
        (EXPERIMENT_ROOT / "experiments" / "configs" / "formal_hardware_matrix_v2.json").read_text(
            encoding="utf-8"
        )
    )
    first_instance = config["instances"][0]
    config.update(
        {
            "experiment_id": "formal_schema_test",
            "backends": ["Baihua"],
            "repeats": 1,
            "instances": [first_instance],
            "execution_order": [
                {
                    "instance_id": first_instance["instance_id"],
                    "backend_requested": "Baihua",
                    "repeat_index": 1,
                }
            ],
            "execution_git_tag": "qrf-preformal-execution-v1",
        }
    )
    spec = expand_matrix(config)[0]
    expected_commit = subprocess.run(
        ["git", "rev-list", "-n", "1", config["execution_git_tag"]],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    instance = generate_dispatch_instance(
        seed=spec.seed,
        num_customers=spec.customers,
        num_vehicles=spec.vehicles,
        vehicle_capacity=spec.capacity,
    )
    qasm = _business_qasm(_selected_customers(instance.customers, spec.customers))
    evidence = {
        "schema_version": 2,
        "run_id": config["experiment_id"],
        "protocol_version": spec.protocol_version,
        "frozen_git_commit": spec.frozen_git_commit,
        "git_commit_actual": expected_commit,
        "protocol_config_sha256": spec.protocol_config_sha256,
        "task_key": spec.task_key,
        "instance_id": spec.instance_id,
        "repeat_index": spec.repeat,
        "source": "hardware",
        "platform": "quarkstudio",
        "task_id": "formal-schema-task-1",
        "backend": spec.backend,
        "backend_requested": spec.backend,
        "backend_actual": spec.backend,
        "status": "completed",
        "shots": spec.shots,
        "shots_received": spec.shots,
        "unique_bitstrings": 1,
        "raw_counts": {"0000": spec.shots},
        "counts": {"0000": spec.shots},
        "raw_response": {"status": "completed"},
        "selected_customer_ids": list(spec.selected_customer_ids_in_qubit_order),
        "bit_order": config["bit_order"],
        "circuit": qasm,
        "circuit_hash": spec.logical_qasm_sha256,
        "threshold_hash": "canonical-threshold-test-hash",
        "threshold_file_sha256": spec.threshold_sha256,
        "threshold_method": "same_budget_classical_and_exact_reference",
        "random_reference": {"quality_hit_rate": 0.375},
        "classical_reference": {"best_energy_feasible": -0.1},
        "submitted_at": "2026-08-01T00:00:00+00:00",
        "completed_at": "2026-08-01T00:01:00+00:00",
        "poll_count": None,
        "backend_queue_snapshot_before_submit": {spec.backend: 0},
        "compile_options": config["compile_options"],
        "hardware_metadata": {
            "physical_mapping": None,
            "compiled_depth": None,
            "two_qubit_gate_count": None,
            "swap_count": None,
            "calibration": None,
        },
        "dependency_snapshot": {"python_version": sys.version.split()[0]},
        "qubit_count": spec.customers,
    }

    store = ResultStore(tmp_path, config["experiment_id"])
    config_hash = store.initialize_config(config)
    store.write_manifest({"config_hash": config_hash, "task_count": 1})
    thresholds = json.loads(
        (ROOT / config["threshold_file"]).read_text(encoding="utf-8")
    )
    store.write_thresholds(thresholds)
    store.write_protocol_snapshot({"config_sha256": canonical_sha256(config)})
    store.write_baseline_manifest({"git_tag": config["baseline_git_tag"]})

    runner = BatchRunner(
        store,
        lambda _spec: {
            "summary": {
                "decision": "PASS",
                "source": "hardware",
                "task_id": evidence["task_id"],
                "backend_actual": spec.backend,
                "shots_received": spec.shots,
            },
            "evidence": evidence,
            "candidates": [
                {
                    "source": "hardware",
                    "bitstring": "0000",
                    "count": spec.shots,
                }
            ],
        },
        formal_sources={"hardware"},
    )
    summaries = runner.run([spec], max_hardware_tasks=1)
    store.write_instance_summary(summaries)
    store.write_aggregate_summary(aggregate_summaries(summaries))
    store.write_task_manifest(store.latest_tasks_by_hash().values())

    report = validate_result_store(config, store.path)
    assert report["valid"] is True
    assert report["complete"] is True
    task_dir = store.path / "tasks" / evidence["task_id"]
    assert (task_dir / "logical_qasm.qasm").read_text(encoding="utf-8") == qasm
    assert json.loads((task_dir / "counts.json").read_text(encoding="utf-8")) == {
        "0000": spec.shots
    }
