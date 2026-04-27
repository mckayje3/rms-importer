# RMS to Procore Sync — User Guide

This guide walks through updating Procore submittal data from RMS using the web app. Run this weekly (or as needed) to keep Procore in sync with RMS.

## Prerequisites

- Access to RMS (Resident Management System)
- A Procore account with submittal access
- The RMS Importer app (web — see deployment URL — or local backend + frontend)

## Step 1: Download RMS Files

Export two CSV files from RMS plus (optionally) a folder of transmittal PDFs.

### Submittal Register Report (required)

1. In RMS, go to **Contract Reports > Submit > Submittal Register**
2. Click **Preview**, then **Save** as **CSV**
3. Save as `Submittal Register Report.csv`

This single file replaces the older Submittal Register + Submittal Assignments combo. It carries all submittals with paragraph references, classifications (Info), and types.

### Transmittal Report (required for revisions/dates/QA codes)

1. In RMS, go to **Contract Reports > Submit > Transmittal Log**
2. Double-click **Transmittal Log**, click **Preview**, then **Save** as **CSV**
3. Save as `Transmittal Report.csv`

### RMS Files folder (optional — only if uploading PDFs this run)

1. In RMS, go to **Import/Export > Document Package Export**
2. Check both:
   - "All Documents in Contractor Transmittal Document Packages"
   - "All Documents in Contractor Submittal Item Document Packages"
3. Download all files into a single folder (e.g., `RMS Files`)

Files should be named `Transmittal {Section}-{Num}[.{Rev}] - {Description}.pdf`. The app filters to that pattern automatically — anything else in the folder is ignored.

## Step 2: Open the App

Local dev:
```
powershell -File rms-importer/start_dev.ps1
```
Backend: http://localhost:8000 — Frontend: http://localhost:3000

Production: open the deployed URL (Vercel) or use the Procore embedded app.

## Step 3: Connect to Procore

1. Click **Connect with Procore**
2. Sign in and authorize the app
3. You'll be redirected back

## Step 4: Select Project & Tool

1. Pick the **Company** and **Project** (auto-selected when embedded in Procore)
2. Wait for stats to load (30-60s for large projects)
3. Pick **Submittals** on the tool selector

## Step 5: Upload Step (CSVs + folder picker)

This is the only step where you provide inputs. Two things happen here:

1. **Upload the two CSVs** (Register Report, Transmittal Report) and click **Upload & Parse Files**.
2. **(Optional) Pick the RMS Files folder.** A "Select RMS Files Folder" button appears below the parse summary once the CSVs are accepted. Click it and pick the folder of transmittal PDFs.
   - The app immediately checks each filename against the project baseline and shows a count: `N new files to upload, M already uploaded, K unrecognized`. **No bytes are uploaded yet** — file handles are held in the browser until you confirm on the next step.
3. Click **Continue to Review**.

If you don't have new PDFs this run, skip the folder picker and just click Continue.

## Step 6: Review Step (preview only)

The Sync Review screen shows what *would* change. Nothing has been touched yet.

### Sections
| Section | Color | Description |
|---------|-------|-------------|
| **New Submittals** | Green | Submittals to create in Procore |
| **QA Code Updates** | Yellow | QA codes that changed |
| **Date Updates** | Blue | Government Received / Returned dates that changed |
| **Other Updates** | Gray | Title / type / paragraph / QC code / info changes |
| **File Plan** | Purple | Files to upload, broken out by destination |
| **Items Removed** | Orange | In baseline but not in latest export — flagged, not deleted |

### File Plan breakdown
- **Will attach to existing submittals** — files whose target submittals already exist in Procore.
- **Will attach to new submittals (created above)** — files whose target submittals will be created in this same run. (This case used to silently fail; now handled in one orchestrated job.)
- **Already uploaded — will skip** — filenames seen in the project baseline.
- **Unrecognized name — will skip** — files that don't match any RMS submittal.

Use the checkboxes on each section to deselect anything you don't want applied.

### "Everything is in sync!"
No changes were detected and you didn't pick any new files. Verify the CSV exports are current.

## Step 7: Apply Step

Click **Apply**. The app posts everything (CSVs, sync options, file bytes) to one background job and shows live progress. Order is fixed:

1. **Create new submittals** (records each new Procore ID in memory)
2. **Save baseline checkpoint**
3. **Upload + attach files** (to both pre-existing and just-created submittals)
4. **Apply field updates** to existing submittals
5. **Save final baseline**

You can navigate away — the job continues. Reopen the app and the Complete page will reattach to the running job's progress.

### Result summary
- **Status: Completed** — all selected changes applied
- **Status: Partial** — some applied, see error list
- **Created / Updated / Files Uploaded** — counts
- **Flagged for Review** — items removed from RMS, surfaced in the app (not deleted from Procore)

## Troubleshooting

### "Failed to load companies" or "Failed to load projects"
Auth session expired. Refresh the page and reconnect to Procore.

### "Failed to analyze data"
Backend may have restarted. Re-upload your CSVs.

### "no Procore ID for submittal key …" during file phase
A file's target submittal isn't in the baseline and wasn't created in this run (e.g. it's a revision whose parent doesn't exist yet). Verify the CSV exports include the parent submittal.

### File upload 400 errors mentioning `/documents`
Usually "name has already been taken" — i.e. a file with that name already exists in the Procore folder. The app paginates the entire target folder to detect duplicates; if you still see this, the duplicate may be in a different folder than `PROCORE_UPLOAD_FOLDER_ID`.

### File upload 401 errors
Stale OAuth token. The app refreshes at job start, but if Procore rejects the refresh, you'll need to reconnect. Click logout, then **Connect with Procore** again.

### Stats take too long to load
Normal for projects with 2000+ submittals. Wait 30-60 seconds.

## Data Flow Summary

```
RMS CSVs (Register + Transmittal Report) + RMS Files folder
    ↓
Upload Step: parse CSVs, filename-check folder against baseline
    ↓
Review Step: diff vs baseline, file plan preview
    ↓
Apply Step (one background job):
    creates → save baseline → file uploads → updates → save final baseline
    ↓
Complete Step: live progress, then summary
```

### What comes from each file

| File | Provides |
|------|----------|
| Submittal Register Report | Section, item number, title, type, paragraph, QC code, Info code, status |
| Transmittal Report | Revisions, government received/returned dates, QA codes (authoritative) |
| RMS Files folder | Transmittal PDFs to upload to Procore Documents and attach to submittals |

### QA Code → Procore Status Mapping

| QA Code | Meaning | Procore Status |
|---------|---------|----------------|
| A | Approved | Closed |
| B | Approved as Noted | Closed |
| C | Approved, Resubmit Required | Open |
| D | Disapproved, Revise/Resubmit | Open |
| E | Disapproved | Open |
| F | For Information Only | Closed |
| G | Revise and Resubmit | Open |
| X | Receipt Acknowledged | Closed |
