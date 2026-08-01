# Quantum Route Forge final acceptance record

Date: 2026-08-01  
Repository: `LPZ-SY/kujinganlai-version`  
Implementation branch: `codex/complete-qrf-workflow`

## Offline implementation acceptance

- [x] Baseline commit `05aa6dd93fe66d717f5a37d6981af8ff94a63736` was audited before implementation.
- [x] Existing single-run CLI, Dash entry point, SQC/SDK adapters, and checked-in evidence replay remain available.
- [x] App, pipeline, Quark adapters, replay, and experiments share `QuantumMeasurementResult` with complete counts.
- [x] Hardware, simulator, replay, manual debug, and fallback sources are distinct; only completed hardware is formal live evidence.
- [x] Counts cleaning covers nested/serialized payloads, probabilities, invalid keys, bit length, bit order, and shot mismatches.
- [x] Schema-v2 thresholds store same-budget all-candidate and raw-feasible classical energies separately.
- [x] Every evaluated bitstring can report energy, raw feasibility, exact gap, normalized score, absolute quality, classical reach, and strict improvement.
- [x] Zero normalization denominators remain null/not evaluable rather than being silently converted to zero.
- [x] Formal matrix is config-driven, two-vehicle, 100%-coverage, and uses 1024-shot multiples.
- [x] Batch runner supports dry-run, task caps, resume, failed-task retry, pause points, and evidence replay.
- [x] Result store writes immutable config/thresholds, task and candidate JSONL, summaries, figures, logs, and redacted evidence.
- [x] C, C+R, and C+Q use equal candidate budgets and a shared evaluator/post-processing path; a deduplicated quantum sensitivity mode is available.
- [x] Dash provides Single Run, Candidate Quality, Batch Experiment, and Experiment History tabs.
- [x] Classical mode hides quantum credentials; the default scenario is feasible; capacity and quantum coverage are explicit.
- [x] Submit, query, and manual-debug actions are separate. Query failure never silently submits a replacement task.
- [x] Paper artifacts and conclusion text are generated from stored data.
- [x] README states the circuit/BQM boundary and does not claim universal advantage, speed advantage, or pure-quantum VRP solving.
- [x] GitHub Actions runs compilation and the complete offline pytest suite without credentials.

Final offline verification: Python 3.12.13, `compileall` passed, `28 passed` in 45.67 seconds, classical CLI smoke passed, both replay/live result stores passed required-file integrity checks, and the final secret-value scan found no API-key, bearer-token, or JWT value pattern.

## Checked-in evidence replay acceptance

Evidence: `results/quarkstudio_candidate_quality_validated/task_evidence.json`

- Historical task ID: `2608011815107080366`
- Backend: `Dongling`
- Counts: 16 valid four-bit outcomes, totaling 1024 shots
- Replay source label: `replay` (not counted as a newly executed hardware task)
- Raw feasible rate: 0.2880859375
- Absolute quality hit rate at tau=0.20: 0.2880859375
- Uniform-random absolute quality hit rate: 0.375
- Same-budget feasible classical reach rate: 0.0556640625
- Strict feasible classical improvement rate: 0.0
- Best exact gap: 0.0

Data-derived interpretation: the historical measurement contains raw-feasible low-energy candidates and reaches the same-budget classical threshold, but its observed absolute-quality hit rate is below the uniform-random reference and no strict improvement is observed. This is candidate evidence, not a claim of general quantum advantage.

## Fresh live-hardware manual gate

Result store: `results/experiments/qrf_live_acceptance_20260801`

- [x] New live `hardware` task ID `2608012138290414123` and backend `Baihua` recorded.
- [x] Completed status with 16 non-empty count outcomes and `sum(counts) == shots_received == 1024`.
- [x] Evidence/store records the circuit, selected customer order `3,4,1,2`, OpenQASM bit order, task time, and circuit/threshold/evidence hashes.
- [x] Frozen thresholds were created at `2026-08-01T21:38:23+08:00`, before the completed task record at `2026-08-01T21:38:34+08:00`.
- [x] Candidate analysis used complete counts without a manual bitstring; source is `hardware`.
- [x] Failure/timeout behavior is covered offline and produces `NOT_EVALUABLE` while retaining evidence.

Fresh live metrics: raw feasible/absolute-quality hit rate `0.2548828125`, uniform-random quality hit rate `0.375`, feasible classical reach rate `0.0595703125`, strict improvement rate `0.0`, and best exact gap `0.0`.

Data-derived interpretation: the fresh hardware task produced candidates that reach the frozen same-budget feasible-classical level, but the absolute-quality hit rate is below the uniform-random reference and no strict classical improvement is observed. The acceptance proves a complete auditable hardware data path, not quantum advantage.
