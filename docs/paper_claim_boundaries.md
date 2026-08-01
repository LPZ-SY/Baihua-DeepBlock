# Paper Claim Boundaries

## Evidence currently available

- The P0-P7 engineering workflow is frozen and reproducible.
- One earlier Baihua live acceptance task and three P10 cross-backend smoke tasks have complete hardware counts.
- The balanced formal 24-task matrix has been frozen and dry-run validated but has not been submitted.

## Allowed current claims

- The project implements an auditable real-hardware candidate-quality pipeline across Baihua, Dongling, and Shenglian.
- In the P10 smoke tasks, measured quality hit rate was below the frozen uniform-random reference on all three backends, some candidates reached the same-budget feasible-classical threshold, and strict improvement was zero.
- The smoke fair-hybrid sensitivity run did not observe a positive C+Q versus C+R route-distance delta.
- These observations are limited to the tested circuit, parameters, instance, capacity, chips, compilation settings, and dates.

## Claims that are not allowed

- Universal or general quantum advantage.
- Quantum speed advantage.
- A pure-quantum solution of the complete vehicle-routing problem.
- Stable cross-chip superiority before the formal matrix is complete.
- Treating classical-threshold reach as beating the classical threshold.
- Treating a quantum-source tie-break win as a route-distance improvement.
- Treating shots as independent hardware repetitions.
- Presenting replay, manual, simulator, or fallback data as fresh hardware.

The final paper language must be regenerated from all valid predeclared tasks, including unfavorable results and every `FAILED` or `NOT_EVALUABLE` task.
