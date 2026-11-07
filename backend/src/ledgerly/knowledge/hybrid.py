"""Hybrid help search: BM25 keywords + embedding similarity, merged with Reciprocal Rank Fusion.

Keywords find exact terms ("CSV", "rounding"); embeddings find the same meaning in other words
("revert the change I made by mistake" -> undo). RRF merges the two ranked lists without having
to compare their very different scores: each list gives a section weight / (60 + rank), and the
sums decide the order.

Keywords count half as much as embeddings by default. With equal weights, common words like
"price" or "change" let keyword matches outvote the right answer that only embeddings found
(see evals/datasets/help-search.json and the live test in tests/test_help_search.py).

The vectors live in memory (the help docs are small) and are computed on the first search.
If Ollama is down, search falls back to BM25 only and says so ("mode": "bm25").
"""
from __future__ import annotations

import asyncio
import logging
import math
from dataclasses import dataclass
from typing import Literal

from ledgerly.knowledge.embeddings import Embedder, EmbeddingUnavailable
from ledgerly.knowledge.help_docs import HelpDocs, SearchResult

logger = logging.getLogger(__name__)

RRF_K = 60  # the usual constant; larger = flatter, so lower ranks still count
CANDIDATES = 10  # sections taken from each list before fusing
# nomic-embed-text was trained with these prefixes; other models ignore them harmlessly.
DOCUMENT_PREFIX = "search_document: "
QUERY_PREFIX = "search_query: "

SearchMode = Literal["hybrid", "vector", "bm25"]


@dataclass(frozen=True)
class HelpSearchResponse:
    mode: SearchMode
    results: list[SearchResult]


def _normalize(vector: list[float]) -> list[float]:
    length = math.sqrt(sum(x * x for x in vector))
    return [x / length for x in vector] if length else vector


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def rrf(rankings: list[list[int]], weights: list[float] | None = None, k: int = RRF_K) -> list[tuple[int, float]]:
    """Weighted Reciprocal Rank Fusion of ranked lists of section indexes. Best first."""
    weights = weights or [1.0] * len(rankings)
    scores: dict[int, float] = {}
    for ranking, weight in zip(rankings, weights, strict=True):
        for rank, index in enumerate(ranking, start=1):
            scores[index] = scores.get(index, 0.0) + weight / (k + rank)
    return sorted(scores.items(), key=lambda pair: (-pair[1], pair[0]))


class HybridHelpSearch:
    def __init__(
        self, docs: HelpDocs, embedder: Embedder | None, mode: SearchMode = "hybrid", bm25_weight: float = 0.5
    ) -> None:
        self.docs = docs
        self._embedder = embedder if mode != "bm25" else None  # None = keyword search only
        self._mode = mode
        self._bm25_weight = bm25_weight
        self._vectors: list[list[float]] | None = None
        self._lock = asyncio.Lock()

    async def _section_vectors(self, embedder: Embedder) -> list[list[float]]:
        async with self._lock:
            if self._vectors is None:
                texts = [f"{DOCUMENT_PREFIX}{s.title}\n{s.text}" for s in self.docs.sections]
                self._vectors = [_normalize(v) for v in await embedder.embed(texts)]
            return self._vectors

    def _bm25_ranking(self, query: str) -> list[int]:
        index_of = {(s.source, s.title): i for i, s in enumerate(self.docs.sections)}
        return [index_of[(r.source, r.title)] for r in self.docs.search(query, limit=CANDIDATES)]

    async def _vector_ranking(self, embedder: Embedder, query: str) -> list[int]:
        vectors = await self._section_vectors(embedder)
        [query_vector] = await embedder.embed([f"{QUERY_PREFIX}{query}"])
        query_vector = _normalize(query_vector)
        similarity = sorted(((_dot(query_vector, v), i) for i, v in enumerate(vectors)), key=lambda p: (-p[0], p[1]))
        return [i for _, i in similarity[:CANDIDATES]]

    async def search(self, query: str, limit: int = 3) -> HelpSearchResponse:
        if self._embedder is None:
            return HelpSearchResponse("bm25", self.docs.search(query, limit))
        try:
            vector_ranking = await self._vector_ranking(self._embedder, query)
        except EmbeddingUnavailable as exc:
            logger.warning("Help search fell back to keywords only: %s", exc)
            return HelpSearchResponse("bm25", self.docs.search(query, limit))

        if self._mode == "vector":
            fused = rrf([vector_ranking])[:limit]
        else:
            fused = rrf([vector_ranking, self._bm25_ranking(query)], [1.0, self._bm25_weight])[:limit]
        results = [
            SearchResult(
                title=self.docs.sections[i].title,
                source=self.docs.sections[i].source,
                text=self.docs.sections[i].text,
                score=round(score, 4),
            )
            for i, score in fused
        ]
        return HelpSearchResponse(self._mode, results)