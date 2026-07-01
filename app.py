import os
import uuid

from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from audit_log import append_entry, get_log, update_entry_for_appeal
from scoring import combine_scores, determine_attribution, generate_label
from signals.llm_classifier import classify_with_llm
from signals.stylometrics import compute_stylometric_score
from store import get_submission, init_db, save_submission, update_submission_appeal

load_dotenv()

app = Flask(__name__)
init_db()

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[],
    storage_uri="memory://",
)

MIN_APPEAL_REASONING_LENGTH = 10


@app.route("/")
def index():
    return jsonify(
        {
            "service": "Provenance Guard",
            "endpoints": {
                "POST /submit": "Submit text for attribution analysis",
                "POST /appeal": "Contest a classification",
                "GET /log": "View audit log entries",
            },
        }
    )


@app.route("/submit", methods=["POST"])
@limiter.limit("10 per minute;100 per day")
def submit():
    data = request.get_json(silent=True) or {}
    text = data.get("text", "").strip()
    creator_id = data.get("creator_id", "").strip()

    if not text or not creator_id:
        return jsonify({"error": "Both 'text' and 'creator_id' are required."}), 400

    content_id = str(uuid.uuid4())
    llm_score = classify_with_llm(text)
    stylometric_score = compute_stylometric_score(text)
    confidence = combine_scores(llm_score, stylometric_score)
    attribution = determine_attribution(confidence, llm_score, stylometric_score)
    label = generate_label(attribution)

    save_submission(
        content_id=content_id,
        creator_id=creator_id,
        text=text,
        attribution=attribution,
        confidence=confidence,
        label=label,
        llm_score=llm_score,
        stylometric_score=stylometric_score,
    )

    append_entry(
        {
            "content_id": content_id,
            "creator_id": creator_id,
            "text": text[:500],
            "attribution": attribution,
            "confidence": confidence,
            "llm_score": llm_score,
            "stylometric_score": stylometric_score,
            "label": label,
            "status": "classified",
        }
    )

    return jsonify(
        {
            "content_id": content_id,
            "attribution": attribution,
            "confidence": confidence,
            "label": label,
            "llm_score": llm_score,
            "stylometric_score": stylometric_score,
            "status": "classified",
        }
    )


@app.route("/appeal", methods=["POST"])
def appeal():
    data = request.get_json(silent=True) or {}
    content_id = data.get("content_id", "").strip()
    creator_reasoning = data.get("creator_reasoning", "").strip()

    if not content_id or not creator_reasoning:
        return jsonify(
            {"error": "Both 'content_id' and 'creator_reasoning' are required."}
        ), 400

    if len(creator_reasoning) < MIN_APPEAL_REASONING_LENGTH:
        return jsonify(
            {
                "error": (
                    f"'creator_reasoning' must be at least "
                    f"{MIN_APPEAL_REASONING_LENGTH} characters."
                )
            }
        ), 400

    submission = get_submission(content_id)
    if submission is None:
        return jsonify({"error": "Submission not found."}), 404

    if submission["status"] == "under_review":
        return jsonify({"error": "An appeal is already under review for this content."}), 409

    update_submission_appeal(content_id, creator_reasoning)
    log_entry = update_entry_for_appeal(content_id, creator_reasoning)
    if log_entry is None:
        append_entry(
            {
                "content_id": content_id,
                "creator_id": submission["creator_id"],
                "text": submission["text"][:500],
                "attribution": submission["attribution"],
                "confidence": submission["confidence"],
                "llm_score": submission["llm_score"],
                "stylometric_score": submission["stylometric_score"],
                "label": submission["label"],
                "status": "under_review",
                "appeal_reasoning": creator_reasoning,
            }
        )

    return jsonify(
        {
            "content_id": content_id,
            "status": "under_review",
            "message": "Your appeal has been received and is under review.",
        }
    )


@app.route("/log", methods=["GET"])
def log():
    return jsonify({"entries": get_log()})


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5001"))
    app.run(debug=True, port=port)
