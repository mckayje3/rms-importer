"""Database for storing sync baselines. Supports local SQLite or Turso (libSQL) cloud."""
import sqlite3
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional
from contextlib import contextmanager

from config import get_settings

logger = logging.getLogger(__name__)

# Database file location (local fallback)
DB_PATH = Path(__file__).parent / "data" / "sync.db"

# Track whether Turso is available (set to False on connection failure)
_turso_available: bool | None = None


def _is_turso_configured() -> bool:
    """Check if Turso cloud database is configured."""
    settings = get_settings()
    return bool(settings.turso_database_url and settings.turso_auth_token)


def _turso_http_url() -> str:
    """Convert libsql:// URL to https:// for direct HTTP connection (no embedded replica)."""
    settings = get_settings()
    url = settings.turso_database_url
    if url.startswith("libsql://"):
        url = "https://" + url[len("libsql://"):]
    return url


def _is_turso_available() -> bool:
    """Check if Turso is configured and reachable."""
    global _turso_available
    if not _is_turso_configured():
        return False
    if _turso_available is not None:
        return _turso_available
    # First call — test the connection
    try:
        import libsql
        settings = get_settings()
        conn = libsql.connect(
            _turso_http_url(),
            auth_token=settings.turso_auth_token,
        )
        conn.close()
        _turso_available = True
        logger.info("Turso database connected (direct HTTP)")
    except Exception as e:
        _turso_available = False
        logger.warning(f"Turso unavailable, falling back to local SQLite: {e}")
    return _turso_available


def get_db_path() -> Path:
    """Get local database path, creating directory if needed."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return DB_PATH


@contextmanager
def get_connection():
    """Get a database connection — Turso via HTTP if available, local SQLite otherwise."""
    if _is_turso_available():
        import libsql

        settings = get_settings()
        conn = libsql.connect(
            _turso_http_url(),
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

        # Sessions table - persistent OAuth token storage
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                token_data TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
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

        # Project configuration table - per-project settings for multi-project support
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS project_config (
                project_id TEXT PRIMARY KEY,
                company_id TEXT NOT NULL,
                config_data TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

        # File upload jobs — background processing of file uploads to Procore
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS file_jobs (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                company_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                status TEXT NOT NULL,
                total_files INTEGER DEFAULT 0,
                uploaded_files INTEGER DEFAULT 0,
                errors TEXT,
                created_at TEXT NOT NULL,
                started_at TEXT,
                completed_at TEXT,
                email TEXT,
                file_manifest TEXT NOT NULL,
                result_summary TEXT
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


class SessionStore:
    """Persistent OAuth session storage."""

    def __init__(self):
        init_db()

    def save_session(self, session_id: str, token_data: dict) -> None:
        """Save or update a session with token data."""
        now = datetime.utcnow().isoformat()
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO sessions (session_id, token_data, created_at, updated_at)
                VALUES (?, ?, COALESCE(
                    (SELECT created_at FROM sessions WHERE session_id = ?), ?
                ), ?)
            """, (session_id, json.dumps(token_data), session_id, now, now))

    def get_session(self, session_id: str) -> Optional[dict]:
        """Get token data for a session."""
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT token_data FROM sessions WHERE session_id = ?",
                (session_id,)
            )
            row = cursor.fetchone()
            if row:
                data = row["token_data"] if hasattr(row, "keys") else row[0]
                return json.loads(data)
            return None

    def delete_session(self, session_id: str) -> None:
        """Delete a session (logout)."""
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM sessions WHERE session_id = ?",
                (session_id,)
            )

    def cleanup_old_sessions(self, days: int = 30) -> int:
        """Remove sessions older than N days."""
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM sessions WHERE updated_at < datetime('now', ?)",
                (f"-{days} days",)
            )
            return cursor.rowcount


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


class ProjectConfigStore:
    """Store for per-project configuration (status mappings, custom field IDs, etc.)."""

    def __init__(self):
        init_db()

    def get_config(self, project_id: str) -> Optional[dict]:
        """Get project configuration. Returns None if not configured."""
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT project_id, company_id, config_data, created_at, updated_at FROM project_config WHERE project_id = ?",
                (project_id,)
            )
            row = cursor.fetchone()
            if not row:
                return None
            # Handle both sqlite3.Row (dict-like) and libsql (tuple)
            if hasattr(row, "keys"):
                data = dict(row)
            elif isinstance(row, dict):
                data = row
            else:
                data = {
                    "project_id": row[0],
                    "company_id": row[1],
                    "config_data": row[2],
                    "created_at": row[3],
                    "updated_at": row[4],
                }
            data["config_data"] = json.loads(data["config_data"])
            return data

    def save_config(self, project_id: str, company_id: str, config_data: dict) -> None:
        """Save or update project configuration."""
        now = datetime.utcnow().isoformat()
        config_json = json.dumps(config_data)
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO project_config (project_id, company_id, config_data, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(project_id) DO UPDATE SET
                    company_id = excluded.company_id,
                    config_data = excluded.config_data,
                    updated_at = excluded.updated_at
            """, (project_id, company_id, config_json, now, now))

    def delete_config(self, project_id: str) -> bool:
        """Delete project configuration. Returns True if deleted."""
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM project_config WHERE project_id = ?", (project_id,))
            return cursor.rowcount > 0


class FileJobStore:
    """Store for background file upload jobs."""

    def __init__(self):
        init_db()

    def create_job(
        self,
        job_id: str,
        project_id: str,
        company_id: str,
        session_id: str,
        manifest: list[dict],
        total_files: int,
        email: Optional[str] = None,
    ) -> None:
        """Create a new file upload job."""
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO file_jobs
                (id, project_id, company_id, session_id, status, total_files,
                 uploaded_files, errors, created_at, email, file_manifest)
                VALUES (?, ?, ?, ?, 'queued', ?, 0, '[]', ?, ?, ?)
            """, (
                job_id, project_id, company_id, session_id,
                total_files,
                datetime.utcnow().isoformat(),
                email,
                json.dumps(manifest),
            ))

    def update_progress(
        self,
        job_id: str,
        *,
        status: Optional[str] = None,
        uploaded_files: Optional[int] = None,
        errors: Optional[list[str]] = None,
        result_summary: Optional[dict] = None,
    ) -> None:
        """Update job progress. Only provided fields are updated."""
        updates = []
        params = []

        if status is not None:
            updates.append("status = ?")
            params.append(status)
            if status == "running":
                updates.append("started_at = ?")
                params.append(datetime.utcnow().isoformat())
            elif status in ("completed", "failed"):
                updates.append("completed_at = ?")
                params.append(datetime.utcnow().isoformat())

        if uploaded_files is not None:
            updates.append("uploaded_files = ?")
            params.append(uploaded_files)

        if errors is not None:
            updates.append("errors = ?")
            params.append(json.dumps(errors))

        if result_summary is not None:
            updates.append("result_summary = ?")
            params.append(json.dumps(result_summary))

        if not updates:
            return

        params.append(job_id)
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"UPDATE file_jobs SET {', '.join(updates)} WHERE id = ?",
                params,
            )

    def get_job(self, job_id: str) -> Optional[dict]:
        """Get a file job by ID."""
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, project_id, company_id, session_id, status, total_files, "
                "uploaded_files, errors, created_at, started_at, completed_at, "
                "email, file_manifest, result_summary FROM file_jobs WHERE id = ?",
                (job_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None

            cols = [
                "id", "project_id", "company_id", "session_id", "status",
                "total_files", "uploaded_files", "errors", "created_at",
                "started_at", "completed_at", "email", "file_manifest",
                "result_summary",
            ]
            if hasattr(row, "keys"):
                data = dict(row)
            else:
                data = dict(zip(cols, row))

            data["errors"] = json.loads(data["errors"]) if data["errors"] else []
            data["file_manifest"] = json.loads(data["file_manifest"]) if data["file_manifest"] else []
            data["result_summary"] = json.loads(data["result_summary"]) if data["result_summary"] else None
            return data

    def get_jobs_for_project(self, project_id: str, limit: int = 10) -> list[dict]:
        """Get recent jobs for a project."""
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, status, total_files, uploaded_files, errors, "
                "created_at, started_at, completed_at, result_summary "
                "FROM file_jobs WHERE project_id = ? ORDER BY created_at DESC LIMIT ?",
                (project_id, limit),
            )
            cols = [
                "id", "status", "total_files", "uploaded_files", "errors",
                "created_at", "started_at", "completed_at", "result_summary",
            ]
            results = []
            for row in cursor.fetchall():
                if hasattr(row, "keys"):
                    d = dict(row)
                else:
                    d = dict(zip(cols, row))
                d["errors"] = json.loads(d["errors"]) if d["errors"] else []
                d["result_summary"] = json.loads(d["result_summary"]) if d["result_summary"] else None
                results.append(d)
            return results


# Global instances
session_store = SessionStore()
baseline_store = BaselineStore()
project_config_store = ProjectConfigStore()
file_job_store = FileJobStore()
