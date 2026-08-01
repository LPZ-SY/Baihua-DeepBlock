# Final Acceptance v2

Date: 2026-08-01

This record is intentionally incomplete until the formal hardware confirmation gate is satisfied.

## Completed

- [x] P8 P0-P7 baseline pushed and tagged `qrf-p0-p7-acceptance-v1`.
- [x] Baseline manifest hashes recompute successfully.
- [x] Earlier Baihua live acceptance evidence remains protected and unchanged.
- [x] P9 balanced `4 x 3 x 2` protocol frozen and tagged `qrf-formal-protocol-v2`.
- [x] Formal dry run contains 24 unique tasks, fixed chips, frozen QASM/customer/threshold hashes, and no `auto` backend.
- [x] P10 Baihua, Dongling, and Shenglian smoke tasks returned complete 1024-shot counts with matching requested/actual backends.
- [x] P10 evidence is task-ID-addressable, includes redacted raw responses, and passes strict integrity validation.
- [x] C/C+R/C+Q offline workflow enforces equal budgets, a shared classical base, provenance eligibility, source tracking, and task-level statistics.
- [x] Dash and CLI default to one-task guarded submission and preserve fresh/replay/manual/fallback provenance.

## Pending explicit user confirmation and fresh hardware execution

- [ ] P11 all 24 planned formal tasks have one terminal status.
- [ ] Every completed task has counts summing to received shots and matching frozen hashes.
- [ ] P12 formal C/C+R/C+Q results have been generated for every evaluable task.
- [ ] P13 task-, instance-, backend-, and overall statistics and paper figures have been generated from the completed matrix.
- [ ] Final conclusions have been rewritten from the complete predeclared dataset.
- [ ] Final credential scan, integrity validation, release commit/tag, and Pull Request are complete.

Until those items are checked, the project must not claim the final formal experiment is complete.
