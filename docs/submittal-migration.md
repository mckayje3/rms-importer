# RMS to Procore Submittal Migration (PowerShell Scripts)

Migration of submittal data from RMS to Procore. Completed March 2026.

## Key Data Files
- `Submittals/1 - Submittal Report.xlsx` - Main RMS export with multiple sheets (current revision only)
- `Submittals/Transmittal Log.xlsx` - Date tracking + item number mapping (288 rows, 834 submittal entries)
- `Submittals/Transmittal Report.xls` - QA Code per revision (332 transmittals, 920 items) - historical data
- `Submittals/procore_upload_config.json` - API credentials (client_id, client_secret, project_id, company_id)
- `Submittals/RMS files/` - 1,090 PDF files to upload as attachments

## Migration Statistics
- **Total Submittals**: 2,210 (1,933 base + 277 revisions)
- **Files Uploaded**: 1,090 PDF attachments (663 re-uploaded after fix)
- **Custom Fields**: 8 (Paragraph, QC Code, QA Code, Info, + 4 date fields)

## Production Scripts

### File Upload
| Script | Description |
|--------|-------------|
| `procore_upload_files_v3.ps1` | **RECOMMENDED** Fixed upload script - uses Transmittal Log for correct item mapping |
| `procore_upload_files_v2.ps1` | **DEPRECATED** Had bug: used transmittal number as item number |
| `fix_attachments.ps1` | Fix misplaced attachments from v2 bug |
| `fix_missing_uploads.ps1` | Find submittals missing files and upload them (uses Transmittal Log + RMS files) |
| `fix_multi_item_attachments.ps1` | Copy attachments to all items in multi-item transmittals |
| `fix_revision_fields.ps1` | Copy Contractor, Paragraph, Info from originals to revisions (Type skipped — Procore API limitation) |
| `retry_failed.ps1` | Retry specific failed files from failed_files.txt |
| `remove_duplicates.ps1` | Remove duplicate attachments from submittals |

**v3 vs v2 Bug Fix:**
- v2 extracted item number from filename (e.g., `Transmittal 03 30 00-1` → item 1) **WRONG**
- v3 looks up transmittal in Transmittal Log to find actual item number(s) **CORRECT**
- v3 handles multi-item transmittals (uploads to all items)
- v3 includes revision in submittal lookup

**Multi-Item Transmittal Bug (March 2026):**
The v3 script called the full 6-step upload for EACH target item, hitting rate limits after
the first few. Files ended up attached to only one item instead of all items in the transmittal.
Fixed by `fix_multi_item_attachments.ps1` which reuses the `prostore_file_id` from the item
that has the file and PATCHes it onto all missing items (2 API calls per fix instead of 6).
The web app (`procore_api.py`) was also fixed to upload once then attach to all targets.

**PowerShell Array Wrap Bug (March 2026):**
When splitting Transmittal Log item numbers by comma, PowerShell returns a **string** (not array)
for single-item transmittals. `"26"[0]` returns `"2"` (first character), not `"26"`.
This caused all single-item transmittals with item number > 9 to look up the wrong submittal.
Fix: always wrap `-split` results in `@()` to force an array:
```powershell
# WRONG - "26"[0] returns "2"
$items = ($str -split ',') | ForEach-Object { $_.Trim() }
# CORRECT - @("26")[0] returns "26"
$items = @(($str -split ',') | ForEach-Object { $_.Trim() })
```
Affected scripts: `fix_missing_uploads.ps1`, `fix_multi_item_attachments.ps1`, `procore_upload_files_v3.ps1`,
`procore_update_date_fields.ps1`, `sync_diff_rms.ps1`. All patched 2026-03-24.

**Upload Script Parameters (v3):**
```powershell
.\procore_upload_files_v3.ps1 -DryRun           # Preview only
.\procore_upload_files_v3.ps1 -Limit 10         # Process only 10 files
.\procore_upload_files_v3.ps1 -ResetState       # Clear state and start fresh
.\procore_upload_files_v3.ps1 -RetryFailed      # Retry previously failed files
```

### Submittal Revisions
| Script | Description |
|--------|-------------|
| `create_revisions.ps1` | Create revision submittals from files with .1, .2 suffixes |
| `fix_revision_fields.ps1` | Copy Responsible Contractor, Type, Paragraph, Info from original to revisions |

**Revision Field Sources:**
| Field | Source | Script |
|-------|--------|--------|
| Type | Original submittal (inherited) | `create_revisions.ps1` / `fix_revision_fields.ps1` |
| Responsible Contractor | Original submittal (inherited) | `create_revisions.ps1` / `fix_revision_fields.ps1` |
| Paragraph | Original submittal (inherited) | `create_revisions.ps1` / `fix_revision_fields.ps1` |
| Info/Classification | Original submittal (inherited) | `create_revisions.ps1` / `fix_revision_fields.ps1` |
| QA Code | Transmittal Report (per-revision) | `procore_update_qa_from_transmittal_report.ps1` |
| Dates | Transmittal Log (per-revision) | `procore_update_date_fields.ps1` |
| Status | Derived from QA Code | `procore_update_qa_from_transmittal_report.ps1 -UpdateStatus` |

**Revision Script Parameters:**
```powershell
.\create_revisions.ps1 -DryRun                  # Preview only
.\fix_revision_fields.ps1 -DryRun               # Preview only
.\fix_revision_fields.ps1 -Limit 5              # Test with 5 revisions
```

### Custom Fields
| Script | Description |
|--------|-------------|
| `procore_update_custom_fields.ps1` | Populate QA/QC/Paragraph/Info from RMS data (current revision only) |
| `procore_update_date_fields.ps1` | Populate date fields from Transmittal Log |
| `procore_update_qa_from_transmittal_report.ps1` | Update QA Code for ALL revisions from Transmittal Report |
| `setup_custom_fields.ps1` | Create custom field definitions in Procore |
| `identify_custom_fields.ps1` | Discover custom field IDs from fieldsets |

**Custom Fields Update Parameters:**
```powershell
.\procore_update_custom_fields.ps1 -DryRun      # Preview only
.\procore_update_custom_fields.ps1 -Limit 10    # Process only 10
.\procore_update_custom_fields.ps1 -SkipCount 512  # Resume from position 512
.\procore_update_custom_fields.ps1 -DiscoverFields # Show field structure
```

**Date Fields Update Parameters:**
```powershell
.\procore_update_date_fields.ps1 -DryRun        # Preview only
.\procore_update_date_fields.ps1 -Limit 10      # Process only 10
.\procore_update_date_fields.ps1 -SkipCount 100 # Resume from position 100
```

**QA Code from Transmittal Report Parameters:**
```powershell
.\procore_update_qa_from_transmittal_report.ps1 -DryRun           # Preview only
.\procore_update_qa_from_transmittal_report.ps1 -UpdateStatus     # Also update Procore Status based on QA Code
.\procore_update_qa_from_transmittal_report.ps1 -Limit 10         # Process only 10
```

### Status Updates
| Script | Description |
|--------|-------------|
| `update_status_from_qa.ps1` | Update Procore Status based on QA Code custom field |
| `update_status_waves.ps1` | Wave-based status update with automatic rate limit handling |

**Status Update Parameters:**
```powershell
.\update_status_from_qa.ps1 -DryRun              # Preview only
.\update_status_from_qa.ps1 -BatchSize 30        # Updates per batch
.\update_status_from_qa.ps1 -BatchPauseMinutes 3 # Pause between batches
.\update_status_from_qa.ps1 -IncludeAllRevisions # Update all revisions (default: current only)
```

**Wave-Based Status Update:**
```powershell
.\update_status_waves.ps1 -DryRun                # Preview only
.\update_status_waves.ps1 -BatchSize 25          # Updates per wave
.\update_status_waves.ps1 -DelayMs 2000          # Delay between API calls
```
The wave script runs updates until rate limited, saves progress to `status_update_progress.json`, then waits 1 hour from wave start before continuing.

## Custom Field Configuration

**Fieldset**: "Dobbins Submittal Fields" (ID: 598134325729153)

| Field | API Key | Type | Options |
|-------|---------|------|---------|
| Paragraph | `custom_field_598134325870420` | string | (text) |
| QC Code | `custom_field_598134325871359` | dropdown | A, B, C, D |
| QA Code | `custom_field_598134325871360` | dropdown | A, B, C, D, E, F, G, X |
| Info | `custom_field_598134325871364` | dropdown | GA, FIO, S |
| Contractor Prepared | `custom_field_598134325872866` | datetime | (date) |
| Government Received | `custom_field_598134325872868` | datetime | (date) |
| Government Returned | `custom_field_598134325872869` | datetime | (date) |
| Contractor Received | `custom_field_598134325872871` | datetime | (date) |

**Data Sources (from 1 - Submittal Report.xlsx):**
- QA Code: "Raw RMS Register" sheet, column 8
- QC Code: "Raw RMS Register" sheet, column 6
- Paragraph: "Paragraphs" sheet, column 3
- Info: "Raw RMS Assignments" sheet, column 5

**Data Sources (from Transmittal Log.xlsx):**
- Contractor Prepared: column 4
- Government Received: column 5
- Government Returned: column 6
- Contractor Received: column 7

## Transmittal Number Parsing

**Transmittal Log Structure:**
- Column 1: Spec Section (e.g., "03 30 00")
- Column 2: Transmittal Number (e.g., "03 30 00-4" or "03 30 00-4.1" for revision)
- Column 3: Item numbers (comma-separated, e.g., "15,11,12,14,20,21,22,23") - ACTUAL item numbers
- Columns 4-7: Date fields

**Parsing Rules:**
```
01 50 00-1.2
   ↑     ↑ ↑
   │     │ └── Revision number (2) ← WE USE THIS
   │     └──── Transmittal order in RMS (ignore)
   └────────── Spec section
```
- The number after `-` is just the order entered into RMS (NOT the item number)
- The `.X` suffix indicates a revision (no suffix = original, .1 = rev 1, .2 = rev 2)
- **Actual item numbers** come from Column 3 (Transmittal Log) or data rows (Transmittal Report)

**Join Logic:**
```
Key = "{Section}-{ItemNo}-{Revision}"
Example: "01 50 00-3-2" = Section 01 50 00, Item 3, Revision 2
```
Dates from one Transmittal Log row apply to ALL items listed in Column 3.
Total: 288 rows expand to 834 submittal entries (including revisions).

## RMS File Naming Convention
Files in `RMS files/` folder follow this pattern:
```
Transmittal {Section}-{ItemNo}.{Revision} - {Description}.pdf
```
Examples:
- `Transmittal 05 12 00-1 - Structural Steel.pdf` (original)
- `Transmittal 05 12 00-1.1 - Structural Steel Rev1.pdf` (revision 1)

## Procore API Notes
- **Authentication**: OAuth2 client credentials flow
- **Submittal Revisions**: Created by setting `source_submittal_log_id` to original's ID
- **Custom Fields**: Must create fieldset at Company level, then assign to project
- **File Attachments**: Upload to ProStore, then attach via `prostore_file_ids`

### Rate Limits (Two-Tier System)

Procore enforces **two separate rate limits** ([docs](https://developers.procore.com/documentation/rate-limiting)):

| Limit | Window | Threshold | What it means |
|-------|--------|-----------|---------------|
| **Hourly limit** | 60-minute sliding window | 3,600 requests | Total budget per hour |
| **Spike limit** | 10-second sliding window | ~20-30 requests (undocumented exact number) | Burst protection |

Both return **429 Too Many Requests** when exceeded. The response headers (`X-Rate-Limit-Remaining`, `X-Rate-Limit-Reset`) reflect whichever limit you're closest to hitting — usually the spike limit.

**Key lesson learned (March 2026):** A 1-second delay between API calls is NOT enough. Even at 1 req/sec, paginated GETs (which don't have delays) can spike the 10-second window. We hit 429s after only ~300 calls total because the spike limit was exceeded, not the hourly limit.

**Rate Limit Strategy (all scripts):**

*Recommended — steady pacing with spike-safe delay:*
```powershell
-DelayMs 2000          # 2 seconds between API calls (~1,800/hour, safe for spike limit)
```

*For large batch jobs (500+ updates):*
```powershell
-DelayMs 2000          # 2 seconds between API calls
-BatchSize 25          # Process 25, then pause
-BatchPauseMinutes 3   # Pause duration between batches
```

*Rules of thumb:*
- Never exceed ~5 requests per 10-second window (including GETs)
- Use `per_page=300` on paginated GETs to reduce total calls
- Dry runs still consume API calls (GETs count toward the limit)
- Multiple scripts in the same hour share the same budget
- Always check response headers rather than assuming a fixed limit

**Token Refresh:** All scripts include automatic token refresh every 2 hours. Token expiration errors trigger automatic refresh and retry.

**Retry Logic:** On 429 rate limit errors, wait 5 minutes and retry up to 3 times. Scripts without retry logic (e.g., `procore_update_qa_from_transmittal_report.ps1`) will log errors and skip — re-run the script and already-updated items will be auto-skipped.

## Utility Scripts
| Script | Description |
|--------|-------------|
| `inspect_procore_fields.ps1` | Inspect custom fields and schedule tasks |
| `check_submittal_fields.ps1` | View full submittal JSON structure |
| `check_rms_columns.ps1` | View RMS Excel column headers |
| `check_transmittal_log.ps1` | View Transmittal Log column headers |
| `check_transmittal_report.ps1` | View Transmittal Report structure |
| `analyze_rms_files.ps1` | Analyze file naming patterns |
| `discover_date_fields.ps1` | Discover date custom field IDs |
| `get_fieldset_raw.ps1` | Get full fieldset JSON for field discovery |
| `check_schedule_tasks.ps1` | Check schedule tasks in Procore project |
| `remove_distribution_member.ps1` | Remove a user from all submittal distribution lists |

## State Files
- `upload_state.json` - Tracks uploaded files for v2 script (deprecated)
- `upload_state_v3.json` - Tracks uploaded files for v3 script (recommended)
- `*_log_*.txt` - Timestamped log files for each script run

## QA Code to Status Mapping

| QA Code | Meaning | Procore Status | Procore Status ID |
|---------|---------|----------------|-------------------|
| A | Approved | closed | 598134326473636 |
| B | Approved as Noted | closed | 598134326473637 |
| C | Approved, Resubmit Required | open | 598134326473638 |
| D | Disapproved, Revise/Resubmit | open | 598134326473639 |
| E | Disapproved | open | 598134326473640 |
| F | For Information Only | closed | 598134326473641 |
| G | Revise and Resubmit | open | 598134326473642 |
| X | Receipt Acknowledged | closed | 598134326473643 |
