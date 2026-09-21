"""Local text embeddings with an optional pretrained backend.

The default path is dependency-free and never downloads a model. If the optional
sentence-transformers package is installed, a pretrained model can be enabled
explicitly; the provider falls back to the deterministic local vectorizer when the
optional backend or model is unavailable.
"""
from __future__ import annotations

import hashlib
import math
import os
import re
from functools import lru_cache
from typing import Any

_TOKEN_RE = re.compile(r"[a-z0-9']+", re.I)
_DIMENSIONS = 384
_DEFAULT_ST_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


def _features(text: str) -> list[str]:
    lowered = text.lower()
    words = _TOKEN_RE.findall(lowered)
    features = [f"w:{word}" for word in words]
    for word in words:
        padded = f"^{word}$"
        for size in (3, 4, 5):
            features.extend(
                f"c:{padded[i:i + size]}"
                for i in range(max(0, len(padded) - size + 1))
            )
    return features


def _local_embed(text: str) -> list[float]:
    vector = [0.0] * _DIMENSIONS
    for feature in _features(text):
        digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
        index = int.from_bytes(digest[:4], "little") % _DIMENSIONS
        sign = 1.0 if digest[4] & 1 else -1.0
        vector[index] += sign
    norm = math.sqrt(sum(value * value for value in vector))
    if norm:
        vector = [value / norm for value in vector]
    return vector


def cosine(left: list[float], right: list[float]) -> float:
    if not left or not right:
        return 0.0
    return max(-1.0, min(1.0, sum(a * b for a, b in zip(left, right))))


def lexical_overlap(query: str, text: str) -> float:
    query_words = set(_TOKEN_RE.findall(query.lower()))
    text_words = set(_TOKEN_RE.findall(text.lower()))
    if not query_words:
        return 0.0
    return len(query_words & text_words) / len(query_words)


def _requested_provider(provider: str | None = None) -> str:
    value = (provider or os.getenv("STORYLAB_EMBEDDING_PROVIDER", "local")).strip().lower()
    aliases = {"default": "local", "fallback": "local", "st": "sentence-transformers"}
    return aliases.get(value, value)


@lru_cache(maxsize=2)
def _sentence_transformer_model(model_name: str, local_only: bool) -> Any:
    from sentence_transformers import SentenceTransformer

    kwargs = {}
    if local_only:
        kwargs["local_files_only"] = True
    return SentenceTransformer(model_name, **kwargs)


def _sentence_transformer_embed(
    texts: list[str],
    model_name: str,
    *,
    local_only: bool,
) -> list[list[float]]:
    model = _sentence_transformer_model(model_name, local_only)
    vectors = model.encode(texts, normalize_embeddings=True, convert_to_numpy=False)
    return [list(map(float, vector)) for vector in vectors]


def embedding_provider(provider: str | None = None) -> str:
    """Return the provider that will actually be used for this process.

    auto uses a locally cached pretrained model when one is available, but never
    downloads one. Explicit sentence-transformers may download the configured model
    on first use.
    """
    requested = _requested_provider(provider)
    if requested == "local":
        return "local-vector"
    if requested not in {"auto", "sentence-transformers"}:
        raise ValueError("Embedding provider must be local, auto, or sentence-transformers.")

    model_name = os.getenv("STORYLAB_EMBEDDING_MODEL", _DEFAULT_ST_MODEL)
    try:
        _sentence_transformer_model(model_name, requested == "auto")
    except Exception:
        return "local-vector"
    return "sentence-transformers"


def embed(text: str, provider: str | None = None) -> list[float]:
    """Embed one text using the configured provider, with safe local fallback."""
    actual = embedding_provider(provider)
    if actual == "sentence-transformers":
        model_name = os.getenv("STORYLAB_EMBEDDING_MODEL", _DEFAULT_ST_MODEL)
        return _sentence_transformer_embed([text], model_name, local_only=False)[0]
    return _local_embed(text)


def rank_texts(
    query: str,
    texts: list[str],
    mode: str = "hybrid",
    provider: str | None = None,
) -> list[tuple[int, float, float, float, str]]:
    """Return (index, score, embedding_score, lexical_score, method), strongest first."""
    actual_provider = embedding_provider(provider)
    if actual_provider == "sentence-transformers":
        model_name = os.getenv("STORYLAB_EMBEDDING_MODEL", _DEFAULT_ST_MODEL)
        vectors = _sentence_transformer_embed([query, *texts], model_name, local_only=False)
        query_vector = vectors[0]
        text_vectors = vectors[1:]
    else:
        query_vector = _local_embed(query)
        text_vectors = [_local_embed(text) for text in texts]

    ranked = []
    for index, text in enumerate(texts):
        embedding_score = max(0.0, (cosine(query_vector, text_vectors[index]) + 1.0) / 2.0)
        lexical_score = lexical_overlap(query, text)
        if mode == "embedding":
            score = embedding_score
            method = actual_provider
        elif mode == "lexical":
            score = lexical_score
            method = "lexical"
        else:
            score = 0.7 * embedding_score + 0.3 * lexical_score
            method = f"hybrid-{actual_provider}"
        ranked.append((index, score, embedding_score, lexical_score, method))
    ranked.sort(key=lambda row: row[1], reverse=True)
    return ranked
