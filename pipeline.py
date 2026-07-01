from typing import Any, Dict, Optional, Tuple

from scoring import (
    combine_scores,
    determine_attribution,
    generate_label,
    generate_verified_label,
)
from signals.llm_classifier import classify_with_llm
from signals.phrase_patterns import compute_phrase_pattern_score
from signals.stylometrics import compute_stylometric_score
from store import is_creator_verified


def build_analysis_text(content_type: str, payload: Dict[str, Any]) -> str:
    """Normalize text, image descriptions, or metadata into analyzable text."""
    if content_type == "text":
        return payload.get("text", "").strip()

    if content_type == "image_description":
        return payload.get("image_description", "").strip()

    if content_type == "metadata":
        metadata = payload.get("metadata") or {}
        parts = [
            metadata.get("title", ""),
            metadata.get("caption", ""),
            metadata.get("description", ""),
            " ".join(metadata.get("tags", []) or []),
            metadata.get("alt_text", ""),
        ]
        return " ".join(part.strip() for part in parts if part and str(part).strip())

    return ""


def run_detection_pipeline(analysis_text: str) -> Dict[str, Any]:
    """Run the three-signal ensemble and return scores + attribution."""
    llm_score = classify_with_llm(analysis_text)
    stylometric_score = compute_stylometric_score(analysis_text)
    phrase_score = compute_phrase_pattern_score(analysis_text)
    confidence = combine_scores(llm_score, stylometric_score, phrase_score)
    attribution = determine_attribution(
        confidence, llm_score, stylometric_score, phrase_score
    )
    label = generate_label(attribution)

    return {
        "llm_score": llm_score,
        "stylometric_score": stylometric_score,
        "phrase_score": phrase_score,
        "confidence": confidence,
        "attribution": attribution,
        "label": label,
    }


def classify_submission(
    content_type: str,
    payload: Dict[str, Any],
    creator_id: str,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Classify content and attach certificate label when applicable."""
    analysis_text = build_analysis_text(content_type, payload)
    if not analysis_text:
        return None, f"No analyzable content found for content_type '{content_type}'."

    result = run_detection_pipeline(analysis_text)
    verified = is_creator_verified(creator_id)
    certificate_label = None

    if verified and result["attribution"] == "likely_human":
        certificate_label = generate_verified_label()
        result["label"] = f"{result['label']} {certificate_label}"

    result["content_type"] = content_type
    result["verified"] = verified
    result["certificate_label"] = certificate_label
    result["analysis_text"] = analysis_text
    return result, None
