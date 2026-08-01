# Cross-Backend Smoke Report

Protocol: `cross-backend-smoke-v1`

Status: P10 completed; three fresh hardware tasks passed evidence-integrity checks.

## Frozen conditions

- Instance: `seed2026_c4_v2_medium`
- Seed/customers/vehicles/capacity: 2026 / 4 / 2 / 6
- Customer IDs in qubit order: 3, 4, 1, 2
- Shots: 1024 per task
- Logical QASM SHA-256: `31310d3f5a6294b3503d6b7bef06cc21db56cac73338ea514ef88006329bdc17`
- Threshold file SHA-256: `0f43c81d0d6d4d3f9a07dba6b1a16f6201967cd2e39563069662310cdc630afb`
- Actual task code commit: `6d48a2c5f0c365f6da373cf97aacb6117ae4367e`
- Bit order: `openqasm_high_classical_bit_left`
- Gamma/beta: 1.1 / 0.8
- Compile options: quarkcircuit, correction disabled, dynamic decoupling unset, no manual target-qubit mapping

Only `backend_requested` varied.

## Task results

| Backend | Task ID | Counts | QHR | Random QHR | Q-R | Classical reach | Strict improvement |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Baihua | `2608012251527123036` | 1024/1024 | 0.2568 | 0.3750 | -0.1182 | 0.0596 | 0.0000 |
| Dongling | `2608012253199368389` | 1024/1024 | 0.3271 | 0.3750 | -0.0479 | 0.1396 | 0.0000 |
| Shenglian | `2608012254449770289` | 1024/1024 | 0.2480 | 0.3750 | -0.1270 | 0.0615 | 0.0000 |

All three tasks have `source=hardware`, `status=completed`, and matching requested/actual backends. Each returned all 16 four-bit outcomes with counts summing to 1024. QASM, threshold file, customer order, bit order, shots, and task code commit match across the three evidence bundles. The result store contains three task records, 48 candidate records, three normalized evidence files, redacted raw platform responses, and task-ID-addressable artifact directories.

## Interpretation

The cross-backend pipeline passed. This smoke test is not the formal 24-task matrix. In all three smoke tasks, quantum quality hit rate was below the frozen random reference and strict improvement was zero. The tasks therefore do not support a quantum-advantage claim and are not used as a substitute for the predeclared formal matrix.

## Artifacts

- Result root: `results/experiments/qrf_cross_backend_smoke_20260801`
- Protocol snapshot: `protocol_snapshot.json`
- Task manifest: `task_manifest.csv`
- Cross-backend summary: `cross_backend_smoke_summary.csv`
- Per-task bundle: `tasks/<task_id>/{raw_response.json,counts.json,candidate_metrics.csv,evidence.json}`
