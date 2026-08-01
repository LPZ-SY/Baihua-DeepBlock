# Quantum Route Forge Formal Hardware Protocol v2

Status: frozen and executed. All 24 formal v2 hardware tasks completed and passed strict validation on 2026-08-02.

## Protocol identity

- Protocol: `formal-matrix-v2`
- Frozen formal-protocol commit: `6f417d6c3c3e8a16132cd3a472567f9090edab85`
- Frozen formal-protocol tag: `qrf-formal-protocol-v2`
- Execution-code commit/tag: `9082b74ee2d22ffdd1103f62e3af9ceca18af740` / `qrf-preformal-execution-v2`
- P0-P7 baseline commit/tag: `8eaeefe92a1dd3c1cf1167d7196cead036695517` / `qrf-p0-p7-acceptance-v1`
- Formal config: `experiments/configs/formal_hardware_matrix_v2.json`
- Frozen thresholds: `experiments/configs/formal_hardware_matrix_v2_thresholds.json`
- Threshold file SHA-256: `0f43c81d0d6d4d3f9a07dba6b1a16f6201967cd2e39563069662310cdc630afb`
- Design: 4 fixed instances x 3 fixed chips x 2 repeats = 24 tasks
- Shots: 1024 per task; 24,576 planned shots total
- Bit order: `openqasm_high_classical_bit_left`
- Fixed QAOA-style parameters: gamma 1.1, beta 0.8

## Audit of the historical matrix

`experiments/configs/qrf_hw_quality_v2.json` is retained unchanged. Its expansion happened to contain 24 tasks, but it is not eligible for the formal experiment because it requests `backend=auto`, combines 18 one-off instance conditions with additional repeats on only three selected instances, and does not run every fixed instance twice on Baihua, Dongling, and Shenglian. The formal v2 protocol was therefore added as a new file rather than overwriting the historical matrix.

## Frozen instances

| Instance | Customers | Capacity policy | Capacity | Customer IDs in qubit order | Logical QASM SHA-256 |
| --- | ---: | --- | ---: | --- | --- |
| `seed2026_c4_v2_medium` | 4 | medium | 6 | 3, 4, 1, 2 | `31310d3f5a6294b3503d6b7bef06cc21db56cac73338ea514ef88006329bdc17` |
| `seed2027_c4_v2_tight` | 4 | tight | 6 | 4, 2, 3, 1 | `ae0b0cd8c2d5f9492c0ae33b01e41dc4929ceb32f9730db0d263376b9c432e5e` |
| `seed2026_c6_v2_medium` | 6 | medium | 9 | 3, 4, 6, 1, 2, 5 | `66be66f9b8f9dabb1c6cb01570c585d1f776866559ca992217f6bbee4d211eeb` |
| `seed2027_c6_v2_tight` | 6 | tight | 8 | 4, 2, 3, 5, 1, 6 | `b4de2c04ddbde194c87fe6839e932295d6623238b01d32dfba45763bce83b756` |

The instances use the first predeclared seeds from the historical matrix across its 4- and 6-customer scales and medium/tight capacity policies. No hardware outcome was used to select them. Each instance has complete customer-to-qubit coverage with two vehicles.

## Execution and uniqueness rules

The checked-in `execution_order` interleaves chips and instances. Each instance has exactly the Cartesian set `{Baihua, Dongling, Shenglian} x {repeat 1, repeat 2}`. A task key hashes at least the protocol version, frozen commit, instance ID, requested backend, repeat, shots, logical QASM hash, frozen threshold hash, capacity, and classical calibration budget. Duplicate task keys are rejected by the result-store resume logic.

Fresh hardware submission is blocked unless all of the following are true:

1. The formal config contains no `backend=auto`.
2. The frozen threshold file exists and its raw SHA-256 matches the config.
3. Recomputed customer order and logical QASM hashes match every frozen instance entry.
4. The user has reviewed the dry run and supplies `--confirm-live`.
5. The invocation submits at most one fresh hardware task by default.

For a completed hardware task, `backend_requested` and `backend_actual` are both stored. A mismatch is recorded as `NOT_EVALUABLE`. Missing, incomplete, replay, manual, or fallback counts are not eligible for formal statistics.

## Dry run

```powershell
.\.venv\Scripts\python.exe experiments\batch_candidate_quality.py `
  --config experiments\configs\formal_hardware_matrix_v2.json `
  --dry-run
```

P9 verification result: exactly 24 tasks, 24 unique task keys, 4 instances, 6 tasks per instance, no `auto` backend, identical frozen threshold hash within the matrix, and identical customer order and QASM hash for each instance across chips and repeats.

## Execution record

P10 completed first with one representative task on each of Baihua, Dongling, and Shenglian. After the smoke evidence passed counts, bit-order, backend, source, idempotency, and storage checks, the user explicitly confirmed the displayed 24-task dry-run manifest.

The formal matrix then ran sequentially with one fresh hardware task per guarded invocation. The final store at `results/experiments/qrf_formal_hardware_matrix_v2` contains 24 completed tasks and 24,576 received shots. Requested and actual backends match for every task; no task is failed or non-evaluable. `integrity_report.json` records `complete=true`, `valid=true`, and zero errors or warnings. Formal results and bounded conclusions are reported in `docs/formal_24_task_report.md` and `docs/hybrid_contribution_report.md`.
