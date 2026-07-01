from audit_log import get_log


def compute_analytics() -> dict:
    """Aggregate audit-log metrics for the analytics dashboard."""
    entries = get_log(limit=500)
    total = len(entries)

    if total == 0:
        return {
            "total_submissions": 0,
            "attribution_breakdown": {
                "likely_ai": 0,
                "uncertain": 0,
                "likely_human": 0,
            },
            "ai_vs_human_ratio": {"ai_pct": 0, "human_pct": 0, "uncertain_pct": 0},
            "appeal_rate_pct": 0.0,
            "appeals_count": 0,
            "average_confidence": 0.0,
            "under_review_count": 0,
        }

    breakdown = {"likely_ai": 0, "uncertain": 0, "likely_human": 0}
    appeals = 0
    under_review = 0
    confidence_sum = 0.0

    for entry in entries:
        attribution = entry.get("attribution", "uncertain")
        if attribution in breakdown:
            breakdown[attribution] += 1

        if entry.get("appeal_reasoning") or entry.get("status") == "under_review":
            appeals += 1
        if entry.get("status") == "under_review":
            under_review += 1

        confidence_sum += float(entry.get("confidence", 0))

    ai_pct = round((breakdown["likely_ai"] / total) * 100, 1)
    human_pct = round((breakdown["likely_human"] / total) * 100, 1)
    uncertain_pct = round((breakdown["uncertain"] / total) * 100, 1)

    return {
        "total_submissions": total,
        "attribution_breakdown": breakdown,
        "ai_vs_human_ratio": {
            "ai_pct": ai_pct,
            "human_pct": human_pct,
            "uncertain_pct": uncertain_pct,
        },
        "appeal_rate_pct": round((appeals / total) * 100, 1),
        "appeals_count": appeals,
        "average_confidence": round(confidence_sum / total, 3),
        "under_review_count": under_review,
    }
