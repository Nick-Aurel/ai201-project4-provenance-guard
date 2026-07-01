import json
import os
import re

from groq import Groq

MODEL = "llama-3.3-70b-versatile"

SYSTEM_PROMPT = """You are an authorship classifier for a creative writing platform.
Assess whether the submitted text reads as human-written or AI-generated.

Return ONLY valid JSON with exactly these fields:
{
  "ai_likelihood": 0.0,
  "reasoning": "one sentence in double quotes"
}

Rules:
- ai_likelihood: number from 0.0 (confident human) to 1.0 (confident AI)
- reasoning: a single JSON string in double quotes
- lightly edited AI drafts should score around 0.5-0.7, not near 0.0
- no extra keys, no markdown, no commentary outside the JSON object"""


def _parse_score(raw: str) -> float:
    try:
        verdict = json.loads(raw)
        score = float(verdict["ai_likelihood"])
        return max(0.0, min(1.0, score))
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        match = re.search(r'"ai_likelihood"\s*:\s*([0-9.]+)', raw)
        if match:
            return max(0.0, min(1.0, float(match.group(1))))
        return 0.5


def classify_with_llm(text: str) -> float:
    """Return ai_likelihood score from 0.0 (human) to 1.0 (AI)."""
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is not set")

    client = Groq(api_key=api_key)
    try:
        response = client.chat.completions.create(
            model=MODEL,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            temperature=0.1,
        )
        raw = response.choices[0].message.content or ""
        return _parse_score(raw)
    except Exception as exc:
        failed = getattr(getattr(exc, "response", None), "json", lambda: {})()
        if isinstance(failed, dict):
            failed_gen = failed.get("error", {}).get("failed_generation", "")
            if failed_gen:
                return _parse_score(failed_gen)
        return 0.5
