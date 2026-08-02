from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np

from deepblock_study import (
    HARDWARE_DIR,
    OFFLINE_DIR,
    aggregate,
    apply_bitflip_noise,
    assignment_for_bits,
    build_proxy,
    context_from_payload,
    ensure_directories,
    enumerate_context,
    ideal_probabilities,
    low_region_metrics,
    observed_distribution_metrics,
    pretrain_parameters,
    read_jsonl,
    repair_capacity,
    sample_probabilities,
    write_csv,
    write_jsonl,
)


def _hardware_lookup(path: Path | None) -> dict[tuple[str, int], dict[str, object]]:
    if path is None:
        return {}
    rows = read_jsonl(path)
    # The primary matrix must remain one independent observation per Seed/depth.
    # Repeated runs are analysed separately and must not silently replace r1.
    primary: dict[tuple[str, int], dict[str, object]] = {}
    for row in rows:
        key = (str(row["instance_id"]), int(row["p"]))
        if int(row.get("replicate", 1)) == 1 and key not in primary:
            primary[key] = row
    return primary


def _counts_probabilities(counts: dict[str, object], width: int) -> np.ndarray:
    probabilities = np.zeros(1 << width, dtype=float)
    for bitstring, raw_count in counts.items():
        cleaned = str(bitstring).replace(" ", "")[-width:].zfill(width)
        if set(cleaned) <= {"0", "1"}:
            probabilities[int(cleaned, 2)] += max(0, int(raw_count))
    if probabilities.sum() <= 0:
        raise ValueError("真机 counts 为空或 bitstring 非法")
    return probabilities / probabilities.sum()


def _end_to_end(contexts: list) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    by_seed: dict[int, list] = {}
    for context in contexts:
        by_seed.setdefault(context.seed, []).append(context)
    for seed, seed_contexts in sorted(by_seed.items())[:3]:
        current = {vehicle: list(customers) for vehicle, customers in seed_contexts[0].assignments.items()}
        baseline = seed_contexts[0].baseline_distance
        accepted = 0
        tasks = 0
        for round_index in range(3):
            ordered = seed_contexts[:2] if round_index % 2 == 0 else list(reversed(seed_contexts[:2]))
            round_accepted = False
            for raw_context in ordered:
                context = replace(raw_context, assignments=current)
                proxy = build_proxy(context, "current_sparse", 25.0)
                space = enumerate_context(context, proxy)
                params = pretrain_parameters(proxy, 2, rounds=1)
                probabilities = ideal_probabilities(proxy, params)
                sampled = sample_probabilities(probabilities, 256, seed * 1000 + tasks)
                counts = np.bincount(sampled, minlength=len(probabilities))
                ranked = np.argsort(-counts, kind="mergesort")
                ranked = ranked[counts[ranked] > 0][:64]
                tasks += 1
                improving = [int(state) for state in ranked if space.improvements[state] > 1e-9]
                if improving:
                    state = min(improving, key=lambda value: (space.distances[value], value))
                    bits = tuple((state >> bit) & 1 for bit in range(context.width))
                    candidate = assignment_for_bits(
                        current,
                        context.block_customers,
                        context.block.vehicle_pair,
                        bits,
                    )
                    current, _, _ = repair_capacity(candidate, context.instance.vehicle_capacity)
                    accepted += 1
                    round_accepted = True
                    break
            if not round_accepted:
                break
        final_context = replace(seed_contexts[0], assignments=current)
        final_distance = final_context.baseline_distance
        rows.append({
            "seed": seed,
            "baseline_distance": baseline,
            "final_distance": final_distance,
            "improvement": baseline - final_distance,
            "accepted_moves": accepted,
            "round_limit": 3,
            "vehicle_pairs_per_round": min(2, len(seed_contexts)),
            "simulator_task_count": tasks,
            "hardware_task_count": 0,
        })
    return rows


def run(instance_count: int = 8, hardware_results: Path | None = None) -> dict[str, object]:
    ensure_directories()
    selected = read_jsonl(OFFLINE_DIR / "selected_instances.jsonl")
    if not selected:
        raise FileNotFoundError("请先运行 deepblock_offline_analysis.py")
    payloads = [row for row in selected if int(row["block_size"]) == 8]
    if not payloads:
        payloads = selected
    unique_payloads: list[dict[str, object]] = []
    seen_seeds: set[int] = set()
    for payload in payloads:
        seed = int(payload["seed"])
        if seed in seen_seeds:
            continue
        seen_seeds.add(seed)
        unique_payloads.append(payload)
        if len(unique_payloads) >= instance_count:
            break
    if len(unique_payloads) < instance_count:
        raise ValueError(
            f"Only {len(unique_payloads)} independent 8-bit Seeds are available; "
            f"requested {instance_count}."
        )
    contexts = [context_from_payload(payload, width=8) for payload in unique_payloads]
    hardware = _hardware_lookup(hardware_results)
    rows: list[dict[str, object]] = []
    comparison: list[dict[str, object]] = []
    manifests: list[dict[str, object]] = []

    for context_index, context in enumerate(contexts):
        full_proxy = build_proxy(context, "full_interaction", 25.0)
        compatible_proxy = build_proxy(context, "current_sparse", 25.0)
        reference = enumerate_context(context, full_proxy)
        p2_probabilities = None
        for depth in (1, 2, 3):
            if depth == 3 and context_index >= 3:
                continue
            full_parameters = pretrain_parameters(full_proxy, depth, rounds=2)
            compatible_parameters = pretrain_parameters(compatible_proxy, depth, rounds=2)
            full_probabilities = ideal_probabilities(full_proxy, full_parameters)
            compatible_probabilities = ideal_probabilities(compatible_proxy, compatible_parameters)
            if depth == 2:
                p2_probabilities = compatible_probabilities
            stage_probabilities = [
                ("完整 QUBO 理想模拟", "ideal", full_probabilities),
                ("硬件兼容理想模拟", "ideal", compatible_probabilities),
                ("带噪声模拟：当前噪声", "current", apply_bitflip_noise(compatible_probabilities, 8, 0.08)),
                ("带噪声模拟：50% 噪声", "50pct", apply_bitflip_noise(compatible_probabilities, 8, 0.04)),
                ("带噪声模拟：25% 噪声", "25pct", apply_bitflip_noise(compatible_probabilities, 8, 0.02)),
                ("噪声缩放：理想无噪声", "zero", compatible_probabilities),
            ]
            for stage, noise_scale, probabilities in stage_probabilities:
                rows.append({
                    "instance_id": context.instance_id,
                    "seed": context.seed,
                    "p": depth,
                    "stage": stage,
                    "noise_scale": noise_scale,
                    "status": "SIMULATED",
                    "task_id": "",
                    "shots": 1024,
                    **low_region_metrics(reference, probabilities, 1024, context.seed * 1000 + depth),
                })
            hardware_row = hardware.get((context.instance_id, depth))
            if hardware_row:
                probabilities = _counts_probabilities(hardware_row["counts"], 8)  # type: ignore[arg-type]
                rows.append({
                    "instance_id": context.instance_id,
                    "seed": context.seed,
                    "p": depth,
                    "stage": "Baihua 真机",
                    "noise_scale": "observed",
                    "status": "COMPLETED",
                    "task_id": str(hardware_row.get("task_id", "")),
                    "shots": int(sum(int(value) for value in hardware_row["counts"].values())),  # type: ignore[union-attr]
                    **observed_distribution_metrics(reference, probabilities),
                })
            else:
                rows.append({
                    "instance_id": context.instance_id,
                    "seed": context.seed,
                    "p": depth,
                    "stage": "Baihua 真机",
                    "noise_scale": "observed",
                    "status": "NOT_RUN",
                    "task_id": "",
                    "shots": 0,
                    "low_energy_probability": None,
                    "improving_probability": None,
                    "found_improvement": None,
                    "best_improvement": None,
                    "distribution_entropy": None,
                    "unique_states": None,
                })
            manifests.append({
                "instance_id": context.instance_id,
                "seed": context.seed,
                "p": depth,
                "vehicle_pair": list(context.block.vehicle_pair),
                "block_customer_ids": [customer.customer_id for customer in context.block_customers],
                "customer_to_qubit_order": [customer.customer_id for customer in context.block_customers],
                "initial_assignments": {
                    str(vehicle): [customer.customer_id for customer in customers]
                    for vehicle, customers in sorted(context.assignments.items())
                },
                "qubo": compatible_proxy.payload(),
                "qaoa_parameters": compatible_parameters.payload(),
                "shots": 1024,
                "top_k": 64,
                "low_energy_state_count": max(1, len(reference.states) // 10),
                "improving_bitstrings": [
                    reference.bitstrings[index]
                    for index in np.flatnonzero(reference.improving_mask)
                ],
            })

        assert p2_probabilities is not None
        random_candidates = np.random.default_rng(context.seed).integers(0, len(reference.states), 256)
        sim_candidates = sample_probabilities(p2_probabilities, 256, context.seed * 99)
        hardware_p2 = hardware.get((context.instance_id, 2))
        hardware_best = None
        if hardware_p2:
            probs = _counts_probabilities(hardware_p2["counts"], 8)  # type: ignore[arg-type]
            candidates = np.argsort(-probs)[:64]
            hardware_best = max(0.0, float(np.max(reference.improvements[candidates])))
        comparison.append({
            "instance_id": context.instance_id,
            "seed": context.seed,
            "Hardware": hardware_best,
            "Random": max(0.0, float(np.max(reference.improvements[random_candidates]))),
            "Simulator": max(0.0, float(np.max(reference.improvements[sim_candidates]))),
            "Exact": max(0.0, reference.best_improvement),
            "hardware_status": "COMPLETED" if hardware_p2 else "NOT_RUN",
        })
        print(f"hardware-gap instance {context_index + 1}/{len(contexts)}: {context.instance_id}", flush=True)

    write_csv(HARDWARE_DIR / "hardware_gap_results.csv", rows)
    comparable = [row for row in rows if row["status"] != "NOT_RUN"]
    write_csv(HARDWARE_DIR / "hardware_gap_aggregate.csv", aggregate(comparable, ("stage", "p")))
    write_csv(HARDWARE_DIR / "method_paired_improvement.csv", comparison)
    write_jsonl(HARDWARE_DIR / "hardware_submission_manifest.jsonl", manifests)
    end_to_end = _end_to_end(contexts)
    write_csv(HARDWARE_DIR / "end_to_end_summary.csv", end_to_end)
    metadata = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "instances": len(contexts),
        "p_main": [1, 2],
        "p3_representative_instances": min(3, len(contexts)),
        "hardware_results_source": str(hardware_results) if hardware_results else None,
        "completed_hardware_tasks": sum(row["status"] == "COMPLETED" for row in rows if row["stage"] == "Baihua 真机"),
        "hardware_status": "COMPLETED" if hardware else "NOT_RUN_NO_COMPATIBLE_COUNTS_PROVIDED",
        "claim_boundary": "噪声曲线为可解释的独立比特翻转模型，不是未来芯片性能预测。",
    }
    (HARDWARE_DIR / "run_metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description="分离拓扑裁剪、噪声与 Baihua 真机差距")
    parser.add_argument("--instances", type=int, default=8, help="8-bit 独立实例数，建议 6～10")
    parser.add_argument("--hardware-results", type=Path, help="可选 JSONL：instance_id、p、task_id、counts")
    args = parser.parse_args()
    if not 6 <= args.instances <= 10:
        parser.error("--instances 必须在 6～10 之间")
    print(json.dumps(run(args.instances, args.hardware_results), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
