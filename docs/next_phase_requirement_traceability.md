# Next-Phase Requirement Traceability

This audit maps the execution guide's P8-P14 requirements to current repository evidence. A stage is marked complete only when its guide-level acceptance evidence exists; implementation readiness is not treated as completed hardware experimentation.

## P8 - Frozen baseline: complete

- Remote commit/tag: `8eaeefe92a1dd3c1cf1167d7196cead036695517` / `qrf-p0-p7-acceptance-v1`.
- Recomputable manifest: `docs/baseline_manifest.json`.
- Protected live acceptance evidence: `results/experiments/qrf_live_acceptance_20260801`.

## P9 - Balanced formal protocol: complete

- Frozen protocol/tag: `experiments/configs/formal_hardware_matrix_v2.json` / `qrf-formal-protocol-v2`.
- Frozen thresholds: `experiments/configs/formal_hardware_matrix_v2_thresholds.json`.
- Dry-run evidence: `docs/formal_24_task_dry_run.json` contains 24 unique fixed-backend tasks and 24,576 requested shots.
- Live code must resolve to `qrf-preformal-execution-v2`; the CLI rejects a different HEAD, tracked changes, `backend=auto`, or a task cap above one.

## P10 - Three-backend smoke: complete

- Baihua: `2608012251527123036`.
- Dongling: `2608012253199368389`.
- Shenglian: `2608012254449770289`.
- Each task has 1024/1024 counts, matching requested/actual backend, identical logical QASM/customer order/threshold hashes, and strict result-store validation.
- Evidence root: `results/experiments/qrf_cross_backend_smoke_20260801`.

## P11 - Formal 24-task hardware matrix: complete

- The user explicitly confirmed the displayed dry run on 2026-08-02.
- All 24 predeclared tasks completed on hardware: 8 each on Baihua, Dongling, and Shenglian, with 1024/1024 shots and requested/actual backend equality for every task.
- The immutable evidence root is `results/experiments/qrf_formal_hardware_matrix_v2`; it includes task identity, timestamps, counts, customer order, QASM and hashes, threshold references, dependency snapshot, queue/poll fields, compile options, optional hardware metadata, redacted raw response, and task-ID-addressable artifacts.
- Strict validation reports `complete=true`, `valid=true`, 24 observed tasks, and zero errors or warnings.

## P12 - Fair C/C+R/C+Q contribution: complete

- Equal budgets and the shared classical subset were enforced for all 24 hardware-task units.
- Quantum bitstrings used the frozen `selected_customer_ids_in_qubit_order`; all 24 C+Q comparisons were evaluable.
- `delta_QR` and `delta_QC` were zero in every task. A quantum candidate won an internal energy/source tie-break in 11/24 tasks, but did not change final route distance.
- Detailed and stratified evidence is retained in `hybrid_summary.csv` and `hybrid/hybrid_aggregate_summary.json`.

## P13 - Task-level statistics and figures: complete

- `experiments/generate_paper_artifacts.py` generated task-, instance-, backend-, and pooled descriptive strata from all 24 predeclared tasks.
- Mean measured quality hit rate was 0.161011 versus a 0.226562 random reference; the mean paired difference was -0.065552 with task-bootstrap 95% CI [-0.079427, -0.051514].
- Feasible-classical threshold reach was positive but low (mean 0.050252); strict improvement was zero in all 24 tasks.
- Required paired, backend-distribution, threshold, hybrid-delta, convergence, and backend-separated energy-CDF artifacts are present under the formal result root.

## P14 - Interface, documentation, and release: final release checks in progress

- Dash exposes requested/actual backend, task ID, shots, source, formal `NOT_EVALUABLE`, and task-level history filters.
- README, protocol, claim boundaries, formal report, hybrid report, and acceptance v2 now distinguish smoke/replay evidence from the completed formal result.
- Final credential scan, test suite, read-only evidence protection, release commit/tag, and Pull Request are the remaining release actions.

## Current gate

Hardware execution and analysis are complete. No further hardware submission is authorized by this phase; only final local validation, evidence protection, release commit/tag, and Pull Request remain.
