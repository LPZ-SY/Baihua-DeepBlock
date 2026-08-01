# Final Acceptance v2

Date: 2026-08-02

The explicit hardware confirmation gate was satisfied on 2026-08-02.

## Completed

- [x] P8 P0-P7 baseline pushed and tagged `qrf-p0-p7-acceptance-v1`.
- [x] Baseline manifest hashes recompute successfully.
- [x] Earlier Baihua live acceptance evidence remains protected and unchanged.
- [x] P9 balanced `4 x 3 x 2` protocol frozen and tagged `qrf-formal-protocol-v2`.
- [x] Formal dry run contains 24 unique tasks, fixed chips, frozen QASM/customer/threshold hashes, and no `auto` backend.
- [x] P10 Baihua, Dongling, and Shenglian smoke tasks returned complete 1024-shot counts with matching requested/actual backends.
- [x] P10 evidence is task-ID-addressable, includes redacted raw responses, and passes strict integrity validation.
- [x] Formal live execution is pinned to `qrf-preformal-execution-v2`, requires a clean tracked worktree, and enforces the frozen one-task cap.
- [x] Formal evidence includes task-addressable raw response/counts/QASM/candidate files, dependencies, timestamps, queue/poll fields, compile options, and optional hardware metadata.
- [x] C/C+R/C+Q offline workflow enforces equal budgets, a shared classical base, frozen customer-to-qubit order, provenance eligibility, source tracking, and task-level statistics.
- [x] Paper outputs preserve task-, instance-, and backend-level strata and use a backend-separated shot-weighted energy CDF.
- [x] Dash and CLI default to one-task guarded submission and preserve fresh/replay/manual/fallback provenance.

## Formal experiment completion

- [x] P11 all 24 planned formal tasks are `COMPLETED`; none are failed or non-evaluable.
- [x] Every completed task has 1024/1024 counts, requested/actual backend equality, and matching frozen hashes.
- [x] P12 formal C/C+R/C+Q results were generated for all 24 evaluable tasks with equal budgets and retained provenance.
- [x] P13 task-, instance-, backend-, and overall statistics and paper figures were generated from the complete matrix.
- [x] Final conclusions were rewritten from all 24 predeclared tasks, including unfavorable results.
- [ ] Final credential scan, integrity validation, release commit/tag, and Pull Request are complete.

The project is data-complete; release acceptance remains open until the final scan, validation, release tag, and Pull Request are recorded.
