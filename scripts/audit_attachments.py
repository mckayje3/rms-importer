"""Audit (and optionally repair) submittal file attachments.

For every file in the Procore upload folder, parse its name with the
Transmittal Log convention to derive the submittals it should be attached to.
Then GET each submittal and report any missing attachments. With `--apply`,
PATCH them back in.

Drives entirely off Procore + the Transmittal Log — doesn't touch the
baseline. The baseline tracks files by filename only and has no record of
which submittals each file is attached to (see `sync_service.py:510` TODO),
which is exactly why divergence accumulates.

Rate limits (per CLAUDE.md):
- Hourly:  3,600 req / 60 min
- Spike:   ~20-30 req / 10s — this is the one that trips first
- Pacing:  1 req/s, 30s backoff on 429, proactive token refresh every 75 min.

Usage:
  python audit_attachments.py                   # dry-run, writes CSV
  python audit_attachments.py --apply           # actually PATCH fixes
  python audit_attachments.py --limit 50        # first 50 files only
  python audit_attachments.py --resume          # skip files already processed
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

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_DIR = SCRIPT_DIR.parent
BACKEND_DIR = REPO_DIR / "backend"
PROJECT_FILES_DIR = REPO_DIR.parent / "project-files" / "submittals"

DB_PATH = BACKEND_DIR / "data" / "sync.db"
ENV_PATH = BACKEND_DIR / ".env"

# Backend's services/__init__.py imports procore_api at module load, which
# triggers Pydantic Settings validation. Hydrate env from .env before we
# touch any backend imports so that validation passes.
if ENV_PATH.exists():
    import os
    for k, v in dotenv_values(ENV_PATH).items():
        if v is not None:
            os.environ.setdefault(k, v)

# Make backend importable so we can reuse the parser + file-mapping logic.
sys.path.insert(0, str(BACKEND_DIR))
from services.rms_parser import RMSParser  # noqa: E402
from services.sync_service import SyncService  # noqa: E402
OUT_CSV = SCRIPT_DIR / "attachment_audit.csv"
PROGRESS_PATH = SCRIPT_DIR / ".attachment_audit_progress.json"

PROJECT_ID = 598134325988700  # Dobbins
DEFAULT_UPLOAD_FOLDER_ID = 598134439643352  # "03 Submittals"

DELAY_SEC = 1.0
RATE_LIMIT_BACKOFF_SEC = 30.0
TOKEN_REFRESH_INTERVAL_SEC = 75 * 60

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("attach-audit")


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
        sys.exit(f"no baseline for project {PROJECT_ID} in {DB_PATH}")
    return row[0]


def load_latest_session() -> str:
    conn = sqlite3.connect(DB_PATH)
    try:
        row = conn.execute(
            "SELECT session_id FROM sessions ORDER BY updated_at DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    if not row:
        sys.exit(f"no session in {DB_PATH} — log in via the app once to seed a session")
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


class _DirectToken:
    """Stand-in for TokenManager when --token is used. Never refreshes."""

    def __init__(self, headers: dict):
        self.headers = headers

    async def maybe_refresh(self) -> None:
        pass

    async def force_refresh(self) -> None:
        log.warning("Token expired and --token mode can't refresh. Re-run with a fresh token.")


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


async def api_get(
    client: httpx.AsyncClient,
    tokens: TokenManager,
    path: str,
    params: Optional[dict] = None,
):
    url = f"https://api.procore.com{path}"
    refreshed_for_401 = False
    for attempt in range(5):
        r = await client.get(url, headers=tokens.headers, params=params, timeout=30.0)
        if r.status_code == 429:
            log.warning(f"429 on GET {path}, sleeping {RATE_LIMIT_BACKOFF_SEC}s")
            await asyncio.sleep(RATE_LIMIT_BACKOFF_SEC)
            continue
        if r.status_code == 401 and not refreshed_for_401:
            log.warning(f"401 on GET {path}, refreshing token")
            await tokens.force_refresh()
            refreshed_for_401 = True
            continue
        if r.status_code == 404:
            return None
        if r.status_code >= 400:
            log.error(f"GET {path} -> {r.status_code}: {r.text[:200]}")
            return None
        return r.json()
    log.error(f"GET {path} failed after retries")
    return None


async def api_patch(
    client: httpx.AsyncClient,
    tokens: TokenManager,
    path: str,
    body: dict,
):
    url = f"https://api.procore.com{path}"
    refreshed_for_401 = False
    for attempt in range(5):
        r = await client.patch(url, headers=tokens.headers, json=body, timeout=30.0)
        if r.status_code == 429:
            log.warning(f"429 on PATCH {path}, sleeping {RATE_LIMIT_BACKOFF_SEC}s")
            await asyncio.sleep(RATE_LIMIT_BACKOFF_SEC)
            continue
        if r.status_code == 401 and not refreshed_for_401:
            await tokens.force_refresh()
            refreshed_for_401 = True
            continue
        if r.status_code >= 400:
            log.error(f"PATCH {path} -> {r.status_code}: {r.text[:300]}")
            return None
        return r.json() if r.text else {}
    log.error(f"PATCH {path} failed after retries")
    return None


async def list_upload_folder(
    client: httpx.AsyncClient, tokens: TokenManager, folder_id: int,
) -> dict[str, int]:
    """Returns {filename: prostore_file_id} for every file in the folder."""
    out: dict[str, int] = {}
    page = 1
    while True:
        await tokens.maybe_refresh()
        docs = await api_get(
            client, tokens,
            f"/rest/v1.0/projects/{PROJECT_ID}/documents",
            params={
                "view": "extended",
                "filters[document_type]": "file",
                "filters[parent_id]": folder_id,
                "per_page": 300,
                "page": page,
            },
        )
        if not docs:
            break
        for doc in docs:
            name = doc.get("name", "")
            prostore = (
                doc.get("file", {})
                .get("current_version", {})
                .get("prostore_file")
            )
            if name and prostore:
                out[name] = prostore["id"]
        if len(docs) < 300:
            break
        page += 1
        await asyncio.sleep(DELAY_SEC)
    return out


async def list_submittals(
    client: httpx.AsyncClient, tokens: TokenManager,
) -> dict[str, int]:
    """Returns {match_key: procore_id} where match_key = section|item|revision."""
    out: dict[str, int] = {}
    page = 1
    while True:
        await tokens.maybe_refresh()
        subs = await api_get(
            client, tokens,
            f"/rest/v1.0/projects/{PROJECT_ID}/submittals",
            params={"per_page": 100, "page": page},
        )
        if not subs:
            break
        for s in subs:
            ss = s.get("specification_section")
            if not ss:
                continue
            section = ss.get("number", "")
            try:
                item_no = int(s.get("number", ""))
            except (TypeError, ValueError):
                continue
            revision = int(s.get("revision", 0) or 0)
            if not section:
                continue
            key = f"{section}|{item_no}|{revision}"
            out[key] = s["id"]
        if len(subs) < 100:
            break
        page += 1
        await asyncio.sleep(DELAY_SEC)
    return out


def load_rms(register_path: Path, transmittal_path: Path):
    if not register_path.exists():
        sys.exit(f"register file not found: {register_path}")
    if not transmittal_path.exists():
        sys.exit(f"transmittal log not found: {transmittal_path}")
    parser = RMSParser()
    return parser.parse_all(
        register_report_bytes=register_path.read_bytes(),
        transmittal_report_bytes=transmittal_path.read_bytes(),
    )


def load_progress() -> set[str]:
    if not PROGRESS_PATH.exists():
        return set()
    try:
        return set(json.loads(PROGRESS_PATH.read_text()))
    except Exception:
        return set()


def save_progress(done: set[str]) -> None:
    PROGRESS_PATH.write_text(json.dumps(sorted(done)))


async def main():
    p = argparse.ArgumentParser()
    p.add_argument(
        "--register", type=Path,
        default=PROJECT_FILES_DIR / "Submittal Register.csv",
        help="Submittal Register CSV (default: project-files/submittals/...)",
    )
    p.add_argument(
        "--transmittal-log", type=Path,
        default=PROJECT_FILES_DIR / "Transmittal Log.csv",
        help="Transmittal Log CSV (default: project-files/submittals/...)",
    )
    p.add_argument(
        "--folder-id", type=int, default=DEFAULT_UPLOAD_FOLDER_ID,
        help=f"Procore upload folder ID (default: {DEFAULT_UPLOAD_FOLDER_ID})",
    )
    p.add_argument("--limit", type=int, default=None, help="process only the first N files")
    p.add_argument("--resume", action="store_true", help="skip files already in progress file")
    p.add_argument(
        "--apply", action="store_true",
        help="actually PATCH missing attachments (otherwise dry-run)",
    )
    p.add_argument(
        "--token", default=None,
        help="Bypass session lookup and use this Procore access token directly. "
             "Useful when the local sync.db's refresh_token has been consumed by "
             "prod. Get one by hitting the local /auth/me endpoint while logged in, "
             "or copy from prod browser dev tools.",
    )
    args = p.parse_args()

    log.info(f"loading RMS files: {args.register.name}, {args.transmittal_log.name}")
    rms_data = load_rms(args.register, args.transmittal_log)
    log.info(f"parsed {len(rms_data.transmittal_report)} Transmittal Log entries")

    company_id = load_company_id()
    headers = {
        "Authorization": "Bearer placeholder",
        "Procore-Company-Id": str(company_id),
        "Content-Type": "application/json",
    }
    if args.token:
        # Direct-token mode: no refresh, no session DB writes.
        headers["Authorization"] = f"Bearer {args.token}"
        tokens = _DirectToken(headers)
    else:
        env = load_env()
        session_id = load_latest_session()
        tokens = TokenManager(env, session_id, headers)
        await tokens.initial_refresh()

    async with httpx.AsyncClient() as client:
        log.info(f"listing upload folder {args.folder_id}")
        files_in_folder = await list_upload_folder(client, tokens, args.folder_id)
        log.info(f"found {len(files_in_folder)} files in upload folder")

        log.info("listing project submittals")
        sub_lookup = await list_submittals(client, tokens)
        log.info(f"found {len(sub_lookup)} submittals in Procore")

        # Reuse the production file-mapping logic so the audit matches what
        # the importer would do.
        svc = SyncService(str(PROJECT_ID), str(company_id), config=None)
        file_to_keys = svc.map_files_to_submittals(
            list(files_in_folder.keys()), rms_data,
        )
        mappable = sorted(f for f in files_in_folder if f in file_to_keys)
        unmappable = sorted(f for f in files_in_folder if f not in file_to_keys)
        log.info(
            f"{len(mappable)} files map to >=1 submittal via Transmittal Log "
            f"({len(unmappable)} unmappable — likely non-Transmittal-named files)"
        )

        done = load_progress() if args.resume else set()
        csv_mode = "a" if args.resume and OUT_CSV.exists() else "w"
        csv_file = OUT_CSV.open(csv_mode, newline="", encoding="utf-8")
        writer = csv.writer(csv_file)
        if csv_mode == "w":
            writer.writerow([
                "filename", "submittal_key", "procore_submittal_id",
                "prostore_file_id", "status", "action",
            ])

        files = mappable if args.limit is None else mappable[: args.limit]

        missing_total = 0
        applied_total = 0
        patch_failed = 0
        no_submittal = 0
        already_ok = 0
        fetch_errors = 0
        # Cache of submittal_id -> set of currently attached prostore_file_ids,
        # so multiple files mapping to the same submittal only cost one GET.
        sub_attachments: dict[int, set[int]] = {}

        for filename in files:
            if filename in done:
                continue

            prostore_id = files_in_folder[filename]
            keys = file_to_keys[filename]

            for key in keys:
                procore_id = sub_lookup.get(key)
                if not procore_id:
                    writer.writerow([filename, key, "", prostore_id, "no_submittal", ""])
                    csv_file.flush()
                    no_submittal += 1
                    continue

                if procore_id not in sub_attachments:
                    await tokens.maybe_refresh()
                    detail = await api_get(
                        client, tokens,
                        f"/rest/v1.0/projects/{PROJECT_ID}/submittals/{procore_id}",
                    )
                    await asyncio.sleep(DELAY_SEC)
                    if detail is None:
                        writer.writerow([
                            filename, key, procore_id, prostore_id,
                            "fetch_error", "",
                        ])
                        csv_file.flush()
                        fetch_errors += 1
                        continue
                    sub_attachments[procore_id] = {
                        att["id"] for att in detail.get("attachments", [])
                    }

                existing = sub_attachments[procore_id]
                if prostore_id in existing:
                    writer.writerow([
                        filename, key, procore_id, prostore_id,
                        "already_attached", "",
                    ])
                    csv_file.flush()
                    already_ok += 1
                    continue

                missing_total += 1
                if args.apply:
                    new_ids = list(existing) + [prostore_id]
                    result = await api_patch(
                        client, tokens,
                        f"/rest/v1.1/projects/{PROJECT_ID}/submittals/{procore_id}",
                        {"submittal": {"prostore_file_ids": new_ids}},
                    )
                    await asyncio.sleep(DELAY_SEC)
                    if result is not None:
                        existing.add(prostore_id)
                        applied_total += 1
                        writer.writerow([
                            filename, key, procore_id, prostore_id,
                            "missing", "attached",
                        ])
                    else:
                        patch_failed += 1
                        writer.writerow([
                            filename, key, procore_id, prostore_id,
                            "missing", "patch_failed",
                        ])
                else:
                    writer.writerow([
                        filename, key, procore_id, prostore_id,
                        "missing", "would_attach",
                    ])
                csv_file.flush()

            done.add(filename)
            if len(done) % 25 == 0:
                save_progress(done)
                log.info(
                    f"processed {len(done)}/{len(files)} files | "
                    f"missing={missing_total} attached={applied_total} "
                    f"ok={already_ok} no_sub={no_submittal} err={fetch_errors}"
                )

        csv_file.close()
        save_progress(done)

        log.info("done")
        log.info(f"  files processed:        {len(done)}")
        log.info(f"  submittals inspected:   {len(sub_attachments)}")
        log.info(f"  attachments OK:         {already_ok}")
        log.info(f"  attachments MISSING:    {missing_total}")
        if args.apply:
            log.info(f"  patched OK:           {applied_total}")
            log.info(f"  patch failures:       {patch_failed}")
        log.info(f"  no matching submittal:  {no_submittal}")
        log.info(f"  submittal fetch errors: {fetch_errors}")
        log.info(f"  CSV: {OUT_CSV}")
        if not args.apply and missing_total > 0:
            log.info("Dry-run. Re-run with --apply to PATCH the missing attachments.")


if __name__ == "__main__":
    asyncio.run(main())
