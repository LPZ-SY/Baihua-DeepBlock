from __future__ import annotations

from itertools import combinations
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
EXPERIMENTS = ROOT / "experiments"
for path in (SRC, EXPERIMENTS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from deepblock_study import (
    StateSpace,
    apply_bitflip_noise,
    make_contexts,
    observed_distribution_metrics,
)
from quantum_route_forge.deepblock.proxy_qubo import build_sparse_proxy_qubo
from quantum_route_forge.deepblock.qaoa_runner import ideal_probabilities, pretrain_parameters


def test_research_proxy_supports_14_bits_while_solver_keeps_hardware_limit():
    context = make_contexts(2, width=14, pair_limit=1, block_limit=1)[0]
    proxy = build_sparse_proxy_qubo(
        assignments=context.assignments,
        block_customers=context.block_customers,
        vehicle_pair=context.block.vehicle_pair,
        depot=context.instance.depot,
        vehicle_capacity=context.instance.vehicle_capacity,
        allowed_logical_edges=list(combinations(range(14), 2)),
    )
    assert proxy.width == 14
    assert len(proxy.quadratic) == 91


def test_ideal_distribution_and_noise_are_normalized():
    context = make_contexts(2, width=6, pair_limit=1, block_limit=1)[0]
    proxy = build_sparse_proxy_qubo(
        assignments=context.assignments,
        block_customers=context.block_customers,
        vehicle_pair=context.block.vehicle_pair,
        depot=context.instance.depot,
        vehicle_capacity=context.instance.vehicle_capacity,
        allowed_logical_edges=list(combinations(range(6), 2)),
    )
    probabilities = ideal_probabilities(proxy, pretrain_parameters(proxy, 1, rounds=1))
    noisy = apply_bitflip_noise(probabilities, width=6, bit_error=0.08)
    assert probabilities.shape == (64,)
    assert np.isclose(probabilities.sum(), 1.0)
    assert np.isclose(noisy.sum(), 1.0)
    assert np.all(noisy >= 0.0)


def test_observed_metrics_do_not_resample_hardware_distribution():
    space = StateSpace(
        states=np.arange(4),
        bitstrings=["00", "01", "10", "11"],
        distances=np.array([10.0, 9.0, 11.0, 12.0]),
        feasible_before=np.ones(4, dtype=bool),
        repaired=np.zeros(4, dtype=bool),
        improvements=np.array([0.0, 1.0, -1.0, -2.0]),
        energies=np.array([0.0, 1.0, 2.0, 3.0]),
        current_state=0,
    )
    metrics = observed_distribution_metrics(space, np.array([0.75, 0.25, 0.0, 0.0]))
    assert metrics["unique_states"] == 2
    assert metrics["improving_probability"] == 0.25
    assert metrics["found_improvement"]
