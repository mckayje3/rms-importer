#!/usr/bin/env python3
"""
Get-ProcoreSubmittal — pull submittal metadata + attachments out of Procore
and stage them locally for entry into RMS (USACE Resident Management System).

Usage:
    # By spec section + item numbers (most common)
    python get_procore_submittal.py --spec-section "10 22 39" --items 9 10

    # By Procore submittal ID(s) (fastest, no search)
    python get_procore_submittal.py --submittal-ids 12345 12346

    # By full submittal "number" string (whatever shows in the Number column)
    python get_procore_submittal.py --numbers "10 22 39-9" "10 22 39-10"

    # Just refresh the stored token (useful for cron / scheduled tasks)
    python get_procore_submittal.py --auth-only

First run opens your browser to log in to Procore. The OAuth refresh token is
saved to scripts/.procore_token.json (gitignored) and reused on every
subsequent run, so this is a one-time step per machine.

Output: each matched submittal gets its own subfolder under --output, named
"<number> - <title>", containing every attachment plus a metadata.json file
with all the fields you'd need to type into RMS.
"""
from __future__ import annotations

import argparse
import http.server
import json
import logging
import os
import re
import secrets
import socket
import sys
import threading
import time
import urllib.parse
import urllib.request
import urllib.error
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
ENV_FILE = REPO_ROOT / "backend" / ".env"
TOKEN_FILE = SCRIPT_DIR / ".procore_token.json"

PROCORE_BASE_URL = "https://api.procore.com"
PROCORE_AUTH_URL = "https://login.procore.com/oauth/token"
PROCORE_AUTHORIZE_URL = "https://login.procore.com/oauth/authorize"
REDIRECT_URI = "http://localhost:8000/auth/callback"
CALLBACK_HOST = "localhost"
CALLBACK_PORT = 8000

# Dobbins project (from rms-importer baselines table). Override with
# --project-id / --company-id if you ever run this against a different job.
DEFAULT_PROJECT_ID = 598134325988700
DEFAULT_COMPANY_ID = 598134325694431

DEFAULT_OUTPUT_DIR = Path(
    r"C:\Users\mckay\Documents\MBS\GlobalGo\Dobbins\project-files\submittals\temp-procore"
)

# Procore rate-limit guard. CLAUDE.md says ~20-30 req/10s spike limit;
# 1.0s between calls keeps us comfortably under it.
API_DELAY_SECONDS = 1.0

# Filename characters Windows doesn't allow.
_ILLEGAL_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|]')

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("procore-fetch")


# ---------------------------------------------------------------------------
# .env loader (no python-dotenv dependency)
# ---------------------------------------------------------------------------
def load_env(path: Path) -> dict[str, str]:
    """Tiny KEY=VALUE parser for backend/.env. Ignores comments and blanks."""
    if not path.is_file():
        raise FileNotFoundError(f"Could not find env file: {path}")
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


# ---------------------------------------------------------------------------
# OAuth: code flow + refresh
# ---------------------------------------------------------------------------
class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    """One-shot HTTP handler that captures ?code=... from Procore's redirect."""

    captured: dict[str, str] = {}
    expected_state: str = ""

    def do_GET(self) -> None:  # noqa: N802 (BaseHTTPRequestHandler API)
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/auth/callback":
            self.send_response(404)
            self.end_headers()
            return

        qs = urllib.parse.parse_qs(parsed.query)
        code = (qs.get("code") or [""])[0]
        state = (qs.get("state") or [""])[0]
        error = (qs.get("error") or [""])[0]

        if error:
            self.captured["error"] = error
            body = f"<h2>Procore returned an error: {error}</h2>"
        elif state != self.expected_state:
            self.captured["error"] = "state_mismatch"
            body = "<h2>OAuth state mismatch — aborting.</h2>"
        elif not code:
            self.captured["error"] = "missing_code"
            body = "<h2>No authorization code received.</h2>"
        else:
            self.captured["code"] = code
            body = (
                "<h2>Authorization received.</h2>"
                "<p>You can close this tab and return to the script.</p>"
            )

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))

    def log_message(self, fmt: str, *args: Any) -> None:  # silence default logging
        return


def _port_is_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def run_oauth_code_flow(client_id: str, client_secret: str) -> dict:
    """One-time browser OAuth. Returns the full token payload from Procore."""
    if not _port_is_free(CALLBACK_HOST, CALLBACK_PORT):
        raise RuntimeError(
            f"Port {CALLBACK_PORT} is in use. If your dev backend is running "
            "(start_dev.ps1), stop it before running OAuth, then start it again."
        )

    state = secrets.token_urlsafe(32)
    _CallbackHandler.captured = {}
    _CallbackHandler.expected_state = state

    server = http.server.HTTPServer((CALLBACK_HOST, CALLBACK_PORT), _CallbackHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    auth_url = (
        f"{PROCORE_AUTHORIZE_URL}"
        f"?client_id={urllib.parse.quote(client_id)}"
        f"&response_type=code"
        f"&redirect_uri={urllib.parse.quote(REDIRECT_URI)}"
        f"&state={state}"
    )
    log.info("Opening browser for Procore login…")
    log.info("If it doesn't open, paste this URL manually:\n  %s", auth_url)
    webbrowser.open(auth_url)

    # Wait up to 5 minutes for the user to complete the login
    deadline = time.time() + 300
    try:
        while time.time() < deadline:
            if _CallbackHandler.captured:
                break
            time.sleep(0.25)
    finally:
        server.shutdown()
        server.server_close()

    captured = _CallbackHandler.captured
    if "error" in captured:
        raise RuntimeError(f"OAuth failed: {captured['error']}")
    if "code" not in captured:
        raise RuntimeError("OAuth timed out (no callback in 5 minutes)")

    code = captured["code"]
    log.info("Authorization code received — exchanging for tokens…")

    token = _post_form(
        PROCORE_AUTH_URL,
        {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": REDIRECT_URI,
        },
    )
    token["_obtained_at"] = int(time.time())
    return token


def refresh_oauth_token(client_id: str, client_secret: str, refresh_token: str) -> dict:
    """Exchange a refresh_token for a new access_token + refresh_token."""
    token = _post_form(
        PROCORE_AUTH_URL,
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
            "client_secret": client_secret,
        },
    )
    token["_obtained_at"] = int(time.time())
    return token


def _post_form(url: str, fields: dict[str, str]) -> dict:
    """POST application/x-www-form-urlencoded and return parsed JSON."""
    data = urllib.parse.urlencode(fields).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"OAuth POST {url} → {e.code}: {body}") from None


def load_or_obtain_token(client_id: str, client_secret: str) -> str:
    """Load a stored token, refreshing or re-authing as needed.

    Returns a valid access_token string.
    """
    token: Optional[dict] = None
    if TOKEN_FILE.is_file():
        try:
            token = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            log.warning("Couldn't read %s (%s) — starting fresh OAuth", TOKEN_FILE, e)
            token = None

    if token and token.get("refresh_token"):
        # Refresh on every run — cheap, and avoids racing the access_token's TTL.
        try:
            log.info("Refreshing stored access token…")
            token = refresh_oauth_token(
                client_id, client_secret, token["refresh_token"]
            )
            _save_token(token)
            return token["access_token"]
        except Exception as e:
            log.warning("Refresh failed (%s) — falling back to full OAuth", e)

    log.info("No usable token on disk — starting one-time browser OAuth")
    token = run_oauth_code_flow(client_id, client_secret)
    _save_token(token)
    return token["access_token"]


def _save_token(token: dict) -> None:
    TOKEN_FILE.write_text(json.dumps(token, indent=2), encoding="utf-8")
    try:
        # Best-effort permission tighten on POSIX; no-op on Windows.
        os.chmod(TOKEN_FILE, 0o600)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Procore API helpers
# ---------------------------------------------------------------------------
class Procore:
    def __init__(self, access_token: str, company_id: int):
        self.access_token = access_token
        self.company_id = company_id

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Procore-Company-Id": str(self.company_id),
        }

    def get_json(self, endpoint: str, params: Optional[dict] = None) -> Any:
        url = PROCORE_BASE_URL + endpoint
        if params:
            url += "?" + urllib.parse.urlencode(params, doseq=True)

        req = urllib.request.Request(url, headers=self._headers(), method="GET")
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = resp.read().decode("utf-8")
                return json.loads(body) if body else None
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"GET {endpoint} → {e.code}: {body}") from None
        finally:
            time.sleep(API_DELAY_SECONDS)

    def get_paginated(
        self, endpoint: str, params: Optional[dict] = None, per_page: int = 100
    ) -> list:
        all_items: list = []
        page = 1
        params = dict(params or {})
        while True:
            params["page"] = page
            params["per_page"] = per_page
            items = self.get_json(endpoint, params)
            if not items:
                break
            all_items.extend(items)
            if len(items) < per_page:
                break
            page += 1
        return all_items

    def list_submittals(self, project_id: int, query: Optional[str] = None) -> list:
        params: dict = {}
        if query:
            params["filters[query]"] = query
        return self.get_paginated(
            f"/rest/v1.0/projects/{project_id}/submittals", params
        )

    def get_submittal_detail(self, project_id: int, submittal_id: int) -> dict:
        # v1.1 returns the richer payload (custom_fields, attachments, etc.)
        return self.get_json(
            f"/rest/v1.1/projects/{project_id}/submittals/{submittal_id}"
        )


# ---------------------------------------------------------------------------
# Submittal selection logic
# ---------------------------------------------------------------------------
def _matches_spec_section(sub: dict, target: str) -> bool:
    sec = sub.get("specification_section")
    if not sec:
        return False
    return str(sec.get("number") or "").strip() == target.strip()


def _matches_item_number(sub: dict, items: list[int]) -> bool:
    n = sub.get("number")
    try:
        return int(str(n)) in items
    except (TypeError, ValueError):
        return False


def find_submittals_by_spec_and_items(
    api: Procore, project_id: int, spec_section: str, items: list[int]
) -> list[dict]:
    """Use Procore's text-search to narrow, then filter precisely client-side."""
    log.info(
        "Searching Dobbins for submittals on '%s' (items %s)…",
        spec_section,
        ", ".join(str(i) for i in items),
    )
    candidates = api.list_submittals(project_id, query=spec_section)
    log.info("  query returned %d candidate(s)", len(candidates))

    matches = [
        s
        for s in candidates
        if _matches_spec_section(s, spec_section) and _matches_item_number(s, items)
    ]
    return matches


# ---------------------------------------------------------------------------
# Download + write
# ---------------------------------------------------------------------------
def _safe_filename(name: str) -> str:
    cleaned = _ILLEGAL_FILENAME_CHARS.sub("_", name).rstrip(". ").strip()
    return cleaned or "untitled"


def _attachment_url(att: dict) -> Optional[str]:
    """Procore attachments expose download URLs under a few possible keys."""
    for key in ("url", "download_url", "file_url"):
        if att.get(key):
            return att[key]
    versions = att.get("file_versions") or []
    if versions and isinstance(versions[0], dict) and versions[0].get("url"):
        return versions[0]["url"]
    return None


def download_attachment(att: dict, dest_dir: Path) -> Optional[Path]:
    name = _safe_filename(att.get("filename") or att.get("name") or f"attachment-{att.get('id')}")
    url = _attachment_url(att)
    if not url:
        log.warning("  Attachment '%s' has no download URL — skipping", name)
        return None

    target = dest_dir / name
    if target.exists():
        log.info("  ↪ already on disk: %s", name)
        return target

    log.info("  ↓ downloading %s", name)
    # Procore's signed S3 URLs don't need our auth header; using urlopen is fine.
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=120) as resp, open(target, "wb") as out:
        while True:
            chunk = resp.read(64 * 1024)
            if not chunk:
                break
            out.write(chunk)
    return target


def write_metadata(sub: dict, dest_dir: Path) -> Path:
    """Write the raw submittal payload + a flattened summary for RMS entry."""
    raw_path = dest_dir / "procore_raw.json"
    raw_path.write_text(json.dumps(sub, indent=2, default=str), encoding="utf-8")

    summary_path = dest_dir / "metadata.json"
    summary = {
        "procore_id": sub.get("id"),
        "number": sub.get("number"),
        "title": sub.get("title"),
        "revision": sub.get("revision"),
        "status": (sub.get("status") or {}).get("status") if isinstance(sub.get("status"), dict) else sub.get("status"),
        "specification_section": (sub.get("specification_section") or {}).get("number"),
        "spec_description": (sub.get("specification_section") or {}).get("description"),
        "submittal_type": (sub.get("type") or {}).get("name") if isinstance(sub.get("type"), dict) else sub.get("type"),
        "responsible_contractor": (sub.get("responsible_contractor") or {}).get("name") if isinstance(sub.get("responsible_contractor"), dict) else None,
        "submit_by_date": sub.get("submit_by_date"),
        "due_date": sub.get("due_date"),
        "received_date": sub.get("received_date") or sub.get("received_from_submitter_date"),
        "issued_date": sub.get("issued_date"),
        "ball_in_court": [bic.get("name") for bic in (sub.get("ball_in_court") or []) if isinstance(bic, dict)],
        "description": sub.get("description"),
        "attachments": [
            {
                "id": a.get("id"),
                "filename": a.get("filename") or a.get("name"),
                "size": a.get("size"),
            }
            for a in (sub.get("attachments") or [])
        ],
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary_path


def submittal_folder_name(sub: dict) -> str:
    num = sub.get("number") or sub.get("id")
    title = sub.get("title") or "untitled"
    spec = (sub.get("specification_section") or {}).get("number") or ""
    base = f"{spec} - {num} - {title}".strip(" -")
    return _safe_filename(base)[:120]


def process_submittal(api: Procore, project_id: int, sub_summary: dict, output_root: Path) -> None:
    sid = sub_summary["id"]
    log.info(
        "→ Submittal %s '%s' (id %s)",
        sub_summary.get("number"),
        sub_summary.get("title"),
        sid,
    )
    detail = api.get_submittal_detail(project_id, sid)

    folder = output_root / submittal_folder_name(detail)
    folder.mkdir(parents=True, exist_ok=True)

    write_metadata(detail, folder)

    attachments = detail.get("attachments") or []
    log.info("  %d attachment(s) on this submittal", len(attachments))
    downloaded: list[Path] = []
    for att in attachments:
        path = download_attachment(att, folder)
        if path:
            downloaded.append(path)

    log.info("  → %s (%d files)", folder, len(downloaded))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Pull Procore submittals + attachments locally for RMS entry.")
    sel = p.add_argument_group("selection (pick one)")
    sel.add_argument("--spec-section", help='e.g. "10 22 39"')
    sel.add_argument("--items", nargs="+", type=int, help="Item numbers, e.g. 9 10")
    sel.add_argument("--submittal-ids", nargs="+", type=int, help="Procore submittal IDs")
    sel.add_argument("--numbers", nargs="+", help='Full submittal numbers, e.g. "10 22 39-9"')
    sel.add_argument("--auth-only", action="store_true", help="Just refresh/obtain token and exit")

    p.add_argument("--project-id", type=int, default=DEFAULT_PROJECT_ID)
    p.add_argument("--company-id", type=int, default=DEFAULT_COMPANY_ID)
    p.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_DIR)
    return p.parse_args()


def main() -> int:
    args = parse_args()

    env = load_env(ENV_FILE)
    client_id = env.get("PROCORE_CLIENT_ID")
    client_secret = env.get("PROCORE_CLIENT_SECRET")
    if not client_id or not client_secret:
        log.error("PROCORE_CLIENT_ID / PROCORE_CLIENT_SECRET missing from %s", ENV_FILE)
        return 2

    access_token = load_or_obtain_token(client_id, client_secret)
    if args.auth_only:
        log.info("Auth refreshed. Token saved to %s", TOKEN_FILE)
        return 0

    api = Procore(access_token, args.company_id)
    args.output.mkdir(parents=True, exist_ok=True)
    log.info("Output folder: %s", args.output)

    # Resolve which submittals to fetch
    targets: list[dict] = []

    if args.submittal_ids:
        for sid in args.submittal_ids:
            targets.append({"id": sid, "number": None, "title": "(by-id)"})

    elif args.numbers:
        # Expand each "number" string into an id by listing+filtering.
        for num in args.numbers:
            log.info("Resolving submittal number '%s'…", num)
            hits = api.list_submittals(args.project_id, query=num)
            for s in hits:
                if str(s.get("number")) == str(num).split("-")[-1].strip():
                    # Best-effort: full-string compare on the displayed Number column
                    targets.append(s)
                    break
            else:
                log.warning("  No exact match for '%s'", num)

    elif args.spec_section and args.items:
        targets = find_submittals_by_spec_and_items(
            api, args.project_id, args.spec_section, args.items
        )

    else:
        log.error(
            "Pick a selection: --spec-section + --items, OR --submittal-ids, "
            "OR --numbers, OR --auth-only."
        )
        return 2

    if not targets:
        log.error("No submittals matched. Nothing to download.")
        return 1

    log.info("Matched %d submittal(s):", len(targets))
    for t in targets:
        log.info(
            "  • #%s  '%s'  (id %s)",
            t.get("number"),
            t.get("title"),
            t.get("id"),
        )

    for t in targets:
        try:
            process_submittal(api, args.project_id, t, args.output)
        except Exception as e:
            log.error("Failed on submittal id %s: %s", t.get("id"), e)

    log.info("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
