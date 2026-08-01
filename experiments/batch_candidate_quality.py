from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional

from experiment_utils import ROOT, build_bqm_for_instance, infer_capacity_from_seed

SRC_DIR = ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from quantum_route_forge import generate_dispatch_instance  # noqa: E402
from quantum_route_forge.candidate_quality import (  # noqa: E402
    exact_assignment_reference,
    freeze_thresholds,
    raw_feasibility,
)
from quantum_route_forge.quantum_measurements import canonical_sha256  # noqa: E402
from quantum_route_forge.result_store import ResultStore  # noqa: E402


@dataclass(frozen=True)
class BatchTaskSpec:
    experiment_id: str
    seed: int
    customers: int
    vehicles: int
    capacity_pressure: str
    capacity: int
    shots: int
    repeat: int
    backend: str
    num_sweeps: int

    @property
    def instance_id(self) -> str:
        return (
            f"seed{self.seed}_c{self.customers}_v{self.vehicles}_"
            f"{self.capacity_pressure}"
        )

    @property
    def config_hash(self) -> str:
        return canonical_sha256(asdict(self))

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "instance_id": self.instance_id, "config_hash": self.config_hash}


def _pressure_ratio(name: str) -> float:
    try:
        return {"loose": 1.30, "medium": 1.15, "tight": 1.0}[name]
    except KeyError as exc:
        raise ValueError(f"unsupported capacity pressure: {name}") from exc


def expand_matrix(config: Mapping[str, Any]) -> list[BatchTaskSpec]:
    experiment_id = str(config["experiment_id"])
    shots = int(config.get("shots", 1024))
    if shots <= 0 or shots % 1024 != 0:
        raise ValueError("shots must be a positive multiple of 1024")
    base_specs: list[BatchTaskSpec] = []
    repeats = max(1, int(config.get("repeats", 1)))
    for customers in config.get("customers", [4, 6, 8]):
        for vehicles in config.get("vehicles", [2]):
            if int(vehicles) != 2:
                raise ValueError("formal candidate-quality matrix requires vehicles=2")
            for seed in config.get("seeds", [2026, 2027, 2028]):
                for pressure in config.get("capacity_pressure", ["medium", "tight"]):
                    capacity = infer_capacity_from_seed(
                        int(seed),
                        int(customers),
                        int(vehicles),
                        ratio=_pressure_ratio(str(pressure)),
                    )
                    for repeat in range(1, repeats + 1):
                        base_specs.append(
                            BatchTaskSpec(
                                experiment_id=experiment_id,
                                seed=int(seed),
                                customers=int(customers),
                                vehicles=int(vehicles),
                                capacity_pressure=str(pressure),
                                capacity=capacity,
                                shots=shots,
                                repeat=repeat,
                                backend=str(config.get("backend", "auto")),
                                num_sweeps=int(config.get("classical_num_sweeps", 40)),
                            )
                        )
    selected_count = max(0, int(config.get("repeat_selected_instances", 0)))
    repeat_count = max(repeats, int(config.get("repeat_count", repeats)))
    if selected_count and repeat_count > repeats:
        unique = []
        seen = set()
        for spec in base_specs:
            key = (spec.seed, spec.customers, spec.vehicles, spec.capacity_pressure)
            if key not in seen:
                unique.append(spec)
                seen.add(key)
        for selected in unique[:selected_count]:
            for repeat in range(repeats + 1, repeat_count + 1):
                base_specs.append(
                    BatchTaskSpec(**{**asdict(selected), "repeat": repeat})
                )
    return sorted(
        base_specs,
        key=lambda spec: (
            spec.customers,
            spec.seed,
            spec.capacity_pressure,
            spec.repeat,
        ),
    )


def bootstrap_ci(
    values: Iterable[float],
    *,
    confidence: float = 0.95,
    resamples: int = 2000,
    seed: int = 2026,
) -> Optional[dict[str, float]]:
    data = [float(value) for value in values if math.isfinite(float(value))]
    if not data:
        return None
    rng = random.Random(seed)
    means = sorted(
        statistics.fmean(rng.choice(data) for _ in range(len(data)))
        for _ in range(max(100, int(resamples)))
    )
    alpha = (1.0 - confidence) / 2.0
    low_index = max(0, min(len(means) - 1, int(alpha * len(means))))
    high_index = max(0, min(len(means) - 1, int((1.0 - alpha) * len(means)) - 1))
    return {
        "mean": statistics.fmean(data),
        "median": statistics.median(data),
        "low": means[low_index],
        "high": means[high_index],
        "confidence": confidence,
        "n": len(data),
    }


def freeze_batch_thresholds(
    config: Mapping[str, Any],
    specs: Iterable[BatchTaskSpec],
) -> dict[str, Any]:
    import dimod

    baseline: dict[str, list[dict[str, Any]]] = {}
    references: dict[str, dict[str, Any]] = {}
    for spec in specs:
        if spec.instance_id in baseline:
            continue
        instance = generate_dispatch_instance(
            seed=spec.seed,
            num_customers=spec.customers,
            num_vehicles=spec.vehicles,
            vehicle_capacity=spec.capacity,
        )
        bqm = build_bqm_for_instance(instance)
        random.seed(spec.seed)
        samples = dimod.SimulatedAnnealingSampler().sample(
            bqm,
            num_reads=spec.shots,
            num_sweeps=spec.num_sweeps,
        )
        rows = []
        for datum in samples.data(fields=["sample", "energy"]):
            sample = {str(key): int(value) for key, value in dict(datum.sample).items()}
            feasible, _onehot, _capacity = raw_feasibility(sample, instance)
            rows.append({"energy": float(bqm.energy(sample)), "feasible": feasible, "weight": 1})
        baseline[spec.instance_id] = rows
        references[spec.instance_id] = exact_assignment_reference(
            instance,
            bqm,
            selected_customer_ids=[customer.customer_id for customer in instance.customers],
        )
    return freeze_thresholds(
        baseline,
        int(config.get("shots", 1024)),
        exact_references=references,
        quality_tau=float(config.get("quality_tau", 0.20)),
        near_quality_tau=float(config.get("near_quality_tau", 0.50)),
        energy_tolerance=float(config.get("energy_tolerance", 1e-9)),
        metadata={"experiment_id": config["experiment_id"], "config_hash": canonical_sha256(config)},
    )


Executor = Callable[[BatchTaskSpec], Mapping[str, Any]]


class BatchRunner:
    def __init__(self, store: ResultStore, executor: Executor):
        self.store = store
        self.executor = executor

    def run(
        self,
        specs: Iterable[BatchTaskSpec],
        *,
        max_hardware_tasks: Optional[int] = None,
        resume: bool = False,
        retry_failed: bool = False,
    ) -> list[dict[str, Any]]:
        latest = self.store.latest_tasks_by_hash()
        completed_this_run = 0
        summaries: list[dict[str, Any]] = []
        for spec in specs:
            if (self.store.path / ".pause").exists():
                break
            previous = latest.get(spec.config_hash)
            if resume and previous and previous.get("status") == "completed":
                continue
            if retry_failed and (not previous or previous.get("status") != "failed"):
                continue
            if max_hardware_tasks is not None and completed_this_run >= max_hardware_tasks:
                break
            try:
                output = dict(self.executor(spec))
                evidence = output.pop("evidence", None)
                candidates = list(output.pop("candidates", []))
                summary = dict(output.pop("summary", output))
                evidence_path = None
                evidence_hash = None
                if evidence is not None:
                    path, evidence_hash = self.store.save_evidence(spec.config_hash, evidence)
                    evidence_path = str(path)
                self.store.append_candidates(
                    ({**row, "config_hash": spec.config_hash} for row in candidates)
                )
                task_row = {
                    **spec.to_dict(),
                    "status": "completed",
                    "evaluation_decision": summary.get("decision"),
                    "task_id": summary.get("task_id"),
                    "source": summary.get("source"),
                    "evidence_path": evidence_path,
                    "evidence_sha256": evidence_hash,
                }
                self.store.append_task(task_row)
                summaries.append({**spec.to_dict(), **summary})
            except Exception as exc:  # task-level fault isolation is intentional
                self.store.append_task(
                    {
                        **spec.to_dict(),
                        "status": "failed",
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
                if not retry_failed:
                    summaries.append(
                        {**spec.to_dict(), "decision": "NOT_EVALUABLE", "error": str(exc)}
                    )
            completed_this_run += 1
        return summaries


def aggregate_summaries(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    metrics = [
        "raw_feasible_rate",
        "quality_hit_rate",
        "random_quality_hit_rate",
        "classical_reach_feasible_rate",
        "strict_improvement_rate",
        "best_gap",
    ]
    return {
        "instances": len(rows),
        "decisions": {
            decision: sum(row.get("decision") == decision for row in rows)
            for decision in ("PASS", "FAIL", "NOT_EVALUABLE")
        },
        "metrics": {
            metric: bootstrap_ci(
                [float(row[metric]) for row in rows if row.get(metric) not in {None, ""}]
            )
            for metric in metrics
        },
        "claim_scope": (
            "Aggregate statistics describe candidate quality under the frozen matrix; "
            "they are not a claim of universal quantum or speed advantage."
        ),
    }


def _subprocess_executor(
    python: Path,
    frozen_path: Path,
    reuse_evidence: Optional[Path],
    store: ResultStore,
) -> Executor:
    script = ROOT / "experiments" / "run_quarkstudio_candidate_quality.py"

    def execute(spec: BatchTaskSpec) -> Mapping[str, Any]:
        outdir = store.path / "instances" / spec.config_hash
        command = [
            str(python),
            str(script),
            "--seed",
            str(spec.seed),
            "--customers",
            str(spec.customers),
            "--vehicles",
            str(spec.vehicles),
            "--capacity-pressure",
            spec.capacity_pressure,
            "--shots",
            str(spec.shots),
            "--num-sweeps",
            str(spec.num_sweeps),
            "--backend",
            spec.backend,
            "--outdir",
            str(outdir),
            "--frozen-thresholds",
            str(frozen_path),
        ]
        if reuse_evidence is not None:
            command.extend(["--reuse-evidence", str(reuse_evidence)])
        completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or completed.stdout.strip())
        summary = json.loads((outdir / "quantum_candidate_quality_summary.json").read_text(encoding="utf-8"))
        evidence = json.loads((outdir / "task_evidence.json").read_text(encoding="utf-8"))
        candidates: list[dict[str, Any]] = []
        candidate_path = outdir / "quantum_candidates.csv"
        if candidate_path.exists() and candidate_path.stat().st_size:
            import csv

            with candidate_path.open("r", encoding="utf-8-sig", newline="") as stream:
                candidates = list(csv.DictReader(stream))
        return {"summary": summary, "evidence": evidence, "candidates": candidates}

    return execute


def main() -> None:
    parser = argparse.ArgumentParser(description="Resumable Quantum Route Forge batch experiments")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--results-root", type=Path, default=ROOT / "results" / "experiments")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-hardware-tasks", type=int, default=None)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--reuse-evidence", type=Path, default=None)
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    specs = expand_matrix(config)
    store = ResultStore(args.results_root, str(config["experiment_id"]))
    config_hash = store.initialize_config(config)
    store.write_manifest(
        {
            "repository": config.get("repository", "LPZ-SY/kujinganlai-version"),
            "config_hash": config_hash,
            "task_count": len(specs),
            "total_requested_shots": sum(spec.shots for spec in specs),
            "mode": "dry_run" if args.dry_run else "evidence_replay" if args.reuse_evidence else "live_hardware",
        }
    )
    if args.dry_run:
        print(
            json.dumps(
                {
                    "experiment_id": config["experiment_id"],
                    "task_count": len(specs),
                    "total_requested_shots": sum(spec.shots for spec in specs),
                    "instances": [spec.to_dict() for spec in specs],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    frozen = freeze_batch_thresholds(config, specs)
    frozen_path = store.write_thresholds(frozen)
    runner = BatchRunner(
        store,
        _subprocess_executor(Path(sys.executable), frozen_path, args.reuse_evidence, store),
    )
    summaries = runner.run(
        specs,
        max_hardware_tasks=args.max_hardware_tasks,
        resume=args.resume,
        retry_failed=args.retry_failed,
    )
    store.write_instance_summary(summaries)
    aggregate = aggregate_summaries(summaries)
    store.write_aggregate_summary(aggregate)
    print(json.dumps(aggregate, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
