# Quantum Route Forge paper result companion

The formal result was generated from all 24 predeclared hardware tasks after strict result-store validation. P10 smoke evidence is not included in the formal statistics.

## Experimental setup

Report the immutable experiment ID/config hash, Git commit, Python/dependency versions, platform/backend, shots, task time, circuit hash, threshold hash, BQM weights, fixed gamma/beta, customer selection order, bit order, and capacity-pressure definition.

The main candidate-quality matrix must use two vehicles and 100% customer-to-qubit coverage. Partial-coverage and 24/48-customer engineering demonstrations must be reported separately.

## Candidate-quality result table

| Instance | Source | Tasks | Shots | Quality HR | Random HR | Classical reach | Strict improve |
|---|---|---:|---:|---:|---:|---:|---:|
| seed2026_c4_v2_medium | Hardware | 6 | 6144 | 0.277181 | 0.375000 | 0.062663 | 0 |
| seed2027_c4_v2_tight | Hardware | 6 | 6144 | 0.064290 | 0.125000 | 0.064290 | 0 |
| seed2026_c6_v2_medium | Hardware | 6 | 6144 | 0.101074 | 0.125000 | 0.039225 | 0 |
| seed2027_c6_v2_tight | Hardware | 6 | 6144 | 0.201497 | 0.281250 | 0.034831 | 0 |

## Required figures

1. Candidate-energy CDF with exact and frozen threshold lines.
2. Measured versus uniform-random absolute quality hit rates.
3. Hit rate by customers/qubits, capacity pressure, and backend.
4. Repeated-task variation with 95% bootstrap intervals.
5. C, C+R, and C+Q energy, repair-moved customers, and final route distance.
6. Shot-budget convergence labeled as empirical resampling unless temporal shot order is actually available.

All uncertainty intervals and paired comparisons use one hardware task as one repeat. Shots describe the within-task measurement distribution and are not independent experimental replicates. Results must also be shown separately for Baihua, Dongling, and Shenglian before any pooled descriptive summary.

## Conclusion rules

- If measured quality hit rate exceeds random with appropriate uncertainty support: “Hardware sampling shows a higher hit tendency for the prespecified low-energy feasible region.”
- If feasible classical reach rate is positive: “At least one measured candidate reaches the frozen same-budget feasible-classical threshold.”
- If strict improvement is positive: “A candidate below the frozen same-budget threshold is observed for this instance and budget; this is not generalized.”
- If complete counts or a usable frozen criterion are absent: “NOT_EVALUABLE: current evidence is insufficient to evaluate quantum-candidate quality.”
- If C+Q improves on C+R only for some instances: “Quantum candidates provide instance-dependent incremental contribution.”

Never replace these bounded statements with claims of universal quantum advantage, speed advantage, or pure-quantum optimization of the full vehicle-routing problem.

For the completed formal matrix, measured QHR was below the prespecified random reference in all 24 tasks, strict feasible-classical improvement was absent, and C+Q changed no final route distance relative to C+R. See `docs/formal_24_task_report.md`, `docs/hybrid_contribution_report.md`, and the generated figures under `results/experiments/qrf_formal_hardware_matrix_v2/figures`.
