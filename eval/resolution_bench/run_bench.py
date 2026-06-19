"""
Resolution Benchmark runner for the lossless-compaction project.

For each dataset record:
  1. Index the injected_text into a fresh per-record JSONL index.
  2. Run ConversationRetriever.query(probe) and take top-3 results.
  3. Check whether any expected_keyword appears in any of the top-3 result contents.

Reports per-category precision and overall precision.

Usage:
    python run_bench.py
    python run_bench.py --index-dir /tmp/bench_indices
    python run_bench.py --dataset path/to/dataset.jsonl --index-dir /tmp/bench_indices
"""

import argparse
import json
import sys
import os
from pathlib import Path
from collections import defaultdict

# ---------------------------------------------------------------------------
# Path bootstrap: resolve ../../src/retriever.py from this file's location.
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve().parent          # .../eval/resolution_bench/
_SRC  = _HERE.parent.parent / "src"             # .../src/
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC.parent))         # insert project root so that
                                                  # "from src.retriever import …"
                                                  # and "import retriever" both work

# Try project-root import first (matches how inject_binding.py does it),
# then fall back to direct module import.
try:
    from src.retriever import ConversationRetriever
    from src.indexer   import ConversationIndexer
except ModuleNotFoundError:
    sys.path.insert(0, str(_SRC))
    from retriever import ConversationRetriever   # type: ignore
    from indexer   import ConversationIndexer     # type: ignore

TOP_K = 3

# ---------------------------------------------------------------------------
# Noise corpus — 20 background turns indexed alongside each fact.
# Without noise, even a random retriever scores 100 % because the index
# contains only the fact being queried.
# ---------------------------------------------------------------------------

NOISE_TURNS = [
    ("assistant", "The migration is 60% complete. Next step is schema validation."),
    ("user", "Can you run the test suite and summarise failures?"),
    ("assistant", "All 42 tests passed. Coverage at 87%."),
    ("user", "Update the changelog for this sprint."),
    ("assistant", "Changelog updated with 3 new entries."),
    ("user", "How should we handle the retry logic for this endpoint?"),
    ("assistant", "Exponential back-off with jitter, cap at 5 attempts."),
    ("user", "Check the CI pipeline logs."),
    ("assistant", "Pipeline green. Last run: 2 min 14 sec."),
    ("user", "Should we bump the minor version before shipping?"),
    ("assistant", "Yes — feature-complete, no breaking changes."),
    ("user", "What is left before we can ship?"),
    ("assistant", "Docs and one integration test. Both in progress."),
    ("user", "Confirm the load-test baseline numbers."),
    ("assistant", "p50 = 12ms, p99 = 48ms at 1000 RPS."),
    ("user", "Is the feature flag cleanup done?"),
    ("assistant", "Three flags removed. One still active pending QA."),
    ("user", "Summarise today's standout decisions."),
    ("assistant", "Deferred caching, locked schema version, approved rollout."),
    ("user", "Let us proceed with the deployment plan as discussed."),
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_dataset(path: Path) -> list[dict]:
    records = []
    with path.open() as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                print(f"[WARN] Skipping line {lineno}: {exc}", file=sys.stderr)
    return records


def index_record(record: dict, index_path: Path) -> None:
    """Write the injected_text plus 20 noise turns into a fresh index."""
    # Remove any stale index so each record gets a clean slate.
    if index_path.exists():
        index_path.unlink()
    indexer = ConversationIndexer(str(index_path))
    # Inject the binding fact first
    indexer.append("user", record["injected_text"])
    # Add noise turns
    for role, content in NOISE_TURNS:
        indexer.append(role, content)


def evaluate_record(record: dict, index_path: Path) -> dict:
    """
    Returns a result dict with keys:
        id, category, probe, hit (bool), matched_keyword (str|None),
        paraphrase_hit (bool|None), top_results (list[str])
    """
    retriever = ConversationRetriever(str(index_path))
    hits = retriever.query(record["probe"], top_k=TOP_K)

    combined_text = " ".join(h["content"].lower() for h in hits)
    matched_kw = None
    for kw in record["expected_keywords"]:
        if kw.lower() in combined_text:
            matched_kw = kw
            break

    # Paraphrase probe — harder, different vocabulary from injected text.
    paraphrase_hit = None
    if "paraphrase_probe" in record:
        para_hits = retriever.query(record["paraphrase_probe"], top_k=TOP_K)
        para_text = " ".join(h["content"].lower() for h in para_hits)
        para_kw = next((kw for kw in record["expected_keywords"] if kw.lower() in para_text), None)
        paraphrase_hit = para_kw is not None

    return {
        "id": record["id"],
        "category": record["category"],
        "probe": record["probe"],
        "hit": matched_kw is not None,
        "matched_keyword": matched_kw,
        "paraphrase_hit": paraphrase_hit,
        "top_results": [h["content"][:120] for h in hits],
    }


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def print_results(results: list[dict]) -> None:
    print(f"\nLoaded {len(results)} records — each indexed with {len(NOISE_TURNS)} noise turns")

    # Per-record detail
    print("\n=== Per-record results ===")
    print(f"{'ID':<8} {'CAT':<12} {'HIT':<5} {'PARA':<5} {'KEYWORD':<20} PROBE")
    print("-" * 90)
    for r in results:
        hit_sym  = "PASS" if r["hit"] else "FAIL"
        para_sym = ("PASS" if r["paraphrase_hit"] else "FAIL") if r["paraphrase_hit"] is not None else "-"
        kw       = r["matched_keyword"] or "-"
        probe    = r["probe"][:50]
        print(f"{r['id']:<8} {r['category']:<12} {hit_sym:<5} {para_sym:<5} {kw:<20} {probe}")

    # Per-category precision
    print("\n=== Precision by category ===")
    by_cat: dict[str, list[bool]] = defaultdict(list)
    for r in results:
        by_cat[r["category"]].append(r["hit"])

    for cat in sorted(by_cat):
        hits  = sum(by_cat[cat])
        total = len(by_cat[cat])
        pct   = hits / total * 100
        bar   = "#" * hits + "." * (total - hits)
        print(f"  {cat:<16} {hits}/{total}  [{bar}]  {pct:.0f}%")

    # Overall — original probes
    total_hits  = sum(r["hit"] for r in results)
    total_all   = len(results)
    overall_pct = total_hits / total_all * 100 if total_all else 0.0
    print(f"\n=== Overall precision (original probes): {total_hits}/{total_all}  ({overall_pct:.1f}%) ===")

    # Paraphrase precision — records that have a paraphrase_probe
    para_results = [r for r in results if r["paraphrase_hit"] is not None]
    if para_results:
        para_hits = sum(r["paraphrase_hit"] for r in para_results)
        para_total = len(para_results)
        para_pct = para_hits / para_total * 100
        print(f"=== Paraphrase precision (harder probes): {para_hits}/{para_total}  ({para_pct:.1f}%) ===\n")
    else:
        print("=== Paraphrase precision: n/a (no paraphrase_probe fields in dataset) ===\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_bench(dataset_path: Path, index_dir: Path) -> list[dict]:
    index_dir.mkdir(parents=True, exist_ok=True)

    records = load_dataset(dataset_path)
    if not records:
        print("No records found in dataset.", file=sys.stderr)
        sys.exit(1)

    print(f"Loaded {len(records)} records from {dataset_path}")

    results = []
    for record in records:
        index_path = index_dir / f"{record['id']}.jsonl"
        index_record(record, index_path)
        result = evaluate_record(record, index_path)
        results.append(result)
        status = "PASS" if result["hit"] else "FAIL"
        print(f"  [{status}] {record['id']} — {record['probe'][:60]}")

    print_results(results)
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run the resolution benchmark against ConversationRetriever."
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path(__file__).resolve().parent / "dataset.jsonl",
        help="Path to dataset.jsonl (default: dataset.jsonl next to this script)",
    )
    parser.add_argument(
        "--index-dir",
        type=Path,
        default=Path("/tmp/bench_indices"),
        help="Directory where per-record JSONL indices are written (default: /tmp/bench_indices)",
    )
    args = parser.parse_args()

    run_bench(args.dataset, args.index_dir)
