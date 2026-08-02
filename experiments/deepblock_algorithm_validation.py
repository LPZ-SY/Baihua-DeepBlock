from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path

import numpy as np

from deepblock_study import (
    ALGORITHM_DIR,
    CAPACITY_PENALTIES,
    OFFLINE_DIR,
    QUBO_VERSIONS,
    aggregate,
    annealing_candidates,
    build_proxy,
    context_from_payload,
    ensure_directories,
    enumerate_context,
    metric_for_candidates,
    multistart_candidates,
    pretrain_parameters,
    ideal_probabilities,
    read_jsonl,
    sample_probabilities,
    single_point_candidates,
    spearman,
    write_csv,
)


def _select_contexts(limit: int) -> list:
    payloads = read_jsonl(OFFLINE_DIR / "selected_instances.jsonl")
    if not payloads:
        raise FileNotFoundError("请先运行 deepblock_offline_analysis.py")
    contexts = []
    widths = (8, 10, 12, 14)
    for index in range(limit):
        contexts.append(context_from_payload(payloads[index % len(payloads)], width=widths[index % len(widths)]))
    return contexts


def _variant_diagnostics(context, space, version: str, penalty: float) -> dict[str, object]:
    proxy = build_proxy(context, version, penalty)
    energies = np.asarray([
        proxy.energy(tuple((state >> bit) & 1 for bit in range(context.width)))
        for state in space.states
    ])
    order = np.argsort(energies, kind="mergesort")
    improving = space.improving_mask
    low_count = max(1, math.ceil(len(order) * 0.10))
    row: dict[str, object] = {
        "instance_id": context.instance_id,
        "seed": context.seed,
        "block_size": context.width,
        "qubo_version": version,
        "capacity_penalty": penalty,
        "spearman_qubo_true_distance": spearman(energies, space.distances),
        "low_10pct_improving_ratio": float(np.mean(improving[order[:low_count]])),
        "feasible_state_ratio": float(np.mean(space.feasible_before)),
        "capacity_repair_ratio": float(np.mean(space.repaired)),
    }
    for top_k in (16, 32, 64):
        row[f"top_{top_k}_contains_improvement"] = bool(np.any(improving[order[:top_k]]))
    return row


def run(instance_count: int = 8) -> dict[str, object]:
    ensure_directories()
    contexts = _select_contexts(instance_count)
    method_rows: list[dict[str, object]] = []
    variant_rows: list[dict[str, object]] = []
    penalty_rows: list[dict[str, object]] = []
    shot_rows: list[dict[str, object]] = []
    exact_rows: list[dict[str, object]] = []

    for context_index, context in enumerate(contexts):
        full = build_proxy(context, "full_interaction", 25.0)
        space = enumerate_context(context, full)
        exact_rows.append({
            "instance_id": context.instance_id,
            "seed": context.seed,
            "block_size": context.width,
            "baseline_distance": context.baseline_distance,
            "exact_best_distance": space.best_distance,
            "exact_best_improvement": space.best_improvement,
            "improving_state_count": int(np.sum(space.improving_mask)),
        })
        qaoa_probabilities: dict[int, np.ndarray] = {}
        for depth in (1, 2, 3):
            parameters = pretrain_parameters(full, depth, rounds=2)
            qaoa_probabilities[depth] = ideal_probabilities(full, parameters)

        for budget in (32, 64, 128, 256):
            rng = np.random.default_rng(context.seed * 1000 + budget)
            methods = {
                "单点局部搜索": single_point_candidates(space, context.width, budget),
                "多起点局部搜索": multistart_candidates(space, context.width, budget, context.seed + budget),
                "模拟退火": annealing_candidates(space, context.width, budget, context.seed * 3 + budget),
                "Random": rng.integers(0, len(space.states), size=budget).tolist(),
                "Exact": np.argsort(space.distances)[: min(budget, len(space.states))].tolist(),
            }
            for depth, probabilities in qaoa_probabilities.items():
                methods[f"Ideal QAOA p={depth}"] = sample_probabilities(
                    probabilities, budget, context.seed * 10_000 + depth * 100 + budget
                )
            for method, candidates in methods.items():
                method_rows.append({
                    "instance_id": context.instance_id,
                    "seed": context.seed,
                    "block_size": context.width,
                    "method": method,
                    "candidate_budget": budget,
                    **metric_for_candidates(space, candidates),
                })

        for version in QUBO_VERSIONS:
            variant_rows.append(_variant_diagnostics(context, space, version, 25.0))
        for penalty in CAPACITY_PENALTIES:
            penalty_rows.append(_variant_diagnostics(context, space, "full_interaction", penalty))

        p2 = qaoa_probabilities[2]
        for shots in (64, 256, 1024):
            sampled = sample_probabilities(p2, shots, context.seed * 100_000 + shots)
            counts = np.bincount(sampled, minlength=len(p2))
            ranked = np.argsort(-counts, kind="mergesort")
            ranked = ranked[counts[ranked] > 0]
            for top_k in (16, 32, 64):
                candidates = ranked[:top_k].tolist()
                shot_rows.append({
                    "instance_id": context.instance_id,
                    "seed": context.seed,
                    "block_size": context.width,
                    "shots": shots,
                    "top_k": top_k,
                    "unique_states": int(np.count_nonzero(counts)),
                    **metric_for_candidates(space, candidates),
                })
        print(f"algorithm instance {context_index + 1}/{len(contexts)}: {context.instance_id}", flush=True)

    write_csv(ALGORITHM_DIR / "candidate_budget_results.csv", method_rows)
    write_csv(ALGORITHM_DIR / "candidate_budget_aggregate.csv", aggregate(method_rows, ("method", "candidate_budget")))
    write_csv(ALGORITHM_DIR / "qubo_variant_results.csv", variant_rows)
    write_csv(ALGORITHM_DIR / "qubo_variant_aggregate.csv", aggregate(variant_rows, ("qubo_version",)))
    write_csv(ALGORITHM_DIR / "capacity_penalty_results.csv", penalty_rows)
    write_csv(ALGORITHM_DIR / "capacity_penalty_aggregate.csv", aggregate(penalty_rows, ("capacity_penalty",)))
    write_csv(ALGORITHM_DIR / "shots_topk_results.csv", shot_rows)
    write_csv(ALGORITHM_DIR / "shots_topk_aggregate.csv", aggregate(shot_rows, ("shots", "top_k")))
    write_csv(ALGORITHM_DIR / "exact_reference.csv", exact_rows)
    metadata = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "instances": len(contexts),
        "block_sizes": sorted({context.width for context in contexts}),
        "depths": [1, 2, 3],
        "candidate_budgets": [32, 64, 128, 256],
        "capacity_penalties": list(CAPACITY_PENALTIES),
        "qubo_versions": list(QUBO_VERSIONS),
        "shots": [64, 256, 1024],
        "top_k": [16, 32, 64],
        "claim_boundary": "Ideal QAOA 结果来自无噪声状态向量；不代表真机量子优势。",
    }
    (ALGORITHM_DIR / "run_metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description="验证 Ideal QAOA 的有限候选生成能力")
    parser.add_argument("--instances", type=int, default=8)
    args = parser.parse_args()
    print(json.dumps(run(max(4, args.instances)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
