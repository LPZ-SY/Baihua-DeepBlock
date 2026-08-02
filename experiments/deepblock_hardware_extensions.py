from __future__ import annotations

import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

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


def _spaces() -> dict[str, object]:
    spaces = {}
    for payload in read_jsonl(OFFLINE_DIR / "selected_instances.jsonl"):
        if int(payload["block_size"]) != 8:
            continue
        context = context_from_payload(payload, width=8)
        spaces[context.instance_id] = enumerate_context(
            context, build_proxy(context, "full_interaction", 25.0)
        )
    return spaces


def _probabilities(counts: dict[str, object], width: int = 8) -> np.ndarray:
    values = np.zeros(1 << width, dtype=float)
    for key, count in counts.items():
        state = int(str(key).replace(" ", "")[-width:].zfill(width), 2)
        values[state] += int(count)
    return values / values.sum()


def _subsample(counts: dict[str, object], budget: int, rng: np.random.Generator) -> np.ndarray:
    population: list[int] = []
    for key, count in counts.items():
        state = int(str(key).replace(" ", "")[-8:].zfill(8), 2)
        population.extend([state] * int(count))
    chosen = rng.choice(np.asarray(population), size=budget, replace=False)
    return np.bincount(chosen, minlength=256).astype(float) / budget


def run(resamples: int = 200) -> dict[str, object]:
    live = read_jsonl(HARDWARE_DIR / "hardware_live_results.jsonl")
    spaces = _spaces()
    primary = [
        row for row in live
        if int(row.get("replicate", 1)) == 1 and int(row["p"]) in (1, 2)
        and str(row["instance_id"]) in spaces
    ]
    detail: list[dict[str, object]] = []
    rng = np.random.default_rng(20260802)
    for row in primary:
        space = spaces[str(row["instance_id"])]
        for budget in (64, 256, 1024):
            iterations = 1 if budget == 1024 else resamples
            for index in range(iterations):
                probabilities = (
                    _probabilities(row["counts"]) if budget == 1024
                    else _subsample(row["counts"], budget, rng)
                )
                detail.append({
                    "instance_id": row["instance_id"], "seed": row["seed"],
                    "p": row["p"], "task_id": row["task_id"], "shots": budget,
                    "resample": index + 1,
                    "method": "exact_real_counts" if budget == 1024 else
                              "posthoc_without_replacement_from_real_1024_counts",
                    **observed_distribution_metrics(space, probabilities),
                })
    write_csv(HARDWARE_DIR / "hardware_shots_scan_detail.csv", detail)
    summary = []
    for p in (1, 2):
        for budget in (64, 256, 1024):
            group = [r for r in detail if int(r["p"]) == p and int(r["shots"]) == budget]
            for metric in ("low_energy_probability", "improving_probability", "found_improvement", "best_improvement"):
                values = np.asarray([float(r[metric]) for r in group])
                summary.append({"p": p, "shots": budget, "metric": metric,
                                "n": len(values), "mean": float(values.mean()),
                                "std": float(values.std(ddof=1)) if len(values) > 1 else 0.0,
                                "q025": float(np.quantile(values, .025)),
                                "q975": float(np.quantile(values, .975))})
    write_csv(HARDWARE_DIR / "hardware_shots_scan_summary.csv", summary)

    repeat_detail = []
    targets = {("seed002_pair1_B2_w8", 1), ("seed002_pair1_B2_w8", 2),
               ("seed003_pair1_B1_w8", 1), ("seed003_pair1_B1_w8", 2)}
    for row in live:
        key = (str(row["instance_id"]), int(row["p"]))
        if key not in targets:
            continue
        repeat_detail.append({"instance_id": key[0], "seed": row["seed"], "p": key[1],
                              "replicate": int(row.get("replicate", 1)), "task_id": row["task_id"],
                              **observed_distribution_metrics(spaces[key[0]], _probabilities(row["counts"]))})
    write_csv(HARDWARE_DIR / "hardware_repeat_detail.csv", repeat_detail)
    repeat_summary = []
    for instance_id, p in sorted(targets):
        group = [r for r in repeat_detail if r["instance_id"] == instance_id and int(r["p"]) == p]
        for metric in ("low_energy_probability", "improving_probability", "found_improvement", "best_improvement"):
            values = np.asarray([float(r[metric]) for r in group])
            repeat_summary.append({"instance_id": instance_id, "p": p, "metric": metric,
                                   "n": len(values), "mean": float(values.mean()),
                                   "sample_std": float(values.std(ddof=1)),
                                   "min": float(values.min()), "max": float(values.max())})
    write_csv(HARDWARE_DIR / "hardware_repeat_summary.csv", repeat_summary)
    result = {"primary_tasks": len(primary), "shot_resamples": resamples,
              "repeat_tasks": len(repeat_detail), "repeat_configurations": len(targets)}
    (HARDWARE_DIR / "hardware_extensions_summary.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
