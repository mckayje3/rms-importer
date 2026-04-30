# RMS Importer — Procore Marketplace Integration Overview

A short summary of what the RMS Importer does, how it uses the Procore REST API, and how its design aligns with Procore's API Usage Guidelines.

**SaaS operator:** The Test Experts, LLC · 1000 Peachtree Ind Blvd, STE 6352, Suwanee, GA 30024
**Origin:** built initially for GlobalGo, LLC's USACE Dobbins ARB Security Forces Facility project (see `marketplace-case-study-dobbins.md`); productized and operated by The Test Experts.

## What the app does

Government construction contractors working on USACE projects are required to record submittals, RFIs, daily logs, and QA deficiencies in **RMS** (Resident Management System, the government's tracking platform). The same project teams use **Procore** day-to-day for collaboration. Today this means double-entry — every submittal logged in RMS gets re-typed in Procore by hand.

The RMS Importer eliminates that double-entry. The user exports CSV reports from RMS, drops them into the app, reviews a diff, and clicks Apply. The app then:

- Creates new submittals / RFIs / observations in Procore
- Updates existing records when their fields drift (QA codes, dates, custom fields)
- Uploads transmittal PDFs to Procore Documents and attaches them to the right submittal or RFI

That's the entire integration. No analytics surface, no exported reports, no third-party data sharing.

## How we use REST APIs

| Operation | Procore endpoints | Purpose |
|-----------|-------------------|---------|
| Create / update submittals | `POST/PATCH /projects/{id}/submittals` | Push parsed RMS records into Procore |
| Create RFIs and replies | `POST /projects/{id}/rfis`, `POST /rfis/{id}/replies` | Same, for RFIs |
| Create daily log entries | `POST /equipment_logs`, `POST /manpower_logs`, `POST /notes_logs` | Same, for daily logs |
| Create observations + locations | `POST /observations/items`, `POST /locations` | Same, for QA deficiencies |
| Upload + attach files | `POST /uploads`, `POST /documents`, `PATCH /submittals/{id}` | Push transmittal PDFs and attach to records |
| Read existing records | `GET /submittals`, `GET /rfis` | Diff against the user's RMS export so we only push changes |
| Read project metadata | `GET /companies`, `GET /projects`, `GET /custom_fields`, `GET /statuses` | Project setup and dynamic field-ID discovery |
| Read documents folder | `GET /projects/{id}/documents` | Deduplicate file uploads — skip files already in Procore |

Every read serves a write. We don't pull data to expose it elsewhere.

## Compliance posture vs. Procore's API Usage Guidelines

### Permitted-use checklist

| Guideline | How we comply |
|-----------|---------------|
| **Creating or updating records** | Primary use case. Submittals, RFIs, daily logs, observations — all CRUD. |
| **Reading project details, user info, financial data** | We read project lists, custom field schemas, statuses, and submittal/RFI lists for diffing. No financial data. |
| **Powering embedded apps** | The app is registered as a Procore Embedded App (Full Screen iframe). The embedded variant auto-selects the active project from `{{procore.project.id}}` interpolation. |

### Not-designed-for list

| Anti-pattern | Our position |
|--------------|--------------|
| **Large-scale data extraction or bulk export** | We don't extract data. The only bulk reads are: (a) diff against the next sync, (b) folder-level dedupe of file uploads, (c) initial project-stats display. None of this leaves the integration. |
| **AI/ML training datasets** | None. No data is used to train, fine-tune, or benchmark any model. |
| **Scraping / harvesting / copies of Procore data** | We store a minimum-necessary baseline of submittal records (10 fields per submittal, all listed in `docs/data-retention.md`). Each field is actively compared against the next RMS export — see the docstring on `StoredSubmittal` for the invariant. Anything not compared is not stored. |
| **High-volume non-complementary analytics** | None. The integration is point-to-point: RMS → Procore. |

### Best practices

| Practice | Implementation |
|----------|----------------|
| **Use APIs for their intended purpose** | Transactional CRUD; see endpoint table above. |
| **Respect rate limits** | `_request_with_retry` in `services/procore_api.py` does exponential backoff (30s/60s/120s) on 429s. Background jobs sleep 2s between API calls. File uploads sleep an extra 5s between files to stay under Procore's spike limit (~20-30 req/10s). Multiple jobs in flight share the same per-hour budget. |
| **Request only the data you need** | `get_submittal_stats` reads the `Total` pagination header from a `per_page=1` list call instead of paginating every record. `_find_existing_document` paginates the target Documents folder (per_page=300) to dedupe uploads, then caches in-memory for the rest of the job. List calls use `filters[…]` (e.g., `filters[parent_id]`) to scope server-side. |
| **Store data responsibly** | Per-project baseline in SQLite on a Railway volume. `DELETE /sync/projects/{id}/baseline` (also surfaced in the UI as a "Reset Stored Data" button on the Sync Review screen) wipes it. Logout (`POST /auth/logout`) deletes the OAuth session. Full retention policy: `docs/data-retention.md`. |

## Architecture summary

- **Frontend:** Next.js (Vercel), TypeScript, embedded-app-aware. Wizard-shaped flow per tool (Upload → Review → Apply).
- **Backend:** FastAPI (Railway), async I/O, SQLite on a Railway persistent volume.
- **Auth:** Procore OAuth (authorization code), refresh-token-based. Tokens refreshed at the start of every background job to avoid mid-flow 401s.
- **Background jobs:** All Procore writes go through one orchestrated `process_sync_job` (or its RFI / daily-logs / observations equivalents). The same job handles creates → file uploads → updates → baseline save in order — files for newly-created records resolve correctly against in-memory IDs without a separate "stale cache" lookup.
- **Operational guards:** Jobs surviving a backend restart are auto-marked failed at startup; in-flight progress is checkpointed to the DB; the frontend reattaches to running jobs on page reload.

## Data flow

```
RMS CSVs ──► Upload step (parse, filter folder against baseline)
                        │
                        ▼
              Review step (diff + file plan)
                        │
                        ▼
              Apply: POST /sync/.../execute-all  (multipart: options + file bytes)
                        │
                        ▼
          Background job, fixed phase order:
              1. Create new submittals
              2. Save baseline checkpoint
              3. Upload files to /documents and attach via PATCH
              4. Update existing records (status, dates, custom fields)
              5. Save final baseline + sync history
                        │
                        ▼
                Procore (target system)
```

No data leaves Procore once it's there. Nothing is exported, replicated, or analyzed externally.

## Pointers

- `docs/data-retention.md` — exactly what we store per project and how to delete it
- `docs/sync_design.md` — internal design notes, API endpoint shapes, UI flow
- `CLAUDE.md` — feature-table changelog of every implemented capability
