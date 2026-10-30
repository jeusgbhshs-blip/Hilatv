"""Character-bigram embedding. Cosine stays deterministic without an embedding API."""

from __future__ import annotations

import hashlib
import math

_DIM = 256
_LIMIT = 0.85


def embed(text: str) -> list[float]:
    chars = [char for char in text if not char.isspace()]
    vector = [0.0] * _DIM
    if not chars:
        return vector
    for index, char in enumerate(chars):
        vector[_bucket(char)] += 1.0
        if index + 1 < len(chars):
            vector[_bucket(char + chars[index + 1])] += 2.5
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]


def cosine(left: str, right: str) -> float:
    a = embed(left)
    b = embed(right)
    return sum(x * y for x, y in zip(a, b, strict=True))


def too_similar(texts: list[str], limit: float = _LIMIT) -> bool:
    for index, left in enumerate(texts):
        for right in texts[index + 1 :]:
            if cosine(left, right) >= limit:
                return True
    return False


def _bucket(token: str) -> int:
    digest = hashlib.sha256(token.encode("utf-8")).digest()
    return int.from_bytes(digest[:2], "big") % _DIM
