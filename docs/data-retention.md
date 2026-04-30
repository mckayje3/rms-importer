# Data Retention Policy

This document describes what data the RMS Importer stores about your Procore projects, why each piece is needed, how long it's kept, and how to delete it.

**Data controller:** The Test Experts, LLC · 1000 Peachtree Ind Blvd, STE 6352, Suwanee, GA 30024.

For the customer-facing privacy policy and your rights as a user, see [/privacy](https://rms-importer.vercel.app/privacy). This document is the engineering-side detail behind it.

## What we store

### 1. OAuth session tokens (`sessions` table)

| Field | Source | Why |
|-------|--------|-----|
| `access_token`, `refresh_token`, `expires_in` | Procore OAuth response | Required to call the Procore API on the user's behalf. Refreshed proactively at the start of each background sync job. |

**Retention:** until the user logs out (`POST /auth/logout`), or until refresh fails (e.g., token revoked in Procore). Stale sessions older than 30 days can be pruned by `SessionStore.cleanup_old_sessions`.

### 2. Sync baseline (`baselines` table, one row per project)

A snapshot of the last RMS export we successfully pushed to Procore. Used purely to compute the diff against the next export.

| Field | Why |
|-------|-----|
| `section`, `item_no`, `revision` | Composite key — identifies the record across exports |
| `procore_id` | The Procore submittal ID created/matched in this project |
| `title`, `type`, `paragraph`, `qa_code`, `qc_code`, `info`, `status`, `government_received`, `government_returned` | Compared against the next RMS export to detect drift. Each field is in `TRACKED_FIELDS` (`backend/services/sync_service.py`). If a field isn't compared, it isn't stored — see the docstring on `StoredSubmittal` (`backend/models/sync.py`). |
| `files` | Filename + Procore document ID for each transmittal PDF we've already uploaded — prevents duplicate uploads on the next sync. |

**Retention:** as long as the integration is active for that project. Deleted via `DELETE /sync/projects/{id}/baseline` or by clicking **Reset Stored Data** on the Sync Review screen.

### 3. Sync history (`sync_history` table)

Counts of each sync run (creates, updates, file uploads, errors) plus a one-line summary. No record-level data.

**Retention:** indefinite, audit trail. Cleared along with the baseline when the user resets project data.

### 4. Per-project configuration (`project_config` table)

User-supplied configuration: which Procore custom fields map to which RMS fields, status mode, SD-type-to-submittal-type mappings. **Not Procore data** — entered by the user during the setup wizard.

**Retention:** until the user resets it via `DELETE /setup/projects/{id}/config`.

### 5. Background job records (`file_jobs` table)

Status, progress counters, and (briefly) a manifest of files in flight. The manifest holds temp filesystem paths and submittal keys; no record content.

**Retention:** kept for audit. Stale running/queued jobs are auto-marked as failed on backend startup.

## What we do NOT store

- Submittal/RFI/observation record content beyond the diff fields listed above
- File bytes — uploaded transmittal PDFs are streamed straight to Procore Documents and the temp copy is deleted at end of job
- Custom field values that aren't on the diff list
- Any user PII beyond what's already in their OAuth session token
- No data is used for analytics, training, or sold to third parties

## How to delete your data

| Action | What it deletes |
|--------|-----------------|
| Click **Reset Stored Data** on the Sync Review screen | Baseline + sync history for that project |
| `POST /auth/logout` (Logout button) | OAuth session token |
| `DELETE /sync/projects/{id}/baseline` | Same as the UI button |
| `DELETE /setup/projects/{id}/config` | Per-project field-mapping config |
| Email the maintainer for full account purge | All of the above across every project |

## API usage posture

The RMS Importer is a transactional integration: every read serves a write. Bulk reads (e.g., paginating submittals to seed a baseline, paginating Documents folders to deduplicate file uploads) exist only to support creates/updates/attaches that follow within the same job. We don't extract data for external analytics, training, or third-party storage. See `docs/marketplace-overview.md` for details.
