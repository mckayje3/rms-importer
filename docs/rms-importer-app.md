# RMS Importer Web App

**Goal:** Build a Procore Marketplace app for USACE contractors to migrate RMS data to Procore.
**App Name:** RMS Importer
**See:** `Procore_Marketplace_Analysis.md` for full market analysis.

## Stack
- Backend: Python FastAPI (`rms-importer/backend/`)
- Frontend: Next.js + TypeScript + Tailwind (`rms-importer/frontend/`)
- Hosting: Vercel (frontend) + Railway (backend)

**To run locally:**
```powershell
cd rms-importer
.\start_dev.ps1
# Backend: http://localhost:8000
# Frontend: http://localhost:3000
```

## Data Sources

| Source | Type | Data Provided |
|--------|------|---------------|
| **Register Report CSV** (recommended) | RMS Export | All submittals with paragraph references, classifications (Info), types, QA/QC codes, activity codes — replaces Register + Assignments |
| **Submittal Register** (legacy) | RMS Export | Submittals (spec section, item#, title, status, QA/QC codes, SD No→Type) - **CURRENT revision only** |
| **Submittal Assignments** (legacy) | RMS Export | Info field (GA/FIO/S) — not needed if using Register Report |
| **Transmittal Report** | RMS Export | Revisions, item numbers, dates (Date In/Date Out), QA Code + Classification for ALL transmittals |
| **Contractor Mapping** | Manual Template | Spec section → contractor name (CSV: Section, Contractor) |

**Recommended setup:** Upload **Register Report CSV** + **Transmittal Report** (2 files). The Register Report replaces both the Submittal Register and Assignments, and adds paragraph references. The Transmittal Report adds revision-level QA codes and dates.

## Field Mappings

**Status Mapping** — configurable per project, two modes available:

*Mode 1: QA Code (default)* — derives status from the government review code:
| QA Code | Procore Status |
|---------|----------------|
| A, B, F, X | closed |
| C, D, E, G | open |
| (none) | unchanged |

*Mode 2: RMS Status* — derives status from the RMS status field:
| RMS Status | Procore Status |
|------------|----------------|
| Outstanding | Draft |
| Complete | Closed |
| In Review | Open |

Projects choose their mode during setup. The `status_mode` field in project config controls which source is used.

**Type Mapping (SD No → Procore Type):**
| SD No | Type |
|-------|------|
| 01 | SD-01: PRECON SUBMTL |
| 02 | SD-02: SHOP DRAWINGS |
| 03 | SD-03: PRODUCT DATA |
| 04 | SD-04: SAMPLES |
| 05 | SD-05: DESIGN DATA |
| 06 | SD-06: TEST REPORTS |
| 07 | SD-07: CERTIFICATES |
| 08 | SD-08: MFRS INSTR |
| 09 | SD-09: MFRS FLD REPT |
| 10 | SD-10: O&M DATA |
| 11 | SD-11: CLOSEOUT SUBMTL |

**QA Code → Status Mapping:**
| Code | Meaning | Procore Status |
|------|---------|----------------|
| A | Approved | closed |
| B | Approved as Noted | closed |
| C | Approved as Noted, Resubmit Required | open |
| D | Disapproved, Revise and Resubmit | open |
| E | Disapproved | open |
| F | For Information Only | closed |
| G | Revise and Resubmit | open |
| X | Receipt Acknowledged | closed |

**Direct Fields (no transformation):**
- QC Code: A, B, C, D
- QA Code: A, B, C, D, E, F, G, X
- Info: GA, FIO, S

## RMS Export File Validation

**Submittal Register** (primary submittal data)
| Column | Header | Sample |
|--------|--------|--------|
| 1 | Section | 00 80 00.00 06 |
| 2 | Item No | 1 |
| 3 | SD No | 01 |
| 4 | Description | Local Agency Check |
| 5 | Date In | (date) |
| 6 | QC Code | A/B/C/D |
| 7 | Date Out | (date) |
| 8 | QA Code | A/B/C/D/E/F/G/X |
| 9 | Status | Approved/Disapproved/etc |

**Submittal Assignments** (Info field)
| Column | Header | Sample |
|--------|--------|--------|
| 1 | Section | 00 80 00.00 06 |
| 2 | Item No | 1 |
| 3 | Description | Local Agency Check |
| 4 | SD No | 01 |
| 5 | Info Only | FIO/GA/S |
| 6 | Required for Activity | (activity code) |

**Transmittal Report** (CSV/Excel — hierarchical format with dates, revisions, QA codes)
- Header line: `Transmittal No {Section}-{Num}[.{Rev}]  Date In: MM/DD/YYYY  Review Date: MM/DD/YYYY  Date Out: MM/DD/YYYY`
- Data rows: `Item No., Description, Type of Submittal, Office, Reviewer, Classification, QA Code`
- One header + one or more data rows per transmittal
- Provides: revisions, item numbers, Date In (government_received), Date Out (government_returned), QA codes

**Transmittal Report** (QA Code per revision - historical data)
| Row Type | Col 1 | Col 13 | Col 14 |
|----------|-------|--------|--------|
| Header | "Transmittal No {Section}-{Num}  Date In: ...  Date Out: ..." | - | - |
| Data | Item No (numeric) | Classification (GA/FIO/S) | QA Code (A-G, X) |

Structure: Row 12 = column headers. Transmittal header rows contain full transmittal number with dates. Data rows follow with item details.

**Validation Rules:**
- Check exact column headers match (case-insensitive)
- Submittal Register: expect ~2000 rows for typical USACE project
- Transmittal Report: ~334 transmittals for Dobbins, hierarchical header+data rows

## App Workflow

### Tool Selection (April 2026)

After login and project setup, users choose which RMS data to import:

```
Login → Select Project → Setup → [Select Tool]
                                      ├── Submittals → Upload RMS → Analyze → Review → Execute
                                      └── RFIs → Upload RFI CSV → Review → Execute
```

The tool selector is a card-based UI designed to accommodate future tools (QA Observations, Daily Logs).

### Submittal Import

1. **Connect & Select Project** — OAuth with Procore, pick company/project (auto-selected when embedded)
2. **Project Setup** (first time only) — Guided wizard checks prerequisites, maps custom fields and statuses. Auto-skipped for configured projects.
3. **Select Tool** — Choose "Submittals"
4. **Upload RMS Exports** — Register Report CSV (recommended) or Register + Assignments, plus Transmittal Report
5. **App Generates Templates** — Contractor Mapping template (spec sections pre-filled)
6. **User Fills Out Templates Offline** — Maps contractors to spec sections
7. **User Uploads Completed Templates** — App validates against Procore Directory, user reviews matches
8. **App Imports to Procore** — Creates submittals, revisions, uploads files, populates custom fields

### File Upload Requirements

| File | Required? | Data Added |
|------|-----------|------------|
| Register Report CSV | **Recommended** | All submittals, classifications, paragraph refs, types — replaces Register + Assignments |
| Submittal Register | Yes (if no Report) | Submittals, status, QA/QC codes, SD types |
| Submittal Assignments | No | Info field (GA/FIO/S) — not needed with Register Report |
| Transmittal Report | No | Revisions, dates (Date In/Out), historical QA codes |

## Use Cases

### Use Case 1: Full Migration
New Procore project, active RMS project. Creates ALL submittals, uploads ALL files, no conflict resolution.

### Use Case 2: Sync/Update
Both systems have data, RMS is source of truth. Matches existing, creates new, flags Procore-only orphans.

### Use Case 3: Hybrid Reconcile
Work done in both systems independently. Shows differences, user decides which values to keep per field.

## Mode Auto-Detection

```
Procore submittal count = 0? → "Full Migration"
Match rate > 80%?            → "Sync from RMS"
Match rate 20-80%?           → "Reconcile"
Match rate < 20%?            → Ask user
```

## Submittal Matching Logic

**Primary Key:** `{Spec Section} + {Item Number} + {Revision}`

**Match Key Format:** `"{Section}-{ItemNo}-{Revision}"`
- Example: `"01 50 00-15-0"` = Section 01 50 00, Item 15, Original
- Example: `"01 50 00-15-2"` = Section 01 50 00, Item 15, Revision 2

**Edge Cases:**
| Scenario | Handling |
|----------|----------|
| Spec section format differs | Normalize before matching |
| Item number as string vs int | Compare as integers |
| Procore has revision, RMS doesn't have dates | Match by Section+Item, revision=0 |

## Conflict Resolution (Reconcile Mode)

**Fields to Compare:** Status, Contractor Prepared, Government Received, Government Returned, Contractor Received

**Bulk Resolution Options:**
- "Use RMS for all Status conflicts"
- "Use RMS for all Date conflicts"
- "Use Procore for all conflicts"
- "Review each individually"

## Incremental Sync System

Uses a **file-based diff** approach — compares new RMS exports against previously-imported RMS exports stored as a baseline. RMS is the source of truth.

**Database:** SQLite (`backend/data/sync.db`)
- `baselines` - last synced RMS data with Procore IDs
- `sync_history` - audit trail of all sync operations
- `flagged_items` - items removed from RMS (flagged for review, not auto-deleted)

**Workflow:**
- First Import: Upload RMS → Full Migration → Save as baseline (with Procore IDs)
- Subsequent Syncs: Upload new RMS → Diff against baseline → Show plan → Execute → Update baseline

**Sync Execution:** All sync operations (creates, updates, file uploads) run as a background job. The `/execute` endpoint returns immediately with a `job_id`. The frontend polls `/file-jobs/{job_id}` every 5 seconds for progress. This prevents HTTP timeouts on large syncs (e.g., 2000+ submittals at 2s rate-limit delay = ~67 minutes). The baseline is updated incrementally as operations complete, so interrupted syncs can be resumed by re-running — the diff will only show remaining changes.

**Network Resilience:** The `FileJobProgress` component tolerates transient network errors (up to 5 consecutive failures before showing an error). On page refresh, the app auto-detects active jobs via `/file-jobs` list endpoint and resumes the progress display. Auth sessions persist in `sessionStorage` across refreshes.

**Bootstrap Option:** If Procore already has submittals from PowerShell migration, upload current RMS, app matches RMS → Procore by key, saves baseline with Procore IDs.

**Tracked Fields:** title, type, status, paragraph, qa_code, qc_code, info, government_received, government_returned

**Deleted Items:** Flagged for review, NOT auto-deleted.

## RFI Import (April 2026)

### Data Source

The **RFI Report CSV** exported from RMS ("All Requests for Information" report). This is a multi-line CSV where each RFI row contains:
- `RFI No.` — e.g., "RFI-0001"
- `Date Requested`, `Date Received`, `Date Answered`
- `Requester's Name / Answer Prepared by` — multi-line field (two names separated by newline)
- `Mod Required? / Change No.` — multi-line field
- `RFI Subject - Information Requested / Government Response` — full Q&A text with markers "INFORMATION REQUESTED:" and "GOVERNMENT RESPONSE:"

### RFI Field Mapping (RMS → Procore, confirmed April 2026)

| RMS CSV Field | Procore API Field | Notes |
|---|---|---|
| RFI No. (numeric part) | `number` (string) | "RFI-0001" → `"1"` |
| Subject (extracted) | `subject` | Text before first " - " in question body |
| Full question text | `question.body` | Singular object `{"body": "..."}`, NOT `question_body` or `questions` array |
| Government Response | Reply `body` | Separate API call: `POST /rfis/{id}/replies` with `{"reply": {"body": "..."}}` |
| Date Requested | `due_date` | ISO format |
| (auto) | `rfi_manager_id` | Required — fetched via `/me` endpoint or from existing RFI |
| (auto) | `assignee_ids` | Required array — defaults to `[rfi_manager_id]` |
| File attachments | `prostore_file_ids` | PATCH with `[new_id]` only — no need to GET existing attachments; filter checks Documents folder for already-uploaded `RFI-*` files |

### Procore RFI API

| Operation | Endpoint | Notes |
|-----------|----------|-------|
| List RFIs | `GET /rest/v1.0/projects/{id}/rfis` | Paginated |
| Create RFI | `POST /rest/v1.0/projects/{id}/rfis` | Wrapped in `{"rfi": {...}}` |
| Update RFI | `PATCH /rest/v1.0/projects/{id}/rfis/{rfi_id}` | |
| Add Reply | `POST /rest/v1.0/projects/{id}/rfis/{rfi_id}/replies` | Government response goes here |

### RFI Workflow

1. **Select Tool** — Choose "RFIs" from tool selector
2. **Upload RFI Report** — Upload the CSV, backend parses all RFIs (handles multi-line quoted fields). Shows parse summary (total, answered, outstanding).
3. **Review** — Shows sync plan: RFIs to create vs already existing in Procore. User toggles: create new, add replies.
4. **Execute** — Background job creates RFIs and adds government responses as replies. Progress polling via `/rfi/jobs/{id}`.
5. **File Upload** (optional) — On review page, select RMS Files folder. Frontend calls `/rfi/projects/{id}/filter-files` to check which files are new vs already uploaded (cached from analyze step — checks Documents folder for `RFI-*` files). Only new files are sent. Backend uploads to Documents, then PATCHes the RFI with `prostore_file_ids`. Background job with progress tracking. Rate-limit-safe: 1s delays between API calls, 5s between files.

### RFI Backend Files

| File | Purpose |
|------|---------|
| `backend/models/rfi.py` | `RMSRFI`, `RFIParseResult`, `RFISyncPlan`, `RFICreateAction` |
| `backend/services/rfi_parser.py` | Parses RFI Report CSV (multi-line fields, Q&A text splitting) |
| `backend/routers/rfi.py` | Upload, analyze, execute, job status endpoints |
| `backend/services/procore_api.py` | `get_rfis()`, `create_rfi()`, `update_rfi()`, `create_rfi_reply()` |

### RFI Frontend Files

| File | Purpose |
|------|---------|
| `frontend/src/components/ToolSelector.tsx` | Card-based tool picker (Submittals / RFIs / Daily Logs / Observations) |
| `frontend/src/components/RFIUpload.tsx` | CSV file picker + upload |
| `frontend/src/components/RFIReview.tsx` | Sync plan review, create/reply toggles, progress |
| `frontend/src/components/RFIFileUpload.tsx` | Folder picker for RFI attachments, upload + attach to RFIs |

## Backend Services

| Service | Purpose | Lookup Key |
|---------|---------|------------|
| `RMSParser` | Parse RMS Excel exports | - |
| `RMSValidator` | Validate RMS files before parsing | - |
| `DateLookup` | Map Transmittal Report dates to submittals | `{Section}|{Item}|{Revision}` |
| `FileJobStore` | Background job tracking (sync + file uploads) | job ID |
| `InfoLookup` | Map Submittal Assignments Info field | `{Section}-{Item}` |
| `ContractorLookup` | Map spec sections to contractors | `{Section}` |
| `VendorMatcher` | Fuzzy match contractor names to Procore Directory | - |
| `SpecMatcher` | Match RMS spec sections to Procore sections (exact, normalized, base) | `{Section}` |
| `MatchingService` | Compare RMS vs Procore submittals | - |
| `SyncService` | File-based diff and sync planning | - |
| `RFIParser` | Parse RFI Report CSV (multi-line fields, Q&A splitting) | - |
| `DailyLogParser` | Parse QC Equipment/Labor/Narrative CSVs | - |
| `DeficiencyParser` | Parse Deficiency Items CSV (QA + QC items) | - |
| `TestParser` | Parse QC Test List CSV (for future Inspections) | - |
| `ProcoreAPI` | Procore REST API client (incl. vendors, file upload, RFIs, observations) | - |

**Database (`backend/database.py`):**
- SQLite storage at `backend/data/sync.db` (Railway volume in production)
- `BaselineStore` class for CRUD operations on baselines, history, flagged items
- `ProjectConfigStore` class for per-project configuration (custom field IDs, status mappings, SD type mappings)
- `SessionStore` class for persistent OAuth sessions
- `FileJobStore` class for background file upload job tracking

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/auth/login` | GET | Start Procore OAuth |
| `/auth/callback` | GET | OAuth callback |
| `/projects/companies` | GET | List companies |
| `/projects/companies/{id}/projects` | GET | List projects |
| `/rms/validate` | POST | Validate RMS files before upload |
| `/rms/upload` | POST | Upload RMS Excel files (validates first) |
| `/rms/session/{id}` | GET | Get parse results |
| `/rms/session/{id}/spec-sections` | GET | List spec sections |
| `/rms/session/{id}/contractor-template` | GET | Download contractor mapping CSV |
| `/rms/session/{id}/contractor-mapping` | POST | Upload filled contractor mapping |
| `/rms/session/{id}/contractor-mapping` | GET | Get current contractor mapping |
| `/rms/session/{id}/match-contractors` | POST | Fuzzy match to Procore Directory |
| `/rms/session/{id}/confirm-match` | POST | Confirm/override a vendor match |
| `/rms/session/{id}/vendors` | GET | List Procore Directory vendors |
| `/submittals/projects/{id}/check-specs` | POST | Check spec section availability |
| `/submittals/projects/{id}/analyze` | POST | Analyze RMS vs Procore |
| `/submittals/projects/{id}/import` | POST | Import submittals |
| `/qaqc/upload` | POST | Upload and parse Deficiency Items CSV |
| `/qaqc/projects/{id}/analyze` | POST | Compare deficiencies vs existing observations + locations |
| `/qaqc/projects/{id}/execute` | POST | Import deficiencies as observations (background job) |
| `/qaqc/jobs/{id}` | GET | Poll observation import job status |
| `/qaqc/session/{id}` | DELETE | Delete QAQC session |
| `/daily-logs/upload` | POST | Upload and parse daily log CSVs (equipment, labor, narratives) |
| `/daily-logs/projects/{id}/analyze` | POST | Compare daily logs vs Procore, match vendors |
| `/daily-logs/projects/{id}/execute` | POST | Import daily log entries (background job) |
| `/daily-logs/jobs/{id}` | GET | Poll daily log import job status |
| `/sync/projects/{id}/baseline` | GET | Get baseline info |
| `/sync/projects/{id}/baseline` | DELETE | Reset baseline for re-import |
| `/sync/projects/{id}/analyze` | POST | Analyze RMS vs baseline, get sync plan |
| `/sync/projects/{id}/execute` | POST | Execute sync plan (always background, returns job_id) |
| `/sync/projects/{id}/history` | GET | View sync history |
| `/sync/projects/{id}/flagged` | GET | Get items flagged for review |
| `/sync/projects/{id}/flagged/{item}/resolve` | POST | Resolve flagged item |
| `/setup/projects/{id}/discover` | GET | Discover custom fields + statuses from Procore |
| `/setup/projects/{id}/config` | GET | Get saved project configuration |
| `/setup/projects/{id}/config` | POST | Save project configuration |
| `/setup/projects/{id}/config` | DELETE | Delete project configuration |
| `/sync/projects/{id}/filter-files` | POST | Check filenames against baseline (new vs already uploaded) |
| `/sync/projects/{id}/upload-files` | POST | Upload files + start background attach job |
| `/sync/projects/{id}/file-jobs/{job}` | GET | Poll file upload job status |
| `/sync/projects/{id}/file-jobs` | GET | List recent file upload jobs |
| `/rfi/upload` | POST | Upload and parse RFI Report CSV |
| `/rfi/session/{id}/items` | GET | List parsed RFIs from session |
| `/rfi/projects/{id}/analyze` | POST | Compare parsed RFIs vs existing Procore RFIs |
| `/rfi/projects/{id}/execute` | POST | Create RFIs + replies (background job) |
| `/rfi/jobs/{id}` | GET | Poll RFI import job status |
| `/rfi/projects/{id}/filter-files` | POST | Check filenames against cached data — returns new vs already-attached (0 API calls) |
| `/rfi/projects/{id}/upload-files` | POST | Upload new files and attach to matching RFIs (background job) |
| `/rfi/session/{id}` | DELETE | Delete RFI session |

## Background Job Architecture

All long-running Procore operations use the same background job system: `file_jobs` table + `asyncio.create_task()` + frontend polling. This applies to both **sync execution** (`process_sync_job`) and **file uploads** (`process_file_job`).

### Browser-Based Upload Flow

Users select their RMS files folder in the browser using `webkitdirectory`. The app intelligently filters to only upload new files:

1. **Filter** — Frontend sends filenames to `/filter-files` endpoint → backend checks baseline → returns new vs already-uploaded
2. **Upload** — Frontend uploads only new files in batches of 5 via FormData to `/upload-files`
3. **Background Job** — Server saves files to temp dir, creates a `file_jobs` DB entry, starts `asyncio.create_task()`, returns job ID immediately
4. **Process** — Background worker uploads each file to Procore and attaches to target submittals
5. **Poll** — Frontend polls `/file-jobs/{id}` every 5 seconds for progress; user can navigate away

### Procore Upload Steps

Files are uploaded once and then attached to all target submittals:

1. **`upload_file()`** — Upload to S3 + create Procore document → returns `prostore_file_id` (4 API calls)
2. **`attach_file_to_submittal()`** — GET existing attachments + PATCH to add file (2 API calls per submittal, skips if already attached)

For multi-item transmittals (one file covering multiple items):
- Calls `upload_file()` **once** per file
- Calls `attach_file_to_submittal()` for **each** target submittal
- Cost: 4 + (2 × N items) API calls instead of 6 × N

### Duplicate Prevention

Two layers:
- **Baseline check** (fast, no API calls): `/filter-files` checks filenames against baseline's uploaded files list
- **Procore check** (API): `attach_file_to_submittal()` skips if prostore_file_id already in attachment list

### File-to-Submittal Mapping

`SyncService.map_files_to_submittals()`:
- Parses filename: `Transmittal {Section}-{TransNum}[.{Rev}] - {Description}.pdf`
- Looks up transmittal in Transmittal Report (CSV) to get actual item number(s)
- Falls back to using transmittal number as item number if not found

## Models

`RMSSubmittal` computed properties:
- `procore_status`: Maps QA code → Procore status (default mode; sync service uses config-aware `map_status_for_config()` instead)
- `procore_type`: Maps SD No → Type
- `match_key`: `{Section}-{Item}-0`

## Directory/Company Matching

**Matching Algorithm:**
| Match Type | Score | Description |
|------------|-------|-------------|
| Exact | 100% | Exact string match |
| Case-insensitive | 99% | Same text, different case |
| Contains | 80% | One name contains the other |
| Fuzzy | 50-79% | Word similarity scoring |
| No match | <50% | Flagged for manual review |

**Contractor Mapping Template:** App generates CSV with spec sections pre-filled, user fills in Column 2, uploads back. Mapping is at spec section level.

**TODO:**
- [x] Fuzzy matching algorithm (VendorMatcher service)
- [x] Match API with top 3 suggestions per contractor
- [x] Confirm/override match endpoint
- [ ] Web UI for match review screen
- [ ] Support company-level AND project-level directory
- [ ] "Create new vendor" API integration for unmatched
- [ ] Persist mappings for reuse across projects

## Target Market
- USACE contractors required to use RMS who also use Procore
- Currently duplicating data entry between both systems
- **Competition:** The Link Submittal Creator (spec parsing only, NOT full RMS migration)

## Deployment

| Service | Platform | URL |
|---------|----------|-----|
| Frontend | Vercel | `rms-importer.vercel.app` |
| Backend | Railway | `rms-importer-production.up.railway.app` |
| Database | SQLite on Railway volume | `/app/data/sync.db` (500 MB volume) |
| Repo | GitHub | `mckayje3/rms-importer` |

Auto-deploys on push to `main`. Backend uses Dockerfile (`backend/Dockerfile`). `.dockerignore` excludes `.env` so Railway env vars take precedence.

Database: `backend/database.py` uses SQLite directly. Railway volume at `/app/data/sync.db` persists across deploys. Local dev uses `backend/data/sync.db`.

## Procore Embedded App (DONE — March 2026)

The app runs natively inside Procore as a **Full Screen** embedded component. Users access it from **Apps** in the Procore project nav — no external URL needed.

### How It Works

```
Procore project page
  └── Apps dropdown → "RMS Installer"
        └── iframe → rms-importer.vercel.app?procore_project_id=...&procore_company_id=...
              └── useEmbeddedContext() detects embedded mode
                    ├── Hides Header (no standalone chrome)
                    ├── Auto-selects project (skips project selector)
                    ├── Simplifies StepIndicator (hides Connect + Select steps)
                    └── OAuth via popup window (redirects blocked in iframe)
```

### Key Files

| File | Purpose |
|------|---------|
| `frontend/src/lib/useEmbeddedContext.ts` | Hook: reads `procore_project_id`/`procore_company_id` from URL, detects iframe |
| `frontend/src/app/page.tsx` | Embedded logic: auto-select project, popup OAuth, hide header, breadcrumb nav |
| `frontend/src/components/StepIndicator.tsx` | Tool-aware step display: shows Submittal or RFI steps based on selection; hides "Connect" and "Select Project" when embedded |
| `frontend/next.config.ts` | CSP `frame-ancestors` header allowing `*.procore.com` |
| `backend/main.py` | CORS: allows `app.procore.com` and `us02.procore.com` origins |

### Embedded vs Standalone Behavior

| Behavior | Standalone | Embedded |
|----------|-----------|----------|
| Header | Shown with logout button | Hidden |
| Project selection | Manual (company → project → stats) | Auto from URL params |
| Project setup | Shown (first time) / auto-skipped | Same |
| OAuth flow | Full page redirect | Popup window + postMessage |
| Step indicator | 7 steps | 5 steps (Connect + Select hidden) |
| "Import Complete" button | "Import Another Project" | "Import More" (returns to tool selector) |
| Layout padding | `py-8` | `py-4` (tighter) |
| Project context | Shown in selector | Breadcrumb: "Company > Project" |

### OAuth in Embedded Mode

Redirect-based OAuth doesn't work inside an iframe (login.procore.com blocks it). Instead:

1. "Connect with Procore" opens a **popup window** to Procore's OAuth URL
2. User authenticates in the popup
3. Backend callback redirects popup to `/?auth=success&session_id=...`
4. Popup detects `window.opener`, sends `postMessage` with session ID
5. Iframe receives message, stores session, proceeds to auto-select
6. Popup closes itself

Fallback: if postMessage fails, the iframe polls for `sessionStorage.auth_session` when the popup closes.

### Procore Developer Console Setup

Three places must be configured:

1. **Developer Console** — Embedded Component:
   - Type: **Full Screen**
   - URL: `https://rms-importer.vercel.app?procore_project_id={{procore.project.id}}&procore_company_id={{procore.company.id}}`
   - No custom parameters needed — uses built-in Procore interpolation
   - **Must save version and promote to Production**

2. **App Management > Installed Apps** — Add Dobbins to "Permitted Projects"

3. **App Management > View > Configurations** — Create configuration:
   - Project: Dobbins
   - Title: "RMS Installer"
   - company_id: `598134325694431`
   - project_id: `598134325988700`

**Important:** Promoting a new version in the Developer Console wipes the Configuration. Re-create it after each promotion.

**Note:** Procore's URL interpolation uses double-curly-brace syntax: `{{procore.project.id}}` and `{{procore.company.id}}`. Single braces (`{project_id}`) do NOT work.

### Procore IDs (Dobbins)

- Company ID: `598134325694431`
- Project ID: `598134325988700`

## Multi-Project Setup (DONE — March 2026)

The app supports any Procore project, not just Dobbins. Custom field IDs, status mappings, and SD type names are stored per-project in the `project_config` database table instead of being hardcoded.

### How It Works

**First-time setup** — guided wizard walks the user through:
1. **Welcome** — explains what setup does and that it's one-time
2. **Prerequisites** — checks Procore for custom fields and statuses, guides user to create missing fields in Company Admin
3. **Custom Field Mapping** — dropdowns to map Paragraph and Info to discovered Procore custom fields
4. **Status Mapping** — choose mode (QA Code or RMS Status), then map values to Procore statuses
5. **Review** — confirm all settings, save to database

**Returning users** — setup auto-skips. The component checks for existing config, and if `setup_completed: true`, immediately advances to Upload.

### Procore API Limitations

These resources **cannot** be created via the Procore API — they require manual one-time setup in the Procore UI:

| Resource | Where to Create | Notes |
|----------|----------------|-------|
| Custom field definitions | Company Admin > Tool Settings > Submittals > Configurable Fieldsets | Max 10 fields per fieldset |
| Submittal statuses | Company Admin > Tool Settings > Submittals > Custom Statuses | Default: Draft, Open, Closed |
| Submittal types | Company Admin > Tool Settings > Submittals > Custom Types | Default: 8 built-in types |

Once created in Procore, the API can:
- **Read** custom field definitions via configurable field sets endpoint
- **Set** custom field values, statuses, and types when creating/updating submittals

### Database Schema

```sql
CREATE TABLE project_config (
    project_id TEXT PRIMARY KEY,
    company_id TEXT NOT NULL,
    config_data TEXT NOT NULL,  -- JSON
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

**`config_data` JSON structure:**
```json
{
  "status_mode": "qa_code",
  "status_map": { "a": "closed", "b": "closed", "c": "open", "d": "open", "e": "open", "f": "closed", "g": "open", "x": "closed" },
  "sd_type_map": { "01": "SD-01: PRECON SUBMTL", ... },
  "custom_fields": { "paragraph": "custom_field_XXXXX", "info": "custom_field_XXXXX" },
  "setup_completed": true
}
```
`status_mode` can be `"qa_code"` (default — maps QA review codes to open/closed) or `"rms_status"` (maps Outstanding/Complete/In Review to Draft/Closed/Open). The `status_map` keys correspond to the chosen mode.

### Key Files

| File | Purpose |
|------|---------|
| `backend/routers/setup.py` | Setup API: discover, get/save/delete config |
| `backend/database.py` | `ProjectConfigStore` class, `project_config` table |
| `backend/services/procore_api.py` | `get_configurable_field_sets()`, `get_submittal_statuses()` |
| `backend/routers/sync.py` | Sync endpoints: analyze, execute (creates background job), baseline, file upload |
| `backend/services/sync_job.py` | Background sync processor: creates, updates, file uploads with progress tracking |
| `backend/models/mappings.py` | `map_status_for_config()`, `get_status_map()`, `get_sd_type_map()` config-aware helpers |
| `frontend/src/components/ProjectSetup.tsx` | Setup wizard UI (5 steps, auto-skip) |

### Backward Compatibility

If no `project_config` row exists for a project (e.g., Dobbins), the sync engine falls back to the original hardcoded Dobbins custom field IDs and default status/type mappings. No migration required.

## Future Improvements

### 1. Dynamic Project Selection (DONE — March 2026)
Procore's URL parameter interpolation now works using double-curly-brace syntax with `procore.` prefix:
- URL: `https://rms-importer.vercel.app?procore_project_id={{procore.project.id}}&procore_company_id={{procore.company.id}}`
- No custom parameters needed — these are built-in Procore variables
- Original `{project_id}` syntax was wrong (single braces, no prefix)
- App automatically detects project/company from any Procore project it's installed on

### 2. Persistent Auth (DONE — March 2026)
OAuth sessions now stored in `sessions` table (SQLite). Users stay logged in across Railway restarts.
- Remaining: Investigate Procore's embedded app auth token pass-through (may eliminate need for separate OAuth)
- Remaining: Token refresh handling for long-running sync operations

### 3. P6 Schedule Integration (MEDIUM)
Link submittals to P6 schedule activities via Procore's `task_id` field:
- Parse P6 export file (385 activities, `SUB.*` pattern)
- Match by spec section + trade code
- 6 trade codes still need mapping (DRYW, ELEC, CARP, PNT, FLR, SPEC)
- Could be a new step in the app workflow or remain a standalone script
- See `docs/p6-schedule.md`

### 4. RFI Import (DONE — April 2026)
Tool selection screen + full RFI import from RMS CSV. Creates RFIs in Procore with question text and government responses as replies. Background job with progress polling. See "RFI Import" section above.

### 5. Daily Logs Import (DONE — April 2026)
Tool selection screen + daily log import from RMS CSVs (QC Equipment, QC Labor, QC Narratives). Background job with vendor matching and progress polling.

### 6. Observations Import (DONE — April 2026)
Import QAQC Deficiency Items (QA + QC) as Procore Observations. CSV parser (replaced old Excel parser), location matching with auto-create, observation type selection, background job. See `docs/qaqc-observations.md`.

### 7. Inspections Import (PLANNED)
Import QC Tests as Procore Inspections. CSV parser built (`TestParser`), Procore Inspections API researched (template-based "Checklists" API). Pending template approach decision — Procore requires inspections to be created from templates. See `docs/qaqc-observations.md`.

### 8. Procore Marketplace Listing (FUTURE)
To make this available to other USACE contractors:
- Contact Procore partner program for fees/requirements
- Validate pain point with 3-5 other USACE contractors
- Dynamic project selection: DONE
- Multi-project setup wizard: DONE
- Optional file uploads: DONE
- Scope full feature set and pricing model
