"""
Indexes conversation turns to a JSONL file for retrieval.
Each turn: {turn_id, role, content, timestamp, metadata}.
"""
import json
import sys
import time
from pathlib import Path
from typing import Optional


class ConversationIndexer:
    def __init__(self, index_path: str):
        self.path = Path(index_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, role: str, content: str, metadata: Optional[dict] = None):
        record = {
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
                    turns.append(json.loads(line))
                except json.JSONDecodeError as e:
                    print(f"[warn] skipping malformed turn at line {lineno}: {e}", file=sys.stderr)
        return turns
