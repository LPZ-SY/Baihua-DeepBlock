## 分布诊断（复用历史 Quafu counts）

本节只做离线后处理：复用 33 个历史 8-bit Quafu/Baihua 任务的原始 counts，没有提交或重跑真机任务。Random 与 Ideal QAOA Simulator 对每个任务使用相同 Block、shots 和实验 Seed；Ideal 分布使用冻结 manifest 中的 QAOA 参数。

低能区域沿用现有门槛：按完整 QUBO 能量排序取最低 10%（8-bit 下为 26/256 个状态）；富集倍数相对均匀随机概率 0.101562 计算。路线改善沿用现有 Top-64 候选中的最佳严格改善。

以下为 23 个主矩阵独立任务的按任务均值；重复运行与闭环任务保留在明细和全历史任务汇总中，不在本表重复加权。

| sampler | low_energy_probability | enrichment_ratio | shannon_entropy | normalized_entropy | unique_states | coverage | effective_states | route_improvement |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Random | 0.108823 | 1.0715 | 7.8057 | 0.9757 | 251.91 | 0.9840 | 223.75 | 0.573889 |
| Ideal QAOA Simulator | 0.182872 | 1.8006 | 7.4376 | 0.9297 | 225.22 | 0.8798 | 183.47 | 0.586087 |
| Quafu Hardware | 0.127420 | 1.2546 | 7.4840 | 0.9355 | 231.43 | 0.9040 | 182.66 | 0.468758 |

### 熵下降是否对应低能集中

在主矩阵中，相对 Random，Quafu Hardware 有 23/23 个任务熵更低，有 14/23 个任务低能概率更高，其中 14/23 个任务同时满足两者；平均熵差（硬件减基线）为 -0.3216 bit，平均低能概率差为 +1.8597%。

相对 Ideal QAOA Simulator，上述数量分别为 17/23、11/23 和 11/23；平均熵差为 0.0464 bit，平均低能概率差为 -5.5452%。

熵与唯一状态数仅用于描述分布集中程度。只有当熵下降与预先定义低能区域概率上升同时出现时，才能说明集中方向与低能区域一致；即使如此，也不能仅凭熵或唯一状态数认定量子正向贡献，仍须结合低能富集、同任务基线和路线改善指标。

counts 缺失任务数：0。若后续历史文件缺少或损坏 counts，明细会将指标留空并标记原因，不会补造数据，也不会自动重跑真机。均值、中位数和样本标准差见 `hardware_gap/distribution_diagnostics_summary.csv`。
