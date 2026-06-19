# lossless-compaction

Retrieval-augmented context compaction for long-running agents.

## The Problem

Context compaction (summarizing a conversation to fit in window) is a lossy operation. The compacted state drops *binding state* — user preferences, rejected approaches, active constraints, and the rationale behind decisions. These look unimportant until they suddenly matter, at which point the agent either asks the user to repeat themselves or silently violates a prior commitment.

The standard solution (better summaries, `/compact [instruction]`) still makes the same Markov assumption: the compacted state is the complete source of truth. It isn't.

## The Fix

Treat compaction as a two-layer system:

1. **Compacted state** — lossy, but intentional. Carries: current objective, active plan/todo, known constraints, active decisions. Small enough to seed a new context window.
2. **Retrieval layer** — the original conversation is indexed and queryable. When the compacted state is insufficient, the agent issues a resolution query against the history.

The compacted state does not pretend to be complete. The original history already exists. The missing piece is the ability to search it.

```
Continue from compacted state
    → Detect possible missing context
    → Query original history
    → Resolve the missing detail
    → Update compacted state
    → Continue
```

This turns compaction from a one-way compression step into a recoverable loop.

## Inspiration

- [@DSantra92 — "On Lossless Context Compaction"](https://x.com/dsantra92/status/2067766139011350942) (Jun 2026)
- AmpCode Neo: conversation threads as first-class context objects (closest existing implementation)
- Claude Code `/compact [instruction]`: user-directed but still lossy, no retrieval

## Evaluation Rubric

Five dimensions for measuring whether lossless compaction actually works:

| Metric | What it measures | How |
|--------|-----------------|-----|
| **Binding State Recovery Rate (BSRR)** | % of injected binding facts recoverable after compaction | Inject N known facts → compact → probe with resolution questions |
| **Redundant Re-ask Rate** | How often agent asks user to repeat pre-compaction info | Count re-asks per session; should trend → 0 with retrieval |
| **Contradiction Rate** | Agent takes approach explicitly rejected in original history | Binary per decision point |
| **Alignment Drift (multi-cycle)** | Deviation from original preferences after K compaction cycles | Compare decisions at cycle K vs preferences at cycle 1 |
| **Retrieval P/R** | Does search surface the right span for a resolution question | Precision, recall, MRR |

### Resolution questions the retrieval layer must answer

- Did the user already specify a preference for this?
- Was this approach rejected earlier?
- Which command failed, and why?
- Was there a constraint attached to this decision?
- Did the user say this was local-only, production-safe, draft-only, or temporary?

These are **resolution questions** — the agent recovering a specific thing the compacted state could not safely carry.

## Repo Structure

```
src/
  compactor.py        # produces compacted state from conversation
  indexer.py          # indexes conversation turns for retrieval
  retriever.py        # resolution query interface (grep → semantic)
  agent_loop.py       # compaction-aware agent loop
eval/
  inject_binding.py   # BSRR test harness
  measure_drift.py    # alignment drift over K cycles
  resolution_bench/   # resolution question benchmark dataset
```

## Status

Early scaffolding. Minimal viable version:
- Conversation indexer (JSONL per turn)
- Grep-based retriever exposed as a tool call
- Compactor that writes structured state (objective / plan / constraints / decisions)
- BSRR eval harness

No semantic retrieval yet — start with exact match, grow from there.
