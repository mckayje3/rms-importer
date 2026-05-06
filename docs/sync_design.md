# RMS Importer - File-Based Sync Design

## Overview

Instead of querying Procore to detect changes, we compare new RMS exports against previously-imported RMS exports. This is faster, uses fewer API calls, and aligns with the workflow where RMS is the source of truth.

---

## User Workflow

### First Import (Full Migration)
1. User uploads two CSVs on the Upload step (Submittal Register, Transmittal Log) and (optionally) picks the RMS Files folder.
2. App parses, computes the plan, and on Apply runs the unified job: creates all submittals → uploads + attaches files → applies field updates → saves baseline.

### Subsequent Syncs
1. User exports fresh CSVs and (optionally) drops new transmittal PDFs into the RMS Files folder.
2. Upload step parses CSVs and runs `/filter-files` on the picked folder — categorizes files into new / already-uploaded / unrecognized without sending bytes.
3. Review step shows the diff vs. baseline plus a File Plan section breaking files out by destination (existing vs. brand-new submittals).
4. Apply runs `/execute-all` (multipart, files in the same request) and a single background job orchestrates creates → file attaches → updates → baseline save.

---

## Data Model

### Stored Baseline (per project)

```json
{
  "project_id": "12345",
  "company_id": "67890",
  "last_sync": "2026-03-19T10:30:00Z",
  "submittals": {
    "03 30 00|1|0": {
      "section": "03 30 00",
      "item_no": "1",
      "revision": 0,
      "title": "Concrete Mix Design",
      "type": "SD-03",
      "paragraph": "1.4.1",
      "qa_code": "A",
      "qc_code": "B",
      "info": "GA",
      "status": "closed",
      "contractor_prepared": "2025-06-15",
      "government_received": "2025-06-18",
      "government_returned": "2025-07-02",
      "contractor_received": "2025-07-05",
      "procore_id": 98765432
    },
    "03 30 00|1|1": {
      "section": "03 30 00",
      "item_no": "1",
      "revision": 1,
      "title": "Concrete Mix Design",
      "qa_code": "B",
      "procore_id": 98765433
    }
  },
  "files": {
    "Transmittal 03 30 00-1 - Concrete Mix Design.pdf": {
      "submittal_key": "03 30 00|1|0",
      "uploaded": true,
      "procore_file_id": 11111
    }
  }
}
```

Key points:
- `submittals` keyed by `section|item_no|revision`
- Each submittal stores its `procore_id` after creation
- `files` tracks which attachments have been uploaded
- `last_sync` for audit trail

---

## Diff Algorithm

### Compare Submittals

```python
def diff_submittals(baseline: dict, new_data: dict) -> SyncPlan:
    """
    Compare baseline (previously imported) with new RMS export.
    Returns a plan of what needs to be created/updated.
    """
    plan = SyncPlan()

    baseline_keys = set(baseline["submittals"].keys())
    new_keys = set(new_data["submittals"].keys())

    # New submittals (in new but not baseline)
    for key in new_keys - baseline_keys:
        plan.creates.append(CreateAction(
            key=key,
            submittal=new_data["submittals"][key]
        ))

    # Existing submittals - check for field changes
    for key in new_keys & baseline_keys:
        old = baseline["submittals"][key]
        new = new_data["submittals"][key]

        changes = diff_fields(old, new)
        if changes:
            plan.updates.append(UpdateAction(
                key=key,
                procore_id=old["procore_id"],
                changes=changes
            ))

    # Deleted submittals (in baseline but not new)
    # Usually just flag for review, don't auto-delete
    for key in baseline_keys - new_keys:
        plan.deletions.append(DeleteAction(
            key=key,
            procore_id=baseline["submittals"][key]["procore_id"]
        ))

    return plan


def diff_fields(old: dict, new: dict) -> list[FieldChange]:
    """Compare individual fields, return list of changes."""
    changes = []

    TRACKED_FIELDS = [
        "title", "type", "paragraph",
        "qa_code", "qc_code", "info",
        "contractor_prepared", "government_received",
        "government_returned", "contractor_received"
    ]

    for field in TRACKED_FIELDS:
        old_val = old.get(field)
        new_val = new.get(field)
        if old_val != new_val:
            changes.append(FieldChange(
                field=field,
                old_value=old_val,
                new_value=new_val
            ))

    return changes
```

### Compare Files

```python
def diff_files(baseline: dict, new_files: list[str]) -> FileSyncPlan:
    """
    Compare baseline uploaded files with new file list.
    """
    plan = FileSyncPlan()

    baseline_files = set(baseline.get("files", {}).keys())
    new_file_set = set(new_files)

    # New files to upload
    for filename in new_file_set - baseline_files:
        plan.uploads.append(filename)

    # Already uploaded (skip)
    plan.already_uploaded = list(new_file_set & baseline_files)

    return plan
```

---

## Sync Plan Model

```python
@dataclass
class FieldChange:
    field: str
    old_value: Any
    new_value: Any

@dataclass
class CreateAction:
    key: str  # "section|item_no|revision"
    submittal: dict

@dataclass
class UpdateAction:
    key: str
    procore_id: int
    changes: list[FieldChange]

@dataclass
class DeleteAction:
    key: str
    procore_id: int

@dataclass
class SyncPlan:
    creates: list[CreateAction]
    updates: list[UpdateAction]
    deletions: list[DeleteAction]  # Flag only, don't auto-delete

    @property
    def summary(self) -> str:
        parts = []
        if self.creates:
            parts.append(f"{len(self.creates)} new submittals")
        if self.updates:
            parts.append(f"{len(self.updates)} updates")
        if self.deletions:
            parts.append(f"{len(self.deletions)} removed in RMS")
        return ", ".join(parts) or "No changes"
```

---

## API Endpoints

CSV uploads happen separately via `POST /rms/upload` (multipart, returns an `rms_session_id`). The sync endpoints below operate against that session.

### POST /sync/projects/{project_id}/filter-files

Filename-only check — categorizes files against the baseline without uploading bytes. Used by the folder picker on the Upload step.

**Request:**
```json
{
  "session_id": "<rms_session_id>",
  "filenames": ["Transmittal 03 30 00-1 - Concrete.pdf", "..."]
}
```

**Response:**
```json
{
  "new_files":         ["Transmittal 03 30 00-1 - Concrete.pdf"],
  "already_uploaded":  ["Transmittal 03 30 00-2 - Rebar.pdf"],
  "unmapped_files":    ["random.pdf"],
  "total_checked":     3
}
```

### POST /sync/projects/{project_id}/analyze

Compute the sync plan from the parsed RMS data and the (optional) list of picked filenames.

**Request:**
```json
{
  "session_id": "<rms_session_id>",
  "project_id": 123,
  "company_id": 456,
  "file_list":  ["Transmittal 03 30 00-1 - Concrete.pdf"]
}
```

**Response:** `{baseline, plan, summary}` where `plan` contains `creates`, `updates`, `flags`, `file_uploads`, `files_already_uploaded`, `has_changes`, `summary`.

### POST /sync/projects/{project_id}/execute-all  ← primary write endpoint

Multipart endpoint that takes both sync options and the actual file bytes. Kicks off `process_sync_job` as one orchestrated background job and returns a `job_id`.

**Request (multipart):**
- `request_json`: JSON `{session_id, apply_creates, apply_updates, apply_date_updates, repair_custom_fields}`
- `files`: zero or more file uploads (the picked transmittal PDFs)
- Headers: `X-Auth-Session`, `X-Company-Id`

**Response:** `SyncExecuteResponse` with `update_job_id` set; poll `GET /sync/projects/{id}/file-jobs/{job_id}` for status.

**Job phases (in order):**
1. Create new submittals → record each new Procore ID in memory.
2. Save baseline checkpoint.
3. Upload + attach files. The `key_to_procore_id` lookup combines pre-existing baseline IDs with the in-memory IDs from phase 1, so files for brand-new submittals attach correctly.
4. Apply field updates (status, dates, custom fields).
5. Save final baseline + sync history entry.
6. Clean up temp files.

The unified order is the fix for the silent-fail bug: previously, file uploads were a separate `process_file_job` that built its lookup from the baseline alone, so files for newly-created submittals couldn't attach.

### POST /sync/projects/{project_id}/execute  (legacy, no files)

Same as `execute-all` but JSON-only with no file bytes. Calls `process_sync_job(file_manifest=None)`. Kept for flows that don't need file uploads.

### GET /sync/projects/{project_id}/baseline / DELETE same

Read or reset the stored baseline. DELETE is used for re-import scenarios.

### POST /sync/projects/{project_id}/bootstrap

Match RMS data against existing Procore submittals and seed a baseline without creating anything. Used when a project was migrated outside this app (e.g. via the PowerShell scripts).

---

## Storage Options

### Option A: Local JSON Files (Simple)

```
/data/baselines/
  project_12345.json
  project_67890.json
```

Pros: Simple, no database needed
Cons: Doesn't scale, no multi-user

### Option B: SQLite (Single-Server)

```sql
CREATE TABLE baselines (
  project_id TEXT PRIMARY KEY,
  company_id TEXT,
  last_sync TIMESTAMP,
  data JSON
);

CREATE TABLE sync_history (
  id INTEGER PRIMARY KEY,
  project_id TEXT,
  sync_date TIMESTAMP,
  creates INTEGER,
  updates INTEGER,
  errors TEXT
);
```

Pros: Query history, more robust
Cons: Still single-server

### Option C: PostgreSQL (Production)

Same schema, but production-ready with:
- Multi-user support
- Backup/restore
- Hosted option (Supabase, RDS)

**Recommendation:** Start with SQLite for MVP, migrate to PostgreSQL for marketplace.

---

## UI Flow

Three-step wizard: **Upload → Review → Apply**. All inputs are collected on Upload, the diff is previewed on Review, and the actual writes happen as one orchestrated background job triggered from Apply.

### Step 1: Upload (CSVs + folder picker)

```
┌─────────────────────────────────────────────────────────────┐
│  Upload RMS Files                                           │
├─────────────────────────────────────────────────────────────┤
│  [Submittal Register.csv]          ✓ Uploaded               │
│  [Transmittal Log.csv]             ✓ Uploaded               │
│                                                             │
│  [Upload & Parse Files]                                     │
│                                                             │
│  ── after parse: green summary appears ──                   │
│                                                             │
│  RMS Files Folder (optional)                                │
│  [Select RMS Files Folder]                                  │
│  → 12 new files to upload, 8 already uploaded               │
│                                                             │
│  [Re-upload RMS Files]   [Continue to Review]               │
└─────────────────────────────────────────────────────────────┘
```

The folder picker calls `/filter-files` immediately on selection. **No file bytes are uploaded yet** — handles are held in the browser until Apply.

### Step 2: Review (preview only)

```
┌─────────────────────────────────────────────────────────────┐
│  Sync Review                                                │
├─────────────────────────────────────────────────────────────┤
│  Baseline: last synced 2026-04-20, 2,084 submittals         │
│                                                             │
│  ☑ 3 New Submittals                          [Expand]       │
│  ☑ 8 QA Code Updates                         [Expand]       │
│  ☑ 2 Date Updates                            [Expand]       │
│    File Plan — 12 to upload                  [Expand]       │
│       └─ 8 will attach to existing submittals               │
│       └─ 4 will attach to NEW submittals (created above)    │
│       └─ 8 already uploaded — skip                          │
│    0 Items Removed                                          │
│                                                             │
│  [Back]                              [Apply]                │
└─────────────────────────────────────────────────────────────┘
```

### Step 3: Apply (live progress)

Apply POSTs to `/execute-all` (multipart with files), receives a `job_id`, and shows a polling progress bar. The user can navigate away — the job continues, and reopening the app reattaches to the running job.

---

## Edge Cases

### 1. No Baseline Exists
- First upload → Full Migration mode
- Create all submittals, then save as baseline

### 2. Submittal Deleted in RMS
- Flag for review, don't auto-delete in Procore
- User can manually close/delete if needed

### 3. Procore ID Not Found
- Submittal was deleted directly in Procore
- Re-create it, update baseline with new ID

### 4. Revision Number Conflict
- RMS has revision 2, baseline has revision 1
- Create revision 2 as new, link to original

### 5. File Already Exists with Different Name
- Match by content hash if needed
- Or just re-upload (Procore handles duplicates)

---

## Implementation Order

1. **Baseline Storage** (SQLite)
   - Schema for baselines and sync history
   - CRUD operations

2. **Diff Algorithm**
   - Compare submittals
   - Compare files
   - Generate SyncPlan

3. **Analyze Endpoint**
   - Upload new files
   - Parse and diff
   - Return plan

4. **Execute Endpoint**
   - Process creates/updates
   - Upload files
   - Update baseline

5. **UI**
   - Sync page
   - Plan review
   - Progress tracking

---

## Comparison: API-Based vs File-Based

| Aspect | API-Based | File-Based |
|--------|-----------|------------|
| API calls for analysis | ~20+ (fetch all submittals) | 0 |
| Detects Procore-only changes | Yes | No |
| Works offline | No | Yes (analysis only) |
| Speed | Slow | Fast |
| Complexity | Higher | Lower |
| Storage needed | None | Baseline per project |
| Rate limit risk | High | Low |

**Verdict:** File-based is better for RMS→Procore sync where RMS is source of truth.

---

## Design Decisions

1. **Storage**: SQLite for MVP, migrate to PostgreSQL/cloud for marketplace
2. **Source of truth**: RMS is authoritative (for now). Future: bidirectional sync
3. **Deleted items**: Flag for review, don't auto-close in Procore
4. **File matching**: By name (matches RMS naming convention)
