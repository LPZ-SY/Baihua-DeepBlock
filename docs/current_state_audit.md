# Quantum Route Forge current-state audit

Audit date: 2026-08-01  
Target repository: `LPZ-SY/kujinganlai-version`  
Baseline branch/commit: `main` / `05aa6dd93fe66d717f5a37d6981af8ff94a63736`  
Implementation branch: `codex/complete-qrf-workflow`

## Baseline verification

- The local repository was clean and exactly matched the commit named by the implementation guide.
- Baseline runtime: Python 3.12.13 in the repository virtual environment.
- Baseline test command: `.venv\Scripts\python.exe -m pytest -q`.
- Baseline result: 12 passed in 40.84 seconds.
- Offline replay command:

  ```powershell
  .venv\Scripts\python.exe experiments\run_quarkstudio_candidate_quality.py `
    --seed 2026 --customers 4 --vehicles 2 --shots 1024 `
    --reuse-evidence results\quarkstudio_candidate_quality_validated\task_evidence.json `
    --outdir ..\tmp\baseline_replay
  ```

- Replay result matched the checked-in validated evidence: threshold `-0.18208246942526785`, best measured bitstring `1001`, 57/1024 reaching the original energy threshold, and no strict improvement.

## Already implemented

- `app.py` provides a working single-run Dash UI with scenario, classical/quantum mode, task lookup, manual bitstring override, and route visualization.
- `pipeline.py` preserves capacity validation/repair, task query before submission, quantum preference hints, classical simulated annealing, route repair, nearest-neighbor construction, and 2-opt refinement.
- `quafu_bridge.py` contains stable Quafu SQC and SDK submit/query paths, serialized-payload traversal, task polling, endpoint fallback, and deterministic bitstring-to-customer mapping.
- `experiments/run_quantum_candidate_quality.py` freezes a same-budget classical threshold and returns PASS/FAIL/NOT_EVALUABLE without requiring online hardware.
- `experiments/run_quarkstudio_candidate_quality.py` preserves complete measurement counts, evaluates every measured bitstring, stores task evidence, and supports evidence replay.
- The checked-in validated evidence is sufficient to exercise the existing offline closed loop without a token or hardware connection.

## Semantic defects to correct

- The README says the threshold is the best *feasible* classical candidate, while `calibrate_thresholds()` currently takes the minimum energy from all budgeted candidates. The test suite also locks in that all-candidate behavior.
- One PASS field conflates absolute candidate quality, reaching a same-budget classical level, and strictly improving that level.
- The app/pipeline path discards all but the most frequent bitstring, so it cannot expose counts, received shots, evidence hashes, source labels, or per-candidate evaluations.
- `AssignmentMetadata.energy` is the classical full-assignment SA energy even when the requested mode is quantum. The current UI can therefore invite a raw-quantum-energy misreading.
- Manual debug input, replay, live hardware, simulator, and fallback are not represented by a single auditable source model.
- The QuarkStudio script duplicates counts cleaning, bit order, BQM completion, feasibility, and storage logic instead of sharing it with the package and UI.
- Several Chinese user-facing strings in experiment scripts are mojibake and need normalization while preserving CLI compatibility.

## Not yet implemented

- A JSON-serializable `QuantumMeasurementResult`, `CandidateEvaluation`, and `ExperimentSummary` model.
- Shared counts parsing, probability-to-count conversion, strict bit-length/order validation, evidence hashing/redaction, and shots mismatch warnings.
- Schema-v2 all/feasible classical thresholds, exact optimum/random median normalization, absolute quality gates, and per-shot summary metrics.
- Idempotent experiment storage with config/manifest/tasks/candidates/summary/figures and resumable config hashes.
- Config-driven batch experiments with dry-run, hardware task caps, resume, failed-task retry, and bulk evidence replay.
- Fair C, C+R, and C+Q candidate-pool comparison under the same candidate and post-processing budgets.
- Four Dash tabs for Single Run, Candidate Quality, Batch Experiment, and Experiment History.
- Automated paper tables/figures, bootstrap confidence intervals, and data-derived conclusion wording.
- CI configuration and the expanded offline unit/integration/UI test matrix.

## Security and privacy audit

- No committed `.env`, token, cookie, credential, or secret-named file was found.
- No value matching common API-key or bearer/JWT secret formats was found in tracked project files.
- Matches for `api_token`, `access_token`, `jwt`, and `cookie` are parameter names, placeholders, request construction, or test fixtures; no live value is embedded.
- Evidence files contain task metadata, circuits, and counts but no authentication material.
- The workspace-level `.env.txt` is outside the repository and is not read by offline tests or evidence replay.

## Compatibility constraints for implementation

- Keep `run_cli.py`, the app's single-run entry point, and existing replay commands working.
- Wrap the stable network code incrementally; do not replace the SQC/SDK behavior wholesale.
- Never count `manual_debug` or `fallback` as live hardware evidence.
- Offline tests must not require tokens, hardware, network access, or QuarkStudio runtime availability.
