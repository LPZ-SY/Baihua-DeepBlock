from __future__ import annotations

from dataclasses import asdict, dataclass
import os
from typing import Mapping, Sequence

from ..models import Customer, DispatchInstance
from .adapters import offline_identity_subgraph
from .builder import (
    BoundaryCandidate,
    DeepBlock,
    build_interaction_graph,
    build_overlapping_blocks,
    rank_vehicle_pairs,
    scan_sequence,
    select_boundary_pool,
)
from .evaluator import CandidateBatch, evaluate_counts, true_route_distance
from .proxy_qubo import SparseProxyQUBO, build_sparse_proxy_qubo
from .qaoa_runner import (
    QAOAParameters,
    QAOARunResult,
    build_qaoa_qasm,
    compilation_audit,
    pretrain_parameters,
    random_counts,
    run_baihua_arm,
    run_simulator_arm,
    transpile_for_baihua,
)


MODE_TO_ARM = {
    "deepblock_random": "random",
    "deepblock_simulator": "simulator",
    "deepblock_exact": "exact",
    "deepblock_hardware": "hardware",
    "random": "random",
    "sim": "simulator",
    "simulator": "simulator",
    "exact": "exact",
    "baihua": "hardware",
    "hardware": "hardware",
}


@dataclass(frozen=True)
class DeepBlockConfig:
    pool_size: int = 16
    block_size: int = 8
    overlap: int = 3
    qaoa_depth: int = 1
    shots: int = 4096
    candidate_k: int = 64
    scan_order: str = "forward"
    routing_method: str = "heuristic"
    backend: str = "Baihua"
    max_cnot: int = 96
    max_depth: int = 240
    submit_hardware: bool = False
    confirm_hardware_submit: bool = False
    wait_hardware: bool = True

    def __post_init__(self) -> None:
        if not 1 <= int(self.block_size) <= 8:
            raise ValueError("block_size must be between 1 and 8")
        if int(self.qaoa_depth) not in {1, 2, 3}:
            raise ValueError("qaoa_depth must be 1, 2, or 3")
        if int(self.shots) < 1 or int(self.candidate_k) < 1:
            raise ValueError("shots and candidate_k must be positive")
        if self.scan_order not in {"forward", "bidirectional"}:
            raise ValueError("scan_order must be forward or bidirectional")


@dataclass(frozen=True)
class BlockTrace:
    sequence: int
    block: DeepBlock
    source: str
    baseline_distance: float
    distance_after: float
    accepted: bool
    decision: str
    proxy: SparseProxyQUBO
    run: QAOARunResult
    candidates: CandidateBatch | None
    status: str

    def payload(self) -> dict[str, object]:
        return {
            "sequence": self.sequence,
            "block": self.block.payload(),
            "source": self.source,
            "baseline_distance": self.baseline_distance,
            "distance_after": self.distance_after,
            "accepted": self.accepted,
            "decision": self.decision,
            "proxy": self.proxy.payload(),
            "run": self.run.payload(),
            "candidates": self.candidates.payload() if self.candidates else None,
            "status": self.status,
        }


@dataclass(frozen=True)
class DeepBlockResult:
    mode: str
    source: str
    status: str
    message: str
    baseline_distance: float
    final_distance: float
    accepted_moves: int
    blocks: tuple[DeepBlock, ...]
    candidate_pool: tuple[BoundaryCandidate, ...]
    assignments: dict[int, list[Customer]]
    traces: tuple[BlockTrace, ...]

    @property
    def improvement(self) -> float:
        return self.baseline_distance - self.final_distance

    def payload(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "source": self.source,
            "status": self.status,
            "message": self.message,
            "baseline_distance": self.baseline_distance,
            "final_distance": self.final_distance,
            "improvement": self.improvement,
            "accepted_moves": self.accepted_moves,
            "blocks": [block.payload() for block in self.blocks],
            "candidate_pool": [row.payload() for row in self.candidate_pool],
            "assignments": {
                str(vehicle): [customer.customer_id for customer in customers]
                for vehicle, customers in sorted(self.assignments.items())
            },
            "traces": [trace.payload() for trace in self.traces],
        }


def prepare_deepblocks(
    instance: DispatchInstance,
    assignments: Mapping[int, Sequence[Customer]],
    config: DeepBlockConfig,
) -> tuple[list[BoundaryCandidate], list[DeepBlock]]:
    pairs = rank_vehicle_pairs(assignments, instance.depot)
    if not pairs:
        return [], []
    vehicle_pair = max(
        pairs,
        key=lambda pair: (
            min(config.pool_size, len(assignments.get(pair[0], ())) + len(assignments.get(pair[1], ()))),
            -pairs.index(pair),
        ),
    )
    pool = select_boundary_pool(
        assignments,
        vehicle_pair=vehicle_pair,
        depot=instance.depot,
        pool_size=config.pool_size,
    )
    by_id = {customer.customer_id: customer for customer in instance.customers}
    pool_customers = [by_id[row.customer_id] for row in pool]
    interactions = build_interaction_graph(
        pool_customers,
        candidate_scores={row.customer_id: row.score for row in pool},
    )
    blocks = build_overlapping_blocks(
        [row.customer_id for row in pool],
        vehicle_pair=vehicle_pair,
        interactions=interactions,
        block_size=config.block_size,
        overlap=config.overlap,
        max_blocks=3,
    )
    return pool, blocks


def _diagnostic_run(
    arm: str,
    proxy: SparseProxyQUBO,
    *,
    shots: int,
    seed: int,
) -> QAOARunResult:
    if arm == "random":
        counts = random_counts(proxy.width, shots=shots, seed=seed)
        message = "Uniform random samples over the identical local state space."
    else:
        counts = {format(value, f"0{proxy.width}b"): 1 for value in range(1 << proxy.width)}
        message = "Exact enumeration of every local bitstring."
    parameters = QAOAParameters(
        depth=1,
        gamma=(0.0,),
        beta=(0.0,),
        optimizer="not_applicable",
        initial_value=0.0,
        final_value=0.0,
        evaluations=0,
    )
    qasm = "// classical diagnostic arm; no quantum circuit\n"
    return QAOARunResult(
        arm=arm,
        counts=counts,
        qasm=qasm,
        physical_qasm="",
        parameters=parameters,
        compilation=compilation_audit(qasm, swap_count=0, mapping_verified=True),
        shots=sum(counts.values()),
        seed=seed,
        message=message,
    )


def _validate_counts(run: QAOARunResult, width: int) -> str:
    if not run.counts:
        return "counts_empty"
    invalid = [
        bitstring
        for bitstring in run.counts
        if len(str(bitstring).replace(" ", "")) != width
        or set(str(bitstring).replace(" ", "")) - {"0", "1"}
    ]
    if invalid:
        return f"invalid_bitstrings={len(invalid)}"
    if sum(int(value) for value in run.counts.values()) != int(run.shots):
        return "counts_shots_mismatch"
    return ""


def _hardware_run(
    proxy: SparseProxyQUBO,
    parameters: QAOAParameters,
    config: DeepBlockConfig,
    seed: int,
    api_token: str,
) -> QAOARunResult:
    logical_qasm = build_qaoa_qasm(
        proxy, config.qaoa_depth, parameters.gamma, parameters.beta
    )
    if not config.submit_hardware:
        audit = compilation_audit(
            logical_qasm,
            swap_count=0,
            mapping_verified=True,
            max_cnot=config.max_cnot,
            max_depth=config.max_depth,
        )
        return run_baihua_arm(
            proxy=proxy,
            parameters=parameters,
            physical_qasm=logical_qasm,
            compilation=audit,
            shots=config.shots,
            seed=seed,
            backend=config.backend,
            api_token=api_token,
            submit_hardware=False,
            confirm_hardware_submit=False,
            wait=config.wait_hardware,
        )
    try:
        physical_qasm, raw_audit = transpile_for_baihua(
            logical_qasm,
            backend_name=config.backend,
            target_qubits=list(range(proxy.width)),
        )
        audit = compilation_audit(
            physical_qasm,
            swap_count=raw_audit.swap_count,
            mapping_verified=raw_audit.mapping_verified,
            max_cnot=config.max_cnot,
            max_depth=config.max_depth,
        )
    except Exception as exc:
        failed = compilation_audit(
            logical_qasm,
            mapping_verified=False,
            max_cnot=config.max_cnot,
            max_depth=config.max_depth,
        )
        return QAOARunResult(
            arm=f"baihua_p{config.qaoa_depth}",
            counts={},
            qasm=logical_qasm,
            physical_qasm="",
            parameters=parameters,
            compilation=failed,
            shots=config.shots,
            seed=seed,
            backend=config.backend,
            message=f"Physical compilation failed: {type(exc).__name__}: {exc}",
        )
    return run_baihua_arm(
        proxy=proxy,
        parameters=parameters,
        physical_qasm=physical_qasm,
        compilation=audit,
        shots=config.shots,
        seed=seed,
        backend=config.backend,
        api_token=api_token,
        submit_hardware=True,
        confirm_hardware_submit=config.confirm_hardware_submit,
        wait=config.wait_hardware,
    )


def run_deepblock(
    *,
    instance: DispatchInstance,
    initial_assignments: Mapping[int, Sequence[Customer]],
    mode: str,
    config: DeepBlockConfig,
    seed: int,
    api_token: str = "",
) -> DeepBlockResult:
    normalized_mode = str(mode or "").strip().lower()
    if normalized_mode not in MODE_TO_ARM:
        raise ValueError(f"unsupported DeepBlock mode: {mode}")
    source = MODE_TO_ARM[normalized_mode]
    current = {vehicle: list(customers) for vehicle, customers in initial_assignments.items()}
    baseline = true_route_distance(current, instance.depot, routing_method=config.routing_method)
    pool, blocks = prepare_deepblocks(instance, current, config)
    if not blocks:
        return DeepBlockResult(
            mode=normalized_mode,
            source=source,
            status="NOT_EVALUABLE",
            message="No vehicle pair contains enough boundary customers for refinement.",
            baseline_distance=baseline,
            final_distance=baseline,
            accepted_moves=0,
            blocks=(),
            candidate_pool=tuple(pool),
            assignments=current,
            traces=(),
        )

    by_id = {customer.customer_id: customer for customer in instance.customers}
    sequence = list(blocks) if config.scan_order == "forward" else scan_sequence(blocks)
    traces: list[BlockTrace] = []
    accepted_moves = 0
    parameter_transfer: QAOAParameters | None = None
    overall_status = "COMPLETED"
    messages: list[str] = []

    for index, block in enumerate(sequence, start=1):
        before = true_route_distance(current, instance.depot, routing_method=config.routing_method)
        block_customers = [by_id[customer_id] for customer_id in block.customer_ids]
        topology = offline_identity_subgraph(len(block_customers))
        proxy = build_sparse_proxy_qubo(
            assignments=current,
            block_customers=block_customers,
            vehicle_pair=block.vehicle_pair,
            depot=instance.depot,
            vehicle_capacity=instance.vehicle_capacity,
            allowed_logical_edges=topology.logical_edges,
        )
        run_seed = int(seed) * 10_000 + index
        try:
            if source in {"random", "exact"}:
                run = _diagnostic_run(source, proxy, shots=config.shots, seed=run_seed)
            else:
                parameters = pretrain_parameters(
                    proxy,
                    config.qaoa_depth,
                    initial_gamma=(
                        parameter_transfer.gamma
                        if parameter_transfer and parameter_transfer.depth == config.qaoa_depth
                        else None
                    ),
                    initial_beta=(
                        parameter_transfer.beta
                        if parameter_transfer and parameter_transfer.depth == config.qaoa_depth
                        else None
                    ),
                )
                parameter_transfer = parameters
                run = (
                    run_simulator_arm(
                        proxy,
                        config.qaoa_depth,
                        shots=config.shots,
                        seed=run_seed,
                        parameters=parameters,
                    )
                    if source == "simulator"
                    else _hardware_run(
                        proxy,
                        parameters,
                        config,
                        run_seed,
                        api_token or os.environ.get("QUAFU_API_TOKEN", ""),
                    )
                )
        except Exception as exc:
            overall_status = "FAILED"
            messages.append(f"{block.block_id}: {type(exc).__name__}: {exc}")
            placeholder = _diagnostic_run("random", proxy, shots=1, seed=run_seed)
            run = QAOARunResult(
                arm=f"{source}_failed",
                counts={},
                qasm=placeholder.qasm,
                physical_qasm="",
                parameters=placeholder.parameters,
                compilation=placeholder.compilation,
                shots=config.shots,
                seed=run_seed,
                backend=config.backend if source == "hardware" else "",
                message=messages[-1],
            )

        validation_error = _validate_counts(run, proxy.width)
        candidate_batch: CandidateBatch | None = None
        accepted_assignment = None
        step_status = "COMPLETED"
        decision = "rejected: no strictly shorter feasible candidate in Top-k"
        if validation_error:
            step_status = "NOT_EVALUABLE" if not config.submit_hardware else "FAILED"
            if source != "hardware":
                step_status = "FAILED"
            decision = f"rejected: {validation_error}"
            if overall_status != "FAILED":
                overall_status = step_status
        else:
            candidate_batch, accepted_assignment = evaluate_counts(
                arm=run.arm,
                counts=run.counts,
                proxy=proxy,
                assignments=current,
                block_customers=block_customers,
                depot=instance.depot,
                vehicle_capacity=instance.vehicle_capacity,
                candidate_k=(1 << proxy.width) if source == "exact" else config.candidate_k,
                routing_method=config.routing_method,
            )
            if accepted_assignment is not None:
                current = accepted_assignment
                accepted_moves += 1
                decision = (
                    f"accepted: strictly shorter by "
                    f"{candidate_batch.accepted.improvement:.6f}"
                )
        after = true_route_distance(current, instance.depot, routing_method=config.routing_method)
        traces.append(
            BlockTrace(
                sequence=index,
                block=block,
                source=source,
                baseline_distance=before,
                distance_after=after,
                accepted=accepted_assignment is not None,
                decision=decision,
                proxy=proxy,
                run=run,
                candidates=candidate_batch,
                status=step_status,
            )
        )

    if source == "hardware" and not config.submit_hardware:
        overall_status = "NOT_EVALUABLE"
        messages.append("Hardware mode completed as a guarded dry-run; no task was submitted.")
    final_distance = true_route_distance(current, instance.depot, routing_method=config.routing_method)
    return DeepBlockResult(
        mode=normalized_mode,
        source=source,
        status=overall_status,
        message=" | ".join(messages) or "DeepBlock scan completed.",
        baseline_distance=baseline,
        final_distance=final_distance,
        accepted_moves=accepted_moves,
        blocks=tuple(blocks),
        candidate_pool=tuple(pool),
        assignments=current,
        traces=tuple(traces),
    )
