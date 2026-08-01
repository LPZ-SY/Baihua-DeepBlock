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

## P11 - Formal 24-task hardware matrix: awaiting explicit confirmation

- Submission is intentionally not started. The guide requires showing the dry-run and receiving explicit user confirmation first.
- Ready evidence schema includes run/task identity, requested/actual backend, timestamps, counts, customer order, QASM and hashes, threshold references, dependency snapshot, queue/poll fields, compile options, optional hardware metadata, redacted raw response, and task-ID-addressable artifacts.
- `experiments/validate_formal_result_store.py` requires all 24 planned tasks to have terminal status and validates completed evidence against the frozen protocol.

## P12 - Fair C/C+R/C+Q contribution: implementation verified; formal result pending P11

- Equal budgets and shared classical subset are enforced.
- Quantum bitstrings use the frozen `selected_customer_ids_in_qubit_order`; missing or ineligible measurement evidence makes C+Q `NOT_EVALUABLE`.
- Outputs include route distances, paired deltas, final source/rank, repair changes, `hybrid_summary.csv`, and overall/backend/instance task-level bootstrap summaries.
- Corrected P10 sensitivity result: all three `delta_QR` values are zero; this is pipeline evidence, not the formal contribution result.

## P13 - Task-level statistics and figures: implementation verified; formal result pending P11/P12

- `experiments/generate_paper_artifacts.py` preserves task, instance, backend, and pooled descriptive strata.
- Required plots exist for the P10 smoke evidence, including paired quantum/random rates, backend distributions, threshold reach versus strict improvement, C+Q versus C+R delta, and backend-separated shot-weighted energy CDF.
- Final statistics and conclusions must be regenerated from all predeclared formal terminal tasks, including unfavorable and non-evaluable outcomes.

## P14 - Interface, documentation, and release: prepared; final release pending P11-P13

- Dash exposes requested/actual backend, task ID, shots, source, formal `NOT_EVALUABLE`, and task-level history filters.
- README, protocol, claim boundaries, formal report, hybrid report, and acceptance v2 distinguish smoke, replay, and pending formal evidence.
- Final experiment commit/tag and Pull Request are prohibited until the formal matrix, analyses, final scan, and integrity validation are complete.

## Current gate

The only authorized next state-changing action is formal hardware execution after the user explicitly confirms the displayed 24-task dry-run. Until then, the project must remain marked as awaiting confirmation and must not claim P11-P14 completion.
