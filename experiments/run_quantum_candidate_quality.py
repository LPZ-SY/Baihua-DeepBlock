from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


ENERGY_FIELDS = ("energy", "bqm_energy", "assignment_energy")
WEIGHT_FIELDS = ("count", "weight", "shots")
DEFAULT_ENERGY_TOLERANCE = 1e-9


def _parse_bool(value: Any) -> bool:
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y"}:
        return True
    if text in {"0", "false", "no", "n", ""}:
        return False
    raise ValueError(f"无法解析 feasible={value!r}，请使用 true/false 或 1/0。")


def _first_present(row: dict[str, str], names: Iterable[str]) -> str | None:
    for name in names:
        if name in row and str(row[name]).strip() != "":
            return str(row[name]).strip()
    return None


def read_candidates(path: Path) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        fields = set(reader.fieldnames or [])
        missing = {"instance_id", "feasible"} - fields
        if missing:
            raise ValueError(f"{path} 缺少字段: {sorted(missing)}")
        if not any(name in fields for name in ENERGY_FIELDS):
            raise ValueError(f"{path} 至少需要一个能量字段: {list(ENERGY_FIELDS)}")

        for line_no, row in enumerate(reader, start=2):
            instance_id = str(row.get("instance_id", "")).strip()
            energy_text = _first_present(row, ENERGY_FIELDS)
            if not instance_id or energy_text is None:
                raise ValueError(f"{path}:{line_no} 的 instance_id 或 energy 为空。")
            energy = float(energy_text)
            if not math.isfinite(energy):
                raise ValueError(f"{path}:{line_no} 的 energy 不是有限数值。")
            weight_text = _first_present(row, WEIGHT_FIELDS)
            weight = int(float(weight_text)) if weight_text is not None else 1
            if weight <= 0:
                raise ValueError(f"{path}:{line_no} 的 count/weight/shots 必须为正整数。")
            grouped[instance_id].append(
                {
                    "energy": energy,
                    "feasible": _parse_bool(row.get("feasible", "")),
                    "weight": weight,
                }
            )
    return dict(grouped)


def _take_budget(rows: list[dict[str, Any]], budget: int) -> list[dict[str, Any]]:
    """按 CSV 顺序截取固定 shot 预算，必要时拆分最后一条计数。"""
    selected: list[dict[str, Any]] = []
    remaining = budget
    for row in rows:
        if remaining <= 0:
            break
        take = min(int(row["weight"]), remaining)
        selected.append({**row, "weight": take})
        remaining -= take
    return selected


def calibrate_thresholds(
    baseline: dict[str, list[dict[str, Any]]], budget: int
) -> dict[str, Any]:
    instances: dict[str, Any] = {}
    for instance_id, rows in sorted(baseline.items()):
        selected = _take_budget(rows, budget)
        observed = sum(int(row["weight"]) for row in selected)
        energies = [float(row["energy"]) for row in selected]
        threshold = min(energies) if observed == budget and energies else None
        instances[instance_id] = {
            "threshold": threshold,
            "observed_baseline_shots": observed,
            "feasible_baseline_shots": sum(
                int(row["weight"]) for row in selected if bool(row["feasible"])
            ),
            "status": "ready" if threshold is not None else "not_evaluable",
            "reason": (
                "阈值已按固定预算冻结。"
                if threshold is not None
                else (
                    "经典校准样本少于固定预算。"
                    if observed < budget
                    else "经典校准预算内没有候选。"
                )
            ),
        }

    return {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "criterion": "quantum candidate energy <= frozen threshold + numerical tolerance",
        "threshold_method": "best classical BQM energy under the same fixed budget",
        "energy_tolerance": DEFAULT_ENERGY_TOLERANCE,
        "feasibility_policy": "reported separately; not part of the primary energy gate",
        "strict_inequality": True,
        "budget_shots_per_instance": budget,
        "instances": instances,
    }


def evaluate_quantum_candidates(
    quantum: dict[str, list[dict[str, Any]]], thresholds: dict[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    budget = int(thresholds["budget_shots_per_instance"])
    tolerance = float(thresholds.get("energy_tolerance", DEFAULT_ENERGY_TOLERANCE))
    rows_out: list[dict[str, Any]] = []

    all_instance_ids = sorted(set(thresholds.get("instances", {})) | set(quantum))
    for instance_id in all_instance_ids:
        threshold_info = thresholds.get("instances", {}).get(instance_id)
        quantum_rows = _take_budget(quantum.get(instance_id, []), budget)
        observed = sum(int(row["weight"]) for row in quantum_rows)

        if not threshold_info or threshold_info.get("threshold") is None:
            decision = "NOT_EVALUABLE"
            reason = "缺少该实例的冻结阈值，或经典校准样本少于预设预算。"
            threshold = None
        elif observed < budget:
            decision = "NOT_EVALUABLE"
            reason = (
                "未获得该实例的量子 measured bitstrings。"
                if observed == 0
                else "量子 measured bitstrings 少于预设固定预算。"
            )
            threshold = float(threshold_info["threshold"])
        else:
            threshold = float(threshold_info["threshold"])
            passing_weight = sum(
                int(row["weight"])
                for row in quantum_rows
                if float(row["energy"]) <= threshold + tolerance
            )
            decision = "PASS" if passing_weight > 0 else "FAIL"
            reason = (
                "至少一个量子候选的 BQM 能量在数值容差内达到或低于冻结阈值。"
                if decision == "PASS"
                else "预算内没有量子候选的 BQM 能量在数值容差内达到冻结阈值。"
            )

        all_energies = [float(row["energy"]) for row in quantum_rows]
        feasible_energies = [
            float(row["energy"])
            for row in quantum_rows
            if bool(row["feasible"])
        ]
        passing_weight = (
            sum(
                int(row["weight"])
                for row in quantum_rows
                if threshold is not None
                and float(row["energy"]) <= threshold + tolerance
            )
            if observed
            else 0
        )
        rows_out.append(
            {
                "instance_id": instance_id,
                "threshold": "" if threshold is None else threshold,
                "budget_shots": budget,
                "observed_quantum_shots": observed,
                "feasible_quantum_shots": sum(
                    int(row["weight"]) for row in quantum_rows if bool(row["feasible"])
                ),
                "quantum_best_energy": "" if not all_energies else min(all_energies),
                "quantum_best_feasible_energy": (
                    "" if not feasible_energies else min(feasible_energies)
                ),
                "passing_shots": passing_weight,
                "passing_rate": (passing_weight / observed) if observed else "",
                "strictly_improving_shots": (
                    sum(
                        int(row["weight"])
                        for row in quantum_rows
                        if threshold is not None
                        and float(row["energy"]) < threshold - tolerance
                    )
                    if observed
                    else 0
                ),
                "decision": decision,
                "reason": reason,
            }
        )

    counts = {
        key: sum(1 for row in rows_out if row["decision"] == key)
        for key in ("PASS", "FAIL", "NOT_EVALUABLE")
    }
    if counts["PASS"] > 0:
        conclusion = "positive_contribution_observed"
    elif counts["FAIL"] > 0:
        conclusion = "no_positive_contribution_observed_under_frozen_threshold"
    else:
        conclusion = "not_evaluable"
    summary = {
        "criterion": thresholds["criterion"],
        "threshold_method": thresholds["threshold_method"],
        "budget_shots_per_instance": budget,
        "energy_tolerance": tolerance,
        "instance_counts": counts,
        "conclusion": conclusion,
        "claim_scope": (
            "PASS 仅表示量子采样向候选池提供了在数值容差内达到或低于同预算经典基线阈值的 BQM 能量候选；"
            "原始可行性另行报告，且 PASS 不等同于最终路径优势或广义量子优势。"
        ),
    }
    return rows_out, summary


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        if not rows:
            return
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="量子候选质量的独立阈值分析")
    subparsers = parser.add_subparsers(dest="command", required=True)

    calibrate = subparsers.add_parser("calibrate", help="仅用经典基线冻结逐实例阈值")
    calibrate.add_argument("--baseline-csv", required=True, type=Path)
    calibrate.add_argument("--budget", required=True, type=int)
    calibrate.add_argument("--output", required=True, type=Path)

    evaluate = subparsers.add_parser("evaluate", help="用冻结阈值独立评价量子候选")
    evaluate.add_argument("--quantum-csv", required=True, type=Path)
    evaluate.add_argument("--thresholds", required=True, type=Path)
    evaluate.add_argument("--outdir", required=True, type=Path)

    args = parser.parse_args()
    if args.command == "calibrate":
        if args.budget <= 0:
            raise SystemExit("--budget 必须为正整数。")
        baseline = read_candidates(args.baseline_csv)
        result = calibrate_thresholds(baseline, args.budget)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"冻结阈值已写入: {args.output}")
        return

    quantum = read_candidates(args.quantum_csv)
    thresholds = json.loads(args.thresholds.read_text(encoding="utf-8"))
    rows, summary = evaluate_quantum_candidates(quantum, thresholds)
    args.outdir.mkdir(parents=True, exist_ok=True)
    csv_path = args.outdir / "quantum_candidate_quality.csv"
    summary_path = args.outdir / "quantum_candidate_quality_summary.json"
    _write_csv(csv_path, rows)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"逐实例判定已写入: {csv_path}")
    print(f"汇总结论已写入: {summary_path}")


if __name__ == "__main__":
    main()
