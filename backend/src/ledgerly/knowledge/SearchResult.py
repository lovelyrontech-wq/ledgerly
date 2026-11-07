from dataclasses import dataclass


@dataclass(frozen=True)
class SearchResult:
    title: str
    source: str
    text: str
    score: float