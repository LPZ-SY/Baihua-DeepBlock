from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple

Point = Tuple[float, float]


@dataclass(frozen=True)
class Customer:
    customer_id: int
    x: float
    y: float
    demand: int

    @property
    def point(self) -> Point:
        return (self.x, self.y)


@dataclass(frozen=True)
class DispatchInstance:
    depot: Point
    customers: List[Customer]
    num_vehicles: int
    vehicle_capacity: int

    @property
    def total_demand(self) -> int:
        return sum(c.demand for c in self.customers)

    @property
    def feasible_capacity(self) -> bool:
        return self.total_demand <= self.num_vehicles * self.vehicle_capacity


@dataclass(frozen=True)
class AssignmentMetadata:
    requested_mode: str
    used_mode: str
    energy: float
    message: str
    quantum_task_id: Optional[str] = None
    quantum_backend: Optional[str] = None
    quantum_bitstring: Optional[str] = None
    quantum_endpoint: Optional[str] = None
    quantum_measurement_summary: Optional[Dict[str, Any]] = None
    quantum_candidate_energy: Optional[float] = None
    quantum_threshold: Optional[float] = None


@dataclass(frozen=True)
class RoutePlan:
    vehicle_id: int
    customers: List[Customer]
    load: int
    distance: float


@dataclass(frozen=True)
class OptimizationResult:
    instance: DispatchInstance
    assignments: Dict[int, List[Customer]]
    routes: List[RoutePlan]
    total_distance: float
    metadata: AssignmentMetadata


@dataclass(frozen=True)
class QuantumMeasurementResult:
    """Normalized quantum task result shared by adapters, experiments, and UI."""

    source: str
    platform: str
    status: str
    task_id: Optional[str] = None
    backend: Optional[str] = None
    endpoint: Optional[str] = None
    shots_requested: int = 0
    shots_received: int = 0
    counts: Dict[str, int] = field(default_factory=dict)
    selected_customer_ids: List[int] = field(default_factory=list)
    bit_order: str = "openqasm_high_classical_bit_left"
    circuit_hash: Optional[str] = None
    raw_payload_sha256: Optional[str] = None
    submitted_at: Optional[str] = None
    completed_at: Optional[str] = None
    evidence_path: Optional[str] = None
    message: str = ""
    warnings: List[str] = field(default_factory=list)

    @property
    def most_frequent_bitstring(self) -> Optional[str]:
        if not self.counts:
            return None
        return max(self.counts.items(), key=lambda item: (item[1], item[0]))[0]

    @property
    def formal_hardware_evidence(self) -> bool:
        return self.source == "hardware" and self.status == "completed" and bool(self.counts)

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["most_frequent_bitstring"] = self.most_frequent_bitstring
        payload["formal_hardware_evidence"] = self.formal_hardware_evidence
        return payload


@dataclass(frozen=True)
class CandidateEvaluation:
    instance_id: str
    source: str
    bitstring: str
    count: int
    probability: float
    energy: float
    raw_feasible: bool
    onehot_violation_count: int
    capacity_violation_count: int
    task_id: Optional[str] = None
    backend: Optional[str] = None
    exact_energy: Optional[float] = None
    energy_gap: Optional[float] = None
    normalized_score: Optional[float] = None
    quality_gate_pass: Optional[bool] = None
    near_quality_gate_pass: Optional[bool] = None
    classical_reach_all_pass: Optional[bool] = None
    classical_reach_feasible_pass: Optional[bool] = None
    strict_improvement_all_pass: Optional[bool] = None
    strict_improvement_feasible_pass: Optional[bool] = None

    @property
    def strict_improvement_pass(self) -> Optional[bool]:
        return self.strict_improvement_feasible_pass

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["strict_improvement_pass"] = self.strict_improvement_pass
        return payload


@dataclass(frozen=True)
class ExperimentSummary:
    instance_id: str
    source: str
    decision: str
    shots_requested: int
    shots_received: int
    unique_bitstrings: int
    qualified_unique: int
    raw_feasible_rate: Optional[float]
    quality_hit_rate: Optional[float]
    near_quality_hit_rate: Optional[float]
    random_quality_hit_rate: Optional[float]
    quality_hit_gain: Optional[float]
    quality_lift: Optional[float]
    classical_reach_all_rate: Optional[float]
    classical_reach_feasible_rate: Optional[float]
    strict_improvement_rate: Optional[float]
    best_gap: Optional[float]
    conclusion: str
    task_id: Optional[str] = None
    backend: Optional[str] = None
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
