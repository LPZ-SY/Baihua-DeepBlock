# Cross-Backend Smoke Report

All three P10 tasks completed with fresh hardware counts. Requested and actual backends matched, each counts distribution summed to 1024, and QASM/threshold/code hashes were identical across tasks.

| Backend | Task ID | QHR | Random QHR | Q-R | Classical reach | Strict improvement |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Baihua | 2608012251527123036 | 0.2568 | 0.3750 | -0.1182 | 0.0596 | 0.0000 |
| Dongling | 2608012253199368389 | 0.3271 | 0.3750 | -0.0479 | 0.1396 | 0.0000 |
| Shenglian | 2608012254449770289 | 0.2480 | 0.3750 | -0.1270 | 0.0615 | 0.0000 |

This smoke test validates the cross-backend evidence pipeline. It is not the formal 24-task result and does not support a quantum-advantage claim.
