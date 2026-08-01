# Fair Hybrid Contribution Report

Date: 2026-08-02

Status: complete for all 24 formal hardware tasks.

## Fair comparison

C, C+R, and C+Q use equal total candidate budgets. C+R and C+Q share the exact same classical subset and differ only in the added uniform-random versus measured-quantum half. Measured bitstrings use the frozen `selected_customer_ids_in_qubit_order`. Every candidate passes through the same BQM evaluation, capacity repair, routing, 2-opt, and final selection rule. No replay, manual, simulator, or fallback evidence was admitted.

## Results

- Hardware task units: 24.
- Evaluable C+Q comparisons: 24; NOT_EVALUABLE: 0.
- `D_C+R - D_C+Q` (`delta_QR`): 0 in all 24 tasks.
- `D_C - D_C+Q` (`delta_QC`): 0 in all 24 tasks.
- Mean and median `delta_QR`: 0; 95% task-bootstrap CI [0, 0].
- Mean and median `delta_QC`: 0; 95% task-bootstrap CI [0, 0].
- A quantum candidate won the C+Q internal energy/source tie-break in 11 of 24 tasks (45.83%), but never changed final route distance.

## Interpretation

The formal experiment observed no task-level C+Q route-distance improvement over the equal-budget C+R control or the pure-classical control. Energy-level ranking or a quantum-source tie-break is not reported as a route improvement. Under this frozen workflow, measured quantum candidates did not provide incremental routing value beyond the matched random candidate supplement.

Detailed task rows are in `results/experiments/qrf_formal_hardware_matrix_v2/hybrid_summary.csv`; overall, backend, and instance strata are in `hybrid/hybrid_aggregate_summary.json`.
