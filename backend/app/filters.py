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


SENTENCE_SPLIT = re.compile(r"(?<=[.!?\n])\s+")


def _matches(phrase: str, text: str) -> bool:
    if _pattern(phrase).search(text):
        return True
    words = phrase.split()
    return len(words) > 1 and any(all(_pattern(w).search(s) for w in words) for s in SENTENCE_SPLIT.split(text))


SWITCH_WORDS = [
    "alternative", "alternatives", "instead of", "replace", "replacement", "switch", "switching", "migrate",
    "moving away", "move away", "leaving", "ditch", "vs", "versus", "compared to", "better than", "cheaper than",
    "recommend", "hate", "frustrated", "fed up", "too expensive", "too complicated", "cancel", "competitor",
]


def competitor_match(text: str, competitors: list[str]) -> list[str]:
    hits = []
    for c in competitors:
        for sentence in SENTENCE_SPLIT.split(text):
            if _pattern(c).search(sentence) and any(_pattern(w).search(sentence) for w in SWITCH_WORDS):
                hits.append(f"{c.lower()} (switching)")
                break
    return hits


def keyword_match(text: str, keywords: list[str], negative: list[str], competitors: list[str] = ()) -> list[str]:
    if any(_pattern(n).search(text) for n in negative):
        return []
    competitor_names = {c.lower() for c in competitors}
    hits = [k for k in keywords if k not in competitor_names and _matches(k, text)]
    return hits + competitor_match(text, competitors)


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
