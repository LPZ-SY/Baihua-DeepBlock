from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import numpy as np

from deepblock_study import (
    HARDWARE_DIR, OFFLINE_DIR, assignment_for_bits, build_proxy, context_from_payload,
    enumerate_context, pretrain_parameters, read_jsonl, repair_capacity,
    true_route_distance, write_csv,
)
from deepblock_submit_first_hardware import submit_one


SEEDS = {
    2: ("seed002_pair1_B2_w8", "seed002_pair1_B3_w8"),
    3: ("seed003_pair1_B1_w8", "seed003_pair1_B3_w8"),
}


def _state_probabilities(counts: dict[str, object]) -> np.ndarray:
    values = np.zeros(256, dtype=float)
    for key, count in counts.items():
        values[int(str(key).replace(" ", "")[-8:].zfill(8), 2)] += int(count)
    return values / values.sum()


def _accept(context, space, counts):
    probabilities = _state_probabilities(counts)
    ranked = np.argsort(-probabilities, kind="mergesort")
    ranked = ranked[probabilities[ranked] > 0][:64]
    improving = [int(state) for state in ranked if space.improvements[state] > 1e-9]
    if not improving:
        return context.assignments, False, 0.0, None
    state = min(improving, key=lambda value: (space.distances[value], value))
    bits = tuple((state >> bit) & 1 for bit in range(context.width))
    candidate = assignment_for_bits(context.assignments, context.block_customers,
                                    context.block.vehicle_pair, bits)
    repaired, _, _ = repair_capacity(candidate, context.instance.vehicle_capacity)
    gain = context.baseline_distance - true_route_distance(repaired, context.instance.depot)
    return repaired, gain > 1e-9, max(0.0, gain), state


def _append_manifest(context, reference) -> None:
    path = HARDWARE_DIR / "hardware_submission_manifest.jsonl"
    rows = read_jsonl(path)
    if any(str(row["instance_id"]) == context.instance_id and int(row["p"]) == 2 for row in rows):
        return
    proxy = build_proxy(context, "current_sparse", 25.0)
    parameters = pretrain_parameters(proxy, 2, rounds=2)
    row = {
        "instance_id": context.instance_id, "seed": context.seed, "p": 2,
        "vehicle_pair": list(context.block.vehicle_pair),
        "block_customer_ids": [c.customer_id for c in context.block_customers],
        "customer_to_qubit_order": [c.customer_id for c in context.block_customers],
        "initial_assignments": {str(v): [c.customer_id for c in customers]
                                for v, customers in sorted(context.assignments.items())},
        "qubo": proxy.payload(), "qaoa_parameters": parameters.payload(), "shots": 1024,
        "top_k": 64, "low_energy_state_count": max(1, len(reference.states) // 10),
        "improving_bitstrings": [reference.bitstrings[i]
                                 for i in np.flatnonzero(reference.improving_mask)],
        "experiment": "adaptive_hardware_closed_loop_round_2",
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def run(*, confirm: bool, timeout_sec: int = 600) -> dict[str, object]:
    if not confirm:
        raise PermissionError("Use --confirm-submit to authorize at most two new closed-loop tasks.")
    selected = read_jsonl(OFFLINE_DIR / "selected_instances.jsonl")
    payloads = {str(row["instance_id"]): row for row in selected if int(row["block_size"]) == 8}
    live_path = HARDWARE_DIR / "hardware_live_results.jsonl"
    round_rows = []
    submitted = 0
    for seed, (round1_id, template_id) in SEEDS.items():
        live = read_jsonl(live_path)
        r1 = next(row for row in live if str(row["instance_id"]) == round1_id
                  and int(row["p"]) == 2 and int(row.get("replicate", 1)) == 1)
        c1 = context_from_payload(payloads[round1_id], width=8)
        s1 = enumerate_context(c1, build_proxy(c1, "full_interaction", 25.0))
        assignments, accepted1, gain1, state1 = _accept(c1, s1, r1["counts"])
        round_rows.append({"seed": seed, "round": 1, "instance_id": round1_id,
                           "task_id": r1["task_id"], "shots": r1["shots"],
                           "accepted": accepted1, "route_improvement": gain1,
                           "selected_state": state1, "block_regenerated_after": True})

        template = context_from_payload(payloads[template_id], width=8)
        c2 = replace(template, instance_id=f"closedloop_seed{seed:03d}_round2_B3_w8",
                     assignments=assignments)
        s2 = enumerate_context(c2, build_proxy(c2, "full_interaction", 25.0))
        _append_manifest(c2, s2)
        live = read_jsonl(live_path)
        r2 = next((row for row in live if str(row["instance_id"]) == c2.instance_id
                   and int(row["p"]) == 2), None)
        if r2 is None:
            if submitted >= 2:
                raise RuntimeError("Closed-loop hard cap of two new tasks reached")
            result = submit_one(confirm=True, instance_id=c2.instance_id, depth=2,
                                timeout_sec=timeout_sec)
            if result["status"] != "COMPLETED" or int(result["shots_received"]) != 1024:
                raise RuntimeError(f"Closed-loop task failed: {result}")
            submitted += 1
            r2 = next(row for row in read_jsonl(live_path)
                      if str(row["instance_id"]) == c2.instance_id and int(row["p"]) == 2)
        _, accepted2, gain2, state2 = _accept(c2, s2, r2["counts"])
        round_rows.append({"seed": seed, "round": 2, "instance_id": c2.instance_id,
                           "task_id": r2["task_id"], "shots": r2["shots"],
                           "accepted": accepted2, "route_improvement": gain2,
                           "selected_state": state2, "block_regenerated_after": False})
    write_csv(HARDWARE_DIR / "hardware_closed_loop_rounds.csv", round_rows)
    summary = {"seeds": len(SEEDS), "rounds_per_seed": 2, "hardware_rounds": len(round_rows),
               "new_tasks_submitted": submitted,
               "accepted_moves": sum(bool(row["accepted"]) for row in round_rows),
               "total_route_improvement": sum(float(row["route_improvement"]) for row in round_rows)}
    (HARDWARE_DIR / "hardware_closed_loop_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm-submit", action="store_true")
    parser.add_argument("--timeout-sec", type=int, default=600)
    args = parser.parse_args()
    print(json.dumps(run(confirm=args.confirm_submit, timeout_sec=args.timeout_sec),
                     ensure_ascii=False, indent=2))
