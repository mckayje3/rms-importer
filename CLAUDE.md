# RMS Importer (App Context)

This file is loaded in addition to the root `CLAUDE.md` when working inside `rms-importer/`. It covers the web app and all Procore API knowledge.

## Tech Stack
- **Backend**: Python 3.12+ / FastAPI (`backend/`) — `main.py`, `routers/`, `services/`, `models/`
- **Frontend**: Next.js / TypeScript (`frontend/`)
- **Database**: SQLite — `backend/data/sync.db` locally, Railway volume in prod
- **Run locally**: `.\start_dev.ps1` (opens both servers); see `README.md` for full setup
- **Scripts**: `scripts/` — standalone PowerShell utilities (e.g., `Export-SubmittalsByContractor*.ps1`)

## Technical Notes
- When automating Excel with PowerShell COM, always kill orphaned Excel processes before running scripts
- Use `Stop-Process -Name Excel -Force -ErrorAction SilentlyContinue` before opening files
- Always release COM objects and call `$excel.Quit()` when done

### Procore Custom Field Format (CRITICAL)
Custom fields on submittals must be **top-level properties** on the `submittal` object:
```json
{ "submittal": { "custom_field_598134325870420": "value" } }
```
**NOT** nested under `custom_fields`:
```json
{ "submittal": { "custom_fields": { "custom_field_598134325870420": "value" } } }
```
The nested format is silently ignored by the API — no error, values just don't save.

For LOV (dropdown) fields, send the integer LOV entry ID directly. For datetime fields, send ISO format `"2025-01-29T00:00:00Z"`.

### Procore Spec Section Numbering
The "Include Spec Section Number in Submittals Numbering" setting is **display-only**. The API always stores/returns plain integer `number` values regardless of this setting. No app changes needed.

### Procore Specifications API Limitations
- Spec PDFs are stored in the Specifications tool, separate from Documents
- No API endpoint to list, download, or manage spec section PDFs
- `/specification_uploads` returns metadata only (no file URLs)
- `/specification_sections` returns 404 — sections are only accessible embedded in submittals
- Workaround: split source PDFs locally and upload to Documents folder for linkability

### Procore API Rate Limits
Procore enforces **two separate rate limits** — scripts must respect both:
- **Hourly limit**: 3,600 requests per 60-minute sliding window
- **Spike limit**: ~20-30 requests per 10-second sliding window (this is the one that usually hits first)

**Rules for all Procore scripts:**
- Use `-DelayMs 2000` (2 seconds) minimum between API calls
- Dry runs still consume API calls (GETs count)
- Multiple scripts in the same hour share the same budget
- On 429 errors, wait and retry — don't just skip
- See `rms-importer/docs/submittal-migration.md` for full rate limit strategy

### Procore RFI API (Confirmed April 2026)
- **Endpoint**: `POST /rest/v1.0/projects/{id}/rfis` (v1.0, NOT v1.1)
- **Required fields**: `subject`, `rfi_manager_id`, `assignee_ids` (array), `question` (object with `body`)
- **Question format**: `"question": {"body": "text"}` — singular object, NOT `questions` array or `question_body`
- **Number**: String type (e.g., `"62"`), not integer
- **Status values**: `"draft"`, `"open"`, `"closed"` (lowercase)
- **Replies**: `POST /rest/v1.0/projects/{id}/rfis/{rfi_id}/replies` with `{"reply": {"body": "...", "official": true, "prostore_file_ids": [id]}}`
- **Reply attachments**: Include `prostore_file_ids` array in POST /replies body — attaches files directly to the reply (confirmed working)
- **Official flag**: `"official": true` in reply body marks it as official response; can also PATCH `/replies/{id}` to set after creation
- **File attachments**: Upload file to Documents, then PATCH RFI with `prostore_file_ids: [id]` (no need to GET existing attachments first — just send the new one)
- **GET /rfis list response**: Does NOT include `attachments` field — to check existing file attachments, search the Documents upload folder for `RFI-*` filenames instead
- **GET /rfis list response**: `questions` array has only `id`, `body`, `errors` (no answers)
- **GET /rfis/{id} detail**: `questions` array includes `plain_text_body`, `rich_text_body`, `attachments`, `answers[]`, `question_date`, `created_by`
- **Answers vs Replies**: Same objects — a reply created via `POST /replies` appears in both `questions[].answers[]` AND `GET /replies`. The `official` boolean distinguishes official responses from comments.
- **Answer fields**: `id`, `plain_text_body`, `rich_text_body`, `answer_date`, `attachments[]`, `created_by`, `created_by_id`, `official` (bool)
- **GET /rfis/{id}/replies**: Returns same answer objects as `questions[].answers[]`
- **GET /rfis/{id}/questions**: 404 — not a valid endpoint; questions only nested in RFI detail
- **No `official_response` field** on the RFI object — responses live inside `questions[].answers[]`
- **Status changes silently ignored**: `PATCH /rfis/{id}` with `status: "closed"` returns 200 but does not change the status — applies to both user OAuth and service account tokens. RFIs must be opened/closed manually in the Procore UI.
- **Replies blocked on closed RFIs**: `POST /replies` returns 403 if the RFI status is "closed". RFIs must be manually reopened before responses can be added via API.
- **Spike rate limit**: File uploads do 4+ API calls per file; add 1s delays between Procore API calls within `upload_file()` and 5s between files to stay under ~20-30 req/10s spike limit

### Procore Daily Log API (Confirmed April 2026)
- **Equipment logs**: `GET/POST /rest/v1.0/projects/{id}/equipment_logs`
  - Fields: `date`, `hours_idle`, `hours_operating`, `notes`, `equipment`, `vendor`
  - Equipment field may require Procore equipment register ID (not free text)
- **Manpower logs**: `GET/POST /rest/v1.0/projects/{id}/manpower_logs`
  - Fields: `date`, `num_workers`, `num_hours`, `man_hours`, `notes`, `vendor_id`, `trade`
  - Vendor requires Procore vendor ID (matched from project directory)
- **Notes logs**: `GET/POST /rest/v1.0/projects/{id}/notes_logs`
  - Fields: `date`, `comment`, `vendor`, custom fields
  - Custom field for Narrative Type: `custom_field_598134325900708` (LOV entries, per-project)
- **Other log types available**: weather_logs, work_logs, visitor_logs, safety_violation_logs, inspection_logs, quantity_logs, delivery_logs, accident_logs, call_logs, dumpster_logs, waste_logs, plan_revision_logs, timecard_entries
- **Date filtering**: Use `log_date=YYYY-MM-DD` param on GET endpoints
- **All endpoints** return `status: "approved"` by default

### Procore Observations API (Confirmed April 2026)
- **Create:** `POST /rest/v1.0/observations/items` with `project_id` + `observation` object at top level
- **Required fields:** `name`, `type_id`
- **Status values:** `initiated`, `ready_for_review`, `not_accepted`, `closed`
- **Priority values:** `Low`, `Medium`, `High`, `Urgent`
- **Default type categories:** Safety (4 types), Quality (4 types), Commissioning (1), Warranty (1)
- Observations are NOT automatically emailed when created via API — use `POST /observations/items/send_unsent`
- **Request body format:** `{"project_id": 123, "observation": {"name": "...", "type_id": 456, ...}}` (NOT path-based project_id)

### Procore Inspections (Checklists) API (Researched April 2026)
- **Inspections are template-based** — must create from a `list_template_id`
- **Create Inspection:** `POST /rest/v1.0/projects/{id}/checklist/lists` — requires `list_template_id` + `list` object
- **Create Template:** `POST /rest/v1.0/projects/{id}/checklist/list_templates`
- **Inspection statuses:** `open`, `in_review`, `closed`
- **Item response statuses:** `conforming`, `non_conforming`, `not_applicable`
- **Inspection types:** `GET/POST /rest/v1.0/companies/{id}/inspection_types`
- **Add sections with items:** `POST /checklist/lists/{id}/sections` (deprecated but functional) — `items_attributes` array with `name`, `position`, `status`
- **Full OAS spec available:** `reference/combined_OAS.json` (project root, 43 MB, all Procore endpoints)

### Procore Documents Folder Structure
| Folder | ID | Contents |
|--------|----|----------|
| 02 Specifications | 598134521781349 | 139 individual spec section PDFs (split from 3 UFGS volumes) |
| 03 Submittals | 598134439643352 | Submittal files uploaded from RMS (was "03 Specifications", renamed by PM) |

---

## RMS to Procore Migration — Active Status

### Dobbins Project (PowerShell scripts)
Migration completed March 2026: 2,280 submittals, 1,166 files, 8 custom fields.
**Details:** `rms-importer/docs/submittal-migration.md`

| Feature | Status |
|---------|--------|
| Submittal Register import | DONE (1,933 base + 35 recreated) |
| Bulk file upload | DONE (1,090 files) |
| Submittal Revisions | DONE (277 revisions) |
| Custom fields (RMS + Dates) | DONE |
| Fix revision fields | DONE (277 updated, Type field skipped — Procore API limitation) |
| Attachment fix | DONE — see `rms-importer/docs/attachment-fix.md` |
| Fix missing uploads | DONE (206 files uploaded, array wrap bug fixed) |
| Fix multi-item attachments | DONE (507 fixes across 113 transmittals) |
| QA Code from Transmittal Report | DONE (835 updated) |
| QA Code to Status sync | DONE (279 updated, 1,654 already correct) |
| Company Submitters | DONE — `populate_submitters.ps1` |
| Remove distribution member | DONE — Removed Perry McCauley |
| Bulk Responsible Contractor | DONE (146 submittals assigned via Sub Scope mapping, 14 spec sections fixed) |
| File upload v3 (CSV mapping) | DONE (1,166 files uploaded, duplicate check, Transmittal Report for item mapping) |
| Fix duplicate attachments | DONE (57 duplicates removed from 9 submittals) |
| Fix open statuses | DONE (20 closed via QA code, 60 moved to Draft) |
| Draft to Open status | DONE (1,618 submittals, `set_draft_to_open.ps1`) |
| Fix empty custom fields | DONE (396 submittals backfilled — `fix_empty_custom_fields.ps1`) |
| Spec PDFs to Documents | DONE (139 section PDFs split and uploaded to "02 Specifications" folder) |
| P6 Schedule Integration | PLANNED — see `rms-importer/docs/p6-schedule.md` |

### Web App (rms-importer/)
**Details:** `rms-importer/docs/rms-importer-app.md`

| Feature | Status |
|---------|--------|
| Status/Type/Date/Info mapping | DONE |
| Contractor mapping + vendor matching | DONE |
| RMS file validation | DONE |
| Spec section matching | DONE — see `rms-importer/docs/specifications.md` (fuzzy matching in sync engine fixed 2026-03-31) |
| QAQC Deficiencies import | DONE — see `rms-importer/docs/qaqc-observations.md` |
| File-based sync system + UI | DONE |
| Bootstrap existing data | DONE (baseline populated via first sync) |
| Transmittal Report validation | DONE |
| Configurable upload folder ID | DONE (env var `PROCORE_UPLOAD_FOLDER_ID`) |
| Turso cloud database | REMOVED — switched to SQLite on Railway volume; Turso fallback code deleted April 2026 |
| **Deployment** | **DONE** — see Deployment section below |
| **Procore Embedded App** | **DONE** — Full Screen embedded in Procore, popup OAuth, auto-project select |
| Dynamic Project Selection | DONE — `{{procore.project.id}}` interpolation, works across all projects |
| Persistent Auth | DONE — OAuth sessions stored in SQLite, survive Railway restarts |
| **Multi-Project Setup Wizard** | **DONE** — per-project config, guided first-time setup, auto-skip for configured projects |
| **Register Report Only** | **DONE** — Submittal Register and Assignments removed; Register Report CSV is the only required input |
| **Transmittal Log Removed** | **DONE** — Transmittal Report (CSV) replaces everything; dates, revisions, QA codes all from Report |
| **Status on Create** | **DONE** — new submittals get QA-code-based status at creation (previously defaulted to Open) |
| **SD Type Mapping Fix** | **DONE** — Excel float SD numbers ("1.0") now correctly map to types (was broken for all submittals) |
| **Custom Field Update Fix** | **DONE** — updates now use Procore field IDs (Info, QA Code, QC Code, Paragraph) |
| **Register Report CSV** | **DONE** — single file replaces Register + Assignments, adds Paragraph field |
| **Background Sync (all ops)** | **DONE** — entire sync (creates, updates, files) runs as background job with progress polling; resilient to network drops, auto-resumes on page refresh |
| **Dynamic Custom Field IDs** | **DONE** — discovered from Procore API, stored per-project (no more hardcoded IDs) |
| **Configurable Status Mapping** | **DONE** — QA Code or RMS Status mode, configurable per project |
| **Browser File Uploads** | **DONE** — folder picker (webkitdirectory), smart baseline filtering, background job processing with progress |
| **Sync Toggles** | **DONE** — checkboxes for creates, QA updates, date updates, other updates. (File uploads no longer have a toggle — they're opt-in via the folder picker on the Upload step.) |
| **Incremental Baseline Saves** | **DONE** — baseline saved after creates and every 50 updates; survives job interruptions |
| **File Bootstrap** | **DONE** — bootstrap populates baseline with existing files from Procore upload folder; add-existing-files endpoint for manual registration |
| **Stale Job Cleanup** | **DONE** — running/queued jobs auto-marked as failed on startup |
| **Custom Field Format Fix** | **DONE** — custom fields must be top-level on submittal object, not nested under `custom_fields` (Procore silently ignores nested format) |
| **All Fields on Create** | **DONE** — creates now include QA code, QC code, paragraph, info, and dates (previously only paragraph and info) |
| **Revision Field Inheritance** | **DONE** — revisions now inherit paragraph and QC code from parent (was hardcoded to null) |
| **Repair Custom Fields Mode** | **DONE** — `repair_custom_fields` toggle re-sends all custom field values for existing submittals to fix Procore nulls |
| **Tool Selection Screen** | **DONE** — after login/setup, user picks Submittals or RFIs (extensible for QA, Daily Logs) |
| **RFI Import** | **DONE** — parse RMS RFI Report CSV, create RFIs in Procore via API, add gov responses as replies, file attachments, sync responses to existing RFIs |
| **Wizard Restructure (Submittals + RFI)** | **DONE** (2026-04-26/27) — folder picker moved from Review to Upload step; Review is preview-only with a File Plan section; single "Apply" button. Same shape across both modules. |
| **Unified Submittal Job** | **DONE** (2026-04-26) — `process_sync_job` runs creates → save baseline → upload+attach files → updates as one orchestrated background job. New endpoint `POST /sync/projects/{id}/execute-all` (multipart). Old `/upload-files` endpoint and `process_file_job` deleted. Fixes silent-fail bug where files for newly-created submittals couldn't attach because their Procore IDs weren't in the baseline yet. |
| **Unified RFI Job** | **DONE** (2026-04-27) — `_process_rfi_job` adds Phase 3 to attach non-response files using a `rfi_id_lookup` populated from existing + just-created RFIs. `/execute-with-files` now takes `rfi_files` (was `response_files`). Old `/upload-files` endpoint and `_process_rfi_file_job` deleted. Fixes the same race the Submittals job had, between the standalone Complete-page uploader and the main execute job. |
| **Token Refresh on Job Start** | **DONE** (2026-04-27) — `_refresh_session_token(session_id)` helper called at the start of `process_sync_job` and both RFI execute endpoints, so long-running unified jobs don't 401 when the original token expires mid-flow. Falls back to stored token on refresh failure. |
| **Doc Cache Pagination** | **DONE** (2026-04-27) — `_find_existing_document` now paginates through every doc in the target folder when building its dedupe cache (was one page of 300). Fixes 400 "name has already been taken" on file uploads to folders with >300 docs (Dobbins "03 Submittals" has 1,166). On step-3 400, busts the cache and rebuilds via the same paginated path. |
| **RFI Apply with files-only** | **DONE** (2026-05-01) — `RFIReview` now shows the Apply button when `plan.has_changes` *or* the user picked at least one file. Previously only checked `plan.has_changes`, so picking files but having no CSV-driven creates/updates would hide Apply and the files would never upload. The unified RFI job's Phase 3 was already correct; this was a frontend-only fix. SyncView (Submittals), DailyLogReview, and ObservationsReview audited at the same time — only RFI had the gap. |
| **Daily Logs Import** | **DONE** — parse QC Equipment, Labor, Narratives CSVs; create equipment_logs, manpower_logs, notes_logs in Procore; vendor matching for labor; background job with rate limiting |
| **Observations Import** | **DONE** — parse Deficiency Items CSV (QA + QC items); create Procore Observations with location matching/auto-create, observation type selection; background job with progress |
| **Inspections Import** | **PLANNED** — QC Tests CSV parser built (`TestParser`); Procore Inspections API researched (template-based); pending template approach decision |

### QA Code → Status Mapping (reference)
| QA Code | Meaning | Procore Status |
|---------|---------|----------------|
| A | Approved | A - Approved as submitted |
| B | Approved as Noted | B - Approved, except as noted on drawings |
| C | Approved, Resubmit Required | C - Approved, except as noted; resubmission required |
| D | Disapproved, Revise/Resubmit | D - Returned by separate correspondence |
| E | Disapproved | E - Dissapproved (see attached) |
| F | For Information Only | F - Receipt acknowledged |
| G | Revise and Resubmit | G - Other (specify) |
| X | Receipt Acknowledged | X - Receipt acknowledged, does not comply with requirements |

### Transmittal Number Parsing (reference)
```
01 50 00-1.2
   ↑     ↑ ↑
   │     │ └── Revision number (2) ← WE USE THIS
   │     └──── Transmittal order in RMS (ignore)
   └────────── Spec section
```
- The number after `-` is just RMS entry order (NOT the item number)
- Actual item numbers come from Transmittal Report data rows
- **Match key format**: `{Section}-{ItemNo}-{Revision}` (e.g., "01 50 00-15-2")

---

## Deployment

| Service | Platform | URL |
|---------|----------|-----|
| Frontend | Vercel | `rms-importer.vercel.app` |
| Backend | Railway | `rms-importer-production.up.railway.app` |
| Database | SQLite on Railway volume | `/app/data/sync.db` (500 MB volume, `sqlite-data`) |
| Repo | GitHub | `mckayje3/rms-importer` |

**Auto-deploy:** Both Vercel and Railway deploy automatically on push to `main`.

**Backend env vars (Railway):** `PROCORE_CLIENT_ID`, `PROCORE_CLIENT_SECRET`, `FRONTEND_URL`, `BACKEND_URL`, `SESSION_SECRET`, `PROCORE_UPLOAD_FOLDER_ID`

**Frontend env vars (Vercel):** `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_SUPPORT_EMAIL` (in-app help footer), `NEXT_PUBLIC_HELP_URL` (in-app help footer), `NEXT_PUBLIC_PRIVACY_URL` (overrides the default iubenda privacy policy URL on `/privacy`), `NEXT_PUBLIC_COOKIE_URL` (overrides the default iubenda cookie policy URL on `/cookies`), `NEXT_PUBLIC_IUBENDA_WIDGET_URL` (overrides the iubenda Privacy Controls + Cookie Solution widget loaded in `app/layout.tsx`)

**Local dev:** Backend reads from `backend/.env` (not committed). Database uses local `backend/data/sync.db`.

**Database notes:** SQLite on Railway persistent volume. Previously used Turso (libSQL) cloud database; switched to SQLite (April 2026) after sync bandwidth exceeded free tier. Turso fallback code fully removed — `libsql` dependency deleted, no Turso env vars needed. Railway volume persists across restarts and deploys.

**Procore Embedded App:** DONE — Full Screen embedded component, configured in App Manager. See `rms-importer/docs/rms-importer-app.md` for setup details. Promoting a new Developer Console version wipes the client-side Configuration.

**Multi-Project Support:** Custom field IDs, status mappings, and SD type mappings are now stored per-project in the `project_config` database table. First-time users get a guided setup wizard; returning users auto-skip to upload. The Procore API cannot create custom fields or statuses — those must be set up manually in Company Admin > Tool Settings > Submittals.

---

## Export Scripts (rms-importer/scripts/)
| Script | Output |
|--------|--------|
| `Export-SubmittalsByContractor.ps1` | PDF per contractor (all submittals) |
| `Export-SubmittalsByContractor-GA.ps1` | PDF per contractor (GA submittals only) |
| `Export-SubmittalsByContractor-GA-Open.ps1` | PDF per contractor (GA submittals, excluding QA codes A & B) |

All three scripts handle MULTIPLE contractors (e.g., "MULTIPLE: Altis Concrete, Superior Rigging") by splitting into individual names and using wildcard filters.

---

## Detailed Documentation

| Document | Content |
|----------|---------|
| `rms-importer/docs/submittal-migration.md` | PowerShell scripts, parameters, custom field config, API notes, rate limits |
| `rms-importer/docs/attachment-fix.md` | Completed attachment fix process (March 2026) |
| `rms-importer/docs/rms-importer-app.md` | Web app: data sources, field mappings, use cases, matching logic, sync system, API endpoints |
| `rms-importer/docs/specifications.md` | Specifications/Divisions feature, Procore API research |
| `rms-importer/docs/qaqc-observations.md` | QAQC → Procore Quality & Safety (Deficiencies→Observations done, QC Tests→Inspections planned) |
| `rms-importer/docs/p6-schedule.md` | P6 Schedule Integration (planned) |
