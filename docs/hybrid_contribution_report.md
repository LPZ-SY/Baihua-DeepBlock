# Fair Hybrid Contribution Report

Status: workflow validated on P10 smoke evidence; formal 24-task contribution result pending.

The comparison uses equal total candidate budgets for C, C+R, and C+Q. C+R and C+Q share the exact same classical subset and differ only in the added uniform-random versus measured-quantum half. All candidates pass through the same BQM evaluator, repair, routing, and 2-opt stages. An empty, failed, replay, manual, or fallback quantum source makes C+Q `NOT_EVALUABLE` for formal analysis.

The task-level outputs are `D_C`, `D_C_plus_R`, `D_C_plus_Q`, `delta_QR = D(C+R) - D(C+Q)`, `delta_QC = D(C) - D(C+Q)`, final winner source, best quantum rank, and repair/route changes. Aggregates report mean, median, standard deviation, positive-task rate, and a 95% bootstrap interval using the hardware task—not the shot—as the repetition unit.

The P10 smoke sensitivity run contains only three tasks from one instance. It observed no positive `delta_QR`; therefore it does not show a C+Q route-distance improvement over C+R. Quantum-source tie-break wins are not described as route improvements. These smoke results validate the fair-comparison pipeline only and are not the formal contribution result.
