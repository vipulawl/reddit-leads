import os
import re
from functools import lru_cache

import numpy as np

EMBED_MODEL = "BAAI/bge-small-en-v1.5"


def item_text(item: dict) -> str:
    return f"{item['title']}\n{item['body']}"[:2000]


@lru_cache(maxsize=2048)
def _pattern(phrase: str) -> re.Pattern:
    return re.compile(r"\b" + re.escape(phrase) + r"\b", re.IGNORECASE)


def _matches(phrase: str, text: str) -> bool:
    return bool(_pattern(phrase).search(text)) or all(_pattern(w).search(text) for w in phrase.split())


def keyword_match(text: str, keywords: list[str], negative: list[str]) -> list[str]:
    if any(_pattern(n).search(text) for n in negative):
        return []
    return [k for k in keywords if _matches(k, text)]


@lru_cache(maxsize=1)
def _model():
    from fastembed import TextEmbedding
    return TextEmbedding(EMBED_MODEL, cache_dir=os.environ.get("FASTEMBED_CACHE_PATH"))


def embed(texts: list[str]) -> np.ndarray:
    if not texts:
        return np.zeros((0, 384), dtype=np.float32)
    vecs = np.array(list(_model().embed(texts)), dtype=np.float32)
    return vecs / np.linalg.norm(vecs, axis=1, keepdims=True)


def similarity(vec: np.ndarray, profile_vec: list[float]) -> float:
    p = np.asarray(profile_vec, dtype=np.float32)
    return float(vec @ (p / np.linalg.norm(p)))
