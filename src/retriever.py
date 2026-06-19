"""
Resolution query interface over indexed conversation history.
Phase 1: grep/substring match.
Phase 2 (TODO): semantic retrieval via embeddings.
"""
import json
from pathlib import Path

_STOP_WORDS = {
    "a","an","the","is","it","in","of","to","for","and","or","we","i","you",
    "was","were","are","be","been","do","did","does","use","used","uses",
    "should","would","could","can","will","that","this","on","at","by","with",
    "have","has","had","not","but","so","if","as","up","out","about","also",
    "all","any","our","my","your","their","there","then","when","what","how",
    "just","now","new","more","other","only","into","from","get","got",
}


class ConversationRetriever:
    def __init__(self, index_path: str):
        self.path = Path(index_path)

    def query(self, question: str, top_k: int = 5) -> list[dict]:
        """
        Resolve a binding-state question against the original history.
        Returns the most relevant turns.
        Phase 1: keyword overlap scoring.
        """
        if not self.path.exists():
            return []
        turns = [json.loads(l) for l in self.path.read_text().splitlines() if l.strip()]
        raw_kw = set(question.lower().split())
        keywords = raw_kw - _STOP_WORDS
        if not keywords:
            keywords = raw_kw  # fallback: use all tokens if everything is a stop word
        scored = []
        for turn in turns:
            content = turn["content"].lower()
            score = sum(1 for kw in keywords if kw in content)
            if score > 0:
                # ponytail: user turns get a small boost — binding facts come from users
                if turn.get("role") == "user":
                    score += 0.1
                scored.append((score, turn))
        scored.sort(key=lambda x: -x[0])
        return [t for _, t in scored[:top_k]]

    def query_tool(self, question: str) -> str:
        """Tool-call-friendly interface — returns formatted string."""
        results = self.query(question)
        if not results:
            return "No relevant history found."
        lines = []
        for r in results:
            lines.append(f"[{r['role']}] {r['content'][:400]}")
        return "\n---\n".join(lines)
