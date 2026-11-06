"""Search over the help articles in data/help-docs.

Each article is split into sections at its "## " headings, and sections are ranked with BM25
(keyword matching that favours rare words and short sections). Step 6 adds embedding search
with Ollama; this keyword search stays as the fallback when Ollama is not running.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

_WORD = re.compile(r"[a-z0-9]+")
# Very common words that carry no meaning for search.
_STOP_WORDS = frozenset(
    {
        "a", "an", "and", "are", "as", "at", "be", "by", "can", "do", "does", "for", "from", "how", "i",
        "in", "is", "it", "my", "of", "on", "or", "the", "this", "to", "what", "when", "where", "which",
        "who", "why", "will", "with", "you", "your",
    }
)  # fmt: skip
_K1 = 1.5
_B = 0.75


def tokenize(text: str) -> list[str]:
    words = (w for w in _WORD.findall(text.lower()) if w not in _STOP_WORDS)
    # Crude plural folding, so "records" matches "record".
    return [w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w for w in words]


@dataclass(frozen=True)
class Section:
    title: str
    source: str
    text: str


@dataclass(frozen=True)
class SearchResult:
    title: str
    source: str
    text: str
    score: float


def split_sections(source: str, markdown: str) -> list[Section]:
    doc_title = source
    sections: list[Section] = []
    heading: str | None = None
    lines: list[str] = []

    def flush() -> None:
        body = "\n".join(lines).strip()
        if body:
            title = f"{doc_title} > {heading}" if heading else doc_title
            sections.append(Section(title=title, source=source, text=body))

    for line in markdown.splitlines():
        if line.startswith("# "):
            doc_title = line[2:].strip()
        elif line.startswith("## "):
            flush()
            heading, lines = line[3:].strip(), []
        else:
            lines.append(line)
    flush()
    return sections


class HelpDocs:
    def __init__(self, sections: list[Section]) -> None:
        self.sections = sections
        self._tokens = [Counter(tokenize(f"{s.title} {s.text}")) for s in sections]
        self._lengths = [sum(t.values()) for t in self._tokens]
        self._avg_length = (sum(self._lengths) / len(self._lengths)) if self._lengths else 0.0
        doc_freq: Counter[str] = Counter()
        for tokens in self._tokens:
            doc_freq.update(tokens.keys())
        n = len(sections)
        self._idf = {term: math.log(1 + (n - df + 0.5) / (df + 0.5)) for term, df in doc_freq.items()}

    @staticmethod
    @lru_cache(maxsize=4)
    def load(docs_dir: Path) -> HelpDocs:
        sections: list[Section] = []
        for path in sorted(docs_dir.glob("*.md")):
            sections += split_sections(path.name, path.read_text(encoding="utf-8"))
        return HelpDocs(sections)

    def search(self, query: str, limit: int = 3) -> list[SearchResult]:
        terms = set(tokenize(query))
        scored: list[tuple[float, int]] = []
        for index, tokens in enumerate(self._tokens):
            score = 0.0
            for term in terms:
                tf = tokens.get(term, 0)
                if tf:
                    norm = _K1 * (1 - _B + _B * self._lengths[index] / self._avg_length)
                    score += self._idf[term] * tf * (_K1 + 1) / (tf + norm)
            if score > 0:
                scored.append((score, index))
        scored.sort(key=lambda pair: (-pair[0], pair[1]))
        return [
            SearchResult(
                title=self.sections[i].title,
                source=self.sections[i].source,
                text=self.sections[i].text,
                score=round(s, 3),
            )
            for s, i in scored[:limit]
        ]
