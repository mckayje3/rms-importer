# Attachment Fix Process (March 2026) - COMPLETE

## Problem
The v2 upload script had a bug: it used the transmittal number as the item number (e.g., "Transmittal 03 30 00-1" → item 1). Transmittal numbers are just sequence numbers, not item numbers.

**Impact:** 663 of 1,114 files (59.5%) were uploaded to wrong submittals. 451 files were correctly placed.

## Solution Steps

| Step | Script | Status |
|------|--------|--------|
| 1. Identify misplaced attachments | `find_misplaced_attachments.ps1` | Done - 663 files |
| 2. Delete submittals with wrong attachments | `delete_wrong_submittals.ps1` | Done - 187 deleted |
| 3. Extract missing target submittals | `extract_missing.ps1` | Done - 56 unique |
| 4. Look up RMS data for missing | `lookup_missing_submittals.ps1` | Done |
| 5. Recreate target submittals | `recreate_submittals.ps1 -Live` | Done - 56 created |
| 6. Re-upload files to correct submittals | `fix_attachments.ps1 -Live` | Done - 663 files |
| 7. Second pass for newly created targets | `fix_attachments.ps1 -Live` | Done |

## Key Data Files
| File | Description |
|------|-------------|
| `misplaced_attachments.csv` | 663 files that needed re-upload |
| `missing_submittals.csv` | 56 unique target submittals that didn't exist |
| `submittals_to_create.csv` | Full RMS data for 56 submittals to recreate |
| `transmittal_mapping.csv` | Transmittal number → item number mapping |

## Numbers
- **187 deleted**: Submittals that had wrongly-placed files (some duplicates)
- **56 recreated**: Unique target submittals needed for correct uploads
- **130 unique deleted**: 56 were both deleted AND recreated
- **74 only deleted**: Wrong submittals not needed as targets
