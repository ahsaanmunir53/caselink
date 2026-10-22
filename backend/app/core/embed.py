"""A small local text embedder (no network, no cost) for 'similar reports' and duplicate checks.

Signed feature hashing of words, word pairs and character n-grams. Identifiers are replaced by
their kind first, so two reports are similar because of how they are written, not because they
share a number (sharing a number is already a strong link).
"""

import hashlib
import re

import numpy as np

_ID = re.compile(r"(?:\+92|0092|92|0)[\s-]?3\d{2}[\s-]?\d{3}[\s-]?\d{4}|PK\s?\d{2}(?:\s?[A-Z0-9]){20}|\S+@\S+|\d[\d,.]*", re.I)


def _features(text: str) -> list[str]:
    t = _ID.sub(" num ", text.lower())
    words = re.findall(r"\w+", t)
    feats = [f"w:{w}" for w in words] + [f"b:{a}_{b}" for a, b in zip(words, words[1:], strict=False)]
    padded = f" {' '.join(words)} "
    feats += [f"c4:{padded[i:i + 4]}" for i in range(max(0, len(padded) - 3))]
    return feats


def embed(text: str, dims: int = 512) -> np.ndarray:
    vec = np.zeros(dims, dtype=np.float32)
    for feat in _features(text):
        h = int.from_bytes(hashlib.blake2b(feat.encode(), digest_size=8).digest(), "big")
        vec[h % dims] += 1.0 if (h >> 63) & 1 else -1.0
    norm = float(np.linalg.norm(vec)) or 1.0
    return vec / norm


def similarity_matrix(texts: list[str]) -> np.ndarray:
    if not texts:
        return np.zeros((0, 0), dtype=np.float32)
    m = np.stack([embed(t) for t in texts])
    return m @ m.T
