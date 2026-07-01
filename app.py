import os
import uuid

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from analytics import compute_analytics
from audit_log import append_entry, get_log, update_entry_for_appeal
from pipeline import classify_submission
from store import (
    MIN_ATTESTATION_LENGTH,
    MIN_WRITING_SAMPLE_WORDS,
    get_submission,
    init_db,
    save_submission,
    update_submission_appeal,
    verify_creator,
)

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
SUPPORTED_CONTENT_TYPES = {"text", "image_description", "metadata"}


def _word_count(text: str) -> int:
    return len(text.split())


@app.route("/")
def index():
    return jsonify(
        {
            "service": "Provenance Guard",
            "endpoints": {
                "POST /submit": "Submit text, image description, or metadata for analysis",
                "POST /appeal": "Contest a classification",
                "POST /verify": "Complete creator verification for provenance certificate",
                "GET /log": "View audit log entries",
                "GET /analytics": "JSON analytics metrics",
                "GET /dashboard": "Analytics dashboard view",
                "GET /ui": "Simple submission interface",
            },
        }
    )


@app.route("/submit", methods=["POST"])
@limiter.limit("10 per minute;100 per day")
def submit():
    data = request.get_json(silent=True) or {}
    creator_id = data.get("creator_id", "").strip()
    content_type = data.get("content_type", "text").strip().lower() or "text"

    if not creator_id:
        return jsonify({"error": "'creator_id' is required."}), 400

    if content_type not in SUPPORTED_CONTENT_TYPES:
        return jsonify(
            {
                "error": (
                    f"Unsupported content_type '{content_type}'. "
                    f"Use one of: {', '.join(sorted(SUPPORTED_CONTENT_TYPES))}."
                )
            }
        ), 400

    result, error = classify_submission(content_type, data, creator_id)
    if error:
        return jsonify({"error": error}), 400

    content_id = str(uuid.uuid4())
    analysis_text = result["analysis_text"]

    save_submission(
        content_id=content_id,
        creator_id=creator_id,
        text=analysis_text[:2000],
        content_type=content_type,
        attribution=result["attribution"],
        confidence=result["confidence"],
        label=result["label"],
        llm_score=result["llm_score"],
        stylometric_score=result["stylometric_score"],
        phrase_score=result["phrase_score"],
        verified=result["verified"],
        certificate_label=result["certificate_label"],
    )

    append_entry(
        {
            "content_id": content_id,
            "creator_id": creator_id,
            "content_type": content_type,
            "text": analysis_text[:500],
            "attribution": result["attribution"],
            "confidence": result["confidence"],
            "llm_score": result["llm_score"],
            "stylometric_score": result["stylometric_score"],
            "phrase_score": result["phrase_score"],
            "label": result["label"],
            "verified": result["verified"],
            "certificate_label": result["certificate_label"],
            "status": "classified",
        }
    )

    return jsonify(
        {
            "content_id": content_id,
            "content_type": content_type,
            "attribution": result["attribution"],
            "confidence": result["confidence"],
            "label": result["label"],
            "llm_score": result["llm_score"],
            "stylometric_score": result["stylometric_score"],
            "phrase_score": result["phrase_score"],
            "verified": result["verified"],
            "certificate_label": result["certificate_label"],
            "status": "classified",
        }
    )


@app.route("/verify", methods=["POST"])
def verify():
    data = request.get_json(silent=True) or {}
    creator_id = data.get("creator_id", "").strip()
    attestation = data.get("attestation", "").strip()
    writing_sample = data.get("writing_sample", "").strip()

    if not creator_id or not attestation or not writing_sample:
        return jsonify(
            {"error": "'creator_id', 'attestation', and 'writing_sample' are required."}
        ), 400

    if len(attestation) < MIN_ATTESTATION_LENGTH:
        return jsonify(
            {
                "error": (
                    f"'attestation' must be at least {MIN_ATTESTATION_LENGTH} characters."
                )
            }
        ), 400

    if _word_count(writing_sample) < MIN_WRITING_SAMPLE_WORDS:
        return jsonify(
            {
                "error": (
                    f"'writing_sample' must be at least "
                    f"{MIN_WRITING_SAMPLE_WORDS} words."
                )
            }
        ), 400

    record = verify_creator(creator_id, attestation, writing_sample)
    return jsonify(
        {
            **record,
            "message": (
                "Verification complete. Future human-classified submissions will "
                "display the verified human creator badge."
            ),
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
                "content_type": submission.get("content_type", "text"),
                "text": submission["text"][:500],
                "attribution": submission["attribution"],
                "confidence": submission["confidence"],
                "llm_score": submission["llm_score"],
                "stylometric_score": submission["stylometric_score"],
                "phrase_score": submission.get("phrase_score"),
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


@app.route("/analytics", methods=["GET"])
def analytics():
    return jsonify(compute_analytics())


@app.route("/dashboard", methods=["GET"])
def dashboard():
    return render_template("dashboard.html")


@app.route("/ui", methods=["GET"])
def ui():
    return render_template("submit.html")


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5001"))
    app.run(debug=True, port=port)
