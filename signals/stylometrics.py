import re
import string
from typing import List

PUNCTUATION = set(string.punctuation)

LLM_WEIGHT = 0.6
STYLO_WEIGHT = 0.4
SHORT_TEXT_WORD_LIMIT = 30


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _interpolate_low_is_ai(value: float, ai_threshold: float, human_threshold: float) -> float:
    """Map a metric where lower values look more AI-like (score → 1.0)."""
    if value <= ai_threshold:
        return 1.0
    if value >= human_threshold:
        return 0.0
    return 1.0 - ((value - ai_threshold) / (human_threshold - ai_threshold))


def _split_sentences(text: str) -> List[str]:
    parts = re.split(r"[.!?]+", text)
    return [part.strip() for part in parts if part.strip()]


def _word_count(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text.lower()))


def _variance_score(text: str) -> float:
    sentences = _split_sentences(text)
    if len(sentences) < 2:
        return 0.5

    lengths = [len(sentence.split()) for sentence in sentences]
    mean = sum(lengths) / len(lengths)
    variance = sum((length - mean) ** 2 for length in lengths) / len(lengths)
    std_dev = variance**0.5
    return _interpolate_low_is_ai(std_dev, ai_threshold=4.0, human_threshold=10.0)


def _ttr_score(text: str) -> float:
    words = re.findall(r"\b\w+\b", text.lower())
    if not words:
        return 0.5

    ttr = len(set(words)) / len(words)
    return _interpolate_low_is_ai(ttr, ai_threshold=0.45, human_threshold=0.70)


def _punctuation_score(text: str) -> float:
    if not text:
        return 0.5

    punct_count = sum(1 for char in text if char in PUNCTUATION)
    density = punct_count / len(text)
    return _interpolate_low_is_ai(density, ai_threshold=0.02, human_threshold=0.06)


def compute_stylometric_score(text: str) -> float:
    """Return structural AI-likelihood from 0.0 (human-like) to 1.0 (AI-like)."""
    if _word_count(text) < SHORT_TEXT_WORD_LIMIT:
        return 0.5

    variance_component = _variance_score(text)
    ttr_component = _ttr_score(text)
    punct_component = _punctuation_score(text)

    score = (
        (0.40 * variance_component)
        + (0.35 * ttr_component)
        + (0.25 * punct_component)
    )
    return round(_clamp(score), 3)
