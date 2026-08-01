# Formal 24-Task Hardware Report

Status: protocol frozen and dry-run validated; fresh hardware submissions pending explicit user confirmation.

The planned matrix is exactly four fixed instances by Baihua, Dongling, and Shenglian by two repeats. It contains 24 unique task keys, requests 1024 shots per task (24,576 total), forbids `backend=auto`, and uses a single frozen threshold file. The exact ordered task list is stored in `docs/formal_24_task_dry_run.json`; live execution is pinned to `qrf-preformal-execution-v2` and capped at one planned task per invocation.

P10 completed successfully on all three backends using one representative instance. That evidence validates counts parsing, bit order, backend provenance, immutable QASM/threshold hashes, task-ID-addressable storage, resume behavior, and raw-response retention. Formal orchestration additionally writes a submission receipt before polling so an interrupted local process resumes the existing task ID instead of submitting a duplicate. P10 is not included as a substitute for any of the 24 planned formal tasks.

No formal task ID, task result, aggregate statistic, or formal conclusion is reported here until the explicit confirmation gate is satisfied and the matrix is actually executed. Missing tasks remain missing; replay, manual bitstrings, simulator data, and classical fallback are not inserted.

After execution, this report must be regenerated from the strict result-store validator and must include every planned task with one terminal status: `COMPLETED`, `FAILED`, or `NOT_EVALUABLE`.
