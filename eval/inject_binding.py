"""
BSRR (Binding State Recovery Rate) test harness.

Injects N known binding facts early in a conversation,
compacts, then probes with resolution questions.
Score = % correctly recovered.
"""
import json
from pathlib import Path
from src.indexer import ConversationIndexer
from src.retriever import ConversationRetriever

BINDING_FACTS = [
    {"fact": "never use pandas, use polars instead", "probe": "should we use pandas?"},
    {"fact": "the user rejected the caching approach", "probe": "was caching rejected?"},
    {"fact": "this is local-only, never touch production", "probe": "is this safe for production?"},
    {"fact": "user prefers type hints in all functions", "probe": "does the user want type hints?"},
    {"fact": "approach A was already tried and failed with OOM error", "probe": "was approach A tried?"},
]


def run_bsrr_eval(index_path: str = "/tmp/bsrr_test.jsonl") -> dict:
    indexer = ConversationIndexer(index_path)
    retriever = ConversationRetriever(index_path)

    # Inject binding facts
    for item in BINDING_FACTS:
        indexer.append("user", item["fact"])
        indexer.append("assistant", "Understood, noted.")

    # Add noise turns
    for i in range(20):
        indexer.append("user", f"continue with step {i}")
        indexer.append("assistant", f"working on step {i}...")

    # Probe
    recovered = 0
    results = []
    for item in BINDING_FACTS:
        hits = retriever.query(item["probe"])
        found = any(item["fact"].lower()[:30] in h["content"].lower() for h in hits)
        recovered += int(found)
        results.append({"probe": item["probe"], "recovered": found})

    bsrr = recovered / len(BINDING_FACTS)
    print(f"BSRR: {bsrr:.0%} ({recovered}/{len(BINDING_FACTS)})")
    for r in results:
        print(f"  {'✓' if r['recovered'] else '✗'} {r['probe']}")
    return {"bsrr": bsrr, "results": results}


if __name__ == "__main__":
    run_bsrr_eval()
