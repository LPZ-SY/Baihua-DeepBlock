from __future__ import annotations

import argparse
import csv
import json
import random
import statistics
import sys
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from experiment_utils import ROOT, build_bqm_for_instance, evaluate_sample

SRC_DIR = ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from quantum_route_forge import generate_dispatch_instance  # noqa: E402
from quantum_route_forge.candidate_quality import (  # noqa: E402
    complete_min_energy_sample,
    fixed_assignment_from_bitstring,
)


Candidate = dict[str, Any]


def _tag(rows: Iterable[Mapping[str, Any]], source: str) -> list[Candidate]:
    return [{**dict(row), "source": source} for row in rows]


def _weighted_quantum(rows: list[Candidate], count: int, rng: random.Random) -> list[Candidate]:
    if count <= 0:
        return []
    if not rows:
        raise ValueError("measured quantum candidates are required for C+Q")
    weights = [max(0, int(float(row.get("count", 1)))) for row in rows]
    if not any(weights):
        weights = [1] * len(rows)
    return [dict(row) for row in rng.choices(rows, weights=weights, k=count)]


def _take(rows: list[Candidate], count: int, rng: random.Random) -> list[Candidate]:
    if len(rows) < count:
        raise ValueError(f"candidate source has {len(rows)} rows but {count} are required")
    order = list(range(len(rows)))
    rng.shuffle(order)
    return [dict(rows[index]) for index in order[:count]]


def build_fair_candidate_pools(
    *,
    classical: Iterable[Mapping[str, Any]],
    random_candidates: Iterable[Mapping[str, Any]],
    quantum: Iterable[Mapping[str, Any]],
    total_budget: int,
    seed: int,
    deduplicate_quantum: bool = False,
) -> dict[str, list[Candidate]]:
    if total_budget <= 1 or total_budget % 2:
        raise ValueError("total_budget must be an even integer greater than one")
    rng = random.Random(seed)
    classical_rows = _tag(classical, "classical")
    random_rows = _tag(random_candidates, "uniform_random")
    quantum_rows = _tag(quantum, "quantum")
    half = total_budget // 2
    if deduplicate_quantum:
        unique: dict[str, Candidate] = {}
        for row in quantum_rows:
            bitstring = str(row.get("bitstring", ""))
            if bitstring and bitstring not in unique:
                unique[bitstring] = row
        selected_quantum = _take(list(unique.values()), half, rng)
    else:
        selected_quantum = _weighted_quantum(quantum_rows, half, rng)
    selected_classical = _take(classical_rows, total_budget, rng)
    shared_classical = [dict(row) for row in selected_classical[:half]]
    pools = {
        "C": selected_classical,
        "C+R": [dict(row) for row in shared_classical] + _take(random_rows, half, rng),
        "C+Q": [dict(row) for row in shared_classical] + selected_quantum,
        "Q-only": _weighted_quantum(quantum_rows, total_budget, rng),
    }
    if any(len(rows) != total_budget for rows in pools.values()):
        raise ValueError("all candidate pools must use the identical total budget")
    return pools


def evaluate_pools(
    pools: Mapping[str, list[Candidate]],
    evaluator: Callable[[Candidate], Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    best_by_group: dict[str, dict[str, Any]] = {}
    for group, candidates in pools.items():
        if not candidates:
            raise ValueError(f"candidate pool {group} is empty")
        evaluated = []
        for index, candidate in enumerate(candidates):
            metrics = dict(evaluator(candidate))
            row = {
                "group": group,
                "candidate_index": index,
                "source": candidate.get("source"),
                "bitstring": candidate.get("bitstring", ""),
                **metrics,
            }
            rows.append(row)
            evaluated.append(row)
        best_by_group[group] = min(
            evaluated,
            key=lambda row: (
                not bool(row.get("route_feasible", False)),
                float(row.get("route_distance_after_2opt", float("inf"))),
                float(row.get("assignment_energy", float("inf"))),
            ),
        )
        ranked = sorted(
            evaluated,
            key=lambda row: (
                not bool(row.get("route_feasible", False)),
                float(row.get("route_distance_after_2opt", float("inf"))),
                float(row.get("assignment_energy", float("inf"))),
            ),
        )
        for rank, row in enumerate(ranked, start=1):
            row["final_rank"] = rank
    classical = best_by_group["C"]
    cq = best_by_group["C+Q"]
    cr = best_by_group["C+R"]
    summary = {
        "candidate_budget": len(pools["C"]),
        "candidate_budget_by_group": {
            group: len(candidates) for group, candidates in pools.items()
        },
        "best_by_group": best_by_group,
        "D_C": float(classical["route_distance_after_2opt"]),
        "D_C_plus_R": float(cr["route_distance_after_2opt"]),
        "D_C_plus_Q": float(cq["route_distance_after_2opt"]),
        "delta_QR": float(cr["route_distance_after_2opt"])
        - float(cq["route_distance_after_2opt"]),
        "delta_QC": float(classical["route_distance_after_2opt"])
        - float(cq["route_distance_after_2opt"]),
        "delta_energy_C_to_CQ": float(classical["assignment_energy"])
        - float(cq["assignment_energy"]),
        "delta_distance_C_to_CQ": float(classical["route_distance_after_2opt"])
        - float(cq["route_distance_after_2opt"]),
        "paired_gain_CQ_vs_CR_energy": float(cr["assignment_energy"])
        - float(cq["assignment_energy"]),
        "paired_gain_CQ_vs_CR_distance": float(cr["route_distance_after_2opt"])
        - float(cq["route_distance_after_2opt"]),
        "quantum_source_win": cq.get("source") == "quantum",
        "final_source": {
            group: row.get("source") for group, row in best_by_group.items()
        },
        "quantum_candidates_in_C_plus_Q": sum(
            row.get("source") == "quantum" for row in rows if row["group"] == "C+Q"
        ),
        "best_quantum_rank_in_C_plus_Q": min(
            (
                int(row["final_rank"])
                for row in rows
                if row["group"] == "C+Q" and row.get("source") == "quantum"
            ),
            default=None,
        ),
        "repair_moved_customers": {
            group: int(row.get("repair_moved_customers", 0))
            for group, row in best_by_group.items()
        },
        "repair_and_route_change": {
            group: {
                "capacity_violations_before": row.get(
                    "capacity_violation_count_before_repair"
                ),
                "capacity_violations_after": row.get("capacity_violation_count"),
                "route_distance_before_2opt": row.get("route_distance_before_2opt"),
                "route_distance_after_2opt": row.get("route_distance_after_2opt"),
            }
            for group, row in best_by_group.items()
        },
    }
    return rows, summary


def aggregate_paired_results(summaries: list[Mapping[str, Any]]) -> dict[str, Any]:
    metric_names = [
        "delta_QR",
        "delta_QC",
        "delta_energy_C_to_CQ",
        "delta_distance_C_to_CQ",
        "paired_gain_CQ_vs_CR_energy",
        "paired_gain_CQ_vs_CR_distance",
    ]
    metrics: dict[str, Any] = {}
    evaluable = [row for row in summaries if row.get("decision", "EVALUATED") != "NOT_EVALUABLE"]
    for name in metric_names:
        values = [float(row[name]) for row in evaluable if row.get(name) is not None]
        rng = random.Random(2026)
        bootstrap_means = sorted(
            statistics.fmean(rng.choice(values) for _ in range(len(values)))
            for _ in range(2000)
        ) if values else []
        metrics[name] = {
            "mean": statistics.fmean(values) if values else None,
            "median": statistics.median(values) if values else None,
            "standard_deviation": statistics.stdev(values) if len(values) > 1 else 0.0 if values else None,
            "positive_instance_rate": sum(value > 0 for value in values) / len(values) if values else None,
            "bootstrap_95_ci": (
                [
                    bootstrap_means[int(0.025 * len(bootstrap_means))],
                    bootstrap_means[int(0.975 * len(bootstrap_means)) - 1],
                ]
                if bootstrap_means
                else None
            ),
            "values": values,
        }
    positive_qr = sum(
        float(row.get("delta_QR", 0.0)) > 0 for row in evaluable
    )
    if not evaluable:
        conclusion = "NOT_EVALUABLE: no completed eligible measured-candidate task is available."
    elif positive_qr == 0:
        conclusion = (
            "No task-level C+Q route-distance improvement over C+R was observed. "
            "A quantum-source tie-break win is not reported as a route improvement."
        )
    elif positive_qr < len(evaluable):
        conclusion = (
            "C+Q improved route distance over C+R for some tasks only; the incremental "
            "contribution is instance/task dependent."
        )
    else:
        conclusion = (
            "C+Q improved route distance over C+R for every evaluable task in this frozen "
            "dataset; the observation is not generalized beyond the tested matrix."
        )
    return {
        "tasks": len(summaries),
        "evaluable_tasks": len(evaluable),
        "not_evaluable_tasks": len(summaries) - len(evaluable),
        "quantum_source_win_rate": (
            sum(bool(row.get("quantum_source_win")) for row in evaluable) / len(evaluable)
            if evaluable
            else None
        ),
        "metrics": metrics,
        "conclusion": conclusion,
    }


def _sample_from_candidate(candidate: Candidate, instance, bqm) -> dict[str, int]:
    if isinstance(candidate.get("sample"), dict):
        return {str(key): int(value) for key, value in candidate["sample"].items()}
    bitstring = str(candidate.get("bitstring", ""))
    if not bitstring:
        raise ValueError("candidate requires sample or bitstring")
    fixed = fixed_assignment_from_bitstring(
        bitstring,
        [customer.customer_id for customer in instance.customers],
        num_vehicles=instance.num_vehicles,
    )
    sample, _energy = complete_min_energy_sample(bqm, fixed)
    return sample


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Fair C/C+R/C+Q hybrid contribution experiment")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--outdir", type=Path, required=True)
    parser.add_argument("--deduplicate-quantum", action="store_true")
    args = parser.parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    all_rows: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    for raw in payload.get("instances", []):
        instance_id = str(raw.get("instance_id") or f"seed{raw['seed']}_c{raw['customers']}")
        allowed_sources = set(payload.get("formal_quantum_sources", ["hardware"]))
        measurement_source = str(raw.get("measurement_source", "hardware"))
        measurement_status = str(raw.get("measurement_status", "completed")).lower()
        if (
            not raw.get("quantum")
            or measurement_source not in allowed_sources
            or measurement_status != "completed"
        ):
            summaries.append(
                {
                    "instance_id": instance_id,
                    "task_id": raw.get("task_id"),
                    "backend": raw.get("backend"),
                    "repeat_index": raw.get("repeat_index"),
                    "task_key": raw.get("task_key"),
                    "decision": "NOT_EVALUABLE",
                    "reason": (
                        "C+Q requires completed measured candidates from an eligible source; "
                        "no classical-only substitution is permitted."
                    ),
                }
            )
            continue
        instance = generate_dispatch_instance(
            seed=int(raw["seed"]),
            num_customers=int(raw["customers"]),
            num_vehicles=int(raw.get("vehicles", 2)),
            vehicle_capacity=int(raw["capacity"]),
        )
        bqm = build_bqm_for_instance(instance)
        pools = build_fair_candidate_pools(
            classical=raw["classical"],
            random_candidates=raw["random"],
            quantum=raw["quantum"],
            total_budget=int(payload.get("candidate_budget", 20)),
            seed=int(raw["seed"]),
            deduplicate_quantum=args.deduplicate_quantum,
        )

        def evaluator(candidate: Candidate) -> Mapping[str, Any]:
            sample = _sample_from_candidate(candidate, instance, bqm)
            return evaluate_sample(
                instance,
                bqm,
                sample,
                two_opt_rounds=int(payload.get("two_opt_rounds", 2)),
            )

        rows, summary = evaluate_pools(pools, evaluator)
        all_rows.extend({"instance_id": instance_id, **row} for row in rows)
        summaries.append(
            {
                "instance_id": instance_id,
                "task_id": raw.get("task_id"),
                "backend": raw.get("backend"),
                "repeat_index": raw.get("repeat_index"),
                "task_key": raw.get("task_key"),
                "decision": "EVALUATED",
                **summary,
            }
        )
    args.outdir.mkdir(parents=True, exist_ok=True)
    _write_csv(args.outdir / "hybrid_candidates.csv", all_rows)
    (args.outdir / "hybrid_instance_summary.json").write_text(
        json.dumps(summaries, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    aggregate = aggregate_paired_results(summaries)
    (args.outdir / "hybrid_aggregate_summary.json").write_text(
        json.dumps(aggregate, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(aggregate, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
