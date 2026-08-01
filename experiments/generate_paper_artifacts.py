from __future__ import annotations

import argparse
import csv
import json
import math
import random
from pathlib import Path
from typing import Any, Iterable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _read_csv(path: Path) -> list[dict[str, Any]]:
    if not path.exists() or not path.stat().st_size:
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def _float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _paper_table(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    fields = [
        ("instance_id", "Instance"),
        ("source", "Source"),
        ("shots_received", "Shots"),
        ("raw_feasible_rate", "Raw feasible"),
        ("quality_hit_rate", "Quality HR"),
        ("random_quality_hit_rate", "Random HR"),
        ("classical_reach_feasible_rate", "Classical reach"),
        ("strict_improvement_rate", "Strict improve"),
        ("best_gap", "Best gap"),
    ]
    return [{label: row.get(key, "") for key, label in fields} for row in rows]


def _latex_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "% No evaluable instance rows.\n"
    headers = list(rows[0])
    lines = [
        "\\begin{tabular}{" + "l" * len(headers) + "}",
        "\\toprule",
        " & ".join(headers) + r" \\",
        "\\midrule",
    ]
    for row in rows:
        values = [str(row.get(header, "")).replace("_", r"\_") for header in headers]
        lines.append(" & ".join(values) + r" \\")
    lines.extend(["\\bottomrule", "\\end{tabular}", ""])
    return "\n".join(lines)


def _energy_cdf(candidates: list[dict[str, Any]], output: Path) -> None:
    fig, ax = plt.subplots(figsize=(7.2, 4.6), dpi=160)
    sources = sorted({str(row.get("source", "unknown")) for row in candidates})
    plotted = False
    for source in sources:
        values = sorted(
            value
            for value in (_float(row.get("energy", row.get("bqm_energy"))) for row in candidates if str(row.get("source", "unknown")) == source)
            if value is not None
        )
        if not values:
            continue
        y = [(index + 1) / len(values) for index in range(len(values))]
        ax.step(values, y, where="post", label=source)
        plotted = True
    ax.set_title("Candidate energy CDF")
    ax.set_xlabel("BQM energy")
    ax.set_ylabel("Empirical CDF over unique candidates")
    ax.grid(alpha=0.25)
    if plotted:
        ax.legend()
    else:
        ax.text(0.5, 0.5, "No candidate data", ha="center", va="center", transform=ax.transAxes)
    fig.tight_layout()
    fig.savefig(output)
    plt.close(fig)


def _hit_rates(rows: list[dict[str, Any]], output: Path) -> None:
    labels = [str(row.get("instance_id", index)) for index, row in enumerate(rows)]
    quality = [_float(row.get("quality_hit_rate")) or 0.0 for row in rows]
    random_rates = [_float(row.get("random_quality_hit_rate")) or 0.0 for row in rows]
    fig, ax = plt.subplots(figsize=(max(7.2, 0.55 * max(1, len(labels))), 4.8), dpi=160)
    x = list(range(len(labels)))
    width = 0.38
    ax.bar([value - width / 2 for value in x], quality, width, label="Measured")
    ax.bar([value + width / 2 for value in x], random_rates, width, label="Uniform random")
    ax.set_title("Prespecified quality-region hit rates")
    ax.set_ylabel("Shot-weighted hit rate")
    ax.set_xticks(x, labels, rotation=35, ha="right")
    ax.set_ylim(bottom=0)
    ax.grid(axis="y", alpha=0.25)
    if labels:
        ax.legend()
    else:
        ax.text(0.5, 0.5, "No instance summaries", ha="center", va="center", transform=ax.transAxes)
    fig.tight_layout()
    fig.savefig(output)
    plt.close(fig)


def _resampling_convergence(candidates: list[dict[str, Any]], output: Path) -> None:
    rows = [row for row in candidates if _float(row.get("probability")) is not None]
    probabilities = [_float(row.get("probability")) or 0.0 for row in rows]
    total = sum(probabilities)
    fig, ax = plt.subplots(figsize=(7.2, 4.6), dpi=160)
    if not rows or total <= 0:
        ax.text(0.5, 0.5, "No probability data", ha="center", va="center", transform=ax.transAxes)
    else:
        probabilities = [value / total for value in probabilities]
        qualifying = [str(row.get("quality_gate_pass", "")).lower() in {"true", "1"} for row in rows]
        rng = random.Random(2026)
        budgets = [128, 256, 512, 1024, 2048, 4096]
        means, lows, highs = [], [], []
        population = list(range(len(rows)))
        for budget in budgets:
            rates = []
            for _ in range(500):
                draws = rng.choices(population, weights=probabilities, k=budget)
                rates.append(sum(qualifying[index] for index in draws) / budget)
            rates.sort()
            means.append(sum(rates) / len(rates))
            lows.append(rates[int(0.025 * len(rates))])
            highs.append(rates[int(0.975 * len(rates)) - 1])
        ax.plot(budgets, means, marker="o", label="Empirical-distribution resampling mean")
        ax.fill_between(budgets, lows, highs, alpha=0.2, label="95% resampling interval")
        ax.legend()
    ax.set_title("Shot-budget convergence (empirical resampling)")
    ax.set_xlabel("Resampled shots")
    ax.set_ylabel("Quality hit rate")
    ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(output)
    plt.close(fig)


def _conclusion(rows: list[dict[str, Any]]) -> str:
    evaluable = [row for row in rows if str(row.get("decision")) in {"PASS", "FAIL"}]
    if not evaluable:
        return "NOT_EVALUABLE: no complete candidate-quality instance summary is available."
    quality = [row for row in evaluable if (_float(row.get("quality_hit_rate")) or 0) > 0]
    above_random = [
        row
        for row in evaluable
        if _float(row.get("quality_hit_rate")) is not None
        and _float(row.get("random_quality_hit_rate")) is not None
        and float(row["quality_hit_rate"]) > float(row["random_quality_hit_rate"])
    ]
    reach = [row for row in evaluable if (_float(row.get("classical_reach_feasible_rate")) or 0) > 0]
    strict = [row for row in evaluable if (_float(row.get("strict_improvement_rate")) or 0) > 0]
    return (
        f"Evaluable instances: {len(evaluable)}. Absolute quality hits occurred in {len(quality)}; "
        f"measured hit rate exceeded uniform random in {len(above_random)}; same-budget feasible "
        f"classical reach occurred in {len(reach)}; strict improvement occurred in {len(strict)}. "
        "These observations concern candidate quality under the frozen matrix and do not establish "
        "universal quantum advantage, speed advantage, or a pure-quantum solution of the full VRP."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate reproducible paper tables and figures")
    parser.add_argument("--experiment-dir", type=Path, required=True)
    args = parser.parse_args()
    experiment_dir = args.experiment_dir
    figures = experiment_dir / "figures"
    figures.mkdir(parents=True, exist_ok=True)
    summaries = _read_csv(experiment_dir / "instance_summary.csv")
    candidates = _read_jsonl(experiment_dir / "candidates.jsonl")
    table = _paper_table(summaries)
    _write_csv(figures / "candidate_quality_table.csv", table)
    (figures / "candidate_quality_table.tex").write_text(_latex_table(table), encoding="utf-8")
    _energy_cdf(candidates, figures / "energy_cdf.png")
    _hit_rates(summaries, figures / "quality_hit_rates.png")
    _resampling_convergence(candidates, figures / "shot_resampling_convergence.png")
    conclusion = _conclusion(summaries)
    (figures / "paper_conclusions.md").write_text(
        "# Data-derived conclusion\n\n" + conclusion + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "experiment_dir": str(experiment_dir),
                "figures": sorted(path.name for path in figures.iterdir()),
                "conclusion": conclusion,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
