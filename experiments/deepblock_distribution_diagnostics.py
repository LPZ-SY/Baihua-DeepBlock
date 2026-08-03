from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from typing import Mapping, Sequence

import numpy as np

from deepblock_study import (
    HARDWARE_DIR,
    OFFLINE_DIR,
    build_proxy,
    context_from_payload,
    enumerate_context,
    observed_distribution_metrics,
    read_jsonl,
    write_csv,
)
from quantum_route_forge.deepblock.qaoa_runner import QAOAParameters, ideal_probabilities


WIDTH = 8
STATE_COUNT = 1 << WIDTH
LOW_ENERGY_FRACTION = 0.10
LOW_ENERGY_STATE_COUNT = math.ceil(STATE_COUNT * LOW_ENERGY_FRACTION)
UNIFORM_LOW_ENERGY_PROBABILITY = LOW_ENERGY_STATE_COUNT / STATE_COUNT
TOP_K = 64
SAMPLERS = ("Random", "Ideal QAOA Simulator", "Quafu Hardware")
SUMMARY_METRICS = (
    "low_energy_probability",
    "enrichment_ratio",
    "shannon_entropy",
    "normalized_entropy",
    "unique_states",
    "coverage",
    "effective_states",
    "route_improvement",
)

DETAIL_CSV = HARDWARE_DIR / "distribution_diagnostics_detail.csv"
DETAIL_JSON = HARDWARE_DIR / "distribution_diagnostics_detail.json"
SUMMARY_CSV = HARDWARE_DIR / "distribution_diagnostics_summary.csv"
SUMMARY_JSON = HARDWARE_DIR / "distribution_diagnostics_summary.json"
PAIRED_CSV = HARDWARE_DIR / "distribution_diagnostics_paired.csv"
PAIRED_JSON = HARDWARE_DIR / "distribution_diagnostics_paired.json"
METADATA_JSON = HARDWARE_DIR / "distribution_diagnostics_metadata.json"
REPORT_SECTION = HARDWARE_DIR / "distribution_diagnostics_report_section.md"


def _counts_vector(counts: object, width: int = WIDTH) -> tuple[np.ndarray | None, str]:
    """Return validated counts without inventing or completing missing observations."""
    if not isinstance(counts, Mapping) or not counts:
        return None, "MISSING_COUNTS"
    values = np.zeros(1 << width, dtype=np.int64)
    for raw_bitstring, raw_count in counts.items():
        cleaned = str(raw_bitstring).replace(" ", "").strip()
        if not cleaned or set(cleaned) - {"0", "1"}:
            return None, f"INVALID_BITSTRING:{raw_bitstring}"
        canonical = cleaned[-width:].zfill(width)
        try:
            count = int(raw_count)
        except (TypeError, ValueError):
            return None, f"INVALID_COUNT:{raw_bitstring}"
        if count < 0 or isinstance(raw_count, float) and not raw_count.is_integer():
            return None, f"INVALID_COUNT:{raw_bitstring}"
        values[int(canonical, 2)] += count
    if int(values.sum()) <= 0:
        return None, "MISSING_COUNTS"
    return values, "COMPLETE"


def distribution_metrics(space, counts: Sequence[int]) -> dict[str, object]:
    """Compute empirical distribution diagnostics for one frozen 8-bit sample."""
    values = np.asarray(counts, dtype=float)
    if values.shape != (STATE_COUNT,) or np.any(values < 0) or values.sum() <= 0:
        raise ValueError("counts must be a non-empty, non-negative 256-state vector")
    probabilities = values / values.sum()
    existing = observed_distribution_metrics(space, probabilities, top_k=TOP_K)
    nonzero = probabilities[probabilities > 0]
    entropy = -float(np.sum(nonzero * np.log2(nonzero)))
    unique_states = int(np.count_nonzero(values))
    return {
        # Keep the existing low-energy, improvement-probability, discovery and
        # Top-64 route-improvement definitions unchanged.
        "low_energy_probability": float(existing["low_energy_probability"]),
        "enrichment_ratio": float(existing["low_energy_probability"])
        / UNIFORM_LOW_ENERGY_PROBABILITY,
        "improving_probability": float(existing["improving_probability"]),
        "found_improvement": bool(existing["found_improvement"]),
        "best_improvement": float(existing["best_improvement"]),
        "route_improvement": float(existing["best_improvement"]),
        "shannon_entropy": entropy,
        "normalized_entropy": entropy / WIDTH,
        "unique_states": unique_states,
        "coverage": unique_states / STATE_COUNT,
        "effective_states": float(2.0**entropy),
    }


def _sample_counts(probabilities: np.ndarray, shots: int, seed: int) -> np.ndarray:
    sampled = np.random.default_rng(seed).choice(
        len(probabilities), size=int(shots), replace=True, p=probabilities
    )
    return np.bincount(sampled, minlength=len(probabilities))


def _manifest_parameters(manifest: Mapping[str, object]) -> QAOAParameters:
    payload = manifest.get("qaoa_parameters")
    if not isinstance(payload, Mapping):
        raise ValueError("frozen manifest has no qaoa_parameters")
    return QAOAParameters(
        depth=int(payload["depth"]),
        gamma=tuple(float(value) for value in payload["gamma"]),  # type: ignore[arg-type]
        beta=tuple(float(value) for value in payload["beta"]),  # type: ignore[arg-type]
        optimizer=str(payload.get("optimizer", "frozen_manifest")),
        initial_value=float(payload.get("initial_value", 0.0)),
        final_value=float(payload.get("final_value", 0.0)),
        evaluations=int(payload.get("evaluations", 0)),
    )


def _build_context(
    instance_id: str,
    manifest: Mapping[str, object],
    selected_by_id: Mapping[str, Mapping[str, object]],
    selected_by_seed: Mapping[int, Mapping[str, object]],
):
    if instance_id in selected_by_id:
        return context_from_payload(selected_by_id[instance_id], width=WIDTH)
    seed = int(manifest["seed"])
    if seed not in selected_by_seed:
        raise KeyError(f"no offline payload for seed {seed}")
    payload = deepcopy(dict(selected_by_seed[seed]))
    pair = [int(value) for value in manifest["vehicle_pair"]]  # type: ignore[index]
    payload.update(
        {
            "seed": seed,
            "assignments": manifest["initial_assignments"],
            "block_size": WIDTH,
            "block_customer_ids": manifest["block_customer_ids"],
            "vehicle_pair": f"{pair[0]}-{pair[1]}",
            "block_id": "B3",
            "pair_rank": 1,
        }
    )
    context = context_from_payload(payload, width=WIDTH)
    context.instance_id = instance_id
    return context


def _task_kind(row: Mapping[str, object]) -> str:
    if str(row.get("instance_id", "")).startswith("closedloop_"):
        return "closed_loop"
    if int(row.get("replicate", 1)) > 1:
        return "repeat"
    return "primary"


def _missing_metrics() -> dict[str, None]:
    fields = (
        "low_energy_probability",
        "enrichment_ratio",
        "improving_probability",
        "found_improvement",
        "best_improvement",
        "route_improvement",
        "shannon_entropy",
        "normalized_entropy",
        "unique_states",
        "coverage",
        "effective_states",
    )
    return {field: None for field in fields}


def _base_detail(
    task: Mapping[str, object],
    sampler: str,
    shots: int,
    status: str,
    reason: str,
) -> dict[str, object]:
    return {
        "task_kind": _task_kind(task),
        "instance_id": str(task["instance_id"]),
        "seed": int(task["seed"]),
        "p": int(task["p"]),
        "replicate": int(task.get("replicate", 1)),
        "task_id": str(task.get("task_id", "")),
        "sampler": sampler,
        "block_size": WIDTH,
        "shots": int(shots),
        "comparison_seed": int(task["seed"]),
        "counts_status": status,
        "missing_reason": reason,
        "low_energy_state_count": LOW_ENERGY_STATE_COUNT,
        "low_energy_fraction_rule": LOW_ENERGY_FRACTION,
        "top_k": TOP_K,
    }


def _summary_rows(detail: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    scopes = {
        "primary_independent_tasks": lambda row: row["task_kind"] == "primary",
        "all_historical_tasks": lambda row: True,
    }
    rows: list[dict[str, object]] = []
    for scope, include in scopes.items():
        for sampler in SAMPLERS:
            group = [row for row in detail if include(row) and row["sampler"] == sampler]
            for metric in SUMMARY_METRICS:
                values = np.asarray(
                    [float(row[metric]) for row in group if row.get(metric) is not None],
                    dtype=float,
                )
                rows.append(
                    {
                        "scope": scope,
                        "sampler": sampler,
                        "metric": metric,
                        "n": int(len(values)),
                        "missing": len(group) - int(len(values)),
                        "mean": float(np.mean(values)) if len(values) else None,
                        "median": float(np.median(values)) if len(values) else None,
                        "sample_std": (
                            float(np.std(values, ddof=1)) if len(values) > 1 else 0.0
                        )
                        if len(values)
                        else None,
                    }
                )
    return rows


def _paired_rows(detail: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    tasks: dict[tuple[str, str], dict[str, Mapping[str, object]]] = {}
    for row in detail:
        key = (str(row["task_id"]), str(row["instance_id"]))
        tasks.setdefault(key, {})[str(row["sampler"])] = row
    result: list[dict[str, object]] = []
    for rows in tasks.values():
        hardware = rows.get("Quafu Hardware")
        if hardware is None:
            continue
        for baseline_name in ("Random", "Ideal QAOA Simulator"):
            baseline = rows.get(baseline_name)
            complete = bool(
                baseline
                and hardware.get("shannon_entropy") is not None
                and baseline.get("shannon_entropy") is not None
            )
            record = {
                "task_kind": hardware["task_kind"],
                "instance_id": hardware["instance_id"],
                "seed": hardware["seed"],
                "p": hardware["p"],
                "replicate": hardware["replicate"],
                "task_id": hardware["task_id"],
                "baseline_sampler": baseline_name,
                "counts_status": "COMPLETE" if complete else "MISSING_COMPARISON",
                "entropy_delta_hardware_minus_baseline": None,
                "low_energy_probability_delta_hardware_minus_baseline": None,
                "enrichment_delta_hardware_minus_baseline": None,
                "route_improvement_delta_hardware_minus_baseline": None,
                "hardware_entropy_lower": None,
                "hardware_low_energy_probability_higher": None,
                "lower_entropy_and_higher_low_energy_probability": None,
            }
            if complete and baseline is not None:
                entropy_delta = float(hardware["shannon_entropy"]) - float(
                    baseline["shannon_entropy"]
                )
                low_delta = float(hardware["low_energy_probability"]) - float(
                    baseline["low_energy_probability"]
                )
                record.update(
                    {
                        "entropy_delta_hardware_minus_baseline": entropy_delta,
                        "low_energy_probability_delta_hardware_minus_baseline": low_delta,
                        "enrichment_delta_hardware_minus_baseline": float(
                            hardware["enrichment_ratio"]
                        )
                        - float(baseline["enrichment_ratio"]),
                        "route_improvement_delta_hardware_minus_baseline": float(
                            hardware["route_improvement"]
                        )
                        - float(baseline["route_improvement"]),
                        "hardware_entropy_lower": entropy_delta < 0.0,
                        "hardware_low_energy_probability_higher": low_delta > 0.0,
                        "lower_entropy_and_higher_low_energy_probability": (
                            entropy_delta < 0.0 and low_delta > 0.0
                        ),
                    }
                )
            result.append(record)
    return result


def _summary_value(
    summary: Sequence[Mapping[str, object]], sampler: str, metric: str, statistic: str
) -> float | None:
    row = next(
        row
        for row in summary
        if row["scope"] == "primary_independent_tasks"
        and row["sampler"] == sampler
        and row["metric"] == metric
    )
    value = row[statistic]
    return float(value) if value is not None else None


def _format_value(value: object, digits: int, *, sign: bool = False) -> str:
    if value is None:
        return "N/A"
    return f"{float(value):{'+' if sign else ''}.{digits}f}"


def _format_percentage_delta(value: object) -> str:
    if value is None:
        return "N/A"
    return f"{float(value):+.4%}"


def _paired_focus(paired: Sequence[Mapping[str, object]], baseline: str) -> dict[str, object]:
    rows = [
        row
        for row in paired
        if row["task_kind"] == "primary"
        and row["baseline_sampler"] == baseline
        and row["counts_status"] == "COMPLETE"
    ]
    entropy_deltas = np.asarray(
        [float(row["entropy_delta_hardware_minus_baseline"]) for row in rows]
    )
    low_deltas = np.asarray(
        [float(row["low_energy_probability_delta_hardware_minus_baseline"]) for row in rows]
    )
    return {
        "baseline_sampler": baseline,
        "n": len(rows),
        "hardware_entropy_lower": sum(bool(row["hardware_entropy_lower"]) for row in rows),
        "hardware_low_energy_probability_higher": sum(
            bool(row["hardware_low_energy_probability_higher"]) for row in rows
        ),
        "lower_entropy_and_higher_low_energy_probability": sum(
            bool(row["lower_entropy_and_higher_low_energy_probability"]) for row in rows
        ),
        "mean_entropy_delta_hardware_minus_baseline": (
            float(np.mean(entropy_deltas)) if len(rows) else None
        ),
        "mean_low_energy_probability_delta_hardware_minus_baseline": (
            float(np.mean(low_deltas)) if len(rows) else None
        ),
    }


def _report_markdown(
    detail: Sequence[Mapping[str, object]],
    summary: Sequence[Mapping[str, object]],
    paired: Sequence[Mapping[str, object]],
) -> str:
    primary_tasks = len(
        {
            (row["task_id"], row["instance_id"])
            for row in detail
            if row["task_kind"] == "primary"
        }
    )
    all_tasks = len({(row["task_id"], row["instance_id"]) for row in detail})
    hardware_missing = sum(
        row["sampler"] == "Quafu Hardware" and row["counts_status"] != "COMPLETE"
        for row in detail
    )
    versus_random = _paired_focus(paired, "Random")
    versus_ideal = _paired_focus(paired, "Ideal QAOA Simulator")
    lines = [
        "## 分布诊断（复用历史 Quafu counts）",
        "",
        f"本节只做离线后处理：复用 {all_tasks} 个历史 8-bit Quafu/Baihua 任务的原始 counts，"
        "没有提交或重跑真机任务。Random 与 Ideal QAOA Simulator 对每个任务使用相同 Block、"
        "shots 和实验 Seed；Ideal 分布使用冻结 manifest 中的 QAOA 参数。",
        "",
        f"低能区域沿用现有门槛：按完整 QUBO 能量排序取最低 10%（8-bit 下为 {LOW_ENERGY_STATE_COUNT}/256 个状态）；"
        f"富集倍数相对均匀随机概率 {UNIFORM_LOW_ENERGY_PROBABILITY:.6f} 计算。路线改善沿用现有 Top-{TOP_K} 候选中的最佳严格改善。",
        "",
        f"以下为 {primary_tasks} 个主矩阵独立任务的按任务均值；重复运行与闭环任务保留在明细和全历史任务汇总中，"
        "不在本表重复加权。",
        "",
        "| sampler | low_energy_probability | enrichment_ratio | shannon_entropy | normalized_entropy | unique_states | coverage | effective_states | route_improvement |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for sampler in SAMPLERS:
        values = {
            metric: _summary_value(summary, sampler, metric, "mean")
            for metric in SUMMARY_METRICS
        }
        lines.append(
            f"| {sampler} | {_format_value(values['low_energy_probability'], 6)} | "
            f"{_format_value(values['enrichment_ratio'], 4)} | "
            f"{_format_value(values['shannon_entropy'], 4)} | "
            f"{_format_value(values['normalized_entropy'], 4)} | "
            f"{_format_value(values['unique_states'], 2)} | "
            f"{_format_value(values['coverage'], 4)} | "
            f"{_format_value(values['effective_states'], 2)} | "
            f"{_format_value(values['route_improvement'], 6)} |"
        )
    lines.extend(
        [
            "",
            "### 熵下降是否对应低能集中",
            "",
            f"在主矩阵中，相对 Random，Quafu Hardware 有 {versus_random['hardware_entropy_lower']}/{versus_random['n']} 个任务熵更低，"
            f"有 {versus_random['hardware_low_energy_probability_higher']}/{versus_random['n']} 个任务低能概率更高，"
            f"其中 {versus_random['lower_entropy_and_higher_low_energy_probability']}/{versus_random['n']} 个任务同时满足两者；"
            f"平均熵差（硬件减基线）为 {_format_value(versus_random['mean_entropy_delta_hardware_minus_baseline'], 4)} bit，"
            f"平均低能概率差为 {_format_percentage_delta(versus_random['mean_low_energy_probability_delta_hardware_minus_baseline'])}。",
            "",
            f"相对 Ideal QAOA Simulator，上述数量分别为 {versus_ideal['hardware_entropy_lower']}/{versus_ideal['n']}、"
            f"{versus_ideal['hardware_low_energy_probability_higher']}/{versus_ideal['n']} 和 "
            f"{versus_ideal['lower_entropy_and_higher_low_energy_probability']}/{versus_ideal['n']}；"
            f"平均熵差为 {_format_value(versus_ideal['mean_entropy_delta_hardware_minus_baseline'], 4)} bit，"
            f"平均低能概率差为 {_format_percentage_delta(versus_ideal['mean_low_energy_probability_delta_hardware_minus_baseline'])}。",
            "",
            "熵与唯一状态数仅用于描述分布集中程度。只有当熵下降与预先定义低能区域概率上升同时出现时，"
            "才能说明集中方向与低能区域一致；即使如此，也不能仅凭熵或唯一状态数认定量子正向贡献，"
            "仍须结合低能富集、同任务基线和路线改善指标。",
            "",
            f"counts 缺失任务数：{hardware_missing}。若后续历史文件缺少或损坏 counts，明细会将指标留空并标记原因，"
            "不会补造数据，也不会自动重跑真机。均值、中位数和样本标准差见 "
            "`hardware_gap/distribution_diagnostics_summary.csv`。",
        ]
    )
    return "\n".join(lines) + "\n"


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )


def run() -> dict[str, object]:
    selected = read_jsonl(OFFLINE_DIR / "selected_instances.jsonl")
    manifests = read_jsonl(HARDWARE_DIR / "hardware_submission_manifest.jsonl")
    live = read_jsonl(HARDWARE_DIR / "hardware_live_results.jsonl")
    if not selected or not manifests:
        raise FileNotFoundError("offline payloads and frozen hardware manifest are required")

    selected_by_id = {
        str(row["instance_id"]): row for row in selected if int(row["block_size"]) == WIDTH
    }
    selected_by_seed: dict[int, Mapping[str, object]] = {}
    for row in selected_by_id.values():
        selected_by_seed.setdefault(int(row["seed"]), row)
    manifest_by_key = {
        (str(row["instance_id"]), int(row["p"])): row for row in manifests
    }

    tasks = list(live)
    live_primary_keys = {
        (str(row["instance_id"]), int(row["p"]))
        for row in live
        if int(row.get("replicate", 1)) == 1
    }
    for key, manifest in manifest_by_key.items():
        if key not in live_primary_keys:
            tasks.append(
                {
                    "instance_id": manifest["instance_id"],
                    "seed": manifest["seed"],
                    "p": manifest["p"],
                    "replicate": 1,
                    "task_id": "",
                    "shots": manifest.get("shots", 0),
                    "counts": None,
                    "historical_status": "MISSING_COUNTS",
                }
            )

    context_cache = {}
    space_cache = {}
    ideal_cache = {}
    detail: list[dict[str, object]] = []
    for task in tasks:
        instance_id = str(task["instance_id"])
        depth = int(task["p"])
        manifest = manifest_by_key.get((instance_id, depth))
        raw_vector, hardware_status = _counts_vector(task.get("counts"))
        declared_shots = int(task.get("shots", 0) or 0)
        observed_shots = int(raw_vector.sum()) if raw_vector is not None else 0
        expected_shots = declared_shots or int(manifest.get("shots", 0) if manifest else 0)
        if raw_vector is not None and expected_shots and observed_shots != expected_shots:
            hardware_status = f"INCOMPLETE_COUNTS:{observed_shots}/{expected_shots}"
            raw_vector = None
        shots = expected_shots or observed_shots

        context_error = ""
        try:
            if manifest is None:
                raise KeyError("no matching frozen manifest")
            if instance_id not in context_cache:
                context_cache[instance_id] = _build_context(
                    instance_id, manifest, selected_by_id, selected_by_seed
                )
                space_cache[instance_id] = enumerate_context(
                    context_cache[instance_id],
                    build_proxy(context_cache[instance_id], "full_interaction", 25.0),
                )
            cache_key = (instance_id, depth)
            if cache_key not in ideal_cache:
                compatible_proxy = build_proxy(
                    context_cache[instance_id], "current_sparse", 25.0
                )
                ideal_cache[cache_key] = ideal_probabilities(
                    compatible_proxy, _manifest_parameters(manifest)
                )
        except (KeyError, TypeError, ValueError) as exc:
            context_error = str(exc)

        seed = int(task["seed"])
        for sampler in SAMPLERS:
            if context_error or shots <= 0:
                reason = context_error or "MISSING_SHOTS"
                row = _base_detail(task, sampler, shots, "MISSING_INPUT", reason)
                row.update(_missing_metrics())
                detail.append(row)
                continue
            if sampler == "Random":
                counts = _sample_counts(
                    np.full(STATE_COUNT, 1.0 / STATE_COUNT), shots, seed
                )
                status, reason = "COMPLETE", ""
            elif sampler == "Ideal QAOA Simulator":
                counts = _sample_counts(ideal_cache[(instance_id, depth)], shots, seed)
                status, reason = "COMPLETE", ""
            elif raw_vector is not None:
                counts = raw_vector
                status, reason = "COMPLETE", ""
            else:
                row = _base_detail(task, sampler, shots, hardware_status, hardware_status)
                row.update(_missing_metrics())
                detail.append(row)
                continue
            row = _base_detail(task, sampler, shots, status, reason)
            row.update(distribution_metrics(space_cache[instance_id], counts))
            detail.append(row)

    summary = _summary_rows(detail)
    paired = _paired_rows(detail)
    report = _report_markdown(detail, summary, paired)
    metadata = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "analysis_type": "offline_reuse_of_historical_counts",
        "hardware_submission_performed": False,
        "width": WIDTH,
        "state_count": STATE_COUNT,
        "low_energy_fraction_rule": LOW_ENERGY_FRACTION,
        "low_energy_state_count": LOW_ENERGY_STATE_COUNT,
        "uniform_low_energy_probability": UNIFORM_LOW_ENERGY_PROBABILITY,
        "top_k": TOP_K,
        "standard_deviation": "sample_std_ddof_1",
        "historical_tasks": len(tasks),
        "detail_rows": len(detail),
        "hardware_complete": sum(
            row["sampler"] == "Quafu Hardware" and row["counts_status"] == "COMPLETE"
            for row in detail
        ),
        "hardware_missing": sum(
            row["sampler"] == "Quafu Hardware" and row["counts_status"] != "COMPLETE"
            for row in detail
        ),
        "paired_focus": {
            "versus_random": _paired_focus(paired, "Random"),
            "versus_ideal": _paired_focus(paired, "Ideal QAOA Simulator"),
        },
        "claim_boundary": (
            "Entropy and unique-state metrics are descriptive aids and are not, by themselves, "
            "evidence of a positive quantum contribution."
        ),
    }

    write_csv(DETAIL_CSV, detail)
    _write_json(DETAIL_JSON, detail)
    write_csv(SUMMARY_CSV, summary)
    _write_json(SUMMARY_JSON, summary)
    write_csv(PAIRED_CSV, paired)
    _write_json(PAIRED_JSON, paired)
    _write_json(METADATA_JSON, metadata)
    REPORT_SECTION.write_text(report, encoding="utf-8")
    return {
        **metadata,
        "detail_csv": str(DETAIL_CSV),
        "detail_json": str(DETAIL_JSON),
        "summary_csv": str(SUMMARY_CSV),
        "summary_json": str(SUMMARY_JSON),
        "paired_csv": str(PAIRED_CSV),
        "paired_json": str(PAIRED_JSON),
        "metadata_json": str(METADATA_JSON),
        "report_section": str(REPORT_SECTION),
    }


def main() -> None:
    argparse.ArgumentParser(
        description="Offline distribution diagnostics from frozen 8-bit Quafu counts"
    ).parse_args()
    print(json.dumps(run(), ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
