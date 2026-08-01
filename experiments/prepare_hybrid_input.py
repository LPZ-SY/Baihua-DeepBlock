from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from typing import Any, Mapping

from experiment_utils import ROOT, build_bqm_for_instance

SRC_DIR = ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from batch_candidate_quality import expand_matrix  # noqa: E402
from quantum_route_forge import generate_dispatch_instance  # noqa: E402
from quantum_route_forge.quantum_measurements import canonical_sha256  # noqa: E402
from validate_formal_result_store import validate_result_store  # noqa: E402


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def build_hybrid_input(
    config: Mapping[str, Any],
    experiment_dir: Path,
    *,
    candidate_budget: int = 20,
) -> dict[str, Any]:
    if candidate_budget <= 1 or candidate_budget % 2:
        raise ValueError("candidate_budget must be an even integer greater than one")
    validation = validate_result_store(config, experiment_dir)
    if not validation["valid"] or not validation["complete"]:
        raise ValueError("formal result store must be complete and valid before hybrid input generation")
    specs = expand_matrix(config)
    latest: dict[str, dict[str, Any]] = {}
    for row in _read_jsonl(experiment_dir / "tasks.jsonl"):
        latest[str(row["config_hash"])] = row
    candidates_by_hash: dict[str, list[dict[str, Any]]] = {}
    for row in _read_jsonl(experiment_dir / "candidates.jsonl"):
        candidates_by_hash.setdefault(str(row.get("config_hash", "")), []).append(row)

    import dimod

    units: list[dict[str, Any]] = []
    for spec in specs:
        task = latest[spec.config_hash]
        instance = generate_dispatch_instance(
            seed=spec.seed,
            num_customers=spec.customers,
            num_vehicles=spec.vehicles,
            vehicle_capacity=spec.capacity,
        )
        bqm = build_bqm_for_instance(instance)
        random.seed(spec.seed)
        classical_samples = dimod.SimulatedAnnealingSampler().sample(
            bqm,
            num_reads=candidate_budget,
            num_sweeps=spec.num_sweeps,
        )
        classical = [
            {
                "sample": {str(key): int(value) for key, value in dict(datum.sample).items()},
                "generation": "same_budget_classical_sa",
            }
            for datum in classical_samples.data(fields=["sample"])
        ]
        rng = random.Random(spec.seed)
        random_candidates = [
            {
                "sample": {str(variable): rng.randint(0, 1) for variable in bqm.variables},
                "generation": "uniform_random_bqm_assignment",
            }
            for _ in range(candidate_budget)
        ]
        quantum = [
            {
                "bitstring": str(row["bitstring"]),
                "count": int(float(row.get("count", 0))),
                "probability": float(row.get("probability", 0.0)),
                "task_id": task.get("task_id"),
                "backend": task.get("backend_actual"),
            }
            for row in candidates_by_hash.get(spec.config_hash, [])
            if str(row.get("source")) == "hardware"
        ]
        units.append(
            {
                "instance_id": spec.instance_id,
                "task_key": spec.task_key,
                "task_id": task.get("task_id"),
                "backend": task.get("backend_actual"),
                "repeat_index": spec.repeat,
                "seed": spec.seed,
                "customers": spec.customers,
                "vehicles": spec.vehicles,
                "capacity": spec.capacity,
                "measurement_source": task.get("source"),
                "measurement_status": task.get("status"),
                "classical": classical,
                "random": random_candidates,
                "quantum": quantum,
            }
        )
    return {
        "schema_version": 1,
        "source_experiment_id": config.get("experiment_id"),
        "source_config_sha256": canonical_sha256(config),
        "candidate_budget": candidate_budget,
        "two_opt_rounds": 2,
        "formal_quantum_sources": ["hardware"],
        "instances": units,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare fair task-level C/C+R/C+Q input")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--experiment-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--candidate-budget", type=int, default=20)
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    payload = build_hybrid_input(
        config,
        args.experiment_dir,
        candidate_budget=args.candidate_budget,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "source_experiment_id": payload["source_experiment_id"],
                "task_units": len(payload["instances"]),
                "candidate_budget": payload["candidate_budget"],
                "output": str(args.output),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
