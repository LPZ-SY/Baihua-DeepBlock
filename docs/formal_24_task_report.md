# Formal 24-Task Hardware Report

Date: 2026-08-02

Status: complete and strictly validated.

## Protocol and integrity

- Design: 4 fixed instances x 3 fixed backends x 2 repeats = 24 hardware tasks.
- Execution code: `9082b74ee2d22ffdd1103f62e3af9ceca18af740` / `qrf-preformal-execution-v2`.
- Protocol: `formal-matrix-v2` / `qrf-formal-protocol-v2`.
- Config SHA-256: `6150452c7d9072344d3addf3979a5e6227ca858991e9a16cab787be2f13ce01b`.
- Threshold file SHA-256: `0f43c81d0d6d4d3f9a07dba6b1a16f6201967cd2e39563069662310cdc630afb`.
- Shots: 1024 per task; 24,576 received in total.
- Status: 24 `COMPLETED`, 0 `FAILED`, 0 `NOT_EVALUABLE`.
- Requested backend equaled actual backend for all 24 tasks.
- Strict result-store validation: complete, valid, 0 task errors, 0 duplicate task IDs.
- All task evidence retains counts, redacted raw response, QASM, customer order, frozen hashes, dependencies, timestamps, compile options, and task-ID-addressable artifacts.

## Task-level results

`QHR` is measured quantum quality hit rate; `Random` is the frozen uniform-random reference; `Reach` is the same-budget feasible-classical threshold reach rate. `Strict` means strictly below that classical threshold.

| # | Task ID | Instance | Backend | Repeat | Status | Shots | QHR | Random | Reach | Strict |
|---:|---|---|---|---:|---|---:|---:|---:|---:|---:|
| 1 | 2608020032220735213 | seed2026_c4_v2_medium | Baihua | 1 | COMPLETED | 1024 | 0.258789 | 0.375000 | 0.053711 | 0 |
| 2 | 2608020035387167015 | seed2027_c4_v2_tight | Shenglian | 1 | COMPLETED | 1024 | 0.066406 | 0.125000 | 0.066406 | 0 |
| 3 | 2608020035573093702 | seed2026_c6_v2_medium | Dongling | 1 | COMPLETED | 1024 | 0.096680 | 0.125000 | 0.029297 | 0 |
| 4 | 2608020036161889350 | seed2027_c6_v2_tight | Baihua | 1 | COMPLETED | 1024 | 0.174805 | 0.281250 | 0.028320 | 0 |
| 5 | 2608020037098703942 | seed2026_c4_v2_medium | Dongling | 1 | COMPLETED | 1024 | 0.289062 | 0.375000 | 0.054688 | 0 |
| 6 | 2608020037262690867 | seed2027_c4_v2_tight | Baihua | 1 | COMPLETED | 1024 | 0.063477 | 0.125000 | 0.063477 | 0 |
| 7 | 2608020037456281068 | seed2026_c6_v2_medium | Shenglian | 1 | COMPLETED | 1024 | 0.110352 | 0.125000 | 0.058594 | 0 |
| 8 | 2608020038033582912 | seed2027_c6_v2_tight | Shenglian | 1 | COMPLETED | 1024 | 0.179688 | 0.281250 | 0.035156 | 0 |
| 9 | 2608020038368682694 | seed2026_c4_v2_medium | Shenglian | 1 | COMPLETED | 1024 | 0.256836 | 0.375000 | 0.062500 | 0 |
| 10 | 2608020038518531868 | seed2027_c4_v2_tight | Dongling | 1 | COMPLETED | 1024 | 0.052734 | 0.125000 | 0.052734 | 0 |
| 11 | 2608020039128886917 | seed2026_c6_v2_medium | Baihua | 1 | COMPLETED | 1024 | 0.083008 | 0.125000 | 0.032227 | 0 |
| 12 | 2608020039322530245 | seed2027_c6_v2_tight | Dongling | 1 | COMPLETED | 1024 | 0.244141 | 0.281250 | 0.040039 | 0 |
| 13 | 2608020040094471234 | seed2026_c4_v2_medium | Shenglian | 2 | COMPLETED | 1024 | 0.263672 | 0.375000 | 0.059570 | 0 |
| 14 | 2608020040246279597 | seed2027_c4_v2_tight | Dongling | 2 | COMPLETED | 1024 | 0.069336 | 0.125000 | 0.069336 | 0 |
| 15 | 2608020040447289172 | seed2026_c6_v2_medium | Baihua | 2 | COMPLETED | 1024 | 0.107422 | 0.125000 | 0.046875 | 0 |
| 16 | 2608020041040293103 | seed2027_c6_v2_tight | Dongling | 2 | COMPLETED | 1024 | 0.259766 | 0.281250 | 0.034180 | 0 |
| 17 | 2608020041346878482 | seed2026_c4_v2_medium | Baihua | 2 | COMPLETED | 1024 | 0.273438 | 0.375000 | 0.075195 | 0 |
| 18 | 2608020041516483770 | seed2027_c4_v2_tight | Shenglian | 2 | COMPLETED | 1024 | 0.077148 | 0.125000 | 0.077148 | 0 |
| 19 | 2608020042116490390 | seed2026_c6_v2_medium | Dongling | 2 | COMPLETED | 1024 | 0.125000 | 0.125000 | 0.037109 | 0 |
| 20 | 2608020042297182893 | seed2027_c6_v2_tight | Baihua | 2 | COMPLETED | 1024 | 0.162109 | 0.281250 | 0.029297 | 0 |
| 21 | 2608020043089686015 | seed2026_c4_v2_medium | Dongling | 2 | COMPLETED | 1024 | 0.321289 | 0.375000 | 0.070312 | 0 |
| 22 | 2608020043245682799 | seed2027_c4_v2_tight | Baihua | 2 | COMPLETED | 1024 | 0.056641 | 0.125000 | 0.056641 | 0 |
| 23 | 2608020043451218721 | seed2026_c6_v2_medium | Shenglian | 2 | COMPLETED | 1024 | 0.083984 | 0.125000 | 0.031250 | 0 |
| 24 | 2608020044026086405 | seed2027_c6_v2_tight | Shenglian | 2 | COMPLETED | 1024 | 0.188477 | 0.281250 | 0.041992 | 0 |

## Task-level statistical summary

- Mean QHR: 0.161011; median 0.143555; SD 0.088802; 95% task-bootstrap CI [0.127035, 0.197795].
- Mean random-reference hit rate: 0.226562; 95% CI [0.186198, 0.270833].
- Mean `Quantum - Random`: -0.065552; median -0.060059; 95% CI [-0.079427, -0.051514].
- Mean feasible-classical threshold reach rate: 0.050252; 95% CI [0.044067, 0.056600].
- Strict improvement rate: 0 for every task.
- Measured QHR exceeded the random reference in 0 of 24 tasks.

Backend-specific mean QHR values were Baihua 0.147461, Dongling 0.182251, and Shenglian 0.153320. These descriptive differences are not treated as a backend ranking because the experiment was not designed or powered for that claim.

## Conclusion

Under the frozen instances, circuit, parameters, compilation settings, and three tested backends, the measured quantum distribution reached the same-budget feasible-classical threshold in every task at a low positive rate, but never strictly improved on that threshold. Its quality hit rate was below the frozen uniform-random reference in every task. The formal matrix therefore does not show a stable positive quantum candidate-quality effect, a route-distance contribution, or quantum advantage. This conclusion is limited to the tested experimental scope and does not establish that all quantum routing approaches are ineffective.
