import re
from typing import List

# Common AI transition and hedging phrases (lexical fingerprint — distinct from
# semantic LLM judgment and structural stylometrics).
AI_PHRASES = [
    r"\bit is important to note\b",
    r"\bfurthermore\b",
    r"\bmoreover\b",
    r"\badditionally\b",
    r"\bin conclusion\b",
    r"\bin summary\b",
    r"\boverall\b",
    r"\bcomprehensive\b",
    r"\brobust\b",
    r"\bleverage\b",
    r"\butilize\b",
    r"\bparadigm\b",
    r"\blandscape\b",
    r"\bnuanced\b",
    r"\bdelve\b",
    r"\bit'?s worth noting\b",
    r"\bon the other hand\b",
    r"\bplays a (?:crucial|vital|key) role\b",
    r"\ba wide range of\b",
    r"\bin today'?s world\b",
]

SENTENCE_STARTERS = [
    "it is",
    "there are",
    "this is",
    "these are",
    "one of",
    "it can",
    "it has",
    "this can",
    "this has",
]


def _split_sentences(text: str) -> List[str]:
    parts = re.split(r"[.!?]+", text)
    return [part.strip().lower() for part in parts if part.strip()]


def _phrase_density_score(text: str) -> float:
    lowered = text.lower()
    hits = sum(1 for pattern in AI_PHRASES if re.search(pattern, lowered))
    words = max(len(re.findall(r"\b\w+\b", lowered)), 1)
    # Normalize: ~3+ hits per 100 words reads AI-like
    density = (hits / words) * 100
    if density >= 3.0:
        return 1.0
    if density <= 0.5:
        return 0.0
    return (density - 0.5) / (3.0 - 0.5)


def _starter_uniformity_score(text: str) -> float:
    sentences = _split_sentences(text)
    if len(sentences) < 2:
        return 0.5

    starter_hits = sum(
        1 for sentence in sentences if any(sentence.startswith(s) for s in SENTENCE_STARTERS)
    )
    ratio = starter_hits / len(sentences)
    if ratio >= 0.6:
        return 1.0
    if ratio <= 0.2:
        return 0.0
    return (ratio - 0.2) / (0.6 - 0.2)


def compute_phrase_pattern_score(text: str) -> float:
    """Return lexical AI-likelihood from 0.0 (human-like) to 1.0 (AI-like)."""
    if not text.strip():
        return 0.5

    density = _phrase_density_score(text)
    uniformity = _starter_uniformity_score(text)
    score = (0.65 * density) + (0.35 * uniformity)
    return round(max(0.0, min(1.0, score)), 3)
