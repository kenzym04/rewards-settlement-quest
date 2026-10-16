"""SQLite ledger: a real database with UNIQUE constraints (standard library only).

Same interface as rewards.store.Store. Every call opens its own short connection, so one
SqliteStore object can be shared by several threads, and several processes can share one file.
"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator, List

from rewards.models import Payout

LOCK_WAIT_SECONDS = 30

SCHEMA = """
CREATE TABLE IF NOT EXISTS payouts (
    key          TEXT PRIMARY KEY,
    task_id      TEXT NOT NULL UNIQUE,
    account_id   TEXT NOT NULL,
    credits      INTEGER NOT NULL,
    window_start TEXT NOT NULL,
    notified     INTEGER NOT NULL DEFAULT 0
)
"""

_COLUMNS = "key, task_id, account_id, credits, window_start"


def _to_text(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat()


def _to_payout(row: tuple) -> Payout:
    key, task_id, account_id, credits, window_start = row
    return Payout(
        key=key,
        account_id=account_id,
        task_id=task_id,
        credits=credits,
        window_start=datetime.fromisoformat(window_start),
    )


class SqliteStore:
    def __init__(self, path: str) -> None:
        self._path = path
        with self._session() as conn:
            conn.execute(SCHEMA)

    @contextmanager
    def _session(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._path, timeout=LOCK_WAIT_SECONDS)
        try:
            with conn:  # one transaction: commit on success, roll back on error
                yield conn
        finally:
            conn.close()

    def has_payout(self, key: str) -> bool:
        with self._session() as conn:
            row = conn.execute("SELECT 1 FROM payouts WHERE key = ?", (key,)).fetchone()
        return row is not None

    def add_payout(self, payout: Payout) -> bool:
        """Insert a payout. Returns False (and changes nothing) if the key or task ID exists."""
        with self._session() as conn:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO payouts (key, task_id, account_id, credits, window_start)"
                " VALUES (?, ?, ?, ?, ?)",
                (
                    payout.key,
                    payout.task_id,
                    payout.account_id,
                    payout.credits,
                    _to_text(payout.window_start),
                ),
            )
            return cursor.rowcount == 1

    def payouts(self) -> List[Payout]:
        with self._session() as conn:
            rows = conn.execute(
                "SELECT %s FROM payouts ORDER BY key" % _COLUMNS
            ).fetchall()
        return [_to_payout(row) for row in rows]

    def unnotified_payouts(self, window_start: datetime) -> List[Payout]:
        with self._session() as conn:
            rows = conn.execute(
                "SELECT %s FROM payouts WHERE window_start = ? AND notified = 0 ORDER BY key"
                % _COLUMNS,
                (_to_text(window_start),),
            ).fetchall()
        return [_to_payout(row) for row in rows]

    def mark_notified(self, key: str) -> None:
        with self._session() as conn:
            conn.execute("UPDATE payouts SET notified = 1 WHERE key = ?", (key,))

    def total_credits(self, account_id: str) -> int:
        with self._session() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(credits), 0) FROM payouts WHERE account_id = ?",
                (account_id,),
            ).fetchone()
        return int(row[0])
