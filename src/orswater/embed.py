"""Local embeddings via sentence-transformers. Nothing here leaves the machine.

Model: BAAI/bge-small-en-v1.5 -- 384 dimensions, ~130MB, MIT licensed, strong retrieval
scores for its size on MTEB, and first-class sentence-transformers support. Matches the
README's suggested default and needs no reranker to be useful.

Per the model card, short *queries* should be prefixed with an instruction to improve
retrieval; passages being indexed get no prefix.
"""

from __future__ import annotations

from functools import lru_cache

MODEL_NAME = "BAAI/bge-small-en-v1.5"
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


@lru_cache(maxsize=1)
def _model():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(MODEL_NAME)


def embed_passages(texts: list[str]) -> list[list[float]]:
    """Embed section text for storage. No instruction prefix -- passages are indexed as-is."""
    vectors = _model().encode(texts, normalize_embeddings=True)
    return [v.tolist() for v in vectors]


def embed_query(text: str) -> list[float]:
    """Embed a user question for retrieval."""
    vector = _model().encode(QUERY_PREFIX + text, normalize_embeddings=True)
    return vector.tolist()
