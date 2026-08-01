# Quantum Route Forge

`LPZ-SY/kujinganlai-version` is a reproducible research and demonstration platform for quantum-seeded fleet assignment and classical route refinement.

The project makes a deliberately narrow claim: real-hardware measurements can be evaluated as assignment candidates, compared with random and same-budget classical candidates, and tested for incremental contribution to a shared hybrid pipeline. It does **not** claim universal quantum advantage, speed advantage, or a pure-quantum solution of the complete vehicle-routing problem.

## What the system does

The production path has two layers:

1. A frozen QAOA-style proximity circuit produces a two-vehicle partition seed. The circuit uses fixed `gamma=1.1` and `beta=0.8`; it is not a direct QAOA encoding of the complete assignment BQM.
2. The shared BQM evaluator scores the seed, while the single-run product path uses it as a soft preference before classical simulated annealing, capacity repair, nearest-neighbor routing, and 2-opt.

Accordingly, the value displayed as **Classical full-assignment energy** in Single Run is the final classical BQM-search energy. It is never described as raw quantum-candidate energy.

## Repository structure

```text
app.py                                  Four-tab Dash experiment platform
run_cli.py                              Compatible single-run CLI
experiments/
  configs/qrf_hw_quality_v2.json        Formal hardware matrix
  run_quantum_candidate_quality.py      CSV compatibility CLI using schema-v2 thresholds
  run_quarkstudio_candidate_quality.py  Single live/replay closed loop
  batch_candidate_quality.py            Resumable, quota-aware batch runner
  hybrid_contribution.py                Fair C / C+R / C+Q comparison
  generate_paper_artifacts.py           Tables, CDFs, hit rates, convergence, conclusions
src/quantum_route_forge/
  models.py                             Shared serializable measurement/candidate/summary models
  quantum_measurements.py               Counts parsing, shots, bit order, source, evidence hashes
  candidate_quality.py                  Exact reference, dual thresholds, three quality gates
  result_store.py                       Immutable config and idempotent experiment artifacts
  quafu_bridge.py                       Existing SQC/SDK networking wrapped by shared models
  pipeline.py                           Compatible hybrid single-run pipeline
tests/                                  Offline unit, integration, replay, batch, fairness, UI tests
docs/
  current_state_audit.md                Frozen baseline audit
  baseline_manifest.json                Baseline hashes and replay result
results/experiments/<experiment_id>/    Reproducible experiment stores
```

## Installation

Python 3.12 is the validated runtime.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pytest -q
```

Offline tests, evidence replay, candidate analysis, dry runs, and history inspection require no token and no network access.

## Dash experiment platform

```powershell
.\.venv\Scripts\python.exe app.py --port 8050
```

Open `http://127.0.0.1:8050`.

The application provides four tabs:

- **Single Run** — defaults to a feasible 8-customer, 2-vehicle classical scenario; shows a compact capacity diagnostic, auto capacity, quantum coverage, source, received shots, and clearly separated submit/query/manual-debug actions. Quantum credentials are hidden in classical mode.
- **Candidate Quality** — loads evidence and frozen thresholds, evaluates complete counts, and displays weighted gate metrics, per-bitstring energy/probability, exact gap, feasibility, and conclusion text.
- **Batch Experiment** — previews the formal matrix, starts/resumes a background CLI runner, requests pause after the current task, and reads progress from JSONL state.
- **Experiment History** — lists experiment integrity, task/candidate/evidence counts, and required artifact presence.

Manual bitstrings are always labeled `manual_debug` and are excluded from formal hardware statistics.

## Single-run CLI

Classical mode needs no token:

```powershell
.\.venv\Scripts\python.exe run_cli.py --mode classical --customers 8 --vehicles 2 --capacity 13 --seed 2026
```

Quantum submit through SQC uses the browser JWT access token:

```powershell
$env:QUAFU_API_TOKEN="your_access_token_jwt"
$env:QUAFU_BASE_URL="https://quafu-sqc.baqis.ac.cn/"
.\.venv\Scripts\python.exe run_cli.py --mode quantum --customers 8 --vehicles 2 --capacity 13 --quafu-wait false
```

The token is used in memory and is never written to evidence, manifests, or logs.

## Unified measurement model

Every adapter converts its result to `QuantumMeasurementResult`:

- `source`: `hardware`, `simulator`, `replay`, `manual_debug`, or `fallback`;
- task status, task ID, platform, backend, endpoint;
- requested and received shots;
- complete cleaned counts and derived most-frequent bitstring;
- selected customer order and `bit_order`;
- circuit/payload hashes, timestamps, evidence path, warnings.

Counts parsing supports nested payloads, JSON/Python-literal strings, count dictionaries, and probability dictionaries. Invalid keys and bit lengths are rejected. A received-shot mismatch is preserved as a warning and rates use `shots_received`, never the requested value. If an adapter exposes only one sample, the result explicitly records `shots_received=1` instead of fabricating a distribution.

Formal summaries accept only completed `hardware` measurements. Replay remains fully evaluable but visibly labeled as replay.

## Candidate-quality criteria

Thresholds are frozen before a hardware result is read. Schema v2 stores both classical diagnostics:

- `best_classical_energy_all`: minimum energy among all same-budget classical candidates;
- `best_classical_energy_feasible`: minimum energy among raw-feasible same-budget classical candidates.

If the fixed classical budget contains no feasible candidate, the feasible reach gate is `NOT_EVALUABLE`; it never falls back to an infeasible threshold.

For a measured candidate `z`:

```text
normalized_score(z) = (E(z) - E*) / (E_random_median - E*)
quality_gate_pass = raw_feasible and normalized_score <= 0.20
near_quality_gate_pass = raw_feasible and normalized_score <= 0.50
classical_reach_feasible_pass = raw_feasible and E(z) <= T_feasible + 1e-9
strict_improvement_feasible_pass = raw_feasible and E(z) < T_feasible - 1e-9
```

If the normalization denominator is zero, normalized fields are `null` and the absolute gate is not evaluable; the exact gap is still reported.

Report interpretation follows this order:

1. Absolute low-energy feasible-region hit rate versus uniform random.
2. Reach of the same-budget frozen feasible-classical threshold.
3. Strict improvement below that threshold.
4. Incremental contribution of C+Q versus the fair C+R control.

Reaching a classical threshold is not rewritten as “quantum beats classical.”

## Single QuarkStudio run or evidence replay

Live run requirements: two vehicles, 100% customer-to-qubit coverage, and shots that are a positive multiple of 1024.

```powershell
$env:QPU_API_TOKEN="your_quarkstudio_token"
.\.venv\Scripts\python.exe experiments\run_quarkstudio_candidate_quality.py `
  --seed 2026 --customers 4 --vehicles 2 --capacity-pressure medium --shots 1024 `
  --outdir results\single_live
```

Offline replay does not read a token:

```powershell
.\.venv\Scripts\python.exe experiments\run_quarkstudio_candidate_quality.py `
  --seed 2026 --customers 4 --vehicles 2 --shots 1024 `
  --reuse-evidence results\quarkstudio_candidate_quality_validated\task_evidence.json `
  --outdir results\single_replay
```

Missing/failed counts produce a preserved evidence record and `NOT_EVALUABLE`, not fallback-positive output.

## Formal batch experiment

Preview the exact matrix and shot budget without submitting:

```powershell
.\.venv\Scripts\python.exe experiments\batch_candidate_quality.py `
  --config experiments\configs\qrf_hw_quality_v2.json `
  --dry-run
```

Run with a per-invocation hardware cap:

```powershell
.\.venv\Scripts\python.exe experiments\batch_candidate_quality.py `
  --config experiments\configs\qrf_hw_quality_v2.json `
  --max-hardware-tasks 3
```

Resume without duplicating completed `config_hash` values:

```powershell
.\.venv\Scripts\python.exe experiments\batch_candidate_quality.py `
  --config experiments\configs\qrf_hw_quality_v2.json `
  --resume --max-hardware-tasks 3
```

Use `--retry-failed` to target failed records and `--reuse-evidence <path>` to exercise the same orchestration/evaluation/storage path offline. Every task is written immediately, so an interrupted run can recover from `tasks.jsonl`.

The formal default matrix contains customers 4/6/8, two vehicles, three fixed seeds, medium/tight capacity pressure, 1024 shots, and selected repeated instances. Large 24/48-customer, four-vehicle pages remain engineering demonstrations and are not mixed with the 100%-coverage main candidate-quality claim.

## Fair hybrid contribution experiment

`experiments/hybrid_contribution.py` compares:

- `C`: `N` classical candidates;
- `C+R`: `N/2` classical plus `N/2` uniform-random candidates;
- `C+Q`: `N/2` classical plus `N/2` measured quantum candidates;
- `Q-only`: diagnostic only.

All groups use the same total budget, evaluator, capacity repair, nearest-neighbor construction, 2-opt rounds, and final selection rule. Results include candidate energy, raw feasibility, repair-moved customer count, final route distance, paired C+Q versus C+R gains, and quantum-source win rate. `--deduplicate-quantum` provides the required unique-candidate sensitivity check.

## Result store

Each batch experiment is stored under:

```text
results/experiments/<experiment_id>/
  config.json
  manifest.json
  frozen_thresholds.json
  tasks.jsonl
  candidates.jsonl
  instance_summary.csv
  aggregate_summary.json
  raw_evidence/
  figures/
  logs/
```

`config.json`, frozen thresholds, and evidence hashes are immutable for a given experiment/config hash. Authentication material is recursively redacted before evidence is written.

## Paper artifacts

After an experiment:

```powershell
.\.venv\Scripts\python.exe experiments\generate_paper_artifacts.py `
  --experiment-dir results\experiments\qrf_hw_quality_v2
```

The `figures/` directory receives a CSV/LaTeX instance table, candidate-energy CDF, measured-versus-random hit-rate chart, empirical shot-resampling convergence chart, and data-derived conclusion text. Neutral or `NOT_EVALUABLE` wording is generated when evidence is incomplete.

## Testing and CI

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

The offline suite covers dual thresholds, equality/strict comparisons, zero normalization denominators, nested/probability counts, shot mismatches, bit order, evidence-source isolation, exact evaluation, result-store idempotence, batch resume, fair candidate budgets, app tabs, capacity behavior, and checked-in evidence replay.

Live hardware is a manual acceptance gate, not a pytest dependency. A valid live acceptance record must contain task ID, backend, completed status, complete counts, received shots, circuit/customer/bit-order evidence, a threshold timestamp/hash predating result evaluation, and a non-debug source. Until a fresh task satisfying these conditions is supplied, the project records live acceptance as pending rather than inventing evidence.

## Network troubleshooting

If Quafu diagnostics show `ConnectionResetError(10054)` or a reserved/test `198.18.x.x` address, local proxy/TUN DNS interception is likely. Change the proxy rule/node for `quafu.baqis.ac.cn` and `quafu-sqc.baqis.ac.cn`, or pass an explicit proxy:

```powershell
$env:QUAFU_PROXY_URL="http://127.0.0.1:7897"
```

Endpoint and DNS diagnostics appear in Single Run without being included in formal candidate claims.
