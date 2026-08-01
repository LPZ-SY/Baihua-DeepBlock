# Cross-Backend Smoke Report

Protocol: `cross-backend-smoke-v1`

Status: dry-run passed; fresh hardware tasks not yet submitted.

## Frozen conditions

- Instance: `seed2026_c4_v2_medium`
- Seed/customers/vehicles/capacity: 2026 / 4 / 2 / 6
- Customer IDs in qubit order: 3, 4, 1, 2
- Shots: 1024 per task
- Logical QASM SHA-256: `31310d3f5a6294b3503d6b7bef06cc21db56cac73338ea514ef88006329bdc17`
- Threshold file SHA-256: `0f43c81d0d6d4d3f9a07dba6b1a16f6201967cd2e39563069662310cdc630afb`
- Bit order: `openqasm_high_classical_bit_left`
- Gamma/beta: 1.1 / 0.8
- Compile options: quarkcircuit, correction disabled, dynamic decoupling unset, no manual target-qubit mapping

Only `backend_requested` varies.

## Dry-run manifest

| Order | Backend requested | Task key |
| ---: | --- | --- |
| 1 | Baihua | `63bf003c200b1a23efbef71ad1810f5c3aa87ed71fe027da7718392ac9049d41` |
| 2 | Dongling | `f1e0f47e90745974c43cd9497317723f577578227990c20b6c646b0bda9d7569` |
| 3 | Shenglian | `be6a609e34695dddf1c7a06c4eef738e5bf27c9867898da41b78df7d4f898826` |

Dry-run checks: 3 tasks, 3 unique keys, identical instance/customer order/QASM/threshold/shots, fixed backends, no `auto`, and one-task-per-invocation enforcement.

## Live results

Pending. A task will be accepted only if the source is fresh hardware, requested and actual backends match, counts contain valid bitstrings, and the counts sum equals `shots_received=1024`. Otherwise it will be retained as `FAILED` or `NOT_EVALUABLE` and will not be replaced with replay, manual, or fallback data.
