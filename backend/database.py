"""Database for storing sync baselines. Supports local SQLite or Turso (libSQL) cloud."""
import sqlite3
import json
from pathlib import Path
from datetime import datetime
from typing import Optional
from contextlib import contextmanager

from config import get_settings

# Database file location (local fallback)
DB_PATH = Path(__file__).parent / "data" / "sync.db"


def _is_turso_configured() -> bool:
    """Check if Turso cloud database is configured."""
    settings = get_settings()
    return bool(settings.turso_database_url and settings.turso_auth_token)


def get_db_path() -> Path:
    """Get local database path, creating directory if needed."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return DB_PATH


@contextmanager
def get_connection():
    """Get a database connection — Turso if configured, local SQLite otherwise."""
    if _is_turso_configured():
        import libsql

        settings = get_settings()
        conn = libsql.connect(
            "sync.db",
            sync_url=settings.turso_database_url,
            auth_token=settings.turso_auth_token,
        )
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()
    else:
        conn = sqlite3.connect(get_db_path())
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()


def init_db():
    """Initialize database schema."""
    with get_connection() as conn:
        cursor = conn.cursor()

        # Baselines table - stores the last synced RMS data per project
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS baselines (
                project_id TEXT PRIMARY KEY,
                company_id TEXT NOT NULL,
                last_sync TEXT NOT NULL,
                submittal_count INTEGER DEFAULT 0,
                file_count INTEGER DEFAULT 0,
                data TEXT NOT NULL
            )
        """)

        # Sync history table - audit trail of all sync operations
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sync_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id TEXT NOT NULL,
                sync_date TEXT NOT NULL,
                mode TEXT NOT NULL,
                creates INTEGER DEFAULT 0,
                updates INTEGER DEFAULT 0,
                file_uploads INTEGER DEFAULT 0,
                errors TEXT,
                summary TEXT,
                FOREIGN KEY (project_id) REFERENCES baselines (project_id)
            )
        """)

        # Flagged items - items removed from RMS that need review
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS flagged_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id TEXT NOT NULL,
                submittal_key TEXT NOT NULL,
                procore_id INTEGER,
                reason TEXT NOT NULL,
                flagged_date TEXT NOT NULL,
                resolved INTEGER DEFAULT 0,
                resolved_date TEXT,
                resolution TEXT,
                FOREIGN KEY (project_id) REFERENCES baselines (project_id)
            )
        """)


def _row_to_dict(row) -> dict:
    """Convert a database row to a dict, handling both sqlite3.Row and libsql tuples."""
    if row is None:
        return None
    if isinstance(row, dict):
        return row
    if hasattr(row, "keys"):
        # sqlite3.Row
        return dict(row)
    # libsql returns tuples — shouldn't reach here with our usage
    return row


class BaselineStore:
    """Store and retrieve sync baselines."""

    def __init__(self):
        init_db()

    def get_baseline(self, project_id: str) -> Optional[dict]:
        """Get the stored baseline for a project."""
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT project_id, company_id, last_sync, submittal_count, file_count, data FROM baselines WHERE project_id = ?",
                (project_id,)
            )
            row = cursor.fetchone()
            if row:
                # Handle both sqlite3.Row (dict-like) and libsql (tuple)
                if hasattr(row, "keys"):
                    return {
                        "project_id": row["project_id"],
                        "company_id": row["company_id"],
                        "last_sync": row["last_sync"],
                        "submittal_count": row["submittal_count"],
                        "file_count": row["file_count"],
                        "data": json.loads(row["data"])
                    }
                else:
                    return {
                        "project_id": row[0],
                        "company_id": row[1],
                        "last_sync": row[2],
                        "submittal_count": row[3],
                        "file_count": row[4],
                        "data": json.loads(row[5])
                    }
            return None

    def save_baseline(
        self,
        project_id: str,
        company_id: str,
        data: dict
    ) -> None:
        """Save or update baseline for a project."""
        submittal_count = len(data.get("submittals", {}))
        file_count = len(data.get("files", {}))

        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO baselines
                (project_id, company_id, last_sync, submittal_count, file_count, data)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                project_id,
                company_id,
                datetime.utcnow().isoformat(),
                submittal_count,
                file_count,
                json.dumps(data)
            ))

    def delete_baseline(self, project_id: str) -> bool:
        """Delete baseline for a project (for re-import)."""
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM baselines WHERE project_id = ?",
                (project_id,)
            )
            return cursor.rowcount > 0

    def add_sync_history(
        self,
        project_id: str,
        mode: str,
        creates: int = 0,
        updates: int = 0,
        file_uploads: int = 0,
        errors: list[str] = None,
        summary: str = ""
    ) -> int:
        """Record a sync operation in history."""
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO sync_history
                (project_id, sync_date, mode, creates, updates, file_uploads, errors, summary)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                project_id,
                datetime.utcnow().isoformat(),
                mode,
                creates,
                updates,
                file_uploads,
                json.dumps(errors or []),
                summary
            ))
            return cursor.lastrowid

    def get_sync_history(self, project_id: str, limit: int = 10) -> list[dict]:
        """Get recent sync history for a project."""
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, sync_date, mode, creates, updates, file_uploads, errors, summary
                FROM sync_history
                WHERE project_id = ?
                ORDER BY sync_date DESC
                LIMIT ?
            """, (project_id, limit))

            results = []
            for row in cursor.fetchall():
                if hasattr(row, "keys"):
                    results.append({
                        "id": row["id"],
                        "sync_date": row["sync_date"],
                        "mode": row["mode"],
                        "creates": row["creates"],
                        "updates": row["updates"],
                        "file_uploads": row["file_uploads"],
                        "errors": json.loads(row["errors"]) if row["errors"] else [],
                        "summary": row["summary"]
                    })
                else:
                    results.append({
                        "id": row[0],
                        "sync_date": row[1],
                        "mode": row[2],
                        "creates": row[3],
                        "updates": row[4],
                        "file_uploads": row[5],
                        "errors": json.loads(row[6]) if row[6] else [],
                        "summary": row[7]
                    })
            return results

    def flag_item(
        self,
        project_id: str,
        submittal_key: str,
        procore_id: int,
        reason: str
    ) -> int:
        """Flag an item for review (e.g., deleted from RMS)."""
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO flagged_items
                (project_id, submittal_key, procore_id, reason, flagged_date)
                VALUES (?, ?, ?, ?, ?)
            """, (
                project_id,
                submittal_key,
                procore_id,
                reason,
                datetime.utcnow().isoformat()
            ))
            return cursor.lastrowid

    def get_flagged_items(self, project_id: str, include_resolved: bool = False) -> list[dict]:
        """Get flagged items for a project."""
        with get_connection() as conn:
            cursor = conn.cursor()

            if include_resolved:
                cursor.execute(
                    "SELECT id, project_id, submittal_key, procore_id, reason, flagged_date, resolved, resolved_date, resolution FROM flagged_items WHERE project_id = ?",
                    (project_id,)
                )
            else:
                cursor.execute(
                    "SELECT id, project_id, submittal_key, procore_id, reason, flagged_date, resolved, resolved_date, resolution FROM flagged_items WHERE project_id = ? AND resolved = 0",
                    (project_id,)
                )

            results = []
            for row in cursor.fetchall():
                if hasattr(row, "keys"):
                    results.append(dict(row))
                else:
                    results.append({
                        "id": row[0],
                        "project_id": row[1],
                        "submittal_key": row[2],
                        "procore_id": row[3],
                        "reason": row[4],
                        "flagged_date": row[5],
                        "resolved": row[6],
                        "resolved_date": row[7],
                        "resolution": row[8],
                    })
            return results

    def resolve_flagged_item(self, item_id: int, resolution: str) -> bool:
        """Mark a flagged item as resolved."""
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE flagged_items
                SET resolved = 1, resolved_date = ?, resolution = ?
                WHERE id = ?
            """, (datetime.utcnow().isoformat(), resolution, item_id))
            return cursor.rowcount > 0


# Global instance
baseline_store = BaselineStore()
