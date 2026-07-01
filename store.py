import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Optional

DB_PATH = os.path.join(os.path.dirname(__file__), "provenance.db")

MIN_ATTESTATION_LENGTH = 50
MIN_WRITING_SAMPLE_WORDS = 30


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS submissions (
                content_id TEXT PRIMARY KEY,
                creator_id TEXT NOT NULL,
                text TEXT NOT NULL,
                content_type TEXT NOT NULL DEFAULT 'text',
                attribution TEXT NOT NULL,
                confidence REAL NOT NULL,
                label TEXT NOT NULL,
                llm_score REAL,
                stylometric_score REAL,
                phrase_score REAL,
                status TEXT NOT NULL DEFAULT 'classified',
                appeal_reasoning TEXT,
                verified INTEGER NOT NULL DEFAULT 0,
                certificate_label TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS creators (
                creator_id TEXT PRIMARY KEY,
                verified INTEGER NOT NULL DEFAULT 0,
                attestation TEXT,
                writing_sample TEXT,
                verified_at TEXT
            )
            """
        )
        for column, definition in [
            ("appeal_reasoning", "TEXT"),
            ("content_type", "TEXT NOT NULL DEFAULT 'text'"),
            ("phrase_score", "REAL"),
            ("verified", "INTEGER NOT NULL DEFAULT 0"),
            ("certificate_label", "TEXT"),
        ]:
            try:
                conn.execute(f"ALTER TABLE submissions ADD COLUMN {column} {definition}")
            except sqlite3.OperationalError:
                pass


def save_submission(
    content_id: str,
    creator_id: str,
    text: str,
    attribution: str,
    confidence: float,
    label: str,
    llm_score: float,
    stylometric_score: Optional[float] = None,
    phrase_score: Optional[float] = None,
    content_type: str = "text",
    status: str = "classified",
    verified: bool = False,
    certificate_label: Optional[str] = None,
) -> None:
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO submissions (
                content_id, creator_id, text, content_type, attribution, confidence,
                label, llm_score, stylometric_score, phrase_score, status,
                verified, certificate_label
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                content_id,
                creator_id,
                text,
                content_type,
                attribution,
                confidence,
                label,
                llm_score,
                stylometric_score,
                phrase_score,
                status,
                int(verified),
                certificate_label,
            ),
        )


def get_submission(content_id: str) -> Optional[dict]:
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM submissions WHERE content_id = ?",
            (content_id,),
        ).fetchone()
    return dict(row) if row else None


def update_submission_appeal(content_id: str, appeal_reasoning: str) -> bool:
    """Set status to under_review and record appeal reasoning."""
    with get_db() as conn:
        cursor = conn.execute(
            """
            UPDATE submissions
            SET status = 'under_review', appeal_reasoning = ?
            WHERE content_id = ?
            """,
            (appeal_reasoning, content_id),
        )
    return cursor.rowcount > 0


def verify_creator(
    creator_id: str,
    attestation: str,
    writing_sample: str,
) -> Dict[str, Any]:
    """Record creator verification after attestation + writing sample."""
    verified_at = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO creators (creator_id, verified, attestation, writing_sample, verified_at)
            VALUES (?, 1, ?, ?, ?)
            ON CONFLICT(creator_id) DO UPDATE SET
                verified = 1,
                attestation = excluded.attestation,
                writing_sample = excluded.writing_sample,
                verified_at = excluded.verified_at
            """,
            (creator_id, attestation, writing_sample, verified_at),
        )
    return {
        "creator_id": creator_id,
        "verified": True,
        "verified_at": verified_at,
    }


def is_creator_verified(creator_id: str) -> bool:
    with get_db() as conn:
        row = conn.execute(
            "SELECT verified FROM creators WHERE creator_id = ?",
            (creator_id,),
        ).fetchone()
    return bool(row and row["verified"])
