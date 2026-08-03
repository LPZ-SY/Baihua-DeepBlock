# Quantum Route Forge：Baihua DeepBlock 量子—经典路径优化平台

Quantum Route Forge 是一个面向车辆分配与路径优化的量子—经典混合研究与演示平台。本仓库重点实现 **Baihua DeepBlock**：利用 Quafu 量子真机产生候选分配，再通过统一的经典评估、容量修复和路径优化流程检验这些候选是否能够为混合算法带来增量价值。

> 本项目只提出与现有实验数据相符的有限结论：量子真机测量结果可以作为车辆分配候选，与均匀随机候选及同预算经典候选进行公平比较，并可纳入同一条混合优化流水线。项目**不宣称**普适量子优势、速度优势，也不宣称已经用纯量子方法解决完整车辆路径问题。

完整的项目背景、技术方案、实验设置、真机结果、网页操作说明与结论边界见：

[`docs/Quantum_Route_Forge_项目完整文档.md`](docs/Quantum_Route_Forge_项目完整文档.md)

## 项目功能

项目提供两条相互兼容的工作路径：

1. **比赛演示路径**：围绕 Baihua DeepBlock 展示路线地图、参数控制、B1/B2/B3 重叠分块、真机采样及 Hardware/Random/Simulator/Exact 公平对照。
2. **研究实验路径**：提供单次实验、候选质量分析、可恢复批处理、证据回放、公平混合贡献比较、结果校验和论文图表生成。

核心计算流程分为两层：

1. 固定参数的 QAOA 风格邻近线路生成双车辆划分种子。线路使用固定参数 `gamma=1.1`、`beta=0.8`，并不是对完整分配 BQM 的直接 QAOA 编码。
2. 统一 BQM 评估器对种子评分；单次运行流程把量子结果作为软偏好，再依次执行经典模拟退火、容量修复、最近邻路径构造与 2-opt 优化。

因此，“单次运行”页面中的“经典完整分配能量”表示最终经典 BQM 搜索结果，不应被描述为未经后处理的量子候选能量。

## 快速启动

项目已在 Python 3.12 环境中验证。

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pytest -q
```

离线测试、证据回放、候选分析、预演和历史记录查看均不需要令牌，也不需要访问量子硬件。

### 启动比赛前端

```powershell
.\.venv\Scripts\python.exe app.py --port 8050
```

浏览器访问：`http://127.0.0.1:8050`

比赛前端包含路线优化、B1/B2/B3 分块过程、四类公平对照和可重新载入的本地运行历史。Baihua DeepBlock 算法位于 `src/quantum_route_forge/deepblock/`。

### 启动研究前端

旧版研究前端完整保留，并使用独立端口：

```powershell
.\.venv\Scripts\python.exe app_research.py --port 8051
```

### 真机提交安全边界

真机模式默认只执行预演。只有在页面中明确确认真实提交后，系统才会向 Baihua 后端提交任务。真机失败会返回 `FAILED` 或 `NOT_EVALUABLE`，不会回退到模拟器后再伪装成硬件结果。

比赛运行历史保存在 `results/competition_history/`。认证令牌只在内存中使用，不会写入证据、清单或日志。

## 网页功能

研究前端提供四个主要页面：

- **单次运行**：默认使用可行的 8 客户、2 车辆经典场景，展示请求后端、实际后端、任务 ID、数据来源、请求/返回 shots、容量和量子覆盖率。未完成、回放、手工或回退数据不进入正式统计。
- **候选质量**：保留新鲜真机数据与回放数据的来源区别，分别展示绝对质量、随机参考、经典阈值到达、严格改进、精确能量差和可行性。
- **批量实验**：预览固定后端实验矩阵，校验冻结阈值哈希；每次界面操作最多提交一个新真机任务，必须显式确认，并支持暂停与恢复。
- **实验历史**：按实例、后端、状态和来源展示任务级记录，同时显示结果存储完整性。

手工输入的比特串统一标记为 `manual_debug`，不会混入正式真机统计。

## 命令行运行

### 经典单次运行

经典模式不需要令牌：

```powershell
.\.venv\Scripts\python.exe run_cli.py `
  --mode classical --customers 8 --vehicles 2 --capacity 13 --seed 2026
```

### 通过 SQC 提交量子任务

```powershell
$env:QUAFU_API_TOKEN="<JWT>"
$env:QUAFU_BASE_URL="https://quafu-sqc.baqis.ac.cn/"
.\.venv\Scripts\python.exe run_cli.py `
  --mode quantum --customers 8 --vehicles 2 --capacity 13 --quafu-wait false
```

## 统一测量模型

所有后端适配器都会把结果转换为 `QuantumMeasurementResult`，统一记录：

- 数据来源：`hardware`、`simulator`、`replay`、`manual_debug` 或 `fallback`；
- 任务状态、任务 ID、平台、后端和端点；
- 请求 shots 与实际返回 shots；
- 清洗后的完整 counts 和最高频比特串；
- 客户顺序与 `bit_order`；
- 线路/载荷哈希、时间戳、证据路径和警告信息。

counts 解析支持嵌套载荷、JSON/Python 字面量字符串、计数字典和概率字典。非法键及错误比特长度会被拒绝。如果返回 shots 与请求值不一致，系统会保留警告，并始终使用 `shots_received` 计算比例。若适配器只能提供一个样本，系统会明确记录 `shots_received=1`，不会伪造概率分布。

正式汇总只接受已完成的 `hardware` 测量。回放数据仍可用于完整复算，但必须明确标记为 `replay`。

## 候选质量判据

所有阈值必须在读取真机结果之前冻结。模式版本 2 同时保存两个经典诊断量：

- `best_classical_energy_all`：同预算全部经典候选中的最低能量；
- `best_classical_energy_feasible`：同预算原始可行经典候选中的最低能量。

如果固定经典预算中没有可行候选，可行阈值判据返回 `NOT_EVALUABLE`，不会退化为使用不可行阈值。

对测量候选 `z`，使用以下定义：

```text
normalized_score(z) = (E(z) - E*) / (E_random_median - E*)
quality_gate_pass = raw_feasible and normalized_score <= 0.20
near_quality_gate_pass = raw_feasible and normalized_score <= 0.50
classical_reach_feasible_pass = raw_feasible and E(z) <= T_feasible + 1e-9
strict_improvement_feasible_pass = raw_feasible and E(z) < T_feasible - 1e-9
```

若归一化分母为零，归一化字段设为 `null`，绝对质量门不参与判断，但仍保留精确能量差。

报告必须按以下顺序解释：

1. 相对于均匀随机分布，进入低能可行区域的命中率；
2. 是否到达同预算冻结经典可行阈值；
3. 是否严格低于该经典阈值；
4. `C+Q` 相对于公平对照 `C+R` 的增量贡献。

“到达经典阈值”不能被改写为“量子优于经典”。

## 单次 QuarkStudio 真机运行与证据回放

真机运行要求：2 辆车、客户到量子比特的覆盖率为 100%，shots 为 1024 的正整数倍。

```powershell
$env:QPU_API_TOKEN="<QPU_TOKEN>"
.\.venv\Scripts\python.exe experiments\run_quarkstudio_candidate_quality.py `
  --seed 2026 --customers 4 --vehicles 2 `
  --capacity-pressure medium --shots 1024 `
  --outdir results\single_live
```

离线回放不会读取令牌：

```powershell
.\.venv\Scripts\python.exe experiments\run_quarkstudio_candidate_quality.py `
  --seed 2026 --customers 4 --vehicles 2 --shots 1024 `
  --reuse-evidence results\quarkstudio_candidate_quality_validated\task_evidence.json `
  --outdir results\single_replay
```

counts 缺失或任务失败时，系统仍会保存证据记录并返回 `NOT_EVALUABLE`，不会产生伪阳性的回退结果。

## 正式批量实验

正式模式版本 2 已于 2026-08-02 完成：预先声明的 24 个真机任务均返回 1024/1024 shots，请求后端与实际后端一致，严格校验器报告结果存储完整且无数据错误。

实验采用平衡设计：

```text
4 个实例 × 3 个固定后端 × 2 次重复 = 24 个任务
```

三个固定后端为 Baihua、Dongling 和 Shenglian。正式协议禁止 `backend=auto`，并验证冻结阈值文件、QASM 哈希和客户顺序哈希。

预览完整实验矩阵与 shot 预算，不提交硬件：

```powershell
.\.venv\Scripts\python.exe experiments\batch_candidate_quality.py `
  --config experiments\configs\formal_hardware_matrix_v2.json `
  --dry-run
```

经过显式确认后，每次最多提交一个真机任务：

```powershell
.\.venv\Scripts\python.exe experiments\batch_candidate_quality.py `
  --config experiments\configs\formal_hardware_matrix_v2.json `
  --confirm-live --max-hardware-tasks 1
```

从中断处恢复且不重复已完成的 `config_hash`：

```powershell
.\.venv\Scripts\python.exe experiments\batch_candidate_quality.py `
  --config experiments\configs\formal_hardware_matrix_v2.json `
  --confirm-live --resume --max-hardware-tasks 1
```

可使用 `--retry-failed` 只处理失败记录，或使用 `--reuse-evidence <path>` 离线复用相同的编排、评估和存储路径。任务会在完成后立即落盘，因此批处理被中断后仍可恢复。

历史配置 `qrf_hw_quality_v2.json` 因使用 `backend=auto` 且没有让每个实例在三个芯片上重复执行，只用于审计，不属于正式实验。

## 公平混合贡献实验

`experiments/hybrid_contribution.py` 比较四组方法：

- `C`：`N` 个经典候选；
- `C+R`：`N/2` 个经典候选加 `N/2` 个均匀随机候选；
- `C+Q`：`N/2` 个经典候选加 `N/2` 个真机测量候选；
- `Q-only`：仅作诊断，不作为主对照。

所有组使用相同总预算、评估器、容量修复、最近邻路径构造、2-opt 轮数和最终选择规则。`C+R` 与 `C+Q` 复用完全相同的经典候选子集，唯一差异是加入随机候选还是真机候选。

如果测量候选缺失或来源不是硬件，`C+Q` 返回 `NOT_EVALUABLE`，不会静默退化为纯经典候选池。

```powershell
.\.venv\Scripts\python.exe experiments\prepare_hybrid_input.py `
  --config experiments\configs\formal_hardware_matrix_v2.json `
  --experiment-dir results\experiments\qrf_formal_hardware_matrix_v2 `
  --output results\experiments\qrf_formal_hardware_matrix_v2\hybrid_input.json

.\.venv\Scripts\python.exe experiments\hybrid_contribution.py `
  --input results\experiments\qrf_formal_hardware_matrix_v2\hybrid_input.json `
  --outdir results\experiments\qrf_formal_hardware_matrix_v2\hybrid
```

结果包含 `D_C`、`D_C_plus_R`、`D_C_plus_Q`、`delta_QR`、`delta_QC`、最终候选来源/排名、修复变化和任务级 bootstrap 区间。`--deduplicate-quantum` 可用于唯一候选敏感性分析。

## 结果存储与校验

每个批量实验存放在：

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

同一实验与配置哈希下，`config.json`、冻结阈值和证据哈希保持不可变。保存证据前会递归清除认证信息。

校验完整正式矩阵：

```powershell
.\.venv\Scripts\python.exe experiments\validate_formal_result_store.py `
  --config experiments\configs\formal_hardware_matrix_v2.json `
  --experiment-dir results\experiments\qrf_formal_hardware_matrix_v2
```

## 生成论文图表

```powershell
.\.venv\Scripts\python.exe experiments\generate_paper_artifacts.py `
  --experiment-dir results\experiments\qrf_formal_hardware_matrix_v2
```

脚本生成任务级、实例级和后端级 CSV/JSON 汇总，以及能量 CDF、测量—随机配对图、经典阈值到达/严格改进图、`C+Q`—`C+R` 路径差异图和经验重采样图。统计推断以硬件任务为重复单位，不把单个 shots 当作独立实验。

当证据不完整时，系统会自动生成中性或 `NOT_EVALUABLE` 表述，不会输出超出证据的结论。

## 仓库结构

```text
app.py                                      四页面 Dash 实验平台
app_research.py                             保留的研究前端
run_cli.py                                  单次运行命令行入口
experiments/
  configs/qrf_hw_quality_v2.json            历史非平衡配置，仅供审计
  configs/formal_hardware_matrix_v2.json    冻结的 4×3×2 平衡协议
  run_quantum_candidate_quality.py          兼容 CSV 的候选质量入口
  run_quarkstudio_candidate_quality.py      单次真机/回放闭环
  batch_candidate_quality.py                可恢复、配额感知批处理
  validate_formal_result_store.py           任务/证据/来源严格校验
  prepare_hybrid_input.py                   公平候选池输入构建
  hybrid_contribution.py                    C、C+R、C+Q 公平比较
  generate_paper_artifacts.py               生成表格、图形与结论文本
src/quantum_route_forge/
  models.py                                 可序列化测量/候选/汇总模型
  quantum_measurements.py                   counts、shots、位序与证据哈希
  candidate_quality.py                      精确参考、双阈值和质量门
  result_store.py                           不可变配置与幂等实验产物
  quafu_bridge.py                           Quafu SQC/SDK 适配
  pipeline.py                               混合单次运行流水线
  deepblock/                                Baihua DeepBlock 核心算法
tests/                                      离线单元、集成和回放测试
docs/                                       协议、审计、报告和结论边界
results/experiments/<experiment_id>/        可复现实验存储
```

## 测试与当前证据

运行完整离线测试：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

测试覆盖双阈值、相等/严格比较、零归一化分母、嵌套及概率 counts、shots 不一致、位序、数据来源隔离、精确评估、结果存储幂等性、批处理恢复、公平预算、网页功能、容量约束和已保存证据回放。

已保存的 P10 冒烟测试证据包括：

- Baihua：任务 `2608012251527123036`；
- Dongling：任务 `2608012253199368389`；
- Shenglian：任务 `2608012254449770289`。

三个任务均返回 1024/1024 counts，且请求/实际后端、QASM、阈值、客户顺序和代码提交一致。这些任务只用于验证流水线。

独立的正式实验矩阵包含 24 个已完成真机任务，没有使用回放、手工输入或回退数据替代。正式矩阵中，测量候选平均质量命中率为 `0.161011`，冻结随机参考为 `0.226562`；所有任务均未观察到对可行经典阈值的严格改进，`C+Q` 相对于 `C+R` 也没有改变最终路线距离。

这些结果表明当前实验已经验证了可审计的真机闭环，但尚不足以支持量子优势结论。

## 网络故障排查

如果 Quafu 诊断出现 `ConnectionResetError(10054)` 或解析到保留测试地址 `198.18.x.x`，通常意味着本地代理或 TUN DNS 拦截。可调整 `quafu.baqis.ac.cn`、`quafu-sqc.baqis.ac.cn` 的代理规则/节点，或显式设置代理：

```powershell
$env:QUAFU_PROXY_URL="http://127.0.0.1:7897"
```

端点与 DNS 诊断只用于连接排查，不会混入正式候选质量结论。

## 许可证

许可证信息见 [LICENSE](LICENSE)。
