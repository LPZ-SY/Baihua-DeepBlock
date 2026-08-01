# Paper Claim Boundaries

## Evidence available as of 2026-08-02

- The P0-P7 engineering workflow and formal protocol are frozen and reproducible.
- One earlier Baihua acceptance task and three P10 cross-backend smoke tasks retain complete hardware counts.
- The balanced formal matrix completed all 24 predeclared tasks: four fixed instances, three fixed backends, and two repeats.
- Every formal task returned complete 1024-shot hardware counts with requested backend equal to actual backend; strict result-store validation found no errors.
- All 24 formal tasks, including every unfavorable result, are retained in task-level analyses.

## Allowed current claims

- The project implements an auditable real-hardware candidate-quality pipeline across Baihua, Dongling, and Shenglian.
- In the tested formal matrix, measured quantum quality hit rate was below its frozen uniform-random reference in all 24 tasks. Mean `Quantum - Random` was -0.065552 with a task-bootstrap 95% CI of [-0.079427, -0.051514].
- Measured candidates reached the same-budget feasible-classical threshold at a mean rate of 0.050252, but the strict improvement rate was zero in every task.
- The fair hybrid comparison found `delta_QR = 0` and `delta_QC = 0` in every task; no measured quantum candidate changed final route distance.
- Under the frozen circuit, parameters, instances, compilation settings, and tested hardware, no stable positive quantum candidate-quality or routing contribution was observed.
- Descriptive backend differences were observed, but the experiment does not support a backend superiority ranking.

## Claims that are not allowed

- Universal or general quantum advantage, or universal quantum-method ineffectiveness.
- Quantum speed advantage.
- A pure-quantum solution of the complete vehicle-routing problem.
- Generalization beyond the four instances, two repeats, three backends, fixed circuit, parameters, and execution dates.
- Treating classical-threshold reach as beating the classical threshold.
- Treating a quantum-source energy tie-break as a route-distance improvement.
- Treating shots as independent hardware repetitions.
- Presenting replay, manual, simulator, or fallback data as fresh hardware.
- Deleting or hiding valid but unfavorable tasks.

All statistical inference uses the hardware task, not the shot, as the repetition unit.
