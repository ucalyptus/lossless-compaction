"""
Compaction-aware agent loop.

Wires together ConversationIndexer, ConversationRetriever, and CompactedState
to give a long-running agent transparent context compaction with lossless
retrieval fallback.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from .compactor import CompactedState
from .indexer import ConversationIndexer
from .retriever import ConversationRetriever

# Keywords for binding state classification.
# Rejection: explicit past-tense rejection or strong negation of a specific approach.
# Constraint: hard rules that must hold (not negations of a specific thing).
# Preference: softer directional choices.
# Note: sets are disjoint to avoid misclassification — "must not" is rejection,
# bare "must" is constraint, "prefer" is preference.
_REJECTION_PHRASES: tuple[str, ...] = (
    "rejected", "was rejected", "ruled out", "don't use", "do not use",
    "must not use", "never use", "avoid using", "not allowed", "prohibited",
)
_CONSTRAINT_PHRASES: tuple[str, ...] = (
    "constraint:", "requirement:", "must be", "always be", "required to",
    "is required", "has to be", "only allowed",
)
_PREFERENCE_PHRASES: tuple[str, ...] = (
    "prefer ", "preference:", "would rather", "like to use", "should use",
    "favor ", "we want to use",
)


def _classify_line(line: str) -> Optional[str]:
    """
    Return the bucket name for a line, or None if it is not binding.
    Uses phrase-level matching (not single-word) to reduce false positives.
    """
    lower = line.lower()
    if any(ph in lower for ph in _REJECTION_PHRASES):
        return "rejected"
    if any(ph in lower for ph in _CONSTRAINT_PHRASES):
        return "constraint"
    if any(ph in lower for ph in _PREFERENCE_PHRASES):
        return "preference"
    return None


class AgentLoop:
    """
    Compaction-aware agent loop.

    Tracks conversation turns via an indexer, decides when compaction is due,
    extracts binding facts heuristically, and exposes a retrieval interface so
    agents can recover context that was dropped from the live window.
    """

    def __init__(self, index_path: str, state_path: str) -> None:
        self.index_path = index_path
        self.state_path = state_path

        self.indexer = ConversationIndexer(index_path)
        self.retriever = ConversationRetriever(index_path)

        state_file = Path(state_path)
        if state_file.exists():
            self.state = CompactedState.load(state_path)
        else:
            state_file.parent.mkdir(parents=True, exist_ok=True)
            self.state = CompactedState()

    # ------------------------------------------------------------------
    # Core recording
    # ------------------------------------------------------------------

    def record_turn(self, role: str, content: str) -> None:
        """Append a single conversation turn to the index."""
        self.indexer.append(role, content)

    # ------------------------------------------------------------------
    # Compaction decision
    # ------------------------------------------------------------------

    def needs_compaction(self, max_turns: int = 50) -> bool:
        """Return True when the indexed turn count exceeds *max_turns*."""
        turns = self.indexer.load_all()
        return len(turns) > max_turns

    # ------------------------------------------------------------------
    # Heuristic compaction
    # ------------------------------------------------------------------

    def compact(self, objective: str = "") -> None:
        """
        Scan all indexed turns and extract binding facts into CompactedState.

        For each line in every turn:
        - Lines containing rejection keywords → rejected_approaches
        - Lines containing constraint keywords → constraints
        - Lines containing preference keywords → active_preferences

        Duplicates (case-insensitive, stripped) are suppressed.
        Sets objective and source_index, then persists state to disk.
        """
        turns = self.indexer.load_all()

        rejected: list[str] = list(self.state.rejected_approaches)
        constraints: list[str] = list(self.state.constraints)
        preferences: list[str] = list(self.state.active_preferences)

        # Track already-seen entries to avoid duplicates.
        seen_rejected: set[str] = {r.lower().strip() for r in rejected}
        seen_constraints: set[str] = {c.lower().strip() for c in constraints}
        seen_preferences: set[str] = {p.lower().strip() for p in preferences}

        for turn in turns:
            # ponytail: only user turns set binding constraints/preferences
            if turn.get("role") != "user":
                continue
            for raw_line in turn["content"].splitlines():
                line = raw_line.strip()
                if not line:
                    continue
                # skip very short lines — likely code or incidental mentions
                if len(line) < 25:
                    continue
                # skip obvious code/shell output lines
                if line.startswith(("#", "$", ">", "```")) or "://" in line:
                    continue
                bucket = _classify_line(line)
                key = line.lower()
                if bucket == "rejected" and key not in seen_rejected:
                    rejected.append(line)
                    seen_rejected.add(key)
                elif bucket == "constraint" and key not in seen_constraints:
                    constraints.append(line)
                    seen_constraints.add(key)
                elif bucket == "preference" and key not in seen_preferences:
                    preferences.append(line)
                    seen_preferences.add(key)

        if objective:
            self.state.objective = objective

        self.state.rejected_approaches = rejected
        self.state.constraints = constraints
        self.state.active_preferences = preferences
        self.state.source_index = self.index_path

        self.state.save(self.state_path)

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def resolve(self, question: str) -> str:
        """
        Recover binding context the agent may have lost from its live window.

        Delegates to the retriever and returns a formatted multi-turn excerpt.
        """
        return self.retriever.query_tool(question)

    # ------------------------------------------------------------------
    # Seed prompt
    # ------------------------------------------------------------------

    def seed_prompt(self) -> str:
        """Return the compacted state rendered as a system-prompt preamble."""
        return self.state.to_prompt()


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

def run_demo() -> None:
    """
    Small end-to-end demonstration:
      1. Record five turns that contain binding facts.
      2. Trigger compaction.
      3. Print the seed prompt.
      4. Resolve two questions against the original history.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        index_path = os.path.join(tmpdir, "conversation.jsonl")
        state_path = os.path.join(tmpdir, "state.json")

        loop = AgentLoop(index_path=index_path, state_path=state_path)

        turns = [
            ("user",  "We need to build a data pipeline for the reporting service."),
            ("assistant",
             "Understood. We should prefer DuckDB for in-process analytics. "
             "Note: we must not use pandas anywhere in this stack because of "
             "memory overhead on large datasets."),
            ("user",  "What about caching the query results in Redis?"),
            ("assistant",
             "Caching via Redis was rejected — it introduces an operational "
             "dependency we want to avoid. We will use file-based caching instead."),
            ("user",  "Okay. Constraint: all outputs must be parquet, never CSV."),
        ]

        for role, content in turns:
            loop.record_turn(role, content)

        print(f"Turns recorded: {len(loop.indexer.load_all())}")
        print(f"Needs compaction (max=3)? {loop.needs_compaction(max_turns=3)}")

        loop.compact(objective="Build a memory-efficient data pipeline for the reporting service.")

        print("\n" + "=" * 60)
        print("SEED PROMPT (compacted state):")
        print("=" * 60)
        print(loop.seed_prompt())

        print("\n" + "=" * 60)
        print("RESOLVE: 'was caching rejected?'")
        print("=" * 60)
        print(loop.resolve("was caching rejected?"))

        print("\n" + "=" * 60)
        print("RESOLVE: 'should we use pandas?'")
        print("=" * 60)
        print(loop.resolve("should we use pandas?"))


if __name__ == "__main__":
    run_demo()
