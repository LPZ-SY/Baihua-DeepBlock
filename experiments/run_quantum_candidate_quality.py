from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from quantum_route_forge.candidate_quality import (  # noqa: E402
    DEFAULT_ENERGY_TOLERANCE,
    freeze_thresholds,
)


ENERGY_FIELDS = ("energy", "bqm_energy", "assignment_energy")
WEIGHT_FIELDS = ("count", "weight", "shots")


def _parse_bool(value: Any) -> bool:
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y"}:
        return True
    if text in {"0", "false", "no", "n", ""}:
        return False
    raise ValueError(f"Cannot parse feasible={value!r}; use true/false or 1/0.")


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
        feasible_field = "raw_feasible" if "raw_feasible" in fields else "feasible"
        if "instance_id" not in fields or feasible_field not in fields:
            raise ValueError(f"{path} must contain instance_id and feasible/raw_feasible")
        if not any(name in fields for name in ENERGY_FIELDS):
            raise ValueError(f"{path} must contain one energy field: {ENERGY_FIELDS}")
        for line_no, row in enumerate(reader, start=2):
            instance_id = str(row.get("instance_id", "")).strip()
            energy_text = _first_present(row, ENERGY_FIELDS)
            if not instance_id or energy_text is None:
                raise ValueError(f"{path}:{line_no} has an empty instance_id or energy")
            energy = float(energy_text)
            if not math.isfinite(energy):
                raise ValueError(f"{path}:{line_no} has a non-finite energy")
            weight_text = _first_present(row, WEIGHT_FIELDS)
            weight = int(float(weight_text)) if weight_text is not None else 1
            if weight <= 0:
                raise ValueError(f"{path}:{line_no} count/weight/shots must be positive")
            grouped[instance_id].append(
                {
                    "energy": energy,
                    "feasible": _parse_bool(row.get(feasible_field, "")),
                    "weight": weight,
                }
            )
    return dict(grouped)


def _take_budget(rows: list[dict[str, Any]], budget: int) -> list[dict[str, Any]]:
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
    """Compatibility wrapper for the package-level schema-v2 threshold freezer."""
    return freeze_thresholds(baseline, budget)


def evaluate_quantum_candidates(
    quantum: dict[str, list[dict[str, Any]]], thresholds: dict[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    budget = int(thresholds["budget_shots_per_instance"])
    tolerance = float(thresholds.get("energy_tolerance", DEFAULT_ENERGY_TOLERANCE))
    rows_out: list[dict[str, Any]] = []
    instance_ids = sorted(set(thresholds.get("instances", {})) | set(quantum))
    for instance_id in instance_ids:
        info = thresholds.get("instances", {}).get(instance_id, {})
        rows = _take_budget(quantum.get(instance_id, []), budget)
        observed = sum(int(row["weight"]) for row in rows)
        threshold_all = info.get("best_classical_energy_all", info.get("threshold"))
        threshold_feasible = info.get("best_classical_energy_feasible", info.get("threshold"))
        if observed < budget or threshold_feasible is None:
            decision = "NOT_EVALUABLE"
            reason = (
                "Measured quantum candidates are below the fixed budget."
                if observed < budget
                else "No feasible classical threshold exists for this instance."
            )
        else:
            feasible_reach = sum(
                int(row["weight"])
                for row in rows
                if bool(row["feasible"])
                and float(row["energy"]) <= float(threshold_feasible) + tolerance
            )
            decision = "PASS" if feasible_reach > 0 else "FAIL"
            reason = (
                "At least one raw-feasible quantum candidate reached the frozen feasible classical threshold."
                if decision == "PASS"
                else "No raw-feasible quantum candidate reached the frozen feasible classical threshold."
            )
        feasible_reach = sum(
            int(row["weight"])
            for row in rows
            if threshold_feasible is not None
            and bool(row["feasible"])
            and float(row["energy"]) <= float(threshold_feasible) + tolerance
        )
        all_reach = sum(
            int(row["weight"])
            for row in rows
            if threshold_all is not None
            and float(row["energy"]) <= float(threshold_all) + tolerance
        )
        strict_feasible = sum(
            int(row["weight"])
            for row in rows
            if threshold_feasible is not None
            and bool(row["feasible"])
            and float(row["energy"]) < float(threshold_feasible) - tolerance
        )
        all_energies = [float(row["energy"]) for row in rows]
        feasible_energies = [float(row["energy"]) for row in rows if bool(row["feasible"])]
        rows_out.append(
            {
                "instance_id": instance_id,
                "energy_threshold_all": "" if threshold_all is None else threshold_all,
                "energy_threshold_feasible": "" if threshold_feasible is None else threshold_feasible,
                "threshold": "" if threshold_feasible is None else threshold_feasible,
                "budget_shots": budget,
                "observed_quantum_shots": observed,
                "feasible_quantum_shots": sum(int(row["weight"]) for row in rows if row["feasible"]),
                "quantum_best_energy": "" if not all_energies else min(all_energies),
                "quantum_best_feasible_energy": "" if not feasible_energies else min(feasible_energies),
                "classical_reach_all_shots": all_reach,
                "classical_reach_feasible_shots": feasible_reach,
                "feasible_passing_shots": feasible_reach,
                "feasible_passing_rate": feasible_reach / observed if observed else "",
                "passing_shots": feasible_reach,
                "passing_rate": feasible_reach / observed if observed else "",
                "strictly_improving_shots": strict_feasible,
                "decision": decision,
                "reason": reason,
            }
        )
    counts = {
        key: sum(row["decision"] == key for row in rows_out)
        for key in ("PASS", "FAIL", "NOT_EVALUABLE")
    }
    conclusion = (
        "positive_contribution_observed"
        if counts["PASS"]
        else "no_positive_contribution_observed_under_frozen_threshold"
        if counts["FAIL"]
        else "not_evaluable"
    )
    return rows_out, {
        "criterion": "raw feasible and energy <= frozen feasible classical threshold + tolerance",
        "threshold_method": thresholds["threshold_method"],
        "budget_shots_per_instance": budget,
        "energy_tolerance": tolerance,
        "instance_counts": counts,
        "conclusion": conclusion,
        "claim_scope": (
            "A reach PASS means that a raw-feasible candidate reached the same-budget frozen "
            "classical level. It is not a claim of universal quantum advantage or final-route superiority."
        ),
    }


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        if rows:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Independent quantum-candidate threshold analysis")
    subparsers = parser.add_subparsers(dest="command", required=True)
    calibrate = subparsers.add_parser("calibrate", help="freeze per-instance classical thresholds")
    calibrate.add_argument("--baseline-csv", required=True, type=Path)
    calibrate.add_argument("--budget", required=True, type=int)
    calibrate.add_argument("--output", required=True, type=Path)
    evaluate = subparsers.add_parser("evaluate", help="evaluate quantum candidates against frozen thresholds")
    evaluate.add_argument("--quantum-csv", required=True, type=Path)
    evaluate.add_argument("--thresholds", required=True, type=Path)
    evaluate.add_argument("--outdir", required=True, type=Path)
    args = parser.parse_args()
    if args.command == "calibrate":
        payload = calibrate_thresholds(read_candidates(args.baseline_csv), args.budget)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Frozen thresholds written to: {args.output}")
        return
    rows, summary = evaluate_quantum_candidates(
        read_candidates(args.quantum_csv),
        json.loads(args.thresholds.read_text(encoding="utf-8")),
    )
    args.outdir.mkdir(parents=True, exist_ok=True)
    _write_csv(args.outdir / "quantum_candidate_quality.csv", rows)
    (args.outdir / "quantum_candidate_quality_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Candidate evaluation written to: {args.outdir}")


if __name__ == "__main__":
    main()
