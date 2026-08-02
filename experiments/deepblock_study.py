from __future__ import annotations

import csv
from dataclasses import dataclass, replace
from itertools import combinations
import json
import math
from pathlib import Path
import random
import sys
from typing import Iterable, Mapping, Sequence

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from quantum_route_forge.deepblock.builder import (
    DeepBlock,
    build_interaction_graph,
    build_overlapping_blocks,
    rank_vehicle_pairs,
    select_boundary_pool,
)
from quantum_route_forge.deepblock.clustering import capacity_constrained_kmeans
from quantum_route_forge.deepblock.evaluator import repair_capacity, true_route_distance
from quantum_route_forge.deepblock.proxy_qubo import (
    ProxyInteraction,
    SparseProxyQUBO,
    assignment_for_bits,
    bits_to_bitstring,
    build_sparse_proxy_qubo,
)
from quantum_route_forge.deepblock.qaoa_runner import (
    ideal_probabilities,
    pretrain_parameters,
)
from quantum_route_forge.models import Customer, DispatchInstance
from quantum_route_forge.scenario import generate_dispatch_instance


RESULT_ROOT = ROOT / "results" / "deepblock_final_study"
OFFLINE_DIR = RESULT_ROOT / "offline"
ALGORITHM_DIR = RESULT_ROOT / "algorithm"
HARDWARE_DIR = RESULT_ROOT / "hardware_gap"
FIGURE_DIR = RESULT_ROOT / "figures"
CAPACITY_PENALTIES = (10.0, 25.0, 50.0)
QUBO_VERSIONS = ("current_sparse", "improved_route_proxy", "full_interaction")


@dataclass
class BlockContext:
    instance_id: str
    seed: int
    instance: DispatchInstance
    assignments: dict[int, list[Customer]]
    pair_rank: int
    block: DeepBlock
    block_customers: list[Customer]

    @property
    def width(self) -> int:
        return len(self.block_customers)

    @property
    def baseline_distance(self) -> float:
        return true_route_distance(self.assignments, self.instance.depot)


@dataclass
class StateSpace:
    states: np.ndarray
    bitstrings: list[str]
    distances: np.ndarray
    feasible_before: np.ndarray
    repaired: np.ndarray
    improvements: np.ndarray
    energies: np.ndarray
    current_state: int

    @property
    def improving_mask(self) -> np.ndarray:
        return self.improvements > 1e-9

    @property
    def best_distance(self) -> float:
        return float(np.min(self.distances))

    @property
    def best_improvement(self) -> float:
        return float(np.max(self.improvements))


def ensure_directories() -> None:
    for path in (OFFLINE_DIR, ALGORITHM_DIR, HARDWARE_DIR, FIGURE_DIR):
        path.mkdir(parents=True, exist_ok=True)


def write_csv(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8-sig")
        return
    fields = list(rows[0])
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_jsonl(path: Path, rows: Iterable[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def read_jsonl(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _instance_shape(seed: int) -> tuple[int, int]:
    return ((30, 3), (40, 4), (50, 5))[(int(seed) - 1) % 3]


def make_instance(seed: int) -> DispatchInstance:
    num_customers, num_vehicles = _instance_shape(seed)
    draft = generate_dispatch_instance(seed, num_customers, num_vehicles, vehicle_capacity=10_000)
    capacity = max(
        max(customer.demand for customer in draft.customers),
        math.ceil(draft.total_demand / num_vehicles * (1.10 if seed % 2 else 1.18)),
    )
    return DispatchInstance(
        depot=draft.depot,
        customers=draft.customers,
        num_vehicles=num_vehicles,
        vehicle_capacity=capacity,
    )


def make_contexts(
    seed: int,
    width: int = 8,
    pair_limit: int = 2,
    block_limit: int = 3,
) -> list[BlockContext]:
    instance = make_instance(seed)
    clustering = capacity_constrained_kmeans(instance, seed=seed)
    assignments = clustering.assignments
    by_id = {customer.customer_id: customer for customer in instance.customers}
    contexts: list[BlockContext] = []
    for pair_rank, pair in enumerate(rank_vehicle_pairs(assignments, instance.depot)[:pair_limit]):
        pool = select_boundary_pool(
            assignments,
            pair,
            instance.depot,
            pool_size=min(len(assignments[pair[0]]) + len(assignments[pair[1]]), width + 6),
        )
        if len(pool) < width:
            continue
        pool_customers = [by_id[row.customer_id] for row in pool]
        interactions = build_interaction_graph(
            pool_customers,
            {row.customer_id: row.score for row in pool},
        )
        blocks = build_overlapping_blocks(
            [row.customer_id for row in pool],
            pair,
            interactions,
            block_size=width,
            overlap=min(3, width - 1),
            max_blocks=block_limit,
        )
        for block_index, block in enumerate(blocks[:block_limit], start=1):
            customers = [by_id[customer_id] for customer_id in block.customer_ids]
            contexts.append(
                BlockContext(
                    instance_id=f"seed{seed:03d}_pair{pair_rank + 1}_{block.block_id}_w{width}",
                    seed=seed,
                    instance=instance,
                    assignments={vehicle: list(rows) for vehicle, rows in assignments.items()},
                    pair_rank=pair_rank,
                    block=replace(block, block_id=f"B{block_index}"),
                    block_customers=customers,
                )
            )
    return contexts


def _all_edges(width: int) -> list[tuple[int, int]]:
    return list(combinations(range(width), 2))


def build_proxy(
    context: BlockContext,
    version: str = "full_interaction",
    capacity_penalty: float = 25.0,
) -> SparseProxyQUBO:
    if version not in QUBO_VERSIONS:
        raise ValueError(f"Unknown QUBO version: {version}")
    width = context.width
    full = build_sparse_proxy_qubo(
        assignments=context.assignments,
        block_customers=context.block_customers,
        vehicle_pair=context.block.vehicle_pair,
        depot=context.instance.depot,
        vehicle_capacity=context.instance.vehicle_capacity,
        allowed_logical_edges=_all_edges(width),
        capacity_penalty=capacity_penalty,
    )
    if version == "full_interaction":
        return full
    if version == "current_sparse":
        kept_edges = {(index, index + 1) for index in range(width - 1)}
    else:
        ranked = sorted(
            full.quadratic,
            key=lambda row: (-abs(row.coefficient), row.left, row.right),
        )
        kept_edges = {(row.left, row.right) for row in ranked[: max(width - 1, 2 * width)]}
    quadratic = tuple(
        ProxyInteraction(
            left=row.left,
            right=row.right,
            coefficient=row.coefficient,
            kept=(row.left, row.right) in kept_edges and abs(row.coefficient) > 1e-9,
            reason=(
                "kept_research_proxy_edge"
                if (row.left, row.right) in kept_edges
                else "pruned_by_research_proxy"
            ),
        )
        for row in full.quadratic
    )
    return replace(full, quadratic=quadratic)


def enumerate_context(context: BlockContext, proxy: SparseProxyQUBO) -> StateSpace:
    width = context.width
    size = 1 << width
    baseline = context.baseline_distance
    by_vehicle = {
        customer.customer_id: vehicle
        for vehicle, customers in context.assignments.items()
        for customer in customers
    }
    current_bits = tuple(
        0 if by_vehicle[customer.customer_id] == context.block.vehicle_pair[0] else 1
        for customer in context.block_customers
    )
    current_state = sum(int(bit) << index for index, bit in enumerate(current_bits))
    distances = np.empty(size, dtype=float)
    feasible_before = np.empty(size, dtype=bool)
    repaired_flags = np.empty(size, dtype=bool)
    energies = np.empty(size, dtype=float)
    bitstrings: list[str] = []
    for state in range(size):
        bits = tuple((state >> index) & 1 for index in range(width))
        bitstrings.append(bits_to_bitstring(bits))
        candidate = assignment_for_bits(
            context.assignments,
            context.block_customers,
            context.block.vehicle_pair,
            bits,
        )
        feasible_before[state] = all(
            sum(customer.demand for customer in rows) <= context.instance.vehicle_capacity
            for rows in candidate.values()
        )
        repaired, changed, _ = repair_capacity(candidate, context.instance.vehicle_capacity)
        repaired_flags[state] = changed
        distances[state] = true_route_distance(repaired, context.instance.depot)
        energies[state] = proxy.energy(bits)
    return StateSpace(
        states=np.arange(size, dtype=int),
        bitstrings=bitstrings,
        distances=distances,
        feasible_before=feasible_before,
        repaired=repaired_flags,
        improvements=baseline - distances,
        energies=energies,
        current_state=current_state,
    )


def _rankdata(values: np.ndarray) -> np.ndarray:
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(len(values), dtype=float)
    start = 0
    while start < len(values):
        end = start + 1
        while end < len(values) and values[order[end]] == values[order[start]]:
            end += 1
        ranks[order[start:end]] = (start + end - 1) / 2.0
        start = end
    return ranks


def spearman(left: np.ndarray, right: np.ndarray) -> float:
    if len(left) < 2:
        return 0.0
    lrank, rrank = _rankdata(left), _rankdata(right)
    if np.std(lrank) <= 1e-15 or np.std(rrank) <= 1e-15:
        return 0.0
    return float(np.corrcoef(lrank, rrank)[0, 1])


def summarize_space(context: BlockContext, space: StateSpace) -> dict[str, object]:
    improving = np.flatnonzero(space.improving_mask)
    current = space.current_state
    one_bit = [current ^ (1 << index) for index in range(context.width)]
    local_trap = bool(len(improving) and not np.any(space.improvements[one_bit] > 1e-9))
    energy_order = np.argsort(space.energies, kind="mergesort")
    true_best = int(np.argmin(space.distances))
    true_rank = int(np.flatnonzero(energy_order == true_best)[0]) + 1
    return {
        "instance_id": context.instance_id,
        "seed": context.seed,
        "num_customers": len(context.instance.customers),
        "num_vehicles": context.instance.num_vehicles,
        "vehicle_capacity": context.instance.vehicle_capacity,
        "vehicle_pair": "-".join(map(str, context.block.vehicle_pair)),
        "pair_rank": context.pair_rank + 1,
        "block_id": context.block.block_id,
        "block_size": context.width,
        "state_count": len(space.states),
        "baseline_distance": context.baseline_distance,
        "exact_best_distance": space.best_distance,
        "best_improvement": space.best_improvement,
        "has_improvement": bool(len(improving)),
        "improving_state_count": int(len(improving)),
        "improving_state_ratio": float(len(improving) / len(space.states)),
        "single_bit_local_trap": local_trap,
        "minimum_required_flips": (
            min((int(state ^ current).bit_count() for state in improving), default=0)
        ),
        "feasible_state_ratio": float(np.mean(space.feasible_before)),
        "capacity_repair_ratio": float(np.mean(space.repaired)),
        "spearman_qubo_true_distance": spearman(space.energies, space.distances),
        "true_optimum_qubo_rank": true_rank,
        "current_bitstring": space.bitstrings[current],
        "qubo_best_bitstring": space.bitstrings[int(np.argmin(space.energies))],
        "true_best_bitstring": space.bitstrings[true_best],
    }


def context_payload(context: BlockContext, summary: Mapping[str, object]) -> dict[str, object]:
    return {
        **dict(summary),
        "block_customer_ids": [customer.customer_id for customer in context.block_customers],
        "assignments": {
            str(vehicle): [customer.customer_id for customer in rows]
            for vehicle, rows in sorted(context.assignments.items())
        },
        "depot": list(context.instance.depot),
        "customers": [
            {
                "customer_id": customer.customer_id,
                "x": customer.x,
                "y": customer.y,
                "demand": customer.demand,
            }
            for customer in context.instance.customers
        ],
    }


def context_from_payload(payload: Mapping[str, object], width: int | None = None) -> BlockContext:
    customers = [Customer(**row) for row in payload["customers"]]  # type: ignore[arg-type]
    by_id = {customer.customer_id: customer for customer in customers}
    assignments = {
        int(vehicle): [by_id[int(customer_id)] for customer_id in customer_ids]
        for vehicle, customer_ids in payload["assignments"].items()  # type: ignore[union-attr]
    }
    target_width = int(width or payload["block_size"])
    original_ids = [int(value) for value in payload["block_customer_ids"]]
    pair = tuple(int(value) for value in str(payload["vehicle_pair"]).split("-"))
    if target_width != len(original_ids):
        pool = select_boundary_pool(
            assignments,
            pair,  # type: ignore[arg-type]
            tuple(payload["depot"]),  # type: ignore[arg-type]
            pool_size=target_width,
        )
        original_ids = [row.customer_id for row in pool]
    instance = DispatchInstance(
        depot=tuple(payload["depot"]),  # type: ignore[arg-type]
        customers=customers,
        num_vehicles=int(payload["num_vehicles"]),
        vehicle_capacity=int(payload["vehicle_capacity"]),
    )
    block = DeepBlock(
        block_id=str(payload["block_id"]),
        customer_ids=tuple(original_ids),
        vehicle_pair=pair,  # type: ignore[arg-type]
    )
    return BlockContext(
        instance_id=f"seed{int(payload['seed']):03d}_pair{int(payload['pair_rank'])}_{block.block_id}_w{target_width}",
        seed=int(payload["seed"]),
        instance=instance,
        assignments=assignments,
        pair_rank=int(payload["pair_rank"]) - 1,
        block=block,
        block_customers=[by_id[customer_id] for customer_id in original_ids],
    )


def metric_for_candidates(space: StateSpace, candidates: Sequence[int]) -> dict[str, object]:
    indices = np.asarray(list(candidates), dtype=int)
    if len(indices) == 0:
        return {
            "found_improvement": False,
            "best_improvement": 0.0,
            "improving_probability": 0.0,
            "global_or_near_optimum_probability": 0.0,
            "relative_exact_gap": 1.0,
        }
    values = space.improvements[indices]
    near = space.distances <= space.best_distance * 1.01 + 1e-9
    best = max(0.0, float(np.max(values)))
    exact = max(0.0, space.best_improvement)
    return {
        "found_improvement": bool(np.any(values > 1e-9)),
        "best_improvement": best,
        "improving_probability": float(np.mean(values > 1e-9)),
        "global_or_near_optimum_probability": float(np.mean(near[indices])),
        "relative_exact_gap": float((exact - best) / exact) if exact > 1e-9 else 0.0,
    }


def single_point_candidates(space: StateSpace, width: int, budget: int) -> list[int]:
    base = [space.current_state] + [space.current_state ^ (1 << index) for index in range(width)]
    return (base * math.ceil(budget / len(base)))[:budget]


def multistart_candidates(space: StateSpace, width: int, budget: int, seed: int) -> list[int]:
    rng = random.Random(seed)
    candidates: list[int] = []
    while len(candidates) < budget:
        state = rng.randrange(len(space.states))
        candidates.append(state)
        improved = True
        while improved and len(candidates) < budget:
            neighbors = [state ^ (1 << bit) for bit in range(width)]
            best = min(neighbors, key=lambda value: (space.distances[value], value))
            candidates.append(best)
            improved = space.distances[best] < space.distances[state] - 1e-9
            if improved:
                state = best
    return candidates[:budget]


def annealing_candidates(space: StateSpace, width: int, budget: int, seed: int) -> list[int]:
    rng = random.Random(seed)
    state = space.current_state
    result: list[int] = []
    scale = max(1.0, float(np.std(space.distances)))
    for step in range(budget):
        candidate = state ^ (1 << rng.randrange(width))
        temperature = scale * max(0.02, 1.0 - step / max(1, budget - 1))
        delta = space.distances[candidate] - space.distances[state]
        if delta <= 0 or rng.random() < math.exp(-delta / temperature):
            state = candidate
        result.append(state)
    return result


def sample_probabilities(probabilities: np.ndarray, budget: int, seed: int) -> list[int]:
    rng = np.random.default_rng(seed)
    return rng.choice(len(probabilities), size=int(budget), replace=True, p=probabilities).tolist()


def low_region_metrics(
    reference_space: StateSpace,
    probabilities: np.ndarray,
    shots: int,
    seed: int,
    top_k: int = 64,
) -> dict[str, object]:
    sampled = sample_probabilities(probabilities, shots, seed)
    counts = np.bincount(sampled, minlength=len(probabilities))
    low_count = max(1, math.ceil(len(probabilities) * 0.10))
    low_mask = np.zeros(len(probabilities), dtype=bool)
    low_mask[np.argsort(reference_space.energies)[:low_count]] = True
    top_states = np.argsort(-counts, kind="mergesort")[: min(top_k, np.count_nonzero(counts))]
    improving = reference_space.improving_mask
    entropy = -float(np.sum(probabilities[probabilities > 0] * np.log2(probabilities[probabilities > 0])))
    return {
        "low_energy_probability": float(np.sum(probabilities[low_mask])),
        "improving_probability": float(np.sum(probabilities[improving])),
        "found_improvement": bool(np.any(improving[top_states])) if len(top_states) else False,
        "best_improvement": max(0.0, float(np.max(reference_space.improvements[top_states]))) if len(top_states) else 0.0,
        "distribution_entropy": entropy,
        "unique_states": int(np.count_nonzero(counts)),
    }


def observed_distribution_metrics(
    reference_space: StateSpace,
    probabilities: np.ndarray,
    top_k: int = 64,
) -> dict[str, object]:
    """Evaluate observed hardware counts without introducing a second sampling layer."""
    probabilities = np.asarray(probabilities, dtype=float)
    probabilities = probabilities / probabilities.sum()
    low_count = max(1, math.ceil(len(probabilities) * 0.10))
    low_mask = np.zeros(len(probabilities), dtype=bool)
    low_mask[np.argsort(reference_space.energies)[:low_count]] = True
    ranked = np.argsort(-probabilities, kind="mergesort")
    top_states = ranked[probabilities[ranked] > 0][:top_k]
    improving = reference_space.improving_mask
    nonzero = probabilities[probabilities > 0]
    entropy = -float(np.sum(nonzero * np.log2(nonzero)))
    return {
        "low_energy_probability": float(np.sum(probabilities[low_mask])),
        "improving_probability": float(np.sum(probabilities[improving])),
        "found_improvement": bool(np.any(improving[top_states])) if len(top_states) else False,
        "best_improvement": (
            max(0.0, float(np.max(reference_space.improvements[top_states])))
            if len(top_states)
            else 0.0
        ),
        "distribution_entropy": entropy,
        "unique_states": int(len(nonzero)),
    }


def apply_bitflip_noise(probabilities: np.ndarray, width: int, bit_error: float) -> np.ndarray:
    noisy = np.asarray(probabilities, dtype=float).copy()
    error = min(0.5, max(0.0, float(bit_error)))
    for bit in range(width):
        step = 1 << bit
        paired = noisy.reshape(-1, step * 2)
        zero = paired[:, :step].copy()
        one = paired[:, step:].copy()
        paired[:, :step] = (1.0 - error) * zero + error * one
        paired[:, step:] = error * zero + (1.0 - error) * one
    return noisy / noisy.sum()


def aggregate(rows: Sequence[Mapping[str, object]], keys: Sequence[str]) -> list[dict[str, object]]:
    groups: dict[tuple[object, ...], list[Mapping[str, object]]] = {}
    for row in rows:
        groups.setdefault(tuple(row[key] for key in keys), []).append(row)
    result: list[dict[str, object]] = []
    for values, group in sorted(groups.items(), key=lambda item: tuple(map(str, item[0]))):
        record = {key: value for key, value in zip(keys, values)}
        numeric_keys = [
            key for key in group[0]
            if key not in keys and isinstance(group[0][key], (int, float, bool))
        ]
        record["instances"] = len(group)
        for key in numeric_keys:
            vals = [float(row[key]) for row in group if row[key] is not None]
            if vals:
                record[f"mean_{key}"] = float(np.mean(vals))
        result.append(record)
    return result
