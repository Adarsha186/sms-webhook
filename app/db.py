import sqlite3
from contextlib import closing
from typing import List, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS tenants (
    id TEXT PRIMARY KEY,
    number TEXT UNIQUE NOT NULL,
    secret TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS claimants (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    phone TEXT NOT NULL,
    opted_out INTEGER NOT NULL DEFAULT 0,
    UNIQUE (tenant_id, phone)
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    message_sid TEXT NOT NULL,
    claimant_id TEXT,
    body TEXT NOT NULL,
    category TEXT,
    needs_review INTEGER NOT NULL,
    UNIQUE (tenant_id, message_sid)
);
"""

TENANTS = [
    ("acme-law", "+15550000001", "acme-secret"),
    ("baker-llp", "+15550000002", "baker-secret"),
]
CLAIMANTS = [
    ("C-100", "acme-law", "+15551110001"),
    ("C-101", "acme-law", "+15551110002"),
    ("C-200", "baker-llp", "+15551110001"),
    ("C-201", "baker-llp", "+15551110003"),
]


def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_db(db_path: str) -> None:
    with closing(connect(db_path)) as conn:
        conn.executescript(SCHEMA)
        conn.executemany("INSERT OR IGNORE INTO tenants VALUES (?, ?, ?)", TENANTS)
        conn.executemany(
            "INSERT OR IGNORE INTO claimants (id, tenant_id, phone) VALUES (?, ?, ?)",
            CLAIMANTS,
        )
        conn.commit()


def get_tenant_by_number(conn, number: str) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM tenants WHERE number = ?", (number,)).fetchone()


def get_tenant(conn, tenant_id: str) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM tenants WHERE id = ?", (tenant_id,)).fetchone()


def find_claimant(conn, tenant_id: str, phone: str) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM claimants WHERE tenant_id = ? AND phone = ?",
        (tenant_id, phone),
    ).fetchone()


def list_messages(conn, tenant_id: str) -> List[dict]:
    rows = conn.execute(
        "SELECT m.message_sid, m.claimant_id, m.body, m.category, m.needs_review, "
        "c.opted_out "
        "FROM messages m "
        "LEFT JOIN claimants c ON c.id = m.claimant_id AND c.tenant_id = m.tenant_id "
        "WHERE m.tenant_id = ? ORDER BY m.id",
        (tenant_id,),
    ).fetchall()
    return [_message_response(row) for row in rows]


def _message_response(row: sqlite3.Row) -> dict:
    message = dict(row)
    opted_out = message.pop("opted_out")
    message["needs_review"] = bool(message["needs_review"])
    # dnc follows the claimant. A null category means a STOP, which also covers
    # an unmatched number that has no claimant to carry the flag.
    message["dnc"] = bool(opted_out) or message["category"] is None
    return message
