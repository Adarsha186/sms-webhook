from contextlib import closing
from typing import Dict

from app.db import connect, find_claimant


def process_sms(db_path: str, classifier, tenant_id: str, form: Dict[str, str]) -> None:
    with closing(connect(db_path)) as conn:
        claimant = find_claimant(conn, tenant_id, form["From"])
        claimant_id = claimant["id"] if claimant else None

        # Stored as needing review until the classifier gives an answer.
        cursor = conn.execute(
            "INSERT INTO messages "
            "(tenant_id, message_sid, claimant_id, body, category, needs_review) "
            "VALUES (?, ?, ?, ?, 'other', 1) "
            "ON CONFLICT (tenant_id, message_sid) DO NOTHING",
            (tenant_id, form["MessageSid"], claimant_id, form["Body"]),
        )
        conn.commit()

        # The database picks one winner; every other delivery is a repeat.
        if cursor.rowcount == 0:
            return

        category = classifier.classify(form["Body"])

        conn.execute(
            "UPDATE messages SET category = ?, needs_review = 0 WHERE id = ?",
            (category, cursor.lastrowid),
        )
        conn.commit()
