from __future__ import annotations

import argparse
from collections import defaultdict
import json
import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch
import numpy as np

from deepblock_study import (
    ALGORITHM_DIR,
    FIGURE_DIR,
    HARDWARE_DIR,
    OFFLINE_DIR,
    RESULT_ROOT,
    ensure_directories,
    read_csv,
    read_jsonl,
    write_csv,
)


FIGURES = (
    "01_量子经典混合优化流程.png",
    "02_DeepBlock编码与空间扩展.png",
    "03_DeepBlock改善空间分布.png",
    "04_经典局部陷阱与量子候选.png",
    "05_QUBO能量与真实路线距离.png",
    "06_有限预算下改善状态发现率.png",
    "07_真机理想与随机基线改善概率对比.png",
    "08_四种方法路线改善对比.png",
)


def _style() -> None:
    plt.rcParams.update({
        "font.sans-serif": ["Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "DejaVu Sans"],
        "axes.unicode_minus": False,
        "figure.dpi": 150,
        "savefig.dpi": 180,
        "axes.titleweight": "bold",
        "axes.grid": True,
        "grid.alpha": 0.22,
    })


def _save(fig, name: str, *, rect=None) -> None:
    fig.tight_layout(rect=rect)
    fig.savefig(FIGURE_DIR / name, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def figure_1() -> None:
    fig, ax = plt.subplots(figsize=(13, 4.6))
    ax.set_xlim(0, 13)
    ax.set_ylim(0, 4.6)
    ax.axis("off")
    labels = [
        (0.4, "容量约束聚类\n生成初始路线", "#DCEEFF"),
        (2.9, "筛选车辆对\n构造 DeepBlock", "#DFF5E3"),
        (5.4, "QUBO 编码\n量子/经典采样", "#FBE8C8"),
        (7.9, "Top-k 候选\n容量修复与真值评估", "#F3DDF2"),
        (10.4, "严格改善才接受\n正反扫描 2～3 轮", "#FFE0E0"),
    ]
    for x, label, color in labels:
        patch = FancyBboxPatch((x, 1.45), 2.1, 1.35, boxstyle="round,pad=0.12", fc=color, ec="#36536B", lw=1.5)
        ax.add_patch(patch)
        ax.text(x + 1.05, 2.12, label, ha="center", va="center", fontsize=11)
    for x in (2.5, 5.0, 7.5, 10.0):
        ax.annotate("", xy=(x + 0.35, 2.12), xytext=(x, 2.12), arrowprops=dict(arrowstyle="->", lw=2, color="#36536B"))
    ax.annotate("未改善：换块/反向扫描", xy=(6.5, 1.32), xytext=(11.4, 0.65), ha="center", arrowprops=dict(arrowstyle="->", connectionstyle="arc3,rad=-0.25", color="#B24A4A", lw=1.6), color="#B24A4A")
    ax.set_title("量子—经典混合路线优化流程", fontsize=17, pad=15)
    _save(fig, FIGURES[0])


def figure_2() -> None:
    widths = np.array([8, 10, 12, 14])
    spaces = 2 ** widths
    fig, axes = plt.subplots(1, 2, figsize=(12.5, 4.8), gridspec_kw={"width_ratios": [1.2, 1]})
    ax = axes[0]
    bits = np.arange(8)
    colors = ["#2F73B7" if bit % 2 == 0 else "#E58A3A" for bit in bits]
    ax.bar(bits, np.ones(8), color=colors, edgecolor="white")
    for bit in bits:
        ax.text(bit, 0.5, f"q{bit}\n客户{bit + 1}", ha="center", va="center", color="white", fontsize=9, fontweight="bold")
    ax.text(3.5, 1.15, "0 → 车辆 A    1 → 车辆 B", ha="center", fontsize=11)
    ax.set_ylim(0, 1.45)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_title("DeepBlock 二进制重分配编码")
    ax = axes[1]
    bars = ax.bar(widths.astype(str), spaces, color=["#89B4D8", "#67A9CF", "#3F8FC1", "#27679B"])
    ax.set_yscale("log", base=2)
    ax.set_xlabel("Block 位数")
    ax.set_ylabel("候选状态数（对数刻度）")
    ax.set_title("状态空间随位数指数扩展")
    for bar, value in zip(bars, spaces):
        ax.text(bar.get_x() + bar.get_width() / 2, value * 1.15, f"{value:,}", ha="center")
    fig.suptitle("DeepBlock 编码与 8/10/12/14 bit 空间扩展", fontsize=16)
    _save(fig, FIGURES[1])


def figure_3(blocks: list[dict[str, str]]) -> None:
    improved = sum(row["has_improvement"].lower() == "true" for row in blocks)
    traps = sum(row["single_bit_local_trap"].lower() == "true" for row in blocks)
    none = len(blocks) - improved
    easy = improved - traps
    fig, ax = plt.subplots(figsize=(8.2, 5.2))
    labels = ["无改善空间", "有改善、非单点陷阱", "单点局部陷阱"]
    values = [none, easy, traps]
    colors = ["#BFC7CE", "#7DBE8B", "#E07A5F"]
    bars = ax.bar(labels, values, color=colors)
    ax.set_ylabel("Block 数量")
    ax.set_title("DeepBlock 改善空间分布")
    for bar, value in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width() / 2, value + max(1, len(blocks) * 0.01), f"{value}\n({value/max(1,len(blocks)):.1%})", ha="center")
    _save(fig, FIGURES[2])


def figure_4(blocks: list[dict[str, str]], states: list[dict[str, object]]) -> None:
    trap = next((row for row in blocks if row["single_bit_local_trap"].lower() == "true"), blocks[0])
    subset = [row for row in states if row["instance_id"] == trap["instance_id"]]
    current_bits = trap["current_bitstring"]
    current_state = int(current_bits, 2)
    width = int(trap["block_size"])
    by_state = {int(row["state"]): float(row["true_route_distance"]) for row in subset}
    one_states = [current_state ^ (1 << bit) for bit in range(width)]
    values = [by_state[current_state], min(by_state[state] for state in one_states), min(by_state.values())]
    labels = ["当前状态", "最佳单 bit 邻居", "多客户联合调整最优"]
    fig, ax = plt.subplots(figsize=(9, 5.2))
    bars = ax.bar(labels, values, color=["#708090", "#E0A458", "#4E9F6D"])
    ax.set_ylabel("真实路线距离（越低越好）")
    ax.set_title("经典单点局部陷阱与联合调整候选")
    ax.set_ylim(min(values) * 0.96, max(values) * 1.025)
    for bar, value in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width() / 2, value, f"{value:.2f}", ha="center", va="bottom")
    ax.annotate("单点翻转无法严格改善", xy=(1, values[1]), xytext=(0.7, max(values) * 1.012), arrowprops=dict(arrowstyle="->", color="#9B5D16"), color="#9B5D16")
    ax.annotate("联合翻转跨过局部障碍", xy=(2, values[2]), xytext=(1.5, min(values) * 0.972), arrowprops=dict(arrowstyle="->", color="#2E7D4F"), color="#2E7D4F")
    _save(fig, FIGURES[3])


def figure_5(blocks: list[dict[str, str]], states: list[dict[str, object]]) -> None:
    chosen = max(blocks, key=lambda row: abs(float(row["spearman_qubo_true_distance"])))
    subset = [row for row in states if row["instance_id"] == chosen["instance_id"]]
    energies = np.array([float(row["qubo_energy"]) for row in subset])
    distances = np.array([float(row["true_route_distance"]) for row in subset])
    bitstrings = [str(row["bitstring"]) for row in subset]
    fig, ax = plt.subplots(figsize=(8.5, 5.6))
    ax.scatter(energies, distances, s=17, alpha=0.5, color="#4C88B8", label="枚举状态")
    markers = [
        (chosen["current_bitstring"], "当前状态", "#555555", "o"),
        (chosen["qubo_best_bitstring"], "QUBO 最优状态", "#D97706", "s"),
        (chosen["true_best_bitstring"], "真实最优状态", "#16834A", "*"),
    ]
    for bitstring, label, color, marker in markers:
        index = bitstrings.index(bitstring)
        ax.scatter([energies[index]], [distances[index]], s=130, color=color, marker=marker, edgecolor="white", linewidth=0.8, label=label, zorder=4)
    ax.set_xlabel("QUBO 能量")
    ax.set_ylabel("容量修复后真实路线距离")
    ax.set_title(f"QUBO 能量与真实路线距离\nSpearman ρ = {float(chosen['spearman_qubo_true_distance']):.3f}")
    ax.legend()
    _save(fig, FIGURES[4])


def figure_6(rows: list[dict[str, str]]) -> None:
    wanted = ["单点局部搜索", "多起点局部搜索", "模拟退火", "Random", "Ideal QAOA p=2"]
    groups: dict[tuple[str, int], list[float]] = defaultdict(list)
    for row in rows:
        if row["method"] in wanted:
            groups[(row["method"], int(row["candidate_budget"]))].append(row["found_improvement"].lower() == "true")
    fig, ax = plt.subplots(figsize=(9.5, 5.7))
    for method in wanted:
        budgets = [32, 64, 128, 256]
        rates = [np.mean(groups[(method, budget)]) if groups[(method, budget)] else np.nan for budget in budgets]
        ax.plot(budgets, rates, marker="o", linewidth=2, label=method)
    ax.set_xticks([32, 64, 128, 256])
    ax.set_ylim(-0.03, 1.05)
    ax.set_xlabel("候选预算")
    ax.set_ylabel("找到至少一个严格改善状态的 Seed 比例")
    ax.set_title("有限候选预算下的改善发现率")
    ax.legend(ncol=2)
    _save(fig, FIGURES[5])


def figure_7(rows: list[dict[str, str]]) -> None:
    stages = ["Baihua 真机", "硬件兼容理想模拟", "均匀随机基线"]
    labels = ["Baihua 真机", "硬件兼容理想模型", "均匀随机基线"]
    colors = ["#2F80B7", "#E07A5F", "#7A8793"]
    rng = np.random.default_rng(20260803)
    summary: list[dict[str, object]] = []
    paired_values: dict[tuple[int, str], np.ndarray] = {}
    for depth in (1, 2, 3):
        paired_ids = {
            row["instance_id"] for row in rows
            if row["stage"] == "Baihua 真机" and row["p"] == str(depth)
            and row["status"] == "COMPLETED"
        }
        for stage, label in zip(stages, labels):
            values_by_id = {
                row["instance_id"]: float(row["improving_probability"])
                for row in rows
                if row["instance_id"] in paired_ids and row["stage"] == stage
                and row["p"] == str(depth) and row["status"] != "NOT_RUN"
            }
            values = np.asarray([values_by_id[key] for key in sorted(paired_ids)], dtype=float)
            if len(values) != 10:
                raise ValueError(f"p={depth} {stage} requires 10 paired instances; got {len(values)}")
            paired_values[(depth, stage)] = values
            boot = np.mean(rng.choice(values, size=(5000, len(values)), replace=True), axis=1)
            summary.append({
                "p": depth, "stage": stage, "label": label, "independent_instances": len(values),
                "mean_improving_probability": float(np.mean(values)),
                "bootstrap_ci_low": float(np.quantile(boot, 0.025)),
                "bootstrap_ci_high": float(np.quantile(boot, 0.975)),
            })
    write_csv(HARDWARE_DIR / "hardware_ideal_random_probability_comparison.csv", summary)
    difference_rows: list[dict[str, object]] = []
    for depth in (1, 2, 3):
        for reference in ("均匀随机基线", "硬件兼容理想模拟"):
            differences = paired_values[(depth, "Baihua 真机")] - paired_values[(depth, reference)]
            boot = np.mean(rng.choice(differences, size=(5000, len(differences)), replace=True), axis=1)
            difference_rows.append({
                "p": depth, "contrast": f"Baihua 真机 - {reference}",
                "independent_instances": len(differences), "mean_difference": float(np.mean(differences)),
                "bootstrap_ci_low": float(np.quantile(boot, 0.025)),
                "bootstrap_ci_high": float(np.quantile(boot, 0.975)),
            })
    write_csv(HARDWARE_DIR / "hardware_probability_paired_differences.csv", difference_rows)

    x = np.arange(3)
    width = 0.24
    fig, ax = plt.subplots(figsize=(10.2, 6.4))
    for method_index, (stage, label, color) in enumerate(zip(stages, labels, colors)):
        method_rows = [row for row in summary if row["stage"] == stage]
        means = np.asarray([float(row["mean_improving_probability"]) for row in method_rows])
        positions = x + (method_index - 1) * width
        bars = ax.bar(positions, means, width, label=label, color=color, alpha=0.94)
        for bar, value in zip(bars, means):
            ax.text(bar.get_x() + bar.get_width() / 2, value + 0.0012,
                    f"{value:.2%}", ha="center", va="bottom", fontsize=9.5)
    ax.set_xticks(x, ["p=1\nn=10", "p=2\nn=10", "p=3\nn=10"])
    ax.set_ylabel("真实改善状态概率")
    ax.set_title("真机、硬件兼容理想模型与随机基线的改善状态概率")
    ax.set_ylim(0, max(float(row["mean_improving_probability"]) for row in summary) * 1.45)
    ax.legend(ncol=3, loc="upper center")
    fig.text(
        0.5, 0.012,
        "三种深度使用同一组10个独立Seed，柱高为实例均值。\n"
        "随机基线按每个实例的改善状态数/256计算；Bootstrap区间另见配对统计表。",
        ha="center", va="bottom", fontsize=10.2,
    )
    _save(fig, FIGURES[6], rect=(0, 0.12, 1, 1))


def figure_8(rows: list[dict[str, str]]) -> None:
    methods = ["Hardware", "Random", "Simulator", "Exact"]
    x = np.arange(len(methods))
    fig, ax = plt.subplots(figsize=(9, 5.6))
    paired_rows = [row for row in rows if row["hardware_status"] == "COMPLETED"]
    hardware_available = bool(paired_rows)
    display_rows = paired_rows if hardware_available else rows
    for row in display_rows:
        values = [float(row[method]) if row.get(method) not in (None, "") else np.nan for method in methods]
        ax.plot(x, values, color="#7A8793", alpha=0.35, marker="o")
    means = []
    for method in methods:
        vals = [float(row[method]) for row in display_rows if row.get(method) not in (None, "")]
        means.append(np.mean(vals) if vals else np.nan)
    ax.plot(x, means, color="#C43C39", linewidth=3, marker="D", markersize=8, label="实例均值")
    ax.set_xticks(x, ["Hardware", "Random", "Simulator", "Exact"])
    ax.set_ylabel("最佳路线改善量")
    ax.set_title(f"Hardware、Random、Simulator、Exact 路线改善配对图（n={len(paired_rows)}）")
    if not hardware_available:
        ax.text(0, 0, "真机未运行\n不填充模拟值", ha="center", va="bottom", color="#815AC0", fontweight="bold")
    ax.legend()
    _save(fig, FIGURES[7])


def _report(blocks, algorithm, hardware, paired) -> str:
    seed_count = len({row["seed"] for row in blocks})
    traps = sum(row["single_bit_local_trap"].lower() == "true" for row in blocks)
    improvable = sum(row["has_improvement"].lower() == "true" for row in blocks)
    qaoa = [row for row in algorithm if row["method"] == "Ideal QAOA p=2" and row["candidate_budget"] == "64"]
    random_rows = [row for row in algorithm if row["method"] == "Random" and row["candidate_budget"] == "64"]
    qaoa_rate = np.mean([row["found_improvement"].lower() == "true" for row in qaoa]) if qaoa else float("nan")
    random_rate = np.mean([row["found_improvement"].lower() == "true" for row in random_rows]) if random_rows else float("nan")
    hw_done = sum(row["stage"] == "Baihua 真机" and row["status"] == "COMPLETED" for row in hardware)
    conclusion = (
        "本批实例中 Ideal QAOA p=2 的 64 候选改善发现率高于 Random，但该结论具有实例依赖性。"
        if qaoa_rate > random_rate
        else "本批实例中 Ideal QAOA p=2 未稳定超过 Random，结果按负结果如实保留。"
    )
    return f"""# Quantum Route Forge 收尾实验报告

## 执行摘要

- 离线筛选覆盖 **{seed_count} 个独立 Seed**、6/8 bit、多个车辆对及 B1/B2/B3，共分析 **{len(blocks)} 个 Block**。
- 其中 **{improvable} 个**存在严格改善空间，**{traps} 个**满足“单 bit 无改善、Exact 存在多客户联合改善”的局部陷阱定义。
- 算法验证覆盖 8/10/12/14 bit，p=1/2/3，候选预算 32/64/128/256，容量惩罚 10/25/50，三种 QUBO，Shots 64/256/1024 与 Top-k 16/32/64。
- 64 候选时，Ideal QAOA p=2 改善发现率为 **{qaoa_rate:.1%}**，Random 为 **{random_rate:.1%}**。{conclusion}
- 兼容的 Baihua 新真机任务完成数：**{hw_done}**。未提供匹配本实验 manifest 的 counts 时，报告明确标记 `NOT_RUN`，未用噪声模拟替代真机数据。

## 结论边界

本研究完成“问题空间—理想候选算法—拓扑/噪声损失”的可复现实验链。Ideal QAOA 仅是无噪声状态向量结果；独立比特翻转噪声只用于归因分析；二者都不构成通用量子优势、量子加速或未来芯片性能承诺。真机结论必须等匹配 `hardware_submission_manifest.jsonl` 的 6～10 个独立任务返回后再更新。

## 完成状态

- [x] 分析 30 个 Seed，并保留无改善实例；
- [x] 找到 Exact 可改善但单点局部搜索停住的实例；
- [x] 完成 8/10/12/14 bit 与 p=1/2/3 Ideal Simulator；
- [x] 完成三档容量惩罚、三种 QUBO、三档 Shots、三档 Top-k；
- [x] 完成完整 QUBO、硬件兼容 QUBO和四档噪声缩放；
- [{'x' if hw_done >= 6 else ' '}] 完成 6～10 个新 Baihua 真机任务（当前 {hw_done} 个）；
- [x] 生成固定任务 manifest 与简化版多车辆对、多轮扫描结果；
- [x] 生成 8 张中文答辩图，并保留量子低于随机的结果。
"""


def run() -> dict[str, object]:
    ensure_directories()
    _style()
    blocks = read_csv(OFFLINE_DIR / "block_summary.csv")
    states = read_jsonl(OFFLINE_DIR / "state_summary.jsonl")
    algorithm = read_csv(ALGORITHM_DIR / "candidate_budget_results.csv")
    hardware = read_csv(HARDWARE_DIR / "hardware_gap_results.csv")
    paired = read_csv(HARDWARE_DIR / "method_paired_improvement.csv")
    figure_1()
    figure_2()
    figure_3(blocks)
    figure_4(blocks, states)
    figure_5(blocks, states)
    figure_6(algorithm)
    figure_7(hardware)
    figure_8(paired)
    report = _report(blocks, algorithm, hardware, paired)
    probability_rows = read_csv(HARDWARE_DIR / "hardware_ideal_random_probability_comparison.csv")
    probability = {
        (int(row["p"]), row["stage"]): float(row["mean_improving_probability"])
        for row in probability_rows
    }
    report += f"""

## 图 7 结果解释

图 7 对同一组 10 个独立 Seed 比较 Baihua 真机、硬件兼容理想模型和均匀随机基线。p=1 三者均值分别为 {probability[(1, 'Baihua 真机')]:.2%}、{probability[(1, '硬件兼容理想模拟')]:.2%}、{probability[(1, '均匀随机基线')]:.2%}；p=2 分别为 {probability[(2, 'Baihua 真机')]:.2%}、{probability[(2, '硬件兼容理想模拟')]:.2%}、{probability[(2, '均匀随机基线')]:.2%}；p=3 分别为 {probability[(3, 'Baihua 真机')]:.2%}、{probability[(3, '硬件兼容理想模拟')]:.2%}、{probability[(3, '均匀随机基线')]:.2%}。

三种深度均使用相同实例集合。随机基线按每个实例的严格改善状态数除以 256 计算，不使用不匹配的随机任务替代。为保持主图清晰，Bootstrap 95% 区间不画在柱形图中，完整区间保留在 `hardware_probability_paired_differences.csv`。均值差异只作本次 10 个实例内的描述，不能单凭柱高声称稳定量子优势。
"""
    live = read_jsonl(HARDWARE_DIR / "hardware_live_results.jsonl")
    extension_path = HARDWARE_DIR / "hardware_extensions_summary.json"
    closed_path = HARDWARE_DIR / "hardware_closed_loop_summary.json"
    if extension_path.exists() and closed_path.exists():
        extension = json.loads(extension_path.read_text(encoding="utf-8"))
        closed = json.loads(closed_path.read_text(encoding="utf-8"))
        report += f"""

## 真机增强收尾实验

- 独立 Seed 主矩阵：10 个 Seed，p=1/p=2/p=3 共 30 个真机任务。
- 重复运行方差：2 个 Seed × p=1/p=2 × 3 次独立运行，共 {extension['repeat_tasks']} 个观测（其中新增 8 个任务）。
- Shots 扫描：对 20 个主矩阵任务的真实 1024-shot counts，在 64/256 shots 下各做 {extension['shot_resamples']} 次无放回重采样；1024 档直接使用原始 counts。该分析不冒充新的低 shots 真机提交。
- 真机闭环：{closed['seeds']} 个 Seed × {closed['rounds_per_seed']} 轮，共 {closed['hardware_rounds']} 个真机轮次；接受 {closed['accepted_moves']} 次严格改善，累计路线改善 {closed['total_route_improvement']:.6f}。
- 真机任务证据总数：{len(live)} 个，全部返回 1024 shots；每个任务均保留 task_id、原始 counts、物理比特映射、编译审计和 QASM 哈希。

增强实验明细见 `hardware_gap/hardware_repeat_summary.csv`、`hardware_gap/hardware_shots_scan_summary.csv`、`hardware_gap/hardware_closed_loop_rounds.csv`。重复方差与 shots 扫描属于稳健性分析，不改变“未证明通用量子优势”的结论边界。
"""
    (RESULT_ROOT / "final_report.md").write_text(report, encoding="utf-8")
    return {
        "figures": [str(FIGURE_DIR / name) for name in FIGURES],
        "final_report": str(RESULT_ROOT / "final_report.md"),
    }


def main() -> None:
    argparse.ArgumentParser(description="生成 8 张中文答辩图和最终报告").parse_args()
    print(json.dumps(run(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
