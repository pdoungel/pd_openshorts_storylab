"""Lightweight local text embeddings used when no external embedding service is available.

This is deliberately dependency-free. It is a deterministic feature embedding over
word and character n-grams, useful for local semantic-ish retrieval and as a safe
fallback until an optional pretrained embedding provider is configured.
"""
from __future__ import annotations

import hashlib
import math
import re

_TOKEN_RE = re.compile(r"[a-z0-9']+", re.I)
_DIMENSIONS = 384


def _features(text: str) -> list[str]:
    lowered = text.lower()
    words = _TOKEN_RE.findall(lowered)
    features = [f"w:{word}" for word in words]
    for word in words:
        padded = f"^{word}$"
        for size in (3, 4, 5):
            features.extend(f"c:{padded[i:i + size]}" for i in range(max(0, len(padded) - size + 1)))
    return features


def embed(text: str) -> list[float]:
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


def rank_texts(query: str, texts: list[str], mode: str = "hybrid") -> list[tuple[int, float, float, float, str]]:
    """Return (index, score, embedding_score, lexical_score, method), strongest first."""
    query_vector = embed(query)
    ranked = []
    for index, text in enumerate(texts):
        embedding_score = max(0.0, (cosine(query_vector, embed(text)) + 1.0) / 2.0)
        lexical_score = lexical_overlap(query, text)
        if mode == "embedding":
            score = embedding_score
            method = "local-vector"
        elif mode == "lexical":
            score = lexical_score
            method = "lexical"
        else:
            score = 0.7 * embedding_score + 0.3 * lexical_score
            method = "hybrid-local-vector"
        ranked.append((index, score, embedding_score, lexical_score, method))
    ranked.sort(key=lambda row: row[1], reverse=True)
    return ranked
