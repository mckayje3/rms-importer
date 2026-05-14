"""Targeted repair: push baseline values back to Procore for the submittals
flagged by audit_custom_fields.py.

Reads audit_mismatches.csv, picks silent_drop rows by default (baseline has,
Procore is empty), and PATCHes each submittal in Procore with the missing
custom-field values. Optional --include-diverged also pushes baseline values
for fields where Procore disagrees.

Always dry-run unless --execute is passed. Resumable via --resume.

Usage:
    python repair_silent_drops.py                         # dry run, silent_drop only
    python repair_silent_drops.py --execute               # run for real
    python repair_silent_drops.py --include-diverged --execute
    python repair_silent_drops.py --execute --resume      # continue after interruption
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
from collections import defaultdict
from pathlib import Path
from typing import Optional

import httpx
from dotenv import dotenv_values

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("repair")

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent / "backend"
DB_PATH = BACKEND_DIR / "sync.db"
ENV_PATH = BACKEND_DIR / ".env"
AUDIT_CSV = SCRIPT_DIR / "audit_mismatches.csv"
RESULTS_CSV = SCRIPT_DIR / "repair_results.csv"
PROGRESS_PATH = SCRIPT_DIR / ".repair_progress.json"

PROJECT_ID = 598134325988700  # Dobbins

FIELDS = {
    "paragraph":           "custom_field_598134325870420",
    "qc_code":             "custom_field_598134325871359",
    "qa_code":             "custom_field_598134325871360",
    "info":                "custom_field_598134325871364",
    "government_received": "custom_field_598134325872868",
    "government_returned": "custom_field_598134325872869",
}

LOV_FIELDS = {"qa_code", "qc_code", "info"}
DATE_FIELDS = {"government_received", "government_returned"}

# Forward LOV mapping (label → entry ID), copied from backend/services/sync_job.py
LOV_ENTRIES = {
    "qa_code": {
        "A": 598134327466502, "B": 598134327466503, "C": 598134327466504,
        "E": 598134327466506, "F": 598134327466507, "G": 598134327466508,
        "X": 598134327466509,
    },
    "qc_code": {
        "A": 598134327466498,
    },
    "info": {
        "GA": 598134327466511, "FIO": 598134327466512, "S": 598134327466513,
    },
}

DELAY_SEC = 1.0
RATE_LIMIT_BACKOFF_SEC = 30.0
MAX_RETRIES = 4
TOKEN_REFRESH_INTERVAL_SEC = 75 * 60


def load_env() -> dict:
    if not ENV_PATH.exists():
        sys.exit(f"missing {ENV_PATH}")
    env = dotenv_values(ENV_PATH)
    for k in ("PROCORE_CLIENT_ID", "PROCORE_CLIENT_SECRET"):
        if not env.get(k):
            sys.exit(f"{k} not set in {ENV_PATH}")
    return env


def load_company_id() -> str:
    conn = sqlite3.connect(DB_PATH)
    try:
        row = conn.execute(
            "SELECT company_id FROM baselines WHERE project_id=?",
            (str(PROJECT_ID),),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        sys.exit(f"no baseline for project {PROJECT_ID}")
    return row[0]


def load_session_id() -> str:
    conn = sqlite3.connect(DB_PATH)
    try:
        row = conn.execute(
            "SELECT session_id FROM sessions ORDER BY updated_at DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    if not row:
        sys.exit("no session in sync.db — log in via the app to seed one")
    return row[0]


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


def save_session_token(session_id: str, token_data: dict) -> None:
    from datetime import datetime
    now = datetime.utcnow().isoformat()
    conn = sqlite3.connect(DB_PATH)
    try:
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
            await self._refresh(load_session_token(self.session_id) or {})

    async def force_refresh(self) -> None:
        await self._refresh(load_session_token(self.session_id) or {})

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


def encode_field_value(field: str, baseline_value: str):
    """Convert a baseline string to the value Procore expects."""
    if not baseline_value:
        return None
    if field in LOV_FIELDS:
        entry_id = LOV_ENTRIES.get(field, {}).get(baseline_value.strip())
        if not entry_id:
            log.warning(f"no LOV entry for {field}={baseline_value!r} — skipping this field")
            return None
        return entry_id
    if field in DATE_FIELDS:
        # Baseline stores YYYY-MM-DD; Procore datetime field wants ISO with time
        return f"{baseline_value.strip()}T00:00:00Z"
    return baseline_value


def load_repairs(
    include_diverged: bool,
    only_diverged: bool,
    field_filter: Optional[set[str]],
) -> dict[int, dict]:
    """Group audit rows by procore_id, build PATCH payload per submittal.

    Returns {procore_id: {"key", "section", "item_no", "revision",
                          "fields": {field_name: baseline_value},
                          "payload": {custom_field_id: encoded_value}}}
    """
    if not AUDIT_CSV.exists():
        sys.exit(f"missing {AUDIT_CSV} — run audit_custom_fields.py first")

    targets: dict[int, dict] = {}
    skipped_unmappable = 0
    with AUDIT_CSV.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            cat = row["category"]
            if cat == "silent_drop" and not only_diverged:
                pass
            elif cat == "diverged" and include_diverged:
                pass
            else:
                continue

            field = row["field"]
            if field not in FIELDS:
                continue
            if field_filter and field not in field_filter:
                continue
            baseline_value = row["baseline_value"]
            encoded = encode_field_value(field, baseline_value)
            if encoded is None:
                skipped_unmappable += 1
                continue

            pid = int(row["procore_id"])
            entry = targets.setdefault(pid, {
                "key": row["key"],
                "section": row["section"],
                "item_no": row["item_no"],
                "revision": row["revision"],
                "fields": {},
                "payload": {},
            })
            entry["fields"][field] = baseline_value
            entry["payload"][FIELDS[field]] = encoded

    if skipped_unmappable:
        log.warning(f"skipped {skipped_unmappable} unmappable values (no LOV entry)")
    return targets


async def patch_submittal(
    client: httpx.AsyncClient,
    tokens: TokenManager,
    procore_id: int,
    payload: dict,
) -> tuple[bool, str]:
    """PATCH one submittal. Returns (success, error_message)."""
    url = f"https://api.procore.com/rest/v1.0/projects/{PROJECT_ID}/submittals/{procore_id}"
    body = {"submittal": payload}
    headers = {**tokens.headers, "Content-Type": "application/json"}
    refreshed_for_401 = False
    for attempt in range(MAX_RETRIES + 1):
        r = await client.patch(url, headers=headers, json=body, timeout=30.0)
        if r.status_code == 429:
            log.warning(f"429 on {procore_id}, sleep {RATE_LIMIT_BACKOFF_SEC}s (try {attempt + 1})")
            await asyncio.sleep(RATE_LIMIT_BACKOFF_SEC)
            continue
        if r.status_code == 401 and not refreshed_for_401:
            log.warning(f"401 on {procore_id}, refreshing token")
            await tokens.force_refresh()
            headers = {**tokens.headers, "Content-Type": "application/json"}
            refreshed_for_401 = True
            continue
        if r.status_code >= 400:
            return False, f"HTTP {r.status_code}: {r.text[:200]}"
        return True, ""
    return False, "max retries exhausted"


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
    parser.add_argument("--execute", action="store_true",
                        help="actually PATCH Procore (default is dry-run)")
    parser.add_argument("--include-diverged", action="store_true",
                        help="also push baseline values where Procore disagrees")
    parser.add_argument("--only-diverged", action="store_true",
                        help="process only diverged rows (exclude silent_drop)")
    parser.add_argument("--fields", default=None,
                        help="comma-separated field whitelist "
                             "(paragraph,qc_code,qa_code,info,government_received,government_returned)")
    parser.add_argument("--resume", action="store_true",
                        help="skip procore_ids already in .repair_progress.json")
    parser.add_argument("--limit", type=int, default=None,
                        help="cap how many submittals to process (testing)")
    args = parser.parse_args()

    if args.only_diverged and not args.include_diverged:
        # only_diverged implies including diverged
        args.include_diverged = True

    field_filter: Optional[set[str]] = None
    if args.fields:
        field_filter = {f.strip() for f in args.fields.split(",") if f.strip()}
        unknown = field_filter - set(FIELDS)
        if unknown:
            sys.exit(f"unknown fields: {sorted(unknown)} (valid: {sorted(FIELDS)})")

    targets = load_repairs(args.include_diverged, args.only_diverged, field_filter)
    log.info(f"loaded {len(targets)} submittals to repair "
             f"({'including' if args.include_diverged else 'excluding'} diverged)")

    # Summary breakdown
    field_counts: dict[str, int] = defaultdict(int)
    for entry in targets.values():
        for f in entry["fields"]:
            field_counts[f] += 1
    log.info("fields to push (across all submittals):")
    for f, n in sorted(field_counts.items(), key=lambda x: -x[1]):
        log.info(f"  {f}: {n}")

    if not args.execute:
        log.info("\n--- DRY RUN — no Procore writes will happen ---")
        log.info("rerun with --execute to apply.")
        # Show first 5 as preview
        for i, (pid, entry) in enumerate(sorted(targets.items())[:5]):
            log.info(f"  {entry['key']} (pid={pid}): {entry['fields']}")
        if len(targets) > 5:
            log.info(f"  ...and {len(targets) - 5} more")
        return

    env = load_env()
    company_id = load_company_id()
    session_id = load_session_id()
    headers = {
        "Authorization": "Bearer placeholder",
        "Procore-Company-Id": str(company_id),
    }
    tokens = TokenManager(env, session_id, headers)
    await tokens.initial_refresh()

    done = load_progress() if args.resume else set()
    if done:
        log.info(f"resuming — {len(done)} already repaired")

    csv_mode = "a" if args.resume and RESULTS_CSV.exists() else "w"
    results = RESULTS_CSV.open(csv_mode, newline="", encoding="utf-8")
    rwriter = csv.writer(results)
    if csv_mode == "w":
        rwriter.writerow(["procore_id", "key", "fields_pushed", "status", "error"])

    items = sorted(targets.items())
    if args.limit:
        items = items[: args.limit]

    successes = 0
    failures = 0
    async with httpx.AsyncClient() as client:
        for pid, entry in items:
            if pid in done:
                continue
            await tokens.maybe_refresh()

            ok, err = await patch_submittal(client, tokens, pid, entry["payload"])
            await asyncio.sleep(DELAY_SEC)

            fields_pushed = ",".join(sorted(entry["fields"].keys()))
            if ok:
                rwriter.writerow([pid, entry["key"], fields_pushed, "ok", ""])
                successes += 1
                done.add(pid)
            else:
                rwriter.writerow([pid, entry["key"], fields_pushed, "fail", err])
                failures += 1
                log.error(f"FAIL {entry['key']} (pid={pid}): {err}")
            results.flush()

            total_done = successes + failures
            if total_done % 25 == 0:
                save_progress(done)
                log.info(f"progress: {total_done}/{len(items)} "
                         f"({successes} ok, {failures} fail)")

    results.close()
    save_progress(done)
    log.info(f"\ndone — {successes} succeeded, {failures} failed "
             f"(of {successes + failures} attempted)")
    log.info(f"results CSV: {RESULTS_CSV}")


if __name__ == "__main__":
    asyncio.run(main())
