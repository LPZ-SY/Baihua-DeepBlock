from __future__ import annotations

import argparse
import json
from pathlib import Path

from deepblock_submit_first_hardware import HARDWARE_DIR, submit_one


def run_batch(
    *,
    confirm: bool,
    depths: tuple[int, ...],
    max_tasks: int,
    timeout_sec: int,
) -> dict[str, object]:
    if not confirm:
        raise PermissionError("Use --confirm-submit to authorize the guarded hardware batch.")
    manifest_path = HARDWARE_DIR / "hardware_submission_manifest.jsonl"
    manifest = [
        json.loads(line)
        for line in manifest_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    result_path = HARDWARE_DIR / "hardware_live_results.jsonl"
    completed = []
    if result_path.exists():
        completed = [
            json.loads(line)
            for line in result_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    completed_keys = {
        (str(row["instance_id"]), int(row["p"]))
        for row in completed
    }
    pending: list[tuple[str, int]] = []
    for row in manifest:
        key = (str(row["instance_id"]), int(row["p"]))
        if key[1] in depths and key not in completed_keys and key not in pending:
            pending.append(key)
    selected = pending[: max(0, int(max_tasks))]
    print(
        "BATCH_PLAN "
        + json.dumps(
            {
                "depths": list(depths),
                "pending": len(pending),
                "selected": len(selected),
                "tasks": [{"instance_id": instance_id, "p": depth} for instance_id, depth in selected],
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    results: list[dict[str, object]] = []
    for index, (instance_id, depth) in enumerate(selected, start=1):
        print(
            f"BATCH_TASK {index}/{len(selected)} instance_id={instance_id} p={depth}",
            flush=True,
        )
        result = submit_one(
            confirm=True,
            instance_id=instance_id,
            depth=depth,
            timeout_sec=timeout_sec,
        )
        results.append(result)
        if result["status"] != "COMPLETED" or int(result["shots_received"]) != 1024:
            print("BATCH_STOP non-completed task encountered", flush=True)
            break
    summary = {
        "requested": len(selected),
        "completed": sum(result["status"] == "COMPLETED" for result in results),
        "stopped_early": len(results) < len(selected),
        "results": results,
    }
    (HARDWARE_DIR / "latest_batch_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Submit a guarded batch from the frozen DeepBlock manifest")
    parser.add_argument("--confirm-submit", action="store_true")
    parser.add_argument("--depths", nargs="+", type=int, choices=(1, 2, 3), required=True)
    parser.add_argument("--max-tasks", type=int, required=True)
    parser.add_argument("--timeout-sec", type=int, default=600)
    args = parser.parse_args()
    summary = run_batch(
        confirm=args.confirm_submit,
        depths=tuple(dict.fromkeys(args.depths)),
        max_tasks=args.max_tasks,
        timeout_sec=args.timeout_sec,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
