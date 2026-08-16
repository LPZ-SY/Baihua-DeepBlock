"""Fetch, validate, and draw current Quafu physical coupling graphs.

This script is read-only with respect to Quafu: it retrieves backend chip_info
and never submits a quantum task.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

import matplotlib.pyplot as plt
from dotenv import load_dotenv
from quark.circuit import Backend


BACKENDS = {
    "Baihua": (156, 182),
    "Dongling": (84, 113),
    "Shenglian": (84, 113),
}

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PROJECT_ROOT.parent
OUTPUT_DIR = WORKSPACE_ROOT / "output" / "quafu_current_topologies"


def normalized_snapshot(name: str, chip_info: dict) -> dict:
    qubits = []
    for row in chip_info["qubits_info"].values():
        qubits.append(
            {
                "label": str(row["label"]),
                "index": int(row["index"]),
                "coordinate": [float(v) for v in row["coordinate"]],
                "single_qubit_fidelity": float(row["fidelity"]),
                "T1": float(row["T1"]),
                "T2": float(row["T2"]),
                "frequency": float(row["frequency"]),
            }
        )

    couplers = []
    for row in chip_info["couplers_info"].values():
        left, right = (int(v) for v in row["qubits_index"])
        couplers.append(
            {
                "label": str(row["label"]),
                "index": int(row["index"]),
                "qubits": [left, right],
                "two_qubit_fidelity": float(row["fidelity"]),
            }
        )

    qubits.sort(key=lambda row: row["index"])
    couplers.sort(key=lambda row: row["index"])
    return {
        "backend": name,
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        "calibration_time": chip_info.get("calibration_time"),
        "qubit_count": len(qubits),
        "coupler_count": len(couplers),
        "qubits": qubits,
        "couplers": couplers,
    }


def validate_snapshot(snapshot: dict, expected: tuple[int, int]) -> None:
    expected_qubits, expected_couplers = expected
    qubits = snapshot["qubits"]
    couplers = snapshot["couplers"]
    indices = {row["index"] for row in qubits}
    coordinates = {tuple(row["coordinate"]) for row in qubits}
    undirected_edges = {
        tuple(sorted(row["qubits"]))
        for row in couplers
    }

    assert len(qubits) == expected_qubits
    assert len(couplers) == expected_couplers
    assert len(indices) == expected_qubits
    assert len(coordinates) == expected_qubits
    assert len(undirected_edges) == expected_couplers
    assert all(left in indices and right in indices for left, right in undirected_edges)
    assert all(left != right for left, right in undirected_edges)


def write_edge_csv(snapshot: dict, path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=("coupler", "qubit_a", "qubit_b", "two_qubit_fidelity"),
        )
        writer.writeheader()
        for row in snapshot["couplers"]:
            writer.writerow(
                {
                    "coupler": row["label"],
                    "qubit_a": row["qubits"][0],
                    "qubit_b": row["qubits"][1],
                    "two_qubit_fidelity": row["two_qubit_fidelity"],
                }
            )


def draw_snapshot(snapshot: dict, output_stem: Path) -> None:
    qubits = snapshot["qubits"]
    couplers = snapshot["couplers"]
    positions = {
        row["index"]: (row["coordinate"][0], -row["coordinate"][1])
        for row in qubits
    }

    xs = [point[0] for point in positions.values()]
    ys = [point[1] for point in positions.values()]
    width_units = max(xs) - min(xs) + 1
    height_units = max(ys) - min(ys) + 1
    fig_width = max(15.0, width_units * 1.3)
    fig_height = max(10.0, height_units * 1.3 + 2.0)
    fig, ax = plt.subplots(figsize=(fig_width, fig_height), constrained_layout=True)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("#f8fafc")

    for row in couplers:
        left, right = row["qubits"]
        x_values = [positions[left][0], positions[right][0]]
        y_values = [positions[left][1], positions[right][1]]
        ax.plot(
            x_values,
            y_values,
            color="#2563eb",
            linewidth=5.0,
            solid_capstyle="round",
            zorder=1,
        )

    ax.scatter(
        xs,
        ys,
        s=1050,
        c="#67e8f9",
        edgecolors="#0f172a",
        linewidths=1.8,
        zorder=2,
    )
    for row in qubits:
        x_value, y_value = positions[row["index"]]
        ax.text(
            x_value,
            y_value,
            f"Q{row['index']}",
            ha="center",
            va="center",
            fontsize=9,
            fontweight="bold",
            color="#111827",
            zorder=3,
        )

    calibration = snapshot.get("calibration_time") or "unknown"
    ax.set_title(
        f"Quafu {snapshot['backend']} - complete physical coupling graph\n"
        f"{snapshot['qubit_count']} qubits, {snapshot['coupler_count']} couplers | calibration: {calibration}",
        fontsize=20,
        fontweight="bold",
        pad=22,
        color="#0f172a",
    )
    ax.set_aspect("equal")
    ax.axis("off")
    ax.margins(0.07)

    fig.savefig(output_stem.with_suffix(".png"), dpi=240, facecolor="white")
    fig.savefig(output_stem.with_suffix(".svg"), facecolor="white")
    plt.close(fig)


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest = []
    for name, expected in BACKENDS.items():
        chip_info = dict(Backend(name).chip_info)
        snapshot = normalized_snapshot(name, chip_info)
        validate_snapshot(snapshot, expected)
        stem = OUTPUT_DIR / name.lower()
        stem.with_suffix(".json").write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        write_edge_csv(snapshot, stem.with_name(f"{stem.name}_edges").with_suffix(".csv"))
        draw_snapshot(snapshot, stem)
        manifest.append(
            {
                "backend": name,
                "qubits": snapshot["qubit_count"],
                "couplers": snapshot["coupler_count"],
                "calibration_time": snapshot["calibration_time"],
                "validation": "passed",
            }
        )

    (OUTPUT_DIR / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    for row in manifest:
        print(
            f"{row['backend']}: {row['qubits']} qubits, "
            f"{row['couplers']} couplers, calibration {row['calibration_time']}"
        )


if __name__ == "__main__":
    main()
