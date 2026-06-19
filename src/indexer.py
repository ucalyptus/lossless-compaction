"""
Indexes conversation turns to a JSONL file for retrieval.
Each turn: {schema_version, turn_id, role, content, ts, metadata}.
"""
import json
import sys
import time
from pathlib import Path
from typing import Optional

_VALID_ROLES = {"user", "assistant", "system"}
_SCHEMA_VERSION = 1


def _validate_turn(role: str, content: str) -> None:
    if role not in _VALID_ROLES:
        raise ValueError(f"Invalid role {role!r}. Must be one of {_VALID_ROLES}.")
    if not content or not content.strip():
        raise ValueError("content must not be empty.")
    if len(content) > 1_000_000:
        raise ValueError("content exceeds 1MB limit.")


def _migrate_record(r: dict) -> dict:
    r.setdefault("schema_version", 1)
    r.setdefault("metadata", {})
    return r


class ConversationIndexer:
    def __init__(self, index_path: str):
        self.path = Path(index_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, role: str, content: str, metadata: Optional[dict] = None):
        _validate_turn(role, content)
        record = {
            "schema_version": _SCHEMA_VERSION,
            "turn_id": int(time.time() * 1000),
            "role": role,
            "content": content,
            "ts": time.time(),
            "metadata": metadata or {}
        }
        with self.path.open("a") as f:
            f.write(json.dumps(record) + "\n")

    def load_all(self) -> list[dict]:
        if not self.path.exists():
            return []
        turns = []
        with self.path.open() as f:
            for lineno, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    turns.append(_migrate_record(json.loads(line)))
                except json.JSONDecodeError as e:
                    print(f"[warn] skipping malformed turn at line {lineno}: {e}", file=sys.stderr)
        return turns
