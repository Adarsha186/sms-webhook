from contextlib import closing
from typing import Dict, Optional

from app.classifier import safe_classify
from app.db import connect, find_claimant

STOP_WORDS = frozenset({"stop", "stopall", "unsubscribe"})

INSERT_MESSAGE = (
    "INSERT INTO messages "
    "(tenant_id, message_sid, claimant_id, body, category, needs_review) "
    "VALUES (?, ?, ?, ?, ?, ?) "
    "ON CONFLICT (tenant_id, message_sid) DO NOTHING"
)


def is_stop(body: str) -> bool:
    return body.strip().lower() in STOP_WORDS


def process_sms(db_path: str, classifier, tenant_id: str, form: Dict[str, str]) -> None:
    with closing(connect(db_path)) as conn:
        claimant = find_claimant(conn, tenant_id, form["From"])
        claimant_id = claimant["id"] if claimant else None

        if is_stop(form["Body"]):
            _store_stop(conn, tenant_id, claimant_id, form)
        else:
            _store_and_classify(conn, classifier, tenant_id, claimant_id, form)


def _store_stop(conn, tenant_id: str, claimant_id: Optional[str], form) -> None:
    # One transaction: if only the message saved, the retry would look like a
    # duplicate and the claimant would never be opted out.
    cursor = conn.execute(
        INSERT_MESSAGE,
        (tenant_id, form["MessageSid"], claimant_id, form["Body"], None, 0),
    )
    if cursor.rowcount and claimant_id is not None:
        conn.execute(
            "UPDATE claimants SET opted_out = 1 WHERE id = ? AND tenant_id = ?",
            (claimant_id, tenant_id),
        )
    conn.commit()


def _store_and_classify(
    conn, classifier, tenant_id: str, claimant_id: Optional[str], form
) -> None:
    # Stored as needing review until the classifier gives an answer.
    cursor = conn.execute(
        INSERT_MESSAGE,
        (tenant_id, form["MessageSid"], claimant_id, form["Body"], "other", 1),
    )
    conn.commit()

    # The database picks one winner; every other delivery is a repeat.
    if cursor.rowcount == 0:
        return

    category, needs_review = safe_classify(classifier, form["Body"])

    conn.execute(
        "UPDATE messages SET category = ?, needs_review = ? WHERE id = ?",
        (category, int(needs_review), cursor.lastrowid),
    )
    conn.commit()
