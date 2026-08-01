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
  configs/qrf_hw_quality_v2.json        Historical unbalanced/auto matrix (audit only)
  configs/formal_hardware_matrix_v2.json Frozen balanced 4x3x2 protocol
  run_quantum_candidate_quality.py      CSV compatibility CLI using schema-v2 thresholds
  run_quarkstudio_candidate_quality.py  Single live/replay closed loop
  batch_candidate_quality.py            Resumable, quota-aware batch runner
  validate_formal_result_store.py       Strict task/evidence/provenance validator
  prepare_hybrid_input.py               Reproducible task-level fair-pool input builder
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
  formal_experiment_protocol.md         Frozen matrix protocol and submission gates
  formal_24_task_dry_run.json           Exact 24-task manifest; no hardware access
  cross_backend_smoke_report.md         P10 Baihua/Dongling/Shenglian evidence report
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

- **Single Run** — defaults to a feasible 8-customer, 2-vehicle classical scenario; shows requested/actual backend, task ID, source, requested/received shots, capacity, and quantum coverage. Incomplete, replay, manual, or fallback measurements are explicitly not evaluable for formal statistics.
- **Candidate Quality** — preserves fresh-hardware versus replay provenance, evaluates complete counts, and displays absolute quality, random reference, classical-threshold reach, strict improvement, exact gap, and feasibility separately.
- **Batch Experiment** — previews the fixed-backend formal matrix, verifies its frozen threshold hash, caps the UI at one fresh task per invocation, requires an explicit confirmation checkbox, and supports resume/pause.
- **Experiment History** — lists task-level instance/backend/status/source provenance with dedicated filters and the result-store integrity state.

Manual bitstrings are always labeled `manual_debug` and are excluded from formal hardware statistics.

## Single-run CLI

Classical mode needs no token:

```powershell
.\.venv\Scripts\python.exe run_cli.py --mode classical --customers 8 --vehicles 2 --capacity 13 --seed 2026
```

Quantum submit through SQC uses the browser JWT access token:

```powershell
$env:QUAFU_API_TOKEN="<JWT>"
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
$env:QPU_API_TOKEN="<QPU_TOKEN>"
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
  --config experiments\configs\formal_hardware_matrix_v2.json `
  --dry-run
```

The frozen v2 protocol is a balanced `4 instances x 3 fixed backends x 2 repeats = 24 tasks`
matrix. It forbids `backend=auto`, verifies the frozen threshold file and QASM/customer
order hashes, and prints 24 unique task keys without accessing hardware. Live submission also
requires `HEAD` to resolve to the frozen `execution_git_tag`, a clean tracked worktree, and the
protocol-enforced one-task cap.

After reviewing the dry-run manifest, submit at most one fresh hardware task with explicit confirmation:

```powershell
.\.venv\Scripts\python.exe experiments\batch_candidate_quality.py `
  --config experiments\configs\formal_hardware_matrix_v2.json `
  --confirm-live --max-hardware-tasks 1
```

Resume without duplicating completed `config_hash` values:

```powershell
.\.venv\Scripts\python.exe experiments\batch_candidate_quality.py `
  --config experiments\configs\formal_hardware_matrix_v2.json `
  --confirm-live --resume --max-hardware-tasks 1
```

Use `--retry-failed` to target failed records and `--reuse-evidence <path>` to exercise the same orchestration/evaluation/storage path offline. Every task is written immediately, so an interrupted run can recover from `tasks.jsonl`.

The historical `qrf_hw_quality_v2.json` is retained for auditability but is not eligible for
formal submission because it used `backend=auto` and did not repeat each fixed instance on
all three chips. The frozen formal v2 matrix contains four predeclared 4/6-customer,
two-vehicle instances, medium/tight capacity pressure, 1024 shots, and two repeats on each
of Baihua, Dongling, and Shenglian. Large 24/48-customer, four-vehicle pages remain
engineering demonstrations and are not mixed with the 100%-coverage main candidate-quality claim.

## Fair hybrid contribution experiment

`experiments/hybrid_contribution.py` compares:

- `C`: `N` classical candidates;
- `C+R`: `N/2` classical plus `N/2` uniform-random candidates;
- `C+Q`: `N/2` classical plus `N/2` measured quantum candidates;
- `Q-only`: diagnostic only.

All groups use the same total budget, evaluator, capacity repair, nearest-neighbor construction, 2-opt rounds, and final selection rule. C+R and C+Q reuse the exact same classical subset; only the added random versus measured-quantum half differs. Missing/non-hardware measured candidates make C+Q `NOT_EVALUABLE` instead of silently degrading to a classical pool. Results include `D_C`, `D_C_plus_R`, `D_C_plus_Q`, `delta_QR`, `delta_QC`, final winner source/rank, repair changes, and task-level bootstrap intervals. `--deduplicate-quantum` provides the required unique-candidate sensitivity check.

Prepare input directly from a complete validated result store:

```powershell
.\.venv\Scripts\python.exe experiments\prepare_hybrid_input.py `
  --config experiments\configs\formal_hardware_matrix_v2.json `
  --experiment-dir results\experiments\qrf_formal_hardware_matrix_v2 `
  --output results\experiments\qrf_formal_hardware_matrix_v2\hybrid_input.json

.\.venv\Scripts\python.exe experiments\hybrid_contribution.py `
  --input results\experiments\qrf_formal_hardware_matrix_v2\hybrid_input.json `
  --outdir results\experiments\qrf_formal_hardware_matrix_v2\hybrid
```

The measured bitstrings are decoded with the frozen
`selected_customer_ids_in_qubit_order`; backend, repeat, final source, and paired deltas are
retained at the hardware-task level. The workflow writes both JSON detail and
`hybrid_summary.csv`, including backend- and instance-stratified bootstrap summaries.

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
  protocol_snapshot.json
  baseline_manifest.json
  task_manifest.csv
  tasks/<task_id>/
    evidence.json
    raw_response.json
    counts.json
    logical_qasm.qasm
    candidate_metrics.csv
    summary.json
  raw_evidence/
  figures/
  logs/
```

`config.json`, frozen thresholds, and evidence hashes are immutable for a given experiment/config hash. Authentication material is recursively redacted before evidence is written.
Completed formal evidence also records the dependency snapshot, timestamps, queue/poll fields,
compile options, optional hardware metadata, requested/actual backend, QASM/customer order, and
all frozen hashes. Validate the complete matrix before analysis:

```powershell
.\.venv\Scripts\python.exe experiments\validate_formal_result_store.py `
  --config experiments\configs\formal_hardware_matrix_v2.json `
  --experiment-dir results\experiments\qrf_formal_hardware_matrix_v2
```

## Paper artifacts

After an experiment:

```powershell
.\.venv\Scripts\python.exe experiments\generate_paper_artifacts.py `
  --experiment-dir results\experiments\qrf_formal_hardware_matrix_v2
```

The result root receives task-, instance-, and backend-level CSV/JSON summaries. The `figures/`
directory receives a CSV/LaTeX result table, backend-separated shot-weighted energy CDF,
task-paired measured-versus-random chart, classical-reach versus strict-improvement chart,
C+Q versus C+R delta chart, empirical resampling chart, and data-derived conclusion text.
Neutral or `NOT_EVALUABLE` wording is generated when evidence is incomplete.

It also writes task-level candidate-quality and cross-backend CSVs, `statistics_summary.json`, separate classical-reach/strict-improvement bars, a backend distribution plot, and the `C+Q` versus `C+R` route-delta plot. Statistical inference uses the hardware task as the repeat unit; shots are never treated as independent experiments.

## Testing and CI

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

The offline suite covers dual thresholds, equality/strict comparisons, zero normalization denominators, nested/probability counts, shot mismatches, bit order, evidence-source isolation, exact evaluation, result-store idempotence, batch resume, fair candidate budgets, app tabs, capacity behavior, and checked-in evidence replay.

Fresh P10 smoke evidence is checked in for Baihua task `2608012251527123036`, Dongling task `2608012253199368389`, and Shenglian task `2608012254449770289`; each has 1024/1024 counts and matching requested/actual backend, QASM, thresholds, customer order, and code commit. These three tasks validate the pipeline only. The formal 24-task matrix remains unsubmitted until explicit user confirmation, and no replay/manual/fallback data is substituted for it.

## Network troubleshooting

If Quafu diagnostics show `ConnectionResetError(10054)` or a reserved/test `198.18.x.x` address, local proxy/TUN DNS interception is likely. Change the proxy rule/node for `quafu.baqis.ac.cn` and `quafu-sqc.baqis.ac.cn`, or pass an explicit proxy:

```powershell
$env:QUAFU_PROXY_URL="http://127.0.0.1:7897"
```

Endpoint and DNS diagnostics appear in Single Run without being included in formal candidate claims.
