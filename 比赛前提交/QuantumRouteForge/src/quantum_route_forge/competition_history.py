from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any


class CompetitionHistory:
    """Small JSON history store used only by the competition front end."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _safe_run_id(run_id: str) -> str:
        value = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(run_id or "")).strip("._")
        if not value:
            raise ValueError("run_id is empty")
        return value

    def save(self, payload: dict[str, Any]) -> Path:
        run_id = self._safe_run_id(str(payload.get("run_id") or ""))
        payload = dict(payload)
        payload.setdefault("saved_at", datetime.now(timezone.utc).isoformat())
        target = self.root / f"{run_id}.json"
        temporary = self.root / f".{run_id}.tmp"
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False),
            encoding="utf-8",
        )
        temporary.replace(target)
        return target

    def load(self, run_id: str) -> dict[str, Any]:
        target = self.root / f"{self._safe_run_id(run_id)}.json"
        return json.loads(target.read_text(encoding="utf-8"))

    def rows(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for path in sorted(self.root.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            selected = payload.get("selected") or {}
            parameters = payload.get("parameters") or {}
            hardware = next(
                (row for row in payload.get("comparisons", []) if row.get("source") == "hardware"),
                {},
            )
            task_ids = hardware.get("task_ids") or []
            rows.append(
                {
                    "run_id": payload.get("run_id", path.stem),
                    "time": payload.get("created_at", ""),
                    "seed": parameters.get("seed"),
                    "customers": parameters.get("num_customers"),
                    "vehicles": parameters.get("num_vehicles"),
                    "mode": parameters.get("mode"),
                    "source": selected.get("source"),
                    "backend": parameters.get("backend"),
                    "task_id": ", ".join(task_ids),
                    "shots": parameters.get("shots"),
                    "initial_distance": payload.get("initial", {}).get("distance"),
                    "final_distance": selected.get("final_distance"),
                    "improvement_pct": selected.get("improvement_pct"),
                    "status": selected.get("status"),
                }
            )
        return rows
