#!/usr/bin/env python3
"""
lc — Lossless Compaction CLI
Usage:
  lc index <role> <content>            — record a turn (role: user|assistant)
  lc query <question>                  — resolve a resolution question from history
  lc compact [objective]               — scan history, extract binding facts, print seed prompt
  lc state                             — print current compacted state
  lc stats                             — print index stats
  lc list [--limit N] [--role R]       — print last N turns (default 20)
  lc delete <turn_id>                  — remove a turn by its turn_id, rewrite the file
  lc reset [--yes]                     — clear both index.jsonl and state.json
"""
import json, os, sys, tempfile, time
from pathlib import Path
from typing import Optional

BASE = Path(os.environ.get("LC_DATA_DIR", Path.home() / ".lossless-compaction"))
INDEX = BASE / "index.jsonl"
STATE = BASE / "state.json"
BASE.mkdir(parents=True, exist_ok=True)

_VALID_ROLES = {"user", "assistant", "system"}
_SCHEMA_VERSION = 1


def _validate_turn(role: str, content: str) -> None:
    if role not in _VALID_ROLES:
        raise ValueError(f"Invalid role {role!r}. Must be one of {_VALID_ROLES}.")
    if not content or not content.strip():
        raise ValueError("content must not be empty.")
    if len(content) > 1_000_000:
        raise ValueError("content exceeds 1MB limit.")


# ── index ──────────────────────────────────────────────────────────────────
def index_append(role: str, content: str) -> int:
    _validate_turn(role, content)
    with INDEX.open("a") as f:
        f.write(json.dumps({"schema_version": _SCHEMA_VERSION,
                            "turn_id": int(time.time()*1000), "role": role,
                            "content": content, "ts": time.time()}) + "\n")
    return sum(1 for _ in INDEX.read_text().splitlines() if _.strip())

def index_load() -> list[dict]:
    if not INDEX.exists(): return []
    turns = []
    for lineno, line in enumerate(INDEX.read_text().splitlines(), 1):
        line = line.strip()
        if not line: continue
        try:
            turns.append(json.loads(line))
        except json.JSONDecodeError as e:
            print(f"[warn] skipping malformed turn at line {lineno}: {e}", file=sys.stderr)
    return turns

def index_list(limit: int = 20, role: Optional[str] = None) -> list[dict]:
    turns = index_load()
    if role:
        turns = [t for t in turns if t.get("role") == role]
    return turns[-limit:]

def index_delete(turn_id: str) -> int:
    """Remove turn(s) matching turn_id. Returns count removed."""
    turns = index_load()
    before = len(turns)
    remaining = [t for t in turns if str(t.get("turn_id")) != str(turn_id)]
    removed = before - len(remaining)
    if removed:
        with INDEX.open("w") as f:
            for t in remaining:
                f.write(json.dumps(t) + "\n")
    return removed

def index_reset(confirm: bool = False) -> None:
    if not confirm:
        ans = input("This will delete all indexed turns and compacted state. Type 'yes' to confirm: ")
        if ans.strip().lower() != "yes":
            print("Aborted.")
            return
    if INDEX.exists():
        INDEX.unlink()
    if STATE.exists():
        STATE.unlink()
    print("Index and state cleared.")

# ── retriever ──────────────────────────────────────────────────────────────
_STOP_WORDS = {
    "a","an","the","is","it","in","of","to","for","and","or","we","i","you",
    "was","were","are","be","been","do","did","does","use","used","uses",
    "should","would","could","can","will","that","this","on","at","by","with",
    "have","has","had","not","but","so","if","as","up","out","about","also",
    "all","any","our","my","your","their","there","then","when","what","how",
    "just","now","new","more","other","only","into","from","get","got",
}

def retrieve(question: str, top_k: int = 5) -> list[dict]:
    raw_kw = set(question.lower().split())
    keywords = raw_kw - _STOP_WORDS
    if not keywords:
        keywords = raw_kw  # fallback: use all tokens if everything is a stop word
    scored = []
    for turn in index_load():
        score = sum(1 for kw in keywords if kw in turn["content"].lower())
        if score > 0:
            # ponytail: user turns get a small boost — binding facts come from users
            if turn.get("role") == "user":
                score += 0.1
            scored.append((score, turn))
    scored.sort(key=lambda x: -x[0])
    return [t for _, t in scored[:top_k]]

# ── compactor ─────────────────────────────────────────────────────────────
_REJ = ("rejected","was rejected","ruled out","don't use","do not use",
        "must not use","never use","avoid using","not allowed","prohibited")
_CON = ("constraint:","requirement:","must be","always be","required to",
        "is required","has to be","only allowed")
_PRE = ("prefer ","preference:","would rather","like to use","should use",
        "favor ","we want to use")

def _classify(line: str) -> Optional[str]:
    lo = line.lower()
    if any(p in lo for p in _REJ): return "rejected"
    if any(p in lo for p in _CON): return "constraint"
    if any(p in lo for p in _PRE): return "preference"
    return None

def load_state() -> dict:
    if STATE.exists(): return json.loads(STATE.read_text())
    return {"objective":"","plan":[],"constraints":[],"decisions":[],
            "rejected_approaches":[],"active_preferences":[],"source_index":""}

def save_state(s: dict):
    data = json.dumps(s, indent=2)
    fd, tmp = tempfile.mkstemp(dir=BASE, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(data)
        os.replace(tmp, STATE)
    except:
        try: os.unlink(tmp)
        except: pass
        raise

def compact(objective: str = "") -> str:
    s = load_state()
    seen_r = {x.lower().strip() for x in s["rejected_approaches"]}
    seen_c = {x.lower().strip() for x in s["constraints"]}
    seen_p = {x.lower().strip() for x in s["active_preferences"]}
    for turn in index_load():
        # ponytail: only user turns set binding constraints/preferences
        if turn.get("role") != "user":
            continue
        for raw in turn["content"].splitlines():
            line = raw.strip()
            # skip very short lines — likely code or incidental mentions
            if len(line) < 25:
                continue
            # skip obvious code/shell output lines
            lo = line.lower()
            if line.startswith(("#", "$", ">", "```")) or "://" in line:
                continue
            b, key = _classify(line), lo
            if b == "rejected" and key not in seen_r:
                s["rejected_approaches"].append(line); seen_r.add(key)
            elif b == "constraint" and key not in seen_c:
                s["constraints"].append(line); seen_c.add(key)
            elif b == "preference" and key not in seen_p:
                s["active_preferences"].append(line); seen_p.add(key)
    if objective: s["objective"] = objective
    s["source_index"] = str(INDEX)
    save_state(s)
    return render_state(s)

def render_state(s: dict) -> str:
    parts = []
    if s["objective"]: parts.append(f"## Objective\n{s['objective']}")
    if s["plan"]: parts.append("## Plan\n" + "\n".join(f"- {p}" for p in s["plan"]))
    if s["constraints"]: parts.append("## Constraints\n" + "\n".join(f"- {c}" for c in s["constraints"]))
    if s["rejected_approaches"]: parts.append("## Rejected Approaches\n" + "\n".join(f"- {r}" for r in s["rejected_approaches"]))
    if s["active_preferences"]: parts.append("## Preferences\n" + "\n".join(f"- {p}" for p in s["active_preferences"]))
    if s["source_index"]: parts.append(f"> Index: {s['source_index']}\n> Run `lc query <question>` to recover context not carried here.")
    return "\n\n".join(parts) if parts else "(no compacted state yet — run `lc compact`)"

# ── CLI ───────────────────────────────────────────────────────────────────
def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__); sys.exit(0)

    cmd, rest = args[0], args[1:]

    if cmd == "index":
        if len(rest) < 2:
            print("usage: lc index <role> <content>"); sys.exit(1)
        role, content = rest[0], " ".join(rest[1:])
        n = index_append(role, content)
        print(f"indexed [{role}]. total turns: {n}")

    elif cmd == "query":
        if not rest:
            print("usage: lc query <question>"); sys.exit(1)
        q = " ".join(rest)
        results = retrieve(q)
        if not results:
            print("no relevant history found.")
        else:
            print(f"top {len(results)} result(s) for: {q!r}\n")
            for i, r in enumerate(results, 1):
                print(f"[{i}] [{r['role']}] {r['content'][:500]}")
                if i < len(results): print()

    elif cmd == "compact":
        obj = " ".join(rest)
        print(compact(obj))

    elif cmd == "state":
        print(render_state(load_state()))

    elif cmd == "stats":
        turns = index_load()
        roles = {}
        for t in turns: roles[t["role"]] = roles.get(t["role"], 0) + 1
        s = load_state()
        print(f"index:    {len(turns)} turns  ({', '.join(f'{k}:{v}' for k,v in roles.items())})")
        print(f"index at: {INDEX}")
        print(f"rejected: {len(s['rejected_approaches'])}")
        print(f"constraints: {len(s['constraints'])}")
        print(f"preferences: {len(s['active_preferences'])}")

    elif cmd == "list":
        limit = 20
        role = None
        i = 0
        while i < len(rest):
            if rest[i] == "--limit" and i+1 < len(rest):
                limit = int(rest[i+1]); i += 2
            elif rest[i] == "--role" and i+1 < len(rest):
                role = rest[i+1]; i += 2
            else:
                i += 1
        turns = index_list(limit=limit, role=role)
        if not turns:
            print("(no turns indexed)")
        for t in turns:
            ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t.get("ts", 0)))
            preview = t["content"][:80].replace("\n", " ")
            print(f"[{t['turn_id']}] [{t['role']}] {ts}  {preview}")

    elif cmd == "delete":
        if not rest:
            print("usage: lc delete <turn_id>"); sys.exit(1)
        turn_id = rest[0]
        removed = index_delete(turn_id)
        if removed:
            print(f"deleted {removed} turn(s) with turn_id={turn_id}")
        else:
            print(f"no turn found with turn_id={turn_id}")

    elif cmd == "reset":
        force = "--yes" in rest
        index_reset(confirm=force)

    else:
        print(f"unknown command: {cmd}\n{__doc__}"); sys.exit(1)

if __name__ == "__main__":
    main()
