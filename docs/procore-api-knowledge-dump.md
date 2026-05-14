# Procore API Knowledge Dump

Starter knowledge base for a "Procore Integration Reviewer" agent. Captures what was actually learned implementing the RMS Importer (submittals, RFIs, daily logs, observations, files). Treat each item as confirmed against Procore production, April–May 2026, unless marked "researched."

---

## 1. Agent scope (suggested)

Use this when reviewing code that touches the Procore REST API:
- OAuth and token handling
- Submittal / RFI / Observation / Daily Log / Inspection creates and updates
- Custom field reads/writes
- File uploads and attachments
- Rate-limit-sensitive batch operations
- Status transitions and workflow assumptions

Flag deviations from the patterns below; many have a "looks fine but silently fails" failure mode.

---

## 2. Base URL, auth, OAuth

- **Base URL (prod):** `https://api.procore.com` (configurable; sandbox available)
- **Auth header:** `Authorization: Bearer <access_token>`
- **Company scoping:** include `Procore-Company-Id: <id>` header on calls that need a company context; some endpoints 403 without it
- **OAuth grant types used:**
  - `authorization_code` → exchange `code` at `/oauth/token` with `client_id`, `client_secret`, `redirect_uri`
  - `refresh_token` → exchange `refresh_token` at the same endpoint
- **Tokens expire.** Long-running background jobs (file uploads, multi-phase imports) must refresh tokens at job start, or re-refresh mid-flight, or they'll 401 partway through.
- **Service-account vs user OAuth:** some admin endpoints (e.g., company-level custom field definitions) require elevated permissions not available to user OAuth tokens.

---

## 3. Rate limits — TWO separate budgets

Procore enforces both; the spike limit is the one you'll hit first:

| Limit | Window | Cap (approx) |
|------|--------|------|
| Hourly | 60-min sliding | 3,600 req |
| Spike  | 10-sec sliding | ~20–30 req |

**Rules that worked in prod:**
- Minimum 2-second delay between API calls in batch scripts (`-DelayMs 2000` in PowerShell)
- 0.5–1s sleep between pagination pages
- File uploads do 4+ API calls per file → add 1s delays inside `upload_file()` and 5s between files
- Dry runs still consume API calls (GETs count)
- Multiple scripts in the same hour share the same budget
- On 429: wait and retry, don't skip
- Production client uses 30s / 60s / 120s exponential backoff with 3 retries

---

## 4. Endpoint patterns

- Most endpoints live under `/rest/v1.0/`. A few resources have v1.1 variants — always check; mixing them can break (see Submittal attachment via v1.1 below).
- **Pagination:** `page` + `per_page` query params; `per_page` max generally 300 for documents, 100 for most others. Use the `Total` (or `X-Total`) response header to get counts without pulling rows — one call instead of N pages.
- **List vs detail diverge.** List responses commonly omit fields the detail response includes (custom fields, attachments, answers). When you need those, GET the detail.
- **Empty list = last page.** Stop paginating when an empty array comes back or when `len(items) < per_page`.

---

## 5. Submittals

### Endpoints
- `GET  /rest/v1.0/projects/{id}/submittals` (list, paginated)
- `GET  /rest/v1.0/projects/{id}/submittals/{sub_id}` (detail; includes custom fields, attachments)
- `POST /rest/v1.0/projects/{id}/submittals` — body: `{"submittal": {...}}`
- `PATCH /rest/v1.0/projects/{id}/submittals/{sub_id}` — body: `{"submittal": {...}}`
- `PATCH /rest/v1.1/projects/{id}/submittals/{sub_id}` — used for attachment PATCHes specifically
- `GET /rest/v1.0/projects/{id}/submittals/settings` — sometimes returns status definitions; not guaranteed
- **Create requires no manager** — project default applies server-side

### Custom fields — CRITICAL FORMAT
Custom fields must be **top-level properties** on the `submittal` object:
```json
{ "submittal": { "custom_field_598134325870420": "value" } }
```
**NOT** nested under `custom_fields`:
```json
{ "submittal": { "custom_fields": { "value" } } }  // silently ignored
```
The nested format returns 200 OK but the values do not save. This is by far the most common silent-failure mode.

- For LOV (dropdown) fields, send the integer LOV entry ID directly
- For datetime fields, send ISO `"2025-01-29T00:00:00Z"`
- Field IDs are per-project. Discover them by GETting one submittal's detail and reading the `custom_fields` keys; the company-level definition endpoint requires elevated perms.

### Spec section numbering
The "Include Spec Section Number in Submittals Numbering" company setting is **display-only.** API always stores/returns plain integer `number`. Don't try to encode the spec section in the number field.

### Spec sections API gaps
- No endpoint to list spec sections independently
- `/specification_sections` returns 404
- `/specification_uploads` returns metadata only — no file URLs, no download
- Workaround: extract unique spec sections by walking project submittals; for PDFs, split locally and upload to Documents

### Statuses
Defaults: `Draft`, `Open`, `Closed`. Per-project status definitions can be discovered from `/submittals/settings` or by scanning existing submittals' `status` objects.

---

## 6. RFIs (confirmed April 2026)

### Endpoints
- `POST /rest/v1.0/projects/{id}/rfis` — **v1.0, NOT v1.1**
- `PATCH /rest/v1.0/projects/{id}/rfis/{rfi_id}`
- `POST /rest/v1.0/projects/{id}/rfis/{rfi_id}/replies`
- `GET  /rest/v1.0/projects/{id}/rfis` — list; `questions` array has only `id`, `body`, `errors` (NO answers, NO attachments)
- `GET  /rest/v1.0/projects/{id}/rfis/{rfi_id}` — detail; `questions[].attachments`, `questions[].answers[]`, full bodies
- `GET  /rest/v1.0/projects/{id}/rfis/{rfi_id}/replies`
- `GET  /rest/v1.0/projects/{id}/rfis/{rfi_id}/questions` → **404, not valid**

### Required create fields
- `subject`
- `rfi_manager_id` (project-level default RFI manager is NOT exposed via API)
- `assignee_ids` (array)
- `question` — **singular object**, not `questions` array, not `question_body`:
  ```json
  "question": {"body": "the question text"}
  ```
- `number` is a string (e.g. `"62"`), not integer

### Status values
`"draft"`, `"open"`, `"closed"` (lowercase).

### Status changes silently ignored
`PATCH /rfis/{id}` with `status: "closed"` returns 200 but does NOT change the status. Applies to both user OAuth and service-account tokens. RFIs must be opened/closed in the Procore UI.

### Replies blocked on closed RFIs
`POST /replies` returns 403 if the RFI is `closed`. Must be manually reopened.

### Attachments
- File-upload-then-attach: PATCH RFI with `prostore_file_ids: [...]` — **PATCH replaces the entire list**, it does not append. To add a file: GET detail, read existing IDs (from `questions[0].attachments` first, fall back to top-level `attachments`), append your new ID, PATCH the merged list. Without merge, every file after the first overwrites the previous one.
- The list GET does NOT include `attachments` — to check existing files, search the Documents upload folder by name pattern (e.g. `RFI-*`).

### Replies and reply attachments
- `POST /replies` body: `{"reply": {"body": "...", "official": true, "prostore_file_ids": [id]}}`
- `official: true` marks the reply as the official response (can also PATCH later)
- Replies returned by `GET /replies` are the same objects as `questions[].answers[]`. No separate `official_response` field on the RFI itself.

---

## 7. Daily Logs (confirmed April 2026)

All under `/rest/v1.0/projects/{id}/...`. All return `status: "approved"` by default. Date filter: `log_date=YYYY-MM-DD`.

| Log type | Endpoint | Notable fields |
|----------|----------|----------------|
| Equipment | `equipment_logs` | `date`, `hours_idle`, `hours_operating`, `notes`, `equipment`, `vendor`. Equipment field may require Procore equipment register ID (not free text). |
| Manpower  | `manpower_logs`  | `date`, `num_workers`, `num_hours`, `man_hours`, `notes`, `vendor_id`, `trade`. Vendor requires Procore vendor ID. |
| Notes     | `notes_logs`     | `date`, `comment`, `vendor`, custom fields (e.g., Narrative Type LOV). |

Other log types available (not yet implemented): `weather_logs`, `work_logs`, `visitor_logs`, `safety_violation_logs`, `inspection_logs`, `quantity_logs`, `delivery_logs`, `accident_logs`, `call_logs`, `dumpster_logs`, `waste_logs`, `plan_revision_logs`, `timecard_entries`.

---

## 8. Observations (confirmed April 2026)

- **Create:** `POST /rest/v1.0/observations/items` — body is `{"project_id": 123, "observation": {...}}`. Project ID is in the **body, not the path.**
- **Update:** `PATCH /rest/v1.0/projects/{id}/observations/items/{obs_id}` — wrapper is `observation_item` (singular item path; confusing inconsistency vs create).
- **List:** `GET /rest/v1.0/projects/{id}/observations/items`
- **Types:** `GET /rest/v1.0/projects/{id}/observations/types`
- **Required fields:** `name`, `type_id`
- **Status values:** `initiated`, `ready_for_review`, `not_accepted`, `closed`
- **Priority values:** `Low`, `Medium`, `High`, `Urgent` (capitalized)
- **Default type categories:** Safety (4), Quality (4), Commissioning (1), Warranty (1)
- **Not auto-emailed.** Created observations are silent until you call `POST /observations/items/send_unsent`.

### Locations (used by observations)
- `GET /rest/v1.0/projects/{id}/locations` — paginated
- `POST /rest/v1.0/projects/{id}/locations` — body: `{"location": {"name": "...", "parent_id": optional}}`

---

## 9. Inspections / Checklists (researched April 2026, not fully implemented)

- **Template-based.** You can't create a freeform inspection — you create from a `list_template_id`.
- `POST /rest/v1.0/projects/{id}/checklist/lists` — requires `list_template_id` + `list` object
- `POST /rest/v1.0/projects/{id}/checklist/list_templates` — create template
- Statuses: `open`, `in_review`, `closed`
- Item response statuses: `conforming`, `non_conforming`, `not_applicable`
- Inspection types: `GET/POST /rest/v1.0/companies/{id}/inspection_types`
- Sections + items: `POST /checklist/lists/{id}/sections` (deprecated but functional) with `items_attributes` array

---

## 10. File uploads and attachments

### Four-step upload flow
Procore uses S3-presigned uploads. Each new file = 4+ API calls:

1. `POST /rest/v1.0/projects/{id}/uploads` with `response_filename` + `response_content_type` → returns `{url, fields, uuid}` (S3 presigned URL)
2. `POST` file bytes to S3 `url` with `fields` as form data (this call is NOT a Procore API call — no rate limit)
3. `POST /rest/v1.0/projects/{id}/documents` with `{"document": {"name", "upload_uuid", "parent_id": folder_id}}`
4. `GET /rest/v1.0/projects/{id}/documents` (filtered/sorted) to retrieve the new doc's `file.current_version.prostore_file.id` — this is the `prostore_file_id` used for attachments

After upload, attach to a record by PATCHing it with `prostore_file_ids: [id, ...]`.

### Dedupe (very important on re-runs)
- POST /documents returns **400 "name has already been taken"** if the filename collides in the parent folder. There's no `?upsert=true`.
- Always check existence first. Build a per-project doc cache by paginating the target folder (`view=extended`, `filters[document_type]=file`, `filters[parent_id]={folder}`, `per_page=300`) — Procore folders from prior migrations can hold 1000+ files; without pagination beyond page 1, you'll 400 out repeatedly. On a 400 mid-run, bust the cache and rebuild.

### Attachment quirks
- **Submittals attach via** `PATCH /rest/v1.1/projects/{id}/submittals/{sub_id}` with `{"submittal": {"prostore_file_ids": [all_ids]}}` — list replaces, not appends. Merge with existing.
- **RFIs attach via** `PATCH /rest/v1.0/projects/{id}/rfis/{id}` with `{"rfi": {"prostore_file_ids": [...]}}` — same merge requirement. RFI attachments stored under `questions[0].attachments`.
- Reply attachments: pass `prostore_file_ids` directly in the POST /replies body.

---

## 11. Common footguns / silent-failure modes

The most useful section. If any of these patterns shows up in code under review, flag it:

1. **Custom fields nested under `custom_fields`** → silent ignore. Must be top-level on the resource object.
2. **RFI `status: "closed"` in PATCH** → 200 but no change. Must use UI.
3. **POST /replies on closed RFI** → 403. Reopen first.
4. **`PATCH /...prostore_file_ids` without merging existing** → previous attachments lost.
5. **No `Total` header read for counts** → wastes pagination on a question that needs no data.
6. **No spike-limit delay (≥1s) inside file upload loops** → 429 storms; first file works, batch 2+ collapses.
7. **Refreshing token only at process start** → multi-hour jobs 401 mid-flight. Refresh at job start AND on long jobs, mid-flow.
8. **Treating list response as authoritative** → missing `attachments`, `answers`, `custom_fields`. Get the detail.
9. **Using v1.1 RFI endpoints** → v1.0 is correct for RFIs; v1.1 attachment PATCH is only confirmed for submittals.
10. **Trying `/specification_sections`** → 404. No way to list spec sections directly.
11. **Skipping documents-folder dedupe cache pagination** → POST /documents 400 once you hit page 2 in a busy folder.
12. **Posting to `/observations/items` with project_id in path** → wrong. Project goes in body for observations create; update is path-based with a different wrapper key (`observation_item`).
13. **`question_body` or `questions: [...]` in RFI create** → wrong. Singular `question: {"body": "..."}`.
14. **Trusting that dry runs are free** → GETs count against rate limits.
15. **PowerShell COM Excel scripts not cleaning up** → orphaned `excel.exe`; kill before opening.

---

## 12. Reference: OAS spec

A full Procore OpenAPI spec exists at (in the originating repo):
`reference/combined_OAS.json` (~43 MB, all endpoints)

Read with Python `json` + utf-8 encoding. When the agent is unsure about an endpoint, the OAS is authoritative for shape but does NOT capture the silent-failure modes above — those came from production.

---

## 13. Production client patterns worth mirroring

From `backend/services/procore_api.py` in the RMS Importer:

- Single `ProcoreAPI` class with `_get / _post / _patch` helpers wrapping a `_request_with_retry` that handles 429 with `[30, 60, 120]` second backoff
- `_get_paginated` with 0.5s sleep between pages
- `_get_with_headers` variant for reading `Total` without parsing body
- Per-class `_doc_cache: dict[int, dict[str, int]]` keyed by project_id → filename → prostore_file_id; built once per project, rebuilt on cache-miss 400
- `_refresh_session_token` callable from job start AND mid-job
- `KNOWN_FIELD_LABELS` dict for known custom-field IDs so labels survive when Procore omits them

---

## 14. Suggested reviewer heuristics

When reviewing a PR that touches Procore code, walk this checklist:

- [ ] Are custom fields written top-level on the resource (not nested)?
- [ ] Does any PATCH that includes `prostore_file_ids` first GET and merge existing IDs?
- [ ] Is there backoff on 429? Is the spike delay (≥1s) inside per-file loops?
- [ ] Does a long-running job refresh the OAuth token at start?
- [ ] Is pagination terminated correctly (`len < per_page` or empty)?
- [ ] Are list-vs-detail expectations correct (attachments, answers, custom fields require detail)?
- [ ] Are status transitions assumed via API actually supported (RFI close, submittal status)?
- [ ] For new endpoints: is the project_id in path vs body matched to the resource (observations are body)?
- [ ] Is the documents-folder dedupe cache paginated?
- [ ] Does the code account for filenames already-taken (400 on POST /documents)?

---

*Last validated against production: May 2026. Sources: `backend/services/procore_api.py` in `mckayje3/rms-importer`, RMS Importer project CLAUDE.md, PowerShell migration scripts (`rms-importer/scripts/`), and observed failures during the Dobbins SFF migration (2,280 submittals, 1,166 files).*
