# Specifications/Divisions Feature

## Overview
Submittals in Procore link to Specification Sections. Before importing submittals, we need to ensure the required Specifications exist.

**Procore Hierarchy:**
```
Division (e.g., "03" = "Concrete")
  └── Specification Section (e.g., "03 30 00" = "Cast-in-Place Concrete")
        └── Submittal (linked to spec section)
```

## MasterFormat Reference
**File:** `masterformat_reference.json`
- Source: CSI MasterFormat 2018 via DesignGuide
- Contains: 36 divisions, ~300 sections

## Key Finding (2026-03-18)

Spec sections are **NOT** auto-created when submittals reference new section numbers. There is **no public API** to create spec sections programmatically. They can only be created via:
1. Upload PDF specs (OCR extraction)
2. Manual creation in Procore UI
3. Procore Excel import tool

**App Strategy:** Match RMS sections to existing Procore sections. Submittals with unmatched sections are created without spec links. Users can manually create/link specs afterward.

## Dobbins Project Stats
- **89 unique spec sections** extracted from RMS files
- Divisions used: 00, 01, 03, 04, 05, 06, 07, 08, 09, 10, 12, 13, 21, 22, 23, 25, 26, 27, 28, 31, 33

## Procore Specifications API

**Working Endpoints:**
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/rest/v1.0/projects/{id}/specification_sets` | GET | List spec sets |
| `/rest/v1.0/projects/{id}/submittals` | GET | Submittals include embedded `specification_section` |

**Embedded Spec Section Structure:**
```json
{
  "specification_section": {
    "id": 598134329174947,
    "number": "00 80 00.00 06",
    "description": "SPECIAL PROVISIONS"
  }
}
```

**Discovery Scripts:**
- `discover_specifications_api.ps1` - Tests various endpoint patterns
- `list_spec_sections.ps1` - Extracts unique spec sections from submittals

## Implementation Status
- [x] Spec sections are NOT auto-created (tested 2026-03-18)
- [x] `SpecMatcher` service - matches RMS sections to Procore sections
- [x] `/submittals/projects/{id}/check-specs` endpoint
- [x] Handle UFGS extended format (e.g., "01 32 01.00 06") - extracts base section "01 32 01"
- [x] Sync engine uses `SpecMatcher` for fuzzy matching during submittal creation (fixed 2026-03-31)

## Spec Section Matching Bug (Fixed 2026-03-31)

**Problem:** Submittals created by the sync engine were missing their spec section link. Two root causes:

1. **Cache built from submittals only** — `sync.py` built its spec section lookup by iterating existing Procore submittals. If a spec section had zero submittals, it wasn't in the cache. The first submittal for any new section was always created without a spec link, and subsequent ones snowballed since the first never got linked either.

2. **Exact string match only** — The cache used a simple `if section in cache` check. RMS sections like `"01 50 00"` wouldn't match Procore sections like `"01 50 00.00 06"`.

**Fix:** The sync engine (`routers/sync.py`) now uses the `SpecMatcher` service (which was already written but only used in the analysis endpoint) for three-tier matching: exact, normalized, and base section. The `SpecMatcher` was already used by `/check-specs` for pre-flight analysis — now it's also used during actual creation.

**Note:** There is no direct Procore API endpoint to list specification sections independently (`/specification_sections` returns 404). The app extracts spec sections from existing submittals. This means the very first project sync (when Procore has zero submittals) cannot link spec sections. The workaround is to bootstrap from a project that already has submittals with spec sections, or manually create one submittal per section first.
