"""Read-only audit: compare submittal custom fields in baseline vs Procore.

Finds submittals where the local baseline records a custom-field value but
Procore actually has nothing (or something different). These are the cases
where the diff-based sync silently misses a fix because the baseline is
already "correct" from its own perspective.

Outputs `audit_mismatches.csv` next to this script. Read-only — never writes
to Procore.

Rate limits (per CLAUDE.md):
- Hourly: 3,600 req / 60 min
- Spike: ~20-30 req / 10s — this is what usually trips first
This script paces at 1 req/s (well under spike), with 429 backoff to 30s.

Usage: python audit_custom_fields.py [--limit N] [--resume]
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
import sqlite3
import sys
import time
from pathlib import Path
from typing import Optional

import httpx
from dotenv import dotenv_values

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("audit")

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_DIR = SCRIPT_DIR.parent
BACKEND_DIR = REPO_DIR / "backend"
DB_PATH = BACKEND_DIR / "sync.db"
ENV_PATH = BACKEND_DIR / ".env"
OUT_CSV = SCRIPT_DIR / "audit_mismatches.csv"
PROGRESS_PATH = SCRIPT_DIR / ".audit_progress.json"

PROJECT_ID = 598134325988700  # Dobbins
COMPANY_ID_HEADER = None      # Filled below from .env or first project lookup if needed

# Custom-field IDs (per backend/services/sync_job.py)
FIELDS = {
    "paragraph":           "custom_field_598134325870420",
    "qc_code":             "custom_field_598134325871359",
    "qa_code":             "custom_field_598134325871360",
    "info":                "custom_field_598134325871364",
    "government_received": "custom_field_598134325872868",
    "government_returned": "custom_field_598134325872869",
}

# LOV reverse map: ID → label (for qa_code/qc_code/info)
LOV_LABEL = {
    598134327466502: "A", 598134327466503: "B", 598134327466504: "C",
    598134327466506: "E", 598134327466507: "F", 598134327466508: "G",
    598134327466509: "X",
    598134327466498: "A",  # qc_code A
    598134327466511: "GA", 598134327466512: "FIO", 598134327466513: "S",
}
LOV_FIELDS = {"qa_code", "qc_code", "info"}
DATE_FIELDS = {"government_received", "government_returned"}

DELAY_SEC = 1.0
RATE_LIMIT_BACKOFF_SEC = 30.0
MAX_RETRIES = 4
# Procore tokens last ~2hr; refresh proactively every 75 min so mid-flight
# expiry never strands a long run.
TOKEN_REFRESH_INTERVAL_SEC = 75 * 60


def load_env() -> dict:
    if not ENV_PATH.exists():
        sys.exit(f"missing {ENV_PATH}")
    env = dotenv_values(ENV_PATH)
    for k in ("PROCORE_CLIENT_ID", "PROCORE_CLIENT_SECRET"):
        if not env.get(k):
            sys.exit(f"{k} not set in {ENV_PATH}")
    return env


def load_baseline() -> tuple[str, dict[str, dict]]:
    """Return (company_id, {key: stored_submittal_dict}) for entries with a procore_id."""
    if not DB_PATH.exists():
        sys.exit(f"missing {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    try:
        row = conn.execute(
            "SELECT company_id, data FROM baselines WHERE project_id=?",
            (str(PROJECT_ID),),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        sys.exit(f"no baseline for project {PROJECT_ID}")
    company_id = row[0]
    data = json.loads(row[1])
    subs = data.get("submittals", {})
    return company_id, {k: v for k, v in subs.items() if v.get("procore_id")}


def load_latest_session() -> tuple[str, dict]:
    """Return (session_id, token_data) for the most recently updated session."""
    conn = sqlite3.connect(DB_PATH)
    try:
        row = conn.execute(
            "SELECT session_id, token_data FROM sessions ORDER BY updated_at DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    if not row:
        sys.exit("no session in sync.db — log in via the app once to seed a session")
    return row[0], json.loads(row[1])


def save_session_token(session_id: str, token_data: dict) -> None:
    conn = sqlite3.connect(DB_PATH)
    try:
        from datetime import datetime
        now = datetime.utcnow().isoformat()
        conn.execute(
            """INSERT OR REPLACE INTO sessions (session_id, token_data, created_at, updated_at)
               VALUES (?, ?, COALESCE(
                 (SELECT created_at FROM sessions WHERE session_id = ?), ?
               ), ?)""",
            (session_id, json.dumps(token_data), session_id, now, now),
        )
        conn.commit()
    finally:
        conn.close()


class TokenManager:
    """Owns the OAuth token lifecycle for a long-running script.

    Refreshes proactively on a timer and reactively on 401. Mutates the shared
    `headers` dict so callers don't need to thread the new token through every
    layer.
    """

    def __init__(self, env: dict, session_id: str, headers: dict):
        self.env = env
        self.session_id = session_id
        self.headers = headers
        self.last_refresh_at: float = 0.0

    async def initial_refresh(self) -> None:
        token_data = load_session_token(self.session_id)
        if not token_data:
            sys.exit(f"session {self.session_id} not found")
        await self._refresh(token_data)

    async def maybe_refresh(self) -> None:
        if time.monotonic() - self.last_refresh_at >= TOKEN_REFRESH_INTERVAL_SEC:
            log.info("proactive token refresh (interval reached)")
            token_data = load_session_token(self.session_id) or {}
            await self._refresh(token_data)

    async def force_refresh(self) -> None:
        token_data = load_session_token(self.session_id) or {}
        await self._refresh(token_data)

    async def _refresh(self, token_data: dict) -> None:
        refresh = token_data.get("refresh_token")
        if not refresh:
            sys.exit("session has no refresh_token — log in via the app to reseed")
        async with httpx.AsyncClient() as client:
            r = await client.post(
                "https://login.procore.com/oauth/token",
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh,
                    "client_id": self.env["PROCORE_CLIENT_ID"],
                    "client_secret": self.env["PROCORE_CLIENT_SECRET"],
                },
            )
        if r.status_code != 200:
            sys.exit(f"token refresh failed: {r.status_code} {r.text[:200]}")
        new = r.json()
        save_session_token(self.session_id, new)
        self.headers["Authorization"] = f"Bearer {new['access_token']}"
        self.last_refresh_at = time.monotonic()
        log.info("refreshed access token")


def load_session_token(session_id: str) -> Optional[dict]:
    conn = sqlite3.connect(DB_PATH)
    try:
        row = conn.execute(
            "SELECT token_data FROM sessions WHERE session_id=?",
            (session_id,),
        ).fetchone()
    finally:
        conn.close()
    return json.loads(row[0]) if row else None


def normalize_baseline_value(field: str, raw):
    """Normalize a baseline value for comparison (string or None)."""
    if raw is None or raw == "":
        return None
    if field in DATE_FIELDS:
        # Baseline stores ISO date "YYYY-MM-DD"
        return str(raw)[:10]
    return str(raw).strip()


def extract_procore_value(field: str, cf_entry):
    """Pull the comparable value from a Procore custom_fields entry.

    Procore typically returns: {"value": <raw>, "data_type": "lov"|...}.
    For LOV: value is the entry id (int) — we map back to the label.
    For dates: value is ISO datetime — we slice to date.
    For text: value is the string.
    """
    if cf_entry is None:
        return None
    if isinstance(cf_entry, dict):
        val = cf_entry.get("value")
    else:
        val = cf_entry
    if val is None or val == "":
        return None
    if field in LOV_FIELDS:
        if isinstance(val, int):
            return LOV_LABEL.get(val, f"LOV#{val}")
        if isinstance(val, dict) and "id" in val:
            return LOV_LABEL.get(val["id"], f"LOV#{val['id']}")
        return str(val)
    if field in DATE_FIELDS:
        return str(val)[:10]
    return str(val).strip()


async def get_submittal(
    client: httpx.AsyncClient, tokens: "TokenManager", sub_id: int,
) -> Optional[dict]:
    url = f"https://api.procore.com/rest/v1.0/projects/{PROJECT_ID}/submittals/{sub_id}"
    refreshed_for_401 = False
    for attempt in range(MAX_RETRIES + 1):
        r = await client.get(url, headers=tokens.headers, timeout=30.0)
        if r.status_code == 429:
            log.warning(f"429 on {sub_id}, sleeping {RATE_LIMIT_BACKOFF_SEC}s (try {attempt + 1})")
            await asyncio.sleep(RATE_LIMIT_BACKOFF_SEC)
            continue
        if r.status_code == 401 and not refreshed_for_401:
            log.warning(f"401 on {sub_id}, refreshing token and retrying")
            await tokens.force_refresh()
            refreshed_for_401 = True
            continue
        if r.status_code == 404:
            return None
        if r.status_code >= 400:
            log.error(f"GET {sub_id} → {r.status_code}: {r.text[:200]}")
            return None
        return r.json()
    log.error(f"GET {sub_id} failed after {MAX_RETRIES} retries")
    return None


def load_progress() -> set[int]:
    if not PROGRESS_PATH.exists():
        return set()
    try:
        return set(json.loads(PROGRESS_PATH.read_text()))
    except Exception:
        return set()


def save_progress(done: set[int]) -> None:
    PROGRESS_PATH.write_text(json.dumps(sorted(done)))


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="audit only the first N submittals")
    parser.add_argument("--resume", action="store_true", help="skip submittals already in progress file")
    args = parser.parse_args()

    env = load_env()
    company_id, baseline = load_baseline()
    log.info(f"baseline has {len(baseline)} submittals with procore_id (company {company_id})")

    session_id, _ = load_latest_session()
    headers = {
        "Authorization": "Bearer placeholder",
        "Procore-Company-Id": str(company_id),
    }
    tokens = TokenManager(env, session_id, headers)
    await tokens.initial_refresh()

    done = load_progress() if args.resume else set()
    if done:
        log.info(f"resuming — {len(done)} already audited")

    # Open CSV in append mode if resuming, write mode otherwise
    csv_mode = "a" if args.resume and OUT_CSV.exists() else "w"
    csv_file = OUT_CSV.open(csv_mode, newline="", encoding="utf-8")
    writer = csv.writer(csv_file)
    if csv_mode == "w":
        writer.writerow([
            "key", "section", "item_no", "revision", "procore_id",
            "field", "category", "baseline_value", "procore_value",
        ])

    items = sorted(baseline.items(), key=lambda kv: (kv[1]["section"], kv[1]["item_no"], kv[1]["revision"]))
    if args.limit:
        items = items[:args.limit]

    mismatch_count = 0
    checked = 0
    by_field: dict[str, int] = {f: 0 for f in FIELDS}
    # Per-category breakdown — silent_drop is the concerning case
    by_category: dict[str, int] = {
        "silent_drop": 0,       # baseline has, Procore empty
        "stale_baseline": 0,    # baseline empty, Procore has
        "diverged": 0,          # both have, but different
    }

    async with httpx.AsyncClient() as client:
        for key, sub in items:
            pid = sub["procore_id"]
            if pid in done:
                continue

            await tokens.maybe_refresh()
            detail = await get_submittal(client, tokens, pid)
            await asyncio.sleep(DELAY_SEC)

            if detail is None:
                # 404 or persistent error — log to CSV as a special row.
                # Don't add to `done` so a --resume run will retry this id.
                writer.writerow([key, sub["section"], sub["item_no"], sub["revision"], pid,
                                 "_FETCH_ERROR", "fetch_error", "", ""])
                csv_file.flush()
                checked += 1
                continue

            cfs = detail.get("custom_fields") or {}
            for field, cf_id in FIELDS.items():
                baseline_val = normalize_baseline_value(field, sub.get(field))
                procore_val = extract_procore_value(field, cfs.get(cf_id))
                if baseline_val == procore_val:
                    continue
                if baseline_val is not None and procore_val is None:
                    category = "silent_drop"
                elif baseline_val is None and procore_val is not None:
                    category = "stale_baseline"
                else:
                    category = "diverged"
                writer.writerow([
                    key, sub["section"], sub["item_no"], sub["revision"], pid,
                    field, category,
                    baseline_val if baseline_val is not None else "",
                    procore_val if procore_val is not None else "",
                ])
                csv_file.flush()
                mismatch_count += 1
                by_field[field] += 1
                by_category[category] += 1

            done.add(pid)
            checked += 1
            if checked % 50 == 0:
                save_progress(done)
                log.info(f"checked {checked}/{len(items)} — {mismatch_count} mismatches so far")

    csv_file.close()
    save_progress(done)

    log.info(f"done — {checked} submittals checked, {mismatch_count} mismatches")
    log.info("by category:")
    for c, n in by_category.items():
        log.info(f"  {c}: {n}")
    log.info("by field:")
    for f, n in by_field.items():
        log.info(f"  {f}: {n}")
    log.info(f"CSV: {OUT_CSV}")


if __name__ == "__main__":
    asyncio.run(main())
