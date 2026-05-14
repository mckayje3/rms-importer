# QAQC → Procore Quality & Safety

## Overview
Import RMS QAQC data into Procore's Quality & Safety tools:
- **Deficiency Items** → Procore Observations
- **QC Tests** → Procore Inspections (planned — pending template approach decision)

## Deficiency Items → Observations (DONE — April 2026)

### RMS File Structure
**File:** `Deficiency Items YYYY_MM_DD.csv` (exported from RMS QAQC module)

**Header rows (1-4):**
| Row | Content | Example |
|-----|---------|---------|
| 1 | Report title + date | `Deficiency Items Issued - by  All,17 Apr 2026` |
| 2 | Project name | `W912QR24C0035  Dobbins AFB, GA -DBB Security Forces Fac` |
| 3 | Organization | `US Army Corps of Engineers` |
| 4 | Contract number | `H2003670` |

**Data (row 5 = headers, row 6+ = data):**
| Column | Header | Procore Mapping |
|--------|--------|-----------------|
| 1 | Item Number | Observation name prefix (e.g., "QA-00001: ...") |
| 2 | Description | Observation description |
| 3 | Location | Procore Location (auto-create if missing) |
| 4 | Status | Mapped to observation status |
| 5 | Date Issued | Observation due_date |
| 6 | Age (days) | (informational) |
| 7 | Staff | (informational) |

**Item prefixes:** Both `QA-` (government-issued) and `QC-` (contractor-issued) items are parsed.

### Status Mapping (RMS → Procore Observation)
| RMS Status | Procore Status |
|------------|----------------|
| QA Verification Required | `ready_for_review` |
| QA Concurs Corrected | `closed` |
| Not Reported Corrected | `closed` |
| (any with "Corrected" or "Closed") | `closed` |
| (all others) | `initiated` |

### Workflow
1. User selects **Observations** from Tool Selector
2. Uploads Deficiency Items CSV
3. App parses and shows summary (total, open, closed, locations)
4. App analyzes: matches locations, fetches observation types, checks for duplicates
5. User selects observation type (required) and location options
6. User clicks Import
7. Background job creates locations (if enabled) then observations
8. Frontend polls job status with progress bar

### Procore Observations API
- **Create:** `POST /rest/v1.0/observations/items` with `project_id` + `observation` object at top level
- **Required fields:** `name`, `type_id`
- **Status values:** `initiated`, `ready_for_review`, `not_accepted`, `closed`
- **Priority values:** `Low`, `Medium`, `High`, `Urgent`
- **Observation types** (default categories): Safety (4 types), Quality (4 types), Commissioning (1), Warranty (1)
- Observations are NOT automatically emailed to assignees when created via API

### Backend Files
| File | Purpose |
|------|---------|
| `backend/services/qaqc_parser.py` | `DeficiencyParser` — CSV parser for Deficiency Items |
| `backend/routers/qaqc.py` | Upload, analyze, execute (background job), job status |
| `backend/models/rms.py` | `RMSDeficiency`, `RMSDeficiencyParseResult` |
| `backend/models/procore.py` | `ProcoreObservation`, `ProcoreObservationType`, `ProcoreLocation` |
| `backend/services/procore_api.py` | `create_observation()`, `get_observations()`, `get_observation_types()`, `get_locations()`, `create_location()` |

### Frontend Files
| File | Purpose |
|------|---------|
| `frontend/src/components/ObservationsUpload.tsx` | CSV file picker + parse summary |
| `frontend/src/components/ObservationsReview.tsx` | Plan review, type selector, location options, progress bar |
| `frontend/src/lib/api.ts` | `observations` namespace (upload, analyze, execute, getJobStatus) |
| `frontend/src/types/index.ts` | `ObservationsSession`, `ObservationSyncPlan`, `ObservationsAnalyzeResponse`, etc. |

### API Endpoints
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/qaqc/upload` | POST | Upload and parse Deficiency Items CSV |
| `/qaqc/projects/{id}/analyze` | POST | Compare deficiencies vs existing observations + locations |
| `/qaqc/projects/{id}/execute` | POST | Import as observations (background job) |
| `/qaqc/jobs/{id}` | GET | Poll import job status |
| `/qaqc/session/{id}` | DELETE | Delete session |

---

## QC Tests → Inspections (PLANNED)

### RMS File Structure
**File:** `QC Tests YYYY_MM_DD.csv` (exported from RMS QAQC module)

**Header rows (1-4):** Same structure as Deficiency Items.

**Data (row 5 = headers, row 6+ = data):**
| Column | Header | Notes |
|--------|--------|-------|
| 1 | QC Test No. | e.g., "CT-00001" |
| 2 | Description | Contains embedded spec section + paragraph refs |
| 3 | Performed By | Testing company (e.g., "NOVA", "DC Mechanical") |
| 4 | Location | e.g., "Building Pad", "Footings" |
| 5 | Status | "Completed" or "Outstanding" |

### Parser (DONE)
`TestParser` in `services/qaqc_parser.py` parses the CSV and extracts:
- Test number, description, performer, location, status
- Spec section extracted from description (e.g., "31 00 00" from "Specification Section: 31 00 00.00 06")
- Paragraph reference extracted from description (e.g., "3.18.3")

**Models:** `RMSTest`, `RMSTestParseResult` in `models/rms.py`

### Procore Inspections API (Researched)
Procore Inspections are template-based ("Checklists" in the API):
- **Create Inspection:** `POST /rest/v1.0/projects/{id}/checklist/lists` — requires `list_template_id`
- **Templates** must be created first, either at company or project level
- **Sections** can be added to inspections with `items_attributes` (deprecated but functional)
- **Item responses:** `POST /projects/{id}/checklist/items/{item_id}/item_response` — statuses: `conforming`, `non_conforming`, `not_applicable`
- **Inspection types:** `GET/POST /companies/{id}/inspection_types`
- **Inspection statuses:** `open`, `in_review`, `closed`

### Open Questions
- **Template approach:** One template per test type? Generic template with items per test? Single "QC Test Log" template?
- **Item mapping:** How to represent each CT-#### test as an inspection item
- Depends on user reviewing Procore Inspections training to decide best approach

### Dobbins Test Data (April 2026)
- 74 tests (CT-00001 through CT-00074)
- 66 completed, 8 outstanding
- 3 performers: NOVA, DC Mechanical, International Fire Protection
- 12 unique locations
- Primary test types: soil density (nuclear gauge), concrete sampling, soil bearing capacity, floor flatness, hydrant flow, mortar/grout cubes
