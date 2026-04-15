"""Side-by-side A/B comparison: legacy score_topics vs new run_sector_pipeline."""

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
from pipeline import SECTORS, run_sector_pipeline


def main() -> None:
    parser = argparse.ArgumentParser(
        description="A/B compare legacy score_topics vs new run_sector_pipeline",
    )
    parser.add_argument(
        "--mode",
        choices=["sector", "hot"],
        required=True,
        help="Mode to run: sector (or its alias hot)",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=5,
        help="Number of top results for legacy scorer (default: 5)",
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

    # ── New sector pipeline ──────────────────────────────────
    pipeline_result = run_sector_pipeline(all_items, dict(mode_config.pipeline_config))
    sectors_out = pipeline_result.get("sectors", {})

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

    # ── Print new pipeline — sectors ─────────────────────────
    print("\n=== NEW PIPELINE — SECTORS ===")
    for name, cfg in SECTORS:
        sector_items = sectors_out.get(name, [])
        label = cfg.get("label", name)
        print(f"\n[{name}] {label} ({len(sector_items)})")
        if not sector_items:
            print("  (no results)")
            continue
        for i, item in enumerate(sector_items, 1):
            final_score = item.get("final_score", 0)
            cross = item.get("cross_source_count", 1)
            url = item.get("url", "")
            title = item.get("title", "")
            print(f"{i}. {title} (final_score={final_score:.2f}, cross={cross})")
            print(f"   URL: {url}")

    # ── Overlap analysis ─────────────────────────────────────
    legacy_urls = set()
    for t in legacy_topics:
        for ref in t.get("references", []):
            url = ref.get("url", "")
            if url:
                legacy_urls.add(url)

    new_urls: set[str] = set()
    for sector_items in sectors_out.values():
        for item in sector_items:
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
        print()
        for u in list(only_legacy)[:3]:
            print(f"  {u}")
    else:
        print()
    print(f"URLs only in new (any sector): {len(only_new)}", end="")
    if only_new:
        print()
        for u in list(only_new)[:3]:
            print(f"  {u}")
    else:
        print()

    # ── Per-sector stats ─────────────────────────────────────
    print("\n=== PER-SECTOR STATS ===")
    for name, cfg in SECTORS:
        sector_items = sectors_out.get(name, [])
        n = len(sector_items)
        cap = cfg.get("count", 5)
        if n == 0:
            print(f"{name}: 0 items")
            continue
        avg = sum(it.get("final_score", 0.0) for it in sector_items) / n
        suffix = "  (under cap — sparse)" if n < cap else ""
        print(f"{name}: {n} items, avg final_score={avg:.2f}{suffix}")


if __name__ == "__main__":
    main()
