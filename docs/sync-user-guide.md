# RMS to Procore Sync — User Guide

This guide walks through updating Procore submittal data from RMS using the web app. Run this weekly (or as needed) to keep Procore in sync with RMS.

## Prerequisites

- Access to RMS (Resident Management System)
- A Procore account with submittal access
- The RMS Importer app running locally (backend + frontend)

## Step 1: Download RMS Files

Export four files from RMS. All files should be saved in Excel (.xlsx) or CSV format.

### Submittal Register
1. In RMS, go to **Submittals > Submittal Register**
2. Click **Export** and save as `.xlsx`

### Submittal Assignments
1. In RMS, go to **Submittals > Submittal Assignments**
2. Click **Export** and save as `.xlsx`

### Transmittal Log
1. In RMS, go to **Submittals > Transmittal Log**
2. **Important:** Click **Completed Transmittals** before downloading
3. Click **Export** and save as `.xlsx`

### Transmittal Report
1. In RMS, go to **Contract Reports**
2. Click **Submit**
3. Double-click **Transmittal Log** (to avoid confusion with the Transmittal Log above, we call this Transmittal Report)
4. Click **Preview**
5. Click the **Save** icon (floppy disk icon) and choose **CSV** format

### RMS Files (Transmittal PDFs)
If there are new transmittal documents since the last sync:
1. In RMS, go to the file download area
2. Filter by date to download only new files (since last sync)
3. Save to the `RMS Files` folder alongside the existing files

## Step 2: Start the App

Open a terminal and run:
```
powershell -File rms-importer/start_dev.ps1
```

This starts two servers:
- **Backend** on http://localhost:8000
- **Frontend** on http://localhost:3000

Open http://localhost:3000 in your browser.

## Step 3: Connect to Procore

1. Click **Connect with Procore**
2. You'll be redirected to Procore's login page
3. Sign in and click **Allow** to authorize the app
4. You'll be redirected back to the app

## Step 4: Select Project

1. Your company will auto-select if you only have one
2. Select the target project from the dropdown (e.g., "Dobbins Security Forces Facility")
3. Wait for the project stats to load — this can take **30-60 seconds** for large projects
4. Once stats appear (submittal count, spec sections, revisions), click **Continue**

## Step 5: Upload RMS Files

1. Select each of the four files using the file pickers:
   - **Submittal Register** — the `.xlsx` export
   - **Submittal Assignments** — the `.xlsx` export
   - **Transmittal Log** — the `.xlsx` export (make sure it's the Completed Transmittals version)
   - **Transmittal Report** — the `.csv` export from Contract Reports
2. Click **Upload & Parse Files**
3. The app will parse all four files and compare against the stored baseline

## Step 6: Review Changes

The Sync Review screen shows what changed since the last sync:

### Baseline Status
- **Last Synced** — when the last sync was run
- **Submittals in Baseline** — total submittals tracked
- **Files Uploaded** — total files tracked

### Changes Detected
Changes are grouped by type with color coding:

| Section | Color | Description |
|---------|-------|-------------|
| **New Submittals** | Green | New submittals or revisions to create in Procore |
| **QA Code Updates** | Yellow | QA codes that changed (e.g., C → A = approved) |
| **Date Updates** | Blue | Transmittal dates that changed |
| **Files to Upload** | Purple | New transmittal PDFs to attach to submittals |
| **Items Removed** | Orange | Items in baseline but not in new RMS export (flagged, not deleted) |

Click on any section to expand and see the details. Use the **checkboxes** to select which changes to apply.

### If "Everything is in sync!"
This means no changes were detected between the uploaded files and the stored baseline. Verify you uploaded the latest files.

## Step 7: Apply Changes

1. Review all sections and uncheck anything you don't want to apply
2. Click **Apply Selected Changes**
3. The app will process each change against the Procore API
4. This may take several minutes for file uploads (each file requires multiple API calls)
5. When complete, you'll see a summary with counts and any errors

### Understanding Results
- **Status: Completed** — all changes applied successfully
- **Status: Partial** — some changes applied, check errors
- **Created** — new submittals created in Procore
- **Updated** — existing submittals updated
- **Files Uploaded** — files attached to submittals
- **Flagged for Review** — items removed from RMS, flagged in the app (not deleted from Procore)

## Troubleshooting

### "Failed to load companies" or "Failed to load projects"
- Your auth session may have expired. Refresh the page and reconnect to Procore.

### "Failed to analyze data"
- The backend may have restarted. Re-upload your files.

### "No Procore ID for ..." errors during file upload
- The submittal exists in Procore but the app doesn't know its ID. This is resolved by running the ID backfill (ask your admin).

### File upload 400 errors
- A file with the same name may already exist in Procore. Check the Procore documents folder.

### Stats take too long to load
- Normal for projects with 2000+ submittals. The app fetches all submittals to calculate counts. Wait 30-60 seconds.

## Data Flow Summary

```
RMS Files (4 exports)
    ↓
Upload & Parse
    ↓
Compare against stored baseline (SQLite)
    ↓
Sync Review (creates, updates, files, flags)
    ↓
Apply to Procore API
    ↓
Update baseline for next sync
```

### What comes from each file

| File | Provides |
|------|----------|
| Submittal Register | Section, item number, title, type, QC code, status |
| Submittal Assignments | Info code (GA/FIO/S), contractor |
| Transmittal Log | Revision numbers, 4 dates (contractor prepared, govt received, govt returned, contractor received) |
| Transmittal Report | QA codes for all submittals and revisions (authoritative source) |

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
