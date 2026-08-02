from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json

from deepblock_study import (
    OFFLINE_DIR,
    build_proxy,
    context_payload,
    ensure_directories,
    enumerate_context,
    make_contexts,
    summarize_space,
    write_csv,
    write_jsonl,
)


def run(seed_count: int = 30) -> dict[str, object]:
    ensure_directories()
    summaries: list[dict[str, object]] = []
    states: list[dict[str, object]] = []
    selected: list[dict[str, object]] = []
    errors: list[dict[str, object]] = []
    for seed in range(1, seed_count + 1):
        for width in (6, 8):
            try:
                contexts = make_contexts(seed, width=width, pair_limit=2, block_limit=3)
            except Exception as exc:
                errors.append({"seed": seed, "block_size": width, "error": f"{type(exc).__name__}: {exc}"})
                continue
            for context in contexts:
                proxy = build_proxy(context, "current_sparse", capacity_penalty=25.0)
                space = enumerate_context(context, proxy)
                summary = summarize_space(context, space)
                summaries.append(summary)
                for state, bitstring, distance, improvement, energy, feasible, repaired in zip(
                    space.states,
                    space.bitstrings,
                    space.distances,
                    space.improvements,
                    space.energies,
                    space.feasible_before,
                    space.repaired,
                ):
                    states.append(
                        {
                            "instance_id": context.instance_id,
                            "seed": seed,
                            "block_size": width,
                            "state": int(state),
                            "bitstring": bitstring,
                            "qubo_energy": float(energy),
                            "true_route_distance": float(distance),
                            "improvement": float(improvement),
                            "strict_improvement": bool(improvement > 1e-9),
                            "feasible_before_repair": bool(feasible),
                            "capacity_repaired": bool(repaired),
                        }
                    )
                if summary["single_bit_local_trap"]:
                    selected.append(context_payload(context, summary))
        print(f"offline seed {seed}/{seed_count}: blocks={len(summaries)}, traps={len(selected)}", flush=True)

    write_csv(OFFLINE_DIR / "block_summary.csv", summaries)
    write_jsonl(OFFLINE_DIR / "state_summary.jsonl", states)
    write_jsonl(OFFLINE_DIR / "selected_instances.jsonl", selected)
    metadata = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "seed_count": seed_count,
        "block_sizes": [6, 8],
        "vehicle_pairs_per_seed": 2,
        "blocks_per_pair": 3,
        "analyzed_blocks": len(summaries),
        "selected_local_traps": len(selected),
        "errors": errors,
        "claim_boundary": "筛选结果只证明所分析 DeepBlock 中的改善空间与局部陷阱。",
    }
    (OFFLINE_DIR / "run_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description="枚举并筛选 DeepBlock 局部困难实例")
    parser.add_argument("--seeds", type=int, default=30, help="独立 Seed 数，建议 30～50")
    args = parser.parse_args()
    if not 1 <= args.seeds <= 50:
        parser.error("--seeds 必须在 1～50 之间")
    print(json.dumps(run(args.seeds), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
