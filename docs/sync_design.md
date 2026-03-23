# RMS Importer - File-Based Sync Design

## Overview

Instead of querying Procore to detect changes, we compare new RMS exports against previously-imported RMS exports. This is faster, uses fewer API calls, and aligns with the workflow where RMS is the source of truth.

---

## User Workflow

### First Import (Full Migration)
1. User uploads RMS files (Submittal Register, Transmittal Log, Transmittal Report)
2. App parses and creates all submittals in Procore
3. App stores the parsed RMS data as the **baseline** for this project

### Subsequent Syncs
1. User exports fresh files from RMS
2. User uploads new files to the app
3. App parses new files and compares against stored baseline
4. App shows diff: "5 new submittals, 8 QA codes changed, 3 new revisions"
5. User reviews and confirms
6. App pushes only the changes to Procore
7. App updates baseline to the new data

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

### POST /projects/{project_id}/sync/analyze

Upload new RMS files and get a sync plan.

**Request:**
```
Content-Type: multipart/form-data
- submittal_register: file
- transmittal_log: file
- transmittal_report: file
```

**Response:**
```json
{
  "has_baseline": true,
  "baseline_date": "2026-03-15T10:30:00Z",
  "plan": {
    "creates": [
      {
        "key": "05 12 00|3|0",
        "title": "Structural Steel Shop Drawings"
      }
    ],
    "updates": [
      {
        "key": "03 30 00|1|0",
        "procore_id": 98765432,
        "changes": [
          {"field": "qa_code", "old": "C", "new": "A"},
          {"field": "status", "old": "open", "new": "closed"}
        ]
      }
    ],
    "deletions": [],
    "file_uploads": ["Transmittal 05 12 00-3 - Steel.pdf"],
    "files_already_uploaded": 45
  },
  "summary": "3 new submittals, 8 updates, 1 file to upload"
}
```

### POST /projects/{project_id}/sync/execute

Execute the sync plan.

**Request:**
```json
{
  "session_id": "abc123",
  "actions": {
    "creates": true,
    "updates": true,
    "deletions": false,
    "file_uploads": true
  }
}
```

**Response:**
```json
{
  "status": "completed",
  "results": {
    "created": 3,
    "updated": 8,
    "files_uploaded": 1,
    "errors": []
  },
  "new_baseline_saved": true
}
```

### GET /projects/{project_id}/sync/baseline

Get info about stored baseline.

**Response:**
```json
{
  "has_baseline": true,
  "last_sync": "2026-03-15T10:30:00Z",
  "submittal_count": 2084,
  "file_count": 1090
}
```

### DELETE /projects/{project_id}/sync/baseline

Reset baseline (for re-import scenarios).

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

### Sync Page

```
┌─────────────────────────────────────────────────────────────┐
│  Sync RMS Data                                              │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Last synced: March 15, 2026 at 10:30 AM                   │
│  Submittals in baseline: 2,084                              │
│  Files uploaded: 1,090                                      │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  Upload new RMS exports to check for changes        │   │
│  │                                                     │   │
│  │  [Submittal Register.xlsx]  ✓ Uploaded              │   │
│  │  [Transmittal Log.xlsx]     ✓ Uploaded              │   │
│  │  [Transmittal Report.xls]   ✓ Uploaded              │   │
│  │                                                     │   │
│  │  [Analyze Changes]                                  │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### Sync Plan Review

```
┌─────────────────────────────────────────────────────────────┐
│  Sync Plan                                                  │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Changes detected:                                          │
│                                                             │
│  ✓ 3 new submittals                          [View]        │
│  ✓ 8 QA code updates                         [View]        │
│  ✓ 2 new revisions                           [View]        │
│  ✓ 5 files to upload                         [View]        │
│  ○ 0 removed in RMS                                        │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  QA Code Updates (8)                                │   │
│  │                                                     │   │
│  │  03 30 00-1    C → A  (Rev & Resubmit → Approved)  │   │
│  │  03 30 00-2    D → B  (Disapproved → Approved)     │   │
│  │  05 12 00-1.1  - → A  (blank → Approved)           │   │
│  │  ...                                                │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  [Apply Selected Changes]        [Cancel]                   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

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
