"""Side-by-side A/B comparison: legacy score_topics vs new run_pipeline."""

import argparse
import sys
import os

sys.stdout.reconfigure(encoding="utf-8")

# Ensure project root is on path when running as script
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from dotenv import load_dotenv

from main import collect_all
from modes import MODES
from scorer import score_topics
from pipeline import run_pipeline


def main() -> None:
    parser = argparse.ArgumentParser(
        description="A/B compare legacy score_topics vs new run_pipeline",
    )
    parser.add_argument(
        "--mode",
        choices=["hot", "general"],
        required=True,
        help="Mode to run: hot or general",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=5,
        help="Number of top results to show (default: 5)",
    )
    parser.add_argument(
        "--no-fetch",
        action="store_true",
        help="Skip fetch and use empty list (dry run)",
    )
    args = parser.parse_args()

    load_dotenv()

    mode_config = MODES[args.mode]
    top = args.top

    if args.no_fetch:
        all_items: list[dict] = []
    else:
        all_items = collect_all(mode_config.fetchers, quiet=True)

    if not all_items:
        print("no data collected")
        sys.exit(0)

    # ── Legacy ───────────────────────────────────────────────
    legacy_topics = score_topics(all_items, top_n=top, weights=mode_config.scorer_weights)

    # ── New pipeline ─────────────────────────────────────────
    pipeline_cfg = dict(mode_config.pipeline_config)
    pipeline_cfg["hot_count"] = top
    pipeline_cfg["evergreen_count"] = top
    pipeline_result = run_pipeline(all_items, pipeline_cfg)

    # ── Print legacy ─────────────────────────────────────────
    print(f"\n=== LEGACY (score_topics) — top {top} ===")
    if not legacy_topics:
        print("  (no results)")
    for i, t in enumerate(legacy_topics, 1):
        score = t.get("score", 0)
        refs = t.get("references", [])
        url = refs[0]["url"] if refs else ""
        print(f"{i}. {t['topic']} (score={score})")
        print(f"   URL: {url}")

    # ── Print new pipeline hot ────────────────────────────────
    hot_items = pipeline_result.get("hot", [])
    print("\n=== NEW PIPELINE — HOT ===")
    if not hot_items:
        print("  (no results)")
    for i, item in enumerate(hot_items, 1):
        final_score = item.get("final_score", 0)
        tier = item.get("matched_tier", "?")
        cross = item.get("cross_source_count", 1)
        url = item.get("url", "")
        title = item.get("title", "")
        print(f"{i}. {title} (final_score={final_score:.2f}, tier={tier}, cross={cross})")
        print(f"   URL: {url}")

    # ── Print new pipeline evergreen ─────────────────────────
    ever_items = pipeline_result.get("evergreen", [])
    print("\n=== NEW PIPELINE — EVERGREEN ===")
    if not ever_items:
        print("  (no results)")
    for i, item in enumerate(ever_items, 1):
        final_score = item.get("final_score", 0)
        tier = item.get("matched_tier", "?")
        cross = item.get("cross_source_count", 1)
        url = item.get("url", "")
        title = item.get("title", "")
        print(f"{i}. {title} (final_score={final_score:.2f}, tier={tier}, cross={cross})")
        print(f"   URL: {url}")

    # ── Overlap analysis ─────────────────────────────────────
    legacy_urls = set()
    for t in legacy_topics:
        for ref in t.get("references", []):
            legacy_urls.add(ref["url"])

    new_urls = set()
    for item in hot_items + ever_items:
        url = item.get("url", "")
        if url:
            new_urls.add(url)

    both = legacy_urls & new_urls
    only_legacy = legacy_urls - new_urls
    only_new = new_urls - legacy_urls

    print("\n=== OVERLAP ANALYSIS ===")
    print(f"URLs in both: {len(both)}")
    print(f"URLs only in legacy: {len(only_legacy)}", end="")
    if only_legacy:
        sample = list(only_legacy)[:3]
        print()
        for u in sample:
            print(f"  {u}")
    else:
        print()
    print(f"URLs only in new: {len(only_new)}", end="")
    if only_new:
        sample = list(only_new)[:3]
        print()
        for u in sample:
            print(f"  {u}")
    else:
        print()


if __name__ == "__main__":
    main()
