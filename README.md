# Quantum Route Forge

Original repository for a quantum-optimization competition project.

## Project Goal
`Quantum Route Forge` solves a synthetic fleet dispatch problem with two stages:

1. **Assignment stage (quantum-ready)**  
   Build a Binary Quadratic Model (BQM) to assign customers to vehicles under capacity constraints.
2. **Routing stage (classical local refinement)**  
   For each vehicle cluster, build a route with nearest-neighbor and improve it with 2-opt.

## What makes it quantum
- The assignment stage is encoded as a BQM using `dimod`.
- Solver option `quantum` submits a real Quafu cloud task (`pyquafu`) and returns `task_id`.
- The returned quantum bitstring is used as a soft assignment hint, then refined by classical BQM search.
- If Quafu is unavailable (network/token/backend), the pipeline keeps running with local classical fallback.
- Capacity is strict: if total demand exceeds fleet capacity, the run exits with an explicit error (no global auto-repair).

## Repository Structure

```text
QuantumRouteForge_Original_20260510/
  app.py
  run_cli.py
  requirements.txt
  README.md
  docs/
    originality.md
  src/
    quantum_route_forge/
      __init__.py
      models.py
      geometry.py
      scenario.py
      assignment_bqm.py
      solvers.py
      routing.py
      pipeline.py
  tests/
    test_smoke.py
```

## Quick Start (Windows)

Recommended Python: `3.10` to `3.12` (best compatibility with `pyquafu` dependencies).

```powershell
cd E:\QuantumRouteForge_Original_20260510
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
$env:QUAFU_API_TOKEN="your_token_here"
python app.py --port 8050
```

Open `http://127.0.0.1:8050`

If you are on Python `3.13` and `pyquafu` dependency resolution fails, use:

```powershell
pip install pyquafu --no-deps
pip install autograd
```

## Quafu token setup

You can provide token in either way:

1. Environment variable:
```powershell
$env:QUAFU_API_TOKEN="your_token_here"
```

2. Web UI input (`Quafu Token` field) at runtime.

The app never writes your token into repository files.

For **competition site** (`quafu-sqc`), use your browser login `access_token` (JWT)
from cookie and set base URL to:

```powershell
$env:QUAFU_API_TOKEN="your_access_token_jwt"
$env:QUAFU_BASE_URL="https://quafu-sqc.baqis.ac.cn/"
```

The pipeline auto-detects JWT token format and submits to `/api/task` on the SQC site.

If your token is issued from another Quafu deployment (for example `quafu-sqc`),
set a custom base URL:

```powershell
$env:QUAFU_BASE_URL="https://quafu-sqc.baqis.ac.cn/"
```

## CLI usage

Single run:

```powershell
python run_cli.py --mode quantum --customers 48 --vehicles 4 --capacity 34 --seed 2026 --quafu-backend ScQ-P10
```

With custom URL:

```powershell
python run_cli.py --mode quantum --quafu-backend ScQ-P10 --quafu-base-url https://quafu-sqc.baqis.ac.cn/
```

SQC composer API mode (JWT access token):

```powershell
$env:QUAFU_API_TOKEN="your_access_token_jwt"
python run_cli.py --mode quantum --quafu-base-url https://quafu-sqc.baqis.ac.cn/ --quafu-backend ScQ-P10 --quafu-wait false
```

With proxy/timeout:

```powershell
python run_cli.py --mode quantum --quafu-backend ScQ-P10 --quafu-base-url https://quafu-sqc.baqis.ac.cn/ --quafu-proxy-url http://127.0.0.1:7897 --quafu-timeout-sec 30
```

Comparison run:

```powershell
python run_cli.py --compare --customers 48 --vehicles 4 --capacity 34 --seed 2026
```

If needed, submit-only (do not wait for result):

```powershell
python run_cli.py --mode quantum --quafu-wait false
```

## Network Troubleshooting (Quafu)

If status contains `ConnectionResetError(10054)` or `reserved/test IP 198.18.x.x`:

1. Your local proxy/TUN DNS may be intercepting `quafu.*` domains.
2. In this case, switch proxy node/rule for `quafu.baqis.ac.cn` and `quafu-sqc.baqis.ac.cn` (or temporarily disable TUN mode).
3. You can also pass proxy explicitly:

```powershell
$env:QUAFU_PROXY_URL="http://127.0.0.1:7897"
python run_cli.py --mode quantum --quafu-base-url https://quafu-sqc.baqis.ac.cn/ --quafu-backend ScQ-P10
```

The web app now shows endpoint and DNS diagnostics directly in the status line.

## Notes for competition submission
- This repo is written as a standalone original codebase.
- No external map API is required for core execution.
- The quantum section is explicit, inspectable, and switchable.
- Web status line includes `task_id` and backend when Quafu submission succeeds.

## Independent quantum-candidate quality gate

`experiments/run_quantum_candidate_quality.py` implements a leakage-free, two-stage
check of the quantum sampler's contribution at the assignment-candidate layer:

1. Freeze a per-instance threshold using only the best feasible classical candidate
   under a fixed sampling budget.
2. Evaluate measured quantum candidates under the same budget without changing the
   frozen threshold.

A quantum candidate passes the primary energy gate when its BQM energy reaches or
falls below the frozen threshold within a fixed `1e-9` numerical tolerance; strict
improvement is reported separately. Raw feasibility is also reported. Missing measured bitstrings produce
`NOT_EVALUABLE`, never a positive claim. See
`../量子候选质量独立分析补充.md` for the paper-ready criterion and response text.

For a real QuarkStudio/SQCLab run, use
`experiments/run_quarkstudio_candidate_quality.py`. It freezes the same-budget
classical threshold before submission, selects the shortest queue among Dongling,
Baihua and Shenglian, submits the business OpenQASM 2.0 circuit, evaluates every
measured bitstring, and preserves the task evidence and threshold files. The primary
gate uses a fixed `1e-9` numerical tolerance; strict improvement is reported separately.
