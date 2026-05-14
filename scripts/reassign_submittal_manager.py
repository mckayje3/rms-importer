"""Bulk-reassign submittal manager from Michael Seligman → Josh McKay.

Reads `reassign_manager_lookup.json` (produced by lookup_managers.py) for the
list of submittal IDs to PATCH. Writes a progress file so the run is resumable.

Rate-limit strategy (per CLAUDE.md):
- Hourly: 3,600 req / 60 min  → 2s/call → 1,800 calls/hr (safe)
- Spike:  ~20-30 req / 10s     → 2s/call stays well under
- 429 → sleep 30s and retry (up to 4 times)
- Proactive token refresh every 75 min

Usage:
    python reassign_submittal_manager.py --dry-run        # first, print plan only
    python reassign_submittal_manager.py --confirm        # actually PATCH
    python reassign_submittal_manager.py --confirm --resume  # skip already-done
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
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx
from dotenv import dotenv_values

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("reassign")

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent / "backend"
DB_PATH = BACKEND_DIR / "sync.db"
ENV_PATH = BACKEND_DIR / ".env"
LOOKUP_PATH = SCRIPT_DIR / "reassign_manager_lookup.json"
PROGRESS_PATH = SCRIPT_DIR / ".reassign_progress.json"
RESULTS_CSV = SCRIPT_DIR / "reassign_results.csv"

DELAY_SEC = 3.0
# Per-retry 429 backoff. Starts at 1 min and escalates so we can ride out an
# exhausted hourly window without burning all retries in <3 minutes (which is
# what happened with a flat 30s × 5 schedule).
RATE_LIMIT_BACKOFFS_SEC = [60, 300, 600, 900, 1200]
MAX_RETRIES = len(RATE_LIMIT_BACKOFFS_SEC)
TOKEN_REFRESH_INTERVAL_SEC = 75 * 60


def load_env() -> dict:
    env = dotenv_values(ENV_PATH)
    for k in ("PROCORE_CLIENT_ID", "PROCORE_CLIENT_SECRET"):
        if not env.get(k):
            sys.exit(f"{k} not set in {ENV_PATH}")
    return env


def load_session() -> tuple[str, dict]:
    conn = sqlite3.connect(DB_PATH)
    try:
        row = conn.execute(
            "SELECT session_id, token_data FROM sessions ORDER BY updated_at DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    if not row:
        sys.exit("no session — log in via the app once")
    return row[0], json.loads(row[1])


def save_session_token(session_id: str, token_data: dict) -> None:
    conn = sqlite3.connect(DB_PATH)
    try:
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


def load_session_token(session_id: str) -> Optional[dict]:
    conn = sqlite3.connect(DB_PATH)
    try:
        row = conn.execute(
            "SELECT token_data FROM sessions WHERE session_id=?", (session_id,),
        ).fetchone()
    finally:
        conn.close()
    return json.loads(row[0]) if row else None


class TokenManager:
    def __init__(self, env: dict, session_id: str, headers: dict):
        self.env = env
        self.session_id = session_id
        self.headers = headers
        self.last_refresh_at: float = 0.0

    async def initial_refresh(self) -> None:
        tok = load_session_token(self.session_id) or {}
        await self._refresh(tok)

    async def maybe_refresh(self) -> None:
        if time.monotonic() - self.last_refresh_at >= TOKEN_REFRESH_INTERVAL_SEC:
            log.info("proactive token refresh (interval reached)")
            await self._refresh(load_session_token(self.session_id) or {})

    async def force_refresh(self) -> None:
        await self._refresh(load_session_token(self.session_id) or {})

    async def _refresh(self, tok: dict) -> None:
        refresh = tok.get("refresh_token")
        if not refresh:
            sys.exit("session has no refresh_token — log in via the app to reseed")
        async with httpx.AsyncClient() as c:
            r = await c.post(
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


def load_progress() -> set[int]:
    if not PROGRESS_PATH.exists():
        return set()
    try:
        return set(json.loads(PROGRESS_PATH.read_text()))
    except Exception:
        return set()


def save_progress(done: set[int]) -> None:
    PROGRESS_PATH.write_text(json.dumps(sorted(done)))


async def patch_submittal_manager(
    client: httpx.AsyncClient, tokens: TokenManager, project_id: int, sub_id: int, new_mgr_id: int,
) -> tuple[bool, str]:
    """Returns (success, message). Logs but doesn't raise on hard failure."""
    url = f"https://api.procore.com/rest/v1.0/projects/{project_id}/submittals/{sub_id}"
    body = {"submittal": {"submittal_manager_id": new_mgr_id}}
    refreshed_for_401 = False
    backoff_idx = 0
    for attempt in range(MAX_RETRIES + 1):
        r = await client.patch(url, headers=tokens.headers, json=body, timeout=30.0)
        if r.status_code == 429:
            sleep_s = RATE_LIMIT_BACKOFFS_SEC[min(backoff_idx, len(RATE_LIMIT_BACKOFFS_SEC) - 1)]
            backoff_idx += 1
            log.warning(f"429 on {sub_id}, sleep {sleep_s}s (try {attempt + 1})")
            await asyncio.sleep(sleep_s)
            continue
        if r.status_code == 401 and not refreshed_for_401:
            log.warning(f"401 on {sub_id}, refreshing token and retrying")
            await tokens.force_refresh()
            refreshed_for_401 = True
            continue
        if r.status_code >= 400:
            return False, f"{r.status_code} {r.text[:300]}"
        # Verify the server actually changed the manager (some Procore PATCHes silently no-op).
        try:
            data = r.json()
            actual = (data.get("submittal_manager") or {}).get("id")
            if actual != new_mgr_id:
                return False, f"silent no-op (response manager id={actual}, wanted {new_mgr_id})"
        except Exception:
            pass
        return True, "ok"
    return False, "exhausted retries"


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="print plan but don't PATCH")
    ap.add_argument("--confirm", action="store_true", help="actually PATCH (required to run without --dry-run)")
    ap.add_argument("--resume", action="store_true", help="skip submittal IDs already in progress file")
    ap.add_argument("--limit", type=int, default=None, help="only process the first N IDs (testing)")
    args = ap.parse_args()

    if not args.dry_run and not args.confirm:
        sys.exit("must pass --dry-run or --confirm")

    if not LOOKUP_PATH.exists():
        sys.exit(f"missing {LOOKUP_PATH} — run lookup_managers.py first")
    lookup = json.loads(LOOKUP_PATH.read_text())
    project_id = lookup["project_id"]
    company_id = lookup["company_id"]
    josh = lookup["josh"]
    michael = lookup["michael"]
    sub_ids: list[int] = lookup["submittal_ids_managed_by_michael"]

    if args.limit:
        sub_ids = sub_ids[: args.limit]

    done = load_progress() if args.resume else set()
    remaining = [s for s in sub_ids if s not in done]

    print(f"\nproject:  {project_id}")
    print(f"company:  {company_id}")
    print(f"from:     {michael['name']} (id {michael['id']})")
    print(f"to:       {josh['name']} (id {josh['id']})")
    print(f"total:    {len(sub_ids)} submittals in lookup file")
    print(f"already:  {len(done)} marked done")
    print(f"todo:     {len(remaining)} this run")
    eta_min = (len(remaining) * DELAY_SEC) / 60
    print(f"eta:      ~{eta_min:.1f} min at {DELAY_SEC}s/call (excluding 429 backoffs)")
    print()

    if args.dry_run:
        print("dry run — no changes will be made")
        return

    # Open results CSV
    csv_mode = "a" if RESULTS_CSV.exists() and args.resume else "w"
    csv_file = RESULTS_CSV.open(csv_mode, newline="", encoding="utf-8")
    writer = csv.writer(csv_file)
    if csv_mode == "w":
        writer.writerow(["timestamp", "submittal_id", "status", "message"])

    env = load_env()
    session_id, _ = load_session()
    headers = {
        "Authorization": "Bearer placeholder",
        "Procore-Company-Id": str(company_id),
    }
    tokens = TokenManager(env, session_id, headers)
    await tokens.initial_refresh()

    ok_count = 0
    fail_count = 0
    started = time.monotonic()

    async with httpx.AsyncClient() as client:
        for i, sub_id in enumerate(remaining, start=1):
            await tokens.maybe_refresh()
            success, msg = await patch_submittal_manager(client, tokens, project_id, sub_id, josh["id"])
            ts = datetime.utcnow().isoformat()
            writer.writerow([ts, sub_id, "ok" if success else "fail", msg])
            csv_file.flush()
            if success:
                ok_count += 1
                done.add(sub_id)
            else:
                fail_count += 1
                log.error(f"FAIL {sub_id}: {msg}")

            if i % 25 == 0:
                save_progress(done)
                elapsed = time.monotonic() - started
                rate = i / elapsed if elapsed else 0
                eta = (len(remaining) - i) / rate if rate else 0
                log.info(
                    f"  {i}/{len(remaining)}  ok={ok_count} fail={fail_count}  "
                    f"({rate:.2f}/s, eta {eta/60:.1f} min)"
                )

            await asyncio.sleep(DELAY_SEC)

    csv_file.close()
    save_progress(done)
    log.info(f"\nDONE — ok={ok_count} fail={fail_count} of {len(remaining)} attempted")
    log.info(f"results: {RESULTS_CSV}")


if __name__ == "__main__":
    asyncio.run(main())
