from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from quantum_route_forge.competition_history import CompetitionHistory
from quantum_route_forge.deepblock.builder import build_overlapping_blocks, scan_sequence
from quantum_route_forge.deepblock.evaluator import evaluate_counts, normalize_counts, repair_capacity
from quantum_route_forge.deepblock.proxy_qubo import (
    bits_to_bitstring,
    bitstring_to_bits,
    build_sparse_proxy_qubo,
)
from quantum_route_forge.deepblock.solver import DeepBlockConfig, run_deepblock
from quantum_route_forge.models import Customer
from quantum_route_forge.scenario import generate_dispatch_instance


def _interaction(ids):
    return {
        (left, right): 1.0 / (1 + abs(left - right))
        for index, left in enumerate(ids)
        for right in ids[index + 1 :]
    }


def _proxy_fixture():
    customers = [
        Customer(1, 0.0, 1.0, 1),
        Customer(2, 0.0, 2.0, 1),
        Customer(3, 10.0, 1.0, 1),
        Customer(4, 10.0, 2.0, 1),
    ]
    assignments = {0: customers[:2], 1: customers[2:]}
    proxy = build_sparse_proxy_qubo(
        assignments=assignments,
        block_customers=customers,
        vehicle_pair=(0, 1),
        depot=(5.0, 0.0),
        vehicle_capacity=4,
        allowed_logical_edges=[(0, 1), (1, 2), (2, 3)],
    )
    return customers, assignments, proxy


def test_bit_order_round_trip_uses_openqasm_leftmost_high_bit():
    bits = (1, 0, 1, 0)
    bitstring = bits_to_bitstring(bits)
    assert bitstring == "0101"
    assert bitstring_to_bits(bitstring, 4) == bits


def test_counts_normalize_deduplicates_and_preserves_shots():
    counts = normalize_counts({"0011": 3, "11": 2, "bad": 90, "0011 ": 4}, width=4)
    assert counts == {"0011": 9}
    assert sum(counts.values()) == 9


def test_capacity_repair_and_customer_coverage():
    customers = [
        Customer(1, 0, 0, 3),
        Customer(2, 1, 0, 3),
        Customer(3, 2, 0, 1),
    ]
    repaired, changed, summary = repair_capacity({0: customers, 1: []}, capacity=4)
    assert changed
    assert summary == "capacity_repaired"
    assert all(sum(customer.demand for customer in rows) <= 4 for rows in repaired.values())
    assert sorted(customer.customer_id for rows in repaired.values() for customer in rows) == [1, 2, 3]


def test_three_blocks_cover_pool_and_scan_order_is_stable():
    ids = list(range(1, 17))
    blocks = build_overlapping_blocks(ids, (0, 1), _interaction(ids), block_size=8, overlap=3)
    assert [block.block_id for block in blocks] == ["B1", "B2", "B3"]
    assert set().union(*(set(block.customer_ids) for block in blocks)) == set(ids)
    assert [block.block_id for block in scan_sequence(blocks)] == ["B1", "B2", "B3", "B3", "B2", "B1"]


def test_top_k_is_unique_stably_sorted_and_acceptance_is_strict():
    customers, assignments, proxy = _proxy_fixture()
    batch, accepted = evaluate_counts(
        arm="test",
        counts={"0000": 8, "0001": 8, "0010": 5, "0011": 1},
        proxy=proxy,
        assignments=assignments,
        block_customers=customers,
        depot=(5.0, 0.0),
        vehicle_capacity=4,
        candidate_k=3,
    )
    assert [row.bitstring for row in batch.top_frequency] == ["0000", "0001", "0010"]
    assert len({row.bitstring for row in batch.top_frequency}) == 3
    if accepted is not None:
        assert batch.accepted is not None
        assert batch.accepted.improvement > 0


def test_hardware_dry_run_is_not_evaluable_and_never_falls_back():
    instance = generate_dispatch_instance(
        seed=4, num_customers=8, num_vehicles=2, vehicle_capacity=20
    )
    assignments = {0: instance.customers[:4], 1: instance.customers[4:]}
    result = run_deepblock(
        instance=instance,
        initial_assignments=assignments,
        mode="deepblock_hardware",
        config=DeepBlockConfig(
            shots=32,
            candidate_k=4,
            block_size=8,
            pool_size=8,
            submit_hardware=False,
        ),
        seed=4,
    )
    assert result.source == "hardware"
    assert result.status == "NOT_EVALUABLE"
    assert all(not trace.run.task_id and not trace.run.counts for trace in result.traces)
    assert all(trace.source == "hardware" for trace in result.traces)


def test_history_save_and_reload(tmp_path):
    history = CompetitionHistory(tmp_path)
    payload = {
        "run_id": "run-001",
        "created_at": "2026-08-02T00:00:00+00:00",
        "parameters": {"seed": 1, "mode": "deepblock_random"},
        "initial": {"distance": 10.0},
        "selected": {"source": "random", "final_distance": 9.0, "improvement_pct": 10.0, "status": "COMPLETED"},
        "comparisons": [],
    }
    history.save(payload)
    assert history.load("run-001")["selected"]["source"] == "random"
    assert history.rows()[0]["run_id"] == "run-001"
