from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from quantum_route_forge import generate_dispatch_instance, run_optimization


def test_classical_smoke():
    instance = generate_dispatch_instance(
        seed=123,
        num_customers=16,
        num_vehicles=3,
        vehicle_capacity=20,
    )
    result = run_optimization(instance=instance, mode="classical", num_reads=100)
    assert len(result.routes) == 3
    assert result.total_distance > 0
    total_load = sum(route.load for route in result.routes)
    assert total_load == instance.total_demand
    for route in result.routes:
        assert route.load <= instance.vehicle_capacity
