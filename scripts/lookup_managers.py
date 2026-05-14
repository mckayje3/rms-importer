"""Read-only: find Procore user IDs for Josh and Michael, and count submittals
currently assigned to Michael as submittal manager.

Does NOT write to Procore. Just resolves IDs and totals so the bulk reassignment
script can run with a confirmed scope.
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
import time
from pathlib import Path
from typing import Optional

import httpx
from dotenv import dotenv_values

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent / "backend"
DB_PATH = BACKEND_DIR / "sync.db"
ENV_PATH = BACKEND_DIR / ".env"

PROJECT_ID = 598134325988700  # Dobbins

JOSH_EMAIL = "josh.mckay@globalgo.com"
MICHAEL_EMAIL = "michael.seligman@globalgo.com"

DELAY_SEC = 1.0


def load_env() -> dict:
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


def load_latest_session() -> tuple[str, dict]:
    conn = sqlite3.connect(DB_PATH)
    try:
        row = conn.execute(
            "SELECT session_id, token_data FROM sessions ORDER BY updated_at DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    if not row:
        sys.exit("no session in sync.db — log in via the app once")
    return row[0], json.loads(row[1])


def save_session_token(session_id: str, token_data: dict) -> None:
    from datetime import datetime
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


async def refresh_token(env: dict, session_id: str) -> str:
    conn = sqlite3.connect(DB_PATH)
    try:
        row = conn.execute(
            "SELECT token_data FROM sessions WHERE session_id=?", (session_id,)
        ).fetchone()
    finally:
        conn.close()
    if not row:
        sys.exit("session missing")
    tok = json.loads(row[0])
    async with httpx.AsyncClient() as c:
        r = await c.post(
            "https://login.procore.com/oauth/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": tok["refresh_token"],
                "client_id": env["PROCORE_CLIENT_ID"],
                "client_secret": env["PROCORE_CLIENT_SECRET"],
            },
        )
    if r.status_code != 200:
        sys.exit(f"refresh failed: {r.status_code} {r.text[:200]}")
    new = r.json()
    save_session_token(session_id, new)
    return new["access_token"]


async def get_paged(client: httpx.AsyncClient, url: str, headers: dict, params: Optional[dict] = None) -> list[dict]:
    """Page through a Procore list endpoint, returning all items."""
    results: list[dict] = []
    page = 1
    per_page = 100
    while True:
        p = dict(params or {})
        p["page"] = page
        p["per_page"] = per_page
        for attempt in range(5):
            r = await client.get(url, headers=headers, params=p, timeout=30.0)
            if r.status_code == 429:
                print(f"  429 — sleep 30s and retry (attempt {attempt + 1})")
                await asyncio.sleep(30)
                continue
            break
        if r.status_code >= 400:
            print(f"  ERROR {r.status_code}: {r.text[:300]}")
            r.raise_for_status()
        batch = r.json()
        if not isinstance(batch, list) or not batch:
            break
        results.extend(batch)
        if len(batch) < per_page:
            break
        page += 1
        await asyncio.sleep(DELAY_SEC)
    return results


async def main():
    env = load_env()
    company_id = load_company_id()
    session_id, _ = load_latest_session()
    token = await refresh_token(env, session_id)
    print(f"company {company_id}, session {session_id[:8]}…, token refreshed")

    headers = {
        "Authorization": f"Bearer {token}",
        "Procore-Company-Id": str(company_id),
    }

    async with httpx.AsyncClient() as client:
        # 1) Current submittal-manager filter options (people who have managed at least one submittal)
        print("\n--- Submittal Manager filter options ---")
        opts = await get_paged(
            client,
            f"https://api.procore.com/rest/v1.0/projects/{PROJECT_ID}/submittals/filter_options/submittal_manager_id",
            headers,
        )
        for o in opts:
            print(f"  id={o.get('key')}  name={o.get('value')!r}")

        # 2) Look up users via /projects/{id}/users to find Josh by email (and confirm Michael's id)
        print("\n--- Project users (matching by email) ---")
        users = await get_paged(
            client,
            f"https://api.procore.com/rest/v1.0/projects/{PROJECT_ID}/users",
            headers,
        )
        print(f"  fetched {len(users)} users")
        josh = None
        michael = None
        for u in users:
            email = (u.get("email_address") or u.get("login") or "").lower()
            if email == JOSH_EMAIL.lower():
                josh = u
            if email == MICHAEL_EMAIL.lower():
                michael = u
        print(f"  Josh:    {josh and {'id': josh.get('id'), 'name': josh.get('name'), 'email': josh.get('email_address') or josh.get('login')}}")
        print(f"  Michael: {michael and {'id': michael.get('id'), 'name': michael.get('name'), 'email': michael.get('email_address') or michael.get('login')}}")

        if not michael:
            sys.exit("Michael not found in project users — aborting")
        if not josh:
            sys.exit("Josh not found in project users — aborting")

        # 3) Count submittals currently filtered by Michael as manager
        print(f"\n--- Submittals filtered by submittal_manager_id={michael['id']} (Michael) ---")
        subs = await get_paged(
            client,
            f"https://api.procore.com/rest/v1.0/projects/{PROJECT_ID}/submittals",
            headers,
            params={"filters[submittal_manager_id]": michael["id"]},
        )
        print(f"  total: {len(subs)} submittals managed by Michael")
        # Sample a few to sanity-check the filter is working
        for s in subs[:5]:
            mgr = s.get("submittal_manager") or {}
            print(f"    #{s.get('number')!r} title={s.get('title')[:60]!r} manager={mgr.get('name')!r} (id {mgr.get('id')})")

        # Also count Josh's current (should likely be near zero)
        josh_subs = await get_paged(
            client,
            f"https://api.procore.com/rest/v1.0/projects/{PROJECT_ID}/submittals",
            headers,
            params={"filters[submittal_manager_id]": josh["id"]},
        )
        print(f"  (for reference) {len(josh_subs)} submittals already managed by Josh")

        # Persist findings for the reassignment script to consume
        out = SCRIPT_DIR / "reassign_manager_lookup.json"
        out.write_text(json.dumps({
            "project_id": PROJECT_ID,
            "company_id": company_id,
            "josh": {"id": josh["id"], "name": josh.get("name"), "email": josh.get("email_address") or josh.get("login")},
            "michael": {"id": michael["id"], "name": michael.get("name"), "email": michael.get("email_address") or michael.get("login")},
            "submittal_ids_managed_by_michael": [s["id"] for s in subs],
        }, indent=2))
        print(f"\nwrote {out}")


if __name__ == "__main__":
    asyncio.run(main())
