"""
Produces a structured compacted state from a conversation.
Compacted state carries: objective, plan/todo, constraints, decisions.
It is intentionally lossy — the retrieval layer handles the rest.
"""
from dataclasses import dataclass, field, fields, asdict
from typing import Any
import json


@dataclass
class CompactedState:
    objective: str = ""
    plan: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    decisions: list[dict] = field(default_factory=list)
    rejected_approaches: list[str] = field(default_factory=list)
    active_preferences: list[str] = field(default_factory=list)
    # pointer back to the indexed conversation
    source_index: str = ""

    def to_prompt(self) -> str:
        parts = [f"## Objective\n{self.objective}\n"]
        if self.plan:
            parts.append("## Active Plan\n" + "\n".join(f"- {p}" for p in self.plan))
        if self.constraints:
            parts.append("## Constraints\n" + "\n".join(f"- {c}" for c in self.constraints))
        if self.decisions:
            parts.append("## Active Decisions\n" + "\n".join(
                f"- {d['decision']} (reason: {d.get('reason', '?')})" for d in self.decisions))
        if self.rejected_approaches:
            parts.append("## Rejected Approaches\n" + "\n".join(f"- {r}" for r in self.rejected_approaches))
        if self.active_preferences:
            parts.append("## User Preferences\n" + "\n".join(f"- {p}" for p in self.active_preferences))
        if self.source_index:
            parts.append(f"\n> Original conversation indexed at: {self.source_index}")
            parts.append("> Use `query_history(question)` to recover context not carried here.")
        return "\n\n".join(parts)

    def save(self, path: str):
        data = asdict(self)
        data["schema_version"] = 1
        with open(path, "w") as f:
            json.dump(data, f, indent=2)

    @classmethod
    def load(cls, path: str) -> "CompactedState":
        with open(path) as f:
            data = json.load(f)
        data.pop("schema_version", None)
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})
