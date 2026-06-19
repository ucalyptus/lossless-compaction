"""
Indexes conversation turns to a JSONL file for retrieval.
Each turn: {turn_id, role, content, timestamp, metadata}.
"""
import json
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
        with self.path.open() as f:
            return [json.loads(line) for line in f if line.strip()]
