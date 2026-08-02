from __future__ import annotations

import argparse
import json

from deepblock_submit_first_hardware import HARDWARE_DIR, submit_one


TARGETS = (
    ("seed002_pair1_B2_w8", 1),
    ("seed002_pair1_B2_w8", 2),
    ("seed003_pair1_B1_w8", 1),
    ("seed003_pair1_B1_w8", 2),
)


def _replicate_count(instance_id: str, depth: int) -> int:
    path = HARDWARE_DIR / "hardware_live_results.jsonl"
    if not path.exists():
        return 0
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return sum(
        str(row.get("instance_id")) == instance_id and int(row.get("p", -1)) == depth
        for row in rows
    )


def run(*, confirm: bool, target_replicates: int = 3, max_tasks: int = 8, timeout_sec: int = 600):
    if not confirm:
        raise PermissionError("Use --confirm-submit to authorize the fixed repeat batch.")
    if target_replicates != 3 or max_tasks > 8:
        raise ValueError("Closure repeat experiment is fixed at r1-r3 and at most 8 new tasks.")
    pending = []
    for instance_id, depth in TARGETS:
        for _ in range(max(0, target_replicates - _replicate_count(instance_id, depth))):
            pending.append((instance_id, depth))
    selected = pending[:max_tasks]
    print("REPEAT_PLAN " + json.dumps(selected, ensure_ascii=False), flush=True)
    results = []
    for index, (instance_id, depth) in enumerate(selected, 1):
        print(f"REPEAT_TASK {index}/{len(selected)} {instance_id} p={depth}", flush=True)
        result = submit_one(
            confirm=True,
            instance_id=instance_id,
            depth=depth,
            timeout_sec=timeout_sec,
            allow_repeat=True,
        )
        results.append(result)
        if result["status"] != "COMPLETED" or int(result["shots_received"]) != 1024:
            break
    summary = {"requested": len(selected), "completed": len(results), "results": results}
    (HARDWARE_DIR / "repeat_batch_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Submit the fixed r2/r3 Baihua repeat matrix")
    parser.add_argument("--confirm-submit", action="store_true")
    parser.add_argument("--max-tasks", type=int, default=8)
    parser.add_argument("--timeout-sec", type=int, default=600)
    args = parser.parse_args()
    print(json.dumps(run(confirm=args.confirm_submit, max_tasks=args.max_tasks,
                         timeout_sec=args.timeout_sec), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
