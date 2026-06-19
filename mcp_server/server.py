#!/usr/bin/env python3
"""
Lossless Compaction MCP Server (raw stdio JSON-RPC — no SDK, Python 3.9+)

Exposes 4 tools to Claude Code:
  index_turn(role, content)    — record a conversation turn
  query_history(question)      — resolve a resolution question against history
  compact(objective?)          — trigger compaction, returns seed prompt
  get_seed_prompt()            — return current compacted state

Index lives at ~/.lossless-compaction/index.jsonl
State lives at ~/.lossless-compaction/state.json
"""
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Optional

# ── paths ──────────────────────────────────────────────────────────────────
BASE_DIR = Path(os.environ.get("LC_DATA_DIR", Path.home() / ".lossless-compaction"))
INDEX_PATH = BASE_DIR / "index.jsonl"
STATE_PATH = BASE_DIR / "state.json"
BASE_DIR.mkdir(parents=True, exist_ok=True)

# ── inline compactor / indexer / retriever (no relative imports needed) ────

def _index_append(role: str, content: str) -> None:
    record = {"turn_id": int(time.time() * 1000), "role": role,
              "content": content, "ts": time.time()}
    with INDEX_PATH.open("a") as f:
        f.write(json.dumps(record) + "\n")

def _index_load() -> list[dict]:
    if not INDEX_PATH.exists():
        return []
    return [json.loads(l) for l in INDEX_PATH.read_text().splitlines() if l.strip()]

_STOP_WORDS = {
    "a","an","the","is","it","in","of","to","for","and","or","we","i","you",
    "was","were","are","be","been","do","did","does","use","used","uses",
    "should","would","could","can","will","that","this","on","at","by","with",
    "have","has","had","not","but","so","if","as","up","out","about","also",
    "all","any","our","my","your","their","there","then","when","what","how",
    "just","now","new","more","other","only","into","from","get","got",
}

def _retrieve(question: str, top_k: int = 5) -> list[dict]:
    turns = _index_load()
    raw_kw = set(question.lower().split())
    keywords = raw_kw - _STOP_WORDS
    if not keywords:
        keywords = raw_kw  # fallback: use all tokens if everything is a stop word
    scored = []
    for turn in turns:
        score = sum(1 for kw in keywords if kw in turn["content"].lower())
        if score > 0:
            # ponytail: user turns get a small boost — binding facts come from users
            if turn.get("role") == "user":
                score += 0.1
            scored.append((score, turn))
    scored.sort(key=lambda x: -x[0])
    return [t for _, t in scored[:top_k]]

_REJECTION_PHRASES = (
    "rejected", "was rejected", "ruled out", "don't use", "do not use",
    "must not use", "never use", "avoid using", "not allowed", "prohibited",
)
_CONSTRAINT_PHRASES = (
    "constraint:", "requirement:", "must be", "always be", "required to",
    "is required", "has to be", "only allowed",
)
_PREFERENCE_PHRASES = (
    "prefer ", "preference:", "would rather", "like to use", "should use",
    "favor ", "we want to use",
)

def _classify(line: str) -> Optional[str]:
    lower = line.lower()
    if any(ph in lower for ph in _REJECTION_PHRASES):
        return "rejected"
    if any(ph in lower for ph in _CONSTRAINT_PHRASES):
        return "constraint"
    if any(ph in lower for ph in _PREFERENCE_PHRASES):
        return "preference"
    return None

def _load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {"objective": "", "plan": [], "constraints": [], "decisions": [],
            "rejected_approaches": [], "active_preferences": [], "source_index": ""}

def _save_state(state: dict) -> None:
    STATE_PATH.write_text(json.dumps(state, indent=2))

def _compact(objective: str = "") -> str:
    state = _load_state()
    turns = _index_load()
    seen_r = {x.lower().strip() for x in state["rejected_approaches"]}
    seen_c = {x.lower().strip() for x in state["constraints"]}
    seen_p = {x.lower().strip() for x in state["active_preferences"]}
    for turn in turns:
        for raw in turn["content"].splitlines():
            line = raw.strip()
            if not line:
                continue
            bucket = _classify(line)
            key = line.lower()
            if bucket == "rejected" and key not in seen_r:
                state["rejected_approaches"].append(line)
                seen_r.add(key)
            elif bucket == "constraint" and key not in seen_c:
                state["constraints"].append(line)
                seen_c.add(key)
            elif bucket == "preference" and key not in seen_p:
                state["active_preferences"].append(line)
                seen_p.add(key)
    if objective:
        state["objective"] = objective
    state["source_index"] = str(INDEX_PATH)
    _save_state(state)
    return _render_state(state)

def _render_state(state: dict) -> str:
    parts = []
    if state["objective"]:
        parts.append(f"## Objective\n{state['objective']}")
    if state["plan"]:
        parts.append("## Active Plan\n" + "\n".join(f"- {p}" for p in state["plan"]))
    if state["constraints"]:
        parts.append("## Constraints\n" + "\n".join(f"- {c}" for c in state["constraints"]))
    if state["rejected_approaches"]:
        parts.append("## Rejected Approaches\n" + "\n".join(f"- {r}" for r in state["rejected_approaches"]))
    if state["active_preferences"]:
        parts.append("## User Preferences\n" + "\n".join(f"- {p}" for p in state["active_preferences"]))
    if state["source_index"]:
        parts.append(f"> History indexed at: {state['source_index']}\n"
                     "> Call query_history(question) to recover context not carried here.")
    return "\n\n".join(parts) if parts else "(no compacted state yet)"

# ── tool definitions ────────────────────────────────────────────────────────

TOOLS = [
    {
        "name": "index_turn",
        "description": (
            "Record a conversation turn into the lossless compaction index. "
            "Call this for important turns — especially ones containing user preferences, "
            "constraints, rejected approaches, or key decisions."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "role": {"type": "string", "enum": ["user", "assistant"], "description": "Who said it"},
                "content": {"type": "string", "description": "The turn content"}
            },
            "required": ["role", "content"]
        }
    },
    {
        "name": "query_history",
        "description": (
            "Resolve a resolution question against the full conversation history. "
            "Use this when you are about to make a decision and are unsure whether "
            "the user already stated a preference, rejected an approach, or set a constraint. "
            "Examples: 'was this approach rejected earlier?', 'did the user specify a preference for X?'"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "The resolution question to answer from history"}
            },
            "required": ["question"]
        }
    },
    {
        "name": "compact",
        "description": (
            "Trigger compaction: scan the full index, extract binding facts "
            "(constraints, rejections, preferences) into a structured compacted state, "
            "and return the seed prompt for seeding a new context window."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "objective": {"type": "string", "description": "Current task objective (optional, updates state)"}
            }
        }
    },
    {
        "name": "get_seed_prompt",
        "description": "Return the current compacted state as a seed prompt (without re-scanning history).",
        "inputSchema": {"type": "object", "properties": {}}
    }
]

# ── JSON-RPC handler ────────────────────────────────────────────────────────

def handle_tool(name: str, args: dict) -> Any:
    if name == "index_turn":
        role = args.get("role", "user")
        content = args.get("content", "")
        _index_append(role, content)
        turns = _index_load()
        return f"Indexed. Total turns in history: {len(turns)}."

    if name == "query_history":
        question = args.get("question", "")
        results = _retrieve(question)
        if not results:
            return "No relevant history found."
        return "\n---\n".join(f"[{r['role']}] {r['content'][:600]}" for r in results)

    if name == "compact":
        objective = args.get("objective", "")
        seed = _compact(objective)
        return seed

    if name == "get_seed_prompt":
        return _render_state(_load_state())

    return f"Unknown tool: {name}"


def send(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def main() -> None:
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            req = json.loads(raw)
        except json.JSONDecodeError:
            continue

        rid = req.get("id")
        method = req.get("method", "")

        if method == "initialize":
            send({"jsonrpc": "2.0", "id": rid, "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "lossless-compaction", "version": "0.1.0"}
            }})

        elif method == "notifications/initialized":
            pass  # no response needed

        elif method == "tools/list":
            send({"jsonrpc": "2.0", "id": rid, "result": {"tools": TOOLS}})

        elif method == "tools/call":
            params = req.get("params", {})
            tool_name = params.get("name", "")
            tool_args = params.get("arguments", {})
            try:
                result = handle_tool(tool_name, tool_args)
                send({"jsonrpc": "2.0", "id": rid, "result": {
                    "content": [{"type": "text", "text": str(result)}]
                }})
            except Exception as e:
                send({"jsonrpc": "2.0", "id": rid, "result": {
                    "content": [{"type": "text", "text": f"Error: {e}"}],
                    "isError": True
                }})

        elif method == "ping":
            send({"jsonrpc": "2.0", "id": rid, "result": {}})

        else:
            if rid is not None:
                send({"jsonrpc": "2.0", "id": rid, "error": {
                    "code": -32601, "message": f"Method not found: {method}"
                }})


if __name__ == "__main__":
    main()
