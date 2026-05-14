# RMS Importer User Guide

Import submittal data from USACE RMS (Resident Management System) to Procore.

---

## Part 1: Export Data from RMS

Both files are required. They follow the same export flow — only the report name differs.

### Step 1: Export the Submittal Register

1. In RMS, go to **Contract Reports > Submit > Submittal Register ENG 4288**
2. Double-click the report
3. On the next screen, click **Preview**
4. When the file opens in the RMS Report Viewer, click the **Export** icon (looks like an old floppy disk)
5. Choose **.csv** as the file type
6. Pick a folder and a filename you'll find easily later (e.g., `Submittal Register.csv`) and save

> **What's in it:** the master list of every submittal — paragraph references, classifications (Info), SD types, and current QA/QC codes.

### Step 2: Export the Transmittal Log

Same flow as Step 1, just a different report:

1. In RMS, go to **Contract Reports > Submit > Transmittal Log**
2. Double-click the report
3. Click **Preview**
4. In the RMS Report Viewer, click the **Export** icon (floppy disk)
5. Choose **.csv**
6. Save it somewhere you'll find later (e.g., `Transmittal Log.csv`)

> **What's in it:** every transmittal's revisions, Date In / Date Out, and QA Code history. The importer uses this for revision tracking, date fields, and setting the correct status on existing submittals.

### Step 3: Export Submittal Files (PDFs)

1. In RMS, go to **Import/Export > Document Package Export**
2. Under **Transmittal Log Packages**, check both:
   - "All Documents in Contractor Transmittal Document Packages"
   - "All Documents in Contractor Submittal Item Document Packages"
3. Download all files to a folder on your computer (e.g., `RMS Files`)

**Verify:** Files should be named like:
- `Transmittal 03 30 00-1 - Description.pdf` (original)
- `Transmittal 03 30 00-1.1 - Description.pdf` (revision 1)
- `Transmittal 03 30 00-1.2 - Description.pdf` (revision 2)

If files are named differently, contact support before proceeding.

> **Note:** You will select this folder in the app during Step 6 of the sync review. The app will automatically detect which files are new and only upload those.

### Step 4: Export QAQC Deficiencies (Optional, for Observations import)

If you want to import QA deficiencies as Procore Observations:

1. In RMS, go to **QAQC > Deficiency Items Issued**
2. Export the report
3. Save the file locally as `QAQC Deficiencies.csv`

### Step 5: Export RFI Report (Optional, for RFI import)

If you want to import RFIs:

1. In RMS, go to **Contract Reports > Submit > All Requests for Information**
2. Export as CSV
3. Save as `RFI Report.csv`

The RFI flow optionally accepts the same `RMS Files` folder. Files named `RFI-XXXX Response*` attach to the official reply; other `RFI-XXXX*` files attach to the RFI itself.

### Step 6: Export Daily Logs (Optional)

If you want to import QC daily logs:

1. In RMS, export the **QC Equipment**, **QC Labor**, and **QC Narratives** reports as CSV
2. Save them locally — you'll upload them together in the Daily Logs tool

---

## Part 2: What Each File Provides

| File | Data Provided |
|------|---------------|
| Submittal Register | All submittals, paragraph references, classifications (Info), types, QA/QC codes, activity codes |
| Transmittal Log | Revisions, dates (Date In/Date Out), QA codes for all transmittals (historical) |
| RMS Files | PDF attachments for each submittal |
| QAQC Deficiencies | Deficiency items to import as Observations |

---

## Part 3: Procore Setup (First Time Only)

Before importing, ensure your Procore project has:

### Custom Fields

The importer uses these custom fields on submittals. If they don't exist, create them at the Company level and assign to your project:

| Field Name | Type | Options |
|------------|------|---------|
| Paragraph | Text | (free text) |
| QC Code | Dropdown | A, B, C, D |
| QA Code | Dropdown | A, B, C, D, E, F, G, X |
| Info | Dropdown | GA, FIO, S |
| Contractor Prepared | Date | - |
| Government Received | Date | - |
| Government Returned | Date | - |
| Contractor Received | Date | - |

### Submittal Types

Ensure these submittal types exist in Procore:

| Type Name |
|-----------|
| SD-01: PRECON SUBMTL |
| SD-02: SHOP DRAWINGS |
| SD-03: PRODUCT DATA |
| SD-04: SAMPLES |
| SD-05: DESIGN DATA |
| SD-06: TEST REPORTS |
| SD-07: CERTIFICATES |
| SD-08: MFRS INSTR |
| SD-09: MFRS FLD REPT |
| SD-10: O&M DATA |
| SD-11: CLOSEOUT SUBMTL |

### Specification Sections

The importer will match submittals to existing spec sections in Procore. Spec sections cannot be created via the API, so:

- If your project already has spec sections, they will be matched automatically
- Submittals with unmatched spec sections will be imported without a spec link
- You can manually link them to spec sections later in Procore

---

## Part 4: Using the RMS Importer (Submittals)

The Submittals tool is a 3-step wizard: **Upload → Review → Apply**. Everything (CSVs, sync options, file bytes) is collected on the Upload step, previewed on Review, and executed in a single background job on Apply.

### Step 1: Log In and Pick Project

1. Open the app (Vercel URL, or open the embedded view inside Procore)
2. Click **Connect with Procore** and authorize
3. Pick your **Company** and **Project** (auto-selected when embedded)
4. On the tool selector, pick **Submittals**

### Step 2: Upload Step (CSVs + folder)

1. **Upload the two CSVs** (Submittal Register, Transmittal Log) and click **Upload & Parse Files**.
   - Total submittals, spec sections, revisions, and any validation warnings appear in a green summary.
2. **(Optional) Pick the RMS Files folder.** A "Select RMS Files Folder" button appears below the parse summary. Click it and pick the folder of transmittal PDFs.
   - The app immediately checks each filename against the project baseline and shows: `N new files to upload, M already uploaded, K unrecognized`. **Files aren't uploaded yet** — they're held in the browser until you confirm on the next step.
   - Skip this if you don't have new PDFs.
3. Click **Continue to Review**.

### Step 3: Review Step (preview only)

The Sync Review screen shows what *would* change. Nothing is touched yet. Sections are color-coded:

| Section | Description |
|---------|-------------|
| **New Submittals** (green) | Submittals to create in Procore |
| **QA Code Updates** (yellow) | QA codes that changed |
| **Date Updates** (blue) | Government Received / Returned dates |
| **Other Updates** (gray) | Title, type, paragraph, QC code, info |
| **File Plan** (purple) | Will-attach-to-existing / will-attach-to-new / already uploaded / unrecognized |
| **Items Removed** (orange) | In baseline but not in latest export — flagged, not deleted |

Use the checkboxes to deselect any section you don't want applied. The **File Plan** section's "will-attach-to-new" count covers files whose target submittals will be created in this same run — used to silently fail in older versions, now handled in one orchestrated job.

### Step 4: Apply Step

Click **Apply**. The app posts everything to one background job and shows live progress. The job runs phases in this order:

1. Create new submittals (recording each new Procore ID)
2. Save baseline checkpoint
3. Upload + attach files (to both pre-existing and just-created submittals)
4. Apply field updates
5. Save final baseline

You can navigate away — the job continues in the background. Reopening the app reattaches to the running job's progress.

### Other Tools

The tool selector also has:
- **RFIs** — same wizard shape (CSV + optional folder of `RFI-XXXX*` PDFs → review → apply)
- **Daily Logs** — uploads QC Equipment / Labor / Narrative CSVs as Procore daily log entries
- **Observations** — uploads QAQC Deficiencies CSV as Procore Observations

---

## Part 5: Field Mappings

### Status Mapping

| RMS Status | Procore Status |
|------------|----------------|
| Outstanding | Draft |
| Complete | Closed |
| In Review | Open |

### QA Code Mapping

| Code | Meaning | Procore Status |
|------|---------|----------------|
| A | Approved | Closed |
| B | Approved as Noted | Closed |
| C | Approved as Noted, Resubmit Required | Open |
| D | Disapproved, Revise and Resubmit | Open |
| E | Disapproved | Open |
| F | For Information Only | Closed |
| G | Revise and Resubmit | Open |
| X | Receipt Acknowledged | Closed |

### Type Mapping (SD Number)

| RMS SD No | Procore Type |
|-----------|--------------|
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

---

## Part 6: After Import

### Verify Import

1. Go to your Procore project > Submittals
2. Spot-check several submittals:
   - Correct spec section linked
   - Correct responsible contractor
   - Custom fields populated (QA Code, dates, etc.)
   - PDF attachments present
3. Check revisions are linked to their original submittals

### Manual Cleanup (if needed)

- **Missing spec section links**: Edit submittals to link to correct spec sections
- **Incorrect contractor**: Update responsible contractor on affected submittals
- **Missing files**: Re-upload individual files through Procore

---

## Part 7: Ongoing Sync (After Initial Import)

After the initial import, you can use the sync feature to keep Procore updated as RMS data changes.

### How Sync Works

The app compares your new RMS exports against the previously-imported data (baseline). It shows you exactly what changed:

- **New submittals** - Items in RMS that weren't there before
- **QA code updates** - Status changes on existing submittals
- **Date updates** - New dates from Transmittal Log
- **New files** - PDFs that haven't been uploaded yet
- **Removed items** - Items that were in the baseline but aren't in the new export

### Sync Workflow

1. **Export fresh data from RMS** (Submittal Register + Transmittal Log; new PDFs into the RMS Files folder)
2. **Upload step** — drop in the two CSVs, then (optionally) pick the RMS Files folder. The app checks every filename against the baseline and shows new / already-uploaded / unrecognized counts. Click **Continue to Review**.
3. **Review step** — preview of all proposed changes including a File Plan breakdown. Deselect anything you don't want applied.
4. **Apply step** — single button posts everything to one background job. The job creates new submittals, then uploads & attaches files (to both pre-existing and just-created submittals), then applies field updates. Live progress shown; you can navigate away.
5. **Baseline updated** — automatically saved at the end (and checkpointed mid-run so a crash doesn't lose progress).

### What Gets Flagged (Not Auto-Deleted)

If a submittal was in the previous export but isn't in the new one, the app flags it for review. It does NOT automatically delete anything from Procore.

You decide what to do:
- Close the submittal in Procore manually
- Ignore (maybe it was removed from RMS by mistake)
- Wait for it to reappear in next export

### First Sync (Bootstrap)

If you already have submittals in Procore from a previous migration (e.g., using scripts), you can bootstrap a baseline:

1. Upload your current RMS exports
2. App matches RMS items to existing Procore submittals
3. App saves this as your baseline
4. Future syncs work incrementally from there

---

## Troubleshooting

### "File validation failed"

- Ensure you exported from RMS in Excel format
- Check that column headers match expected names
- Verify the file isn't corrupted (try opening in Excel)

### "No matching submittal for file"

- The file name couldn't be matched to a submittal
- Check the file follows the naming convention: `Transmittal {Section}-{Num} - {Description}.pdf`
- Verify the transmittal exists in your Transmittal Log export

### "Contractor not found in Directory"

- The contractor name doesn't match any vendor in Procore
- Either select a match from the suggestions, or add the vendor to Procore Directory first

### "Rate limit exceeded"

- Procore limits API requests
- The importer will automatically pause and retry
- For large imports, this is normal - let it complete

---

## Support

For issues or questions, contact: **rms-support@thetestexperts.com**
