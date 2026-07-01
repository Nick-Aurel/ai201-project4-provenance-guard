import os
import sqlite3
from contextlib import contextmanager
from typing import Optional

DB_PATH = os.path.join(os.path.dirname(__file__), "provenance.db")


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
                attribution TEXT NOT NULL,
                confidence REAL NOT NULL,
                label TEXT NOT NULL,
                llm_score REAL,
                stylometric_score REAL,
                status TEXT NOT NULL DEFAULT 'classified',
                appeal_reasoning TEXT
            )
            """
        )
        try:
            conn.execute("ALTER TABLE submissions ADD COLUMN appeal_reasoning TEXT")
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
    status: str = "classified",
) -> None:
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO submissions (
                content_id, creator_id, text, attribution, confidence,
                label, llm_score, stylometric_score, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                content_id,
                creator_id,
                text,
                attribution,
                confidence,
                label,
                llm_score,
                stylometric_score,
                status,
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
