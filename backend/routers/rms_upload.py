"""RMS file upload and parsing endpoints."""
from fastapi import APIRouter, UploadFile, File, HTTPException, Header
from fastapi.responses import Response
from typing import Optional
from pydantic import BaseModel
import secrets

from services.rms_parser import RMSParser
from services.rms_validator import RMSValidator
from services.contractor_lookup import ContractorLookup
from services.vendor_matching import VendorMatcher
from services.procore_api import ProcoreAPI
from models.rms import RMSParseResult
from models.procore import VendorMatch
from routers.auth import get_token

router = APIRouter()

# In-memory storage for parsed RMS data (use Redis/DB in production)
_rms_sessions: dict[str, RMSParseResult] = {}
_contractor_mappings: dict[str, ContractorLookup] = {}


@router.post("/validate")
async def validate_rms_files(
    submittal_register: UploadFile = File(...),
    submittal_assignments: Optional[UploadFile] = File(None),
    transmittal_report: Optional[UploadFile] = File(None),
) -> dict:
    """
    Validate RMS export files without parsing.

    Only the Submittal Register is required. Other files are optional
    and add additional data (assignments, revisions, QA codes, dates).

    Use this to check files before upload. Returns detailed
    validation results with actionable error messages.
    """
    validator = RMSValidator()

    # Read file contents
    register_content = await submittal_register.read()
    assignments_content = await submittal_assignments.read() if submittal_assignments else None
    report_content = await transmittal_report.read() if transmittal_report else None

    result = validator.validate_all(
        register_bytes=register_content,
        assignments_bytes=assignments_content,
        transmittal_report_bytes=report_content,
    )

    return result.to_dict()


@router.post("/upload")
async def upload_rms_files(
    submittal_register: UploadFile = File(...),
    submittal_assignments: Optional[UploadFile] = File(None),
    transmittal_report: Optional[UploadFile] = File(None),
    skip_validation: bool = False,
) -> dict:
    """
    Upload and parse RMS export files.

    Only the Submittal Register is required. Other files are optional
    and add additional data (assignments, revisions, QA codes, dates).

    Returns a session ID to reference the parsed data.
    Files are validated before parsing unless skip_validation=true.
    """
    # Read file contents
    register_content = await submittal_register.read()
    assignments_content = await submittal_assignments.read() if submittal_assignments else None
    report_content = await transmittal_report.read() if transmittal_report else None

    import logging
    logger = logging.getLogger(__name__)
    logger.warning(f"Upload: register={len(register_content)}b, assignments={len(assignments_content) if assignments_content else 'None'}b, report={len(report_content) if report_content else 'None'}b")

    # Validate first (unless skipped)
    validation_result = None
    if not skip_validation:
        validator = RMSValidator()
        validation_result = validator.validate_all(
            register_bytes=register_content,
            assignments_bytes=assignments_content,
            transmittal_report_bytes=report_content,
        )

        # Block on validation errors
        if not validation_result.is_valid:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "Validation failed. Fix errors and try again.",
                    "validation": validation_result.to_dict(),
                },
            )

    # Parse files
    parser = RMSParser()
    try:
        result = parser.parse_all(
            register_bytes=register_content,
            assignments_bytes=assignments_content,
            transmittal_report_bytes=report_content,
        )

        logger.warning(f"Parsed: {result.submittal_count} submittals, {len(result.transmittal_report)} report entries")

        # Store in session
        session_id = secrets.token_urlsafe(16)
        _rms_sessions[session_id] = result

        response = {
            "session_id": session_id,
            "submittal_count": result.submittal_count,
            "spec_section_count": result.spec_section_count,
            "revision_count": result.revision_count,
            "errors": result.errors,
            "warnings": result.warnings,
        }

        # Include validation warnings if we validated
        if validation_result and validation_result.warnings:
            response["validation_warnings"] = [
                w.to_dict() for w in validation_result.warnings
            ]

        return response

    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse files: {str(e)}")


@router.get("/session/{session_id}")
async def get_rms_session(session_id: str) -> dict:
    """Get summary of parsed RMS data."""
    if session_id not in _rms_sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    result = _rms_sessions[session_id]
    return {
        "session_id": session_id,
        "submittal_count": result.submittal_count,
        "spec_section_count": result.spec_section_count,
        "revision_count": result.revision_count,
        "errors": result.errors,
        "warnings": result.warnings,
    }


@router.get("/session/{session_id}/submittals")
async def get_rms_submittals(session_id: str, limit: int = 100, offset: int = 0):
    """Get parsed submittals (paginated)."""
    if session_id not in _rms_sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    result = _rms_sessions[session_id]
    submittals = result.submittals[offset : offset + limit]

    return {
        "total": len(result.submittals),
        "offset": offset,
        "limit": limit,
        "submittals": submittals,
    }


@router.get("/session/{session_id}/spec-sections")
async def get_spec_sections(session_id: str):
    """Get unique spec sections from parsed data."""
    if session_id not in _rms_sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    result = _rms_sessions[session_id]
    sections = sorted(set(s.section for s in result.submittals))

    return {"count": len(sections), "sections": sections}


@router.delete("/session/{session_id}")
async def delete_rms_session(session_id: str):
    """Delete a parsed RMS session."""
    if session_id in _rms_sessions:
        del _rms_sessions[session_id]
    return {"status": "deleted"}


def get_rms_data(session_id: str) -> RMSParseResult:
    """Get RMS data for a session (used by other routers)."""
    if session_id not in _rms_sessions:
        raise HTTPException(status_code=404, detail="RMS session not found")
    return _rms_sessions[session_id]


# === Contractor Mapping Endpoints ===


@router.get("/session/{session_id}/contractor-template")
async def download_contractor_template(session_id: str):
    """
    Download CSV template for contractor mapping.

    Pre-fills Column 1 with all spec sections from RMS data.
    User fills in Column 2 (Contractor) and uploads back.
    """
    if session_id not in _rms_sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    result = _rms_sessions[session_id]
    sections = [s.section for s in result.submittals]

    csv_bytes = ContractorLookup.generate_template(sections)

    return Response(
        content=csv_bytes,
        media_type="text/csv",
        headers={
            "Content-Disposition": "attachment; filename=contractor_mapping_template.csv"
        },
    )


@router.post("/session/{session_id}/contractor-mapping")
async def upload_contractor_mapping(
    session_id: str,
    file: UploadFile = File(...),
):
    """
    Upload filled contractor mapping (CSV or Excel).

    Expected format:
        Section,Contractor
        03 30 00,Altis Concrete
        05 12 00,XYZ Steel
    """
    if session_id not in _rms_sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    try:
        content = await file.read()
        filename = file.filename or ""

        if filename.endswith((".xlsx", ".xls")):
            lookup = ContractorLookup.from_excel(content)
        else:
            lookup = ContractorLookup.from_csv(content)

        _contractor_mappings[session_id] = lookup

        return {
            "status": "success",
            "total_sections": lookup.total_entries,
            "sections": lookup.sections(),
        }

    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse file: {str(e)}")


@router.get("/session/{session_id}/contractor-mapping")
async def get_contractor_mapping(session_id: str):
    """Get current contractor mapping for a session."""
    if session_id not in _rms_sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    if session_id not in _contractor_mappings:
        return {
            "has_mapping": False,
            "total_sections": 0,
            "mappings": {},
        }

    lookup = _contractor_mappings[session_id]
    return {
        "has_mapping": True,
        "total_sections": lookup.total_entries,
        "mappings": lookup.to_dict(),
    }


def get_contractor_lookup(session_id: str) -> Optional[ContractorLookup]:
    """Get contractor lookup for a session (used by other routers)."""
    return _contractor_mappings.get(session_id)


# === Vendor Matching Endpoints ===


# Store for vendor matchers (keyed by auth session)
_vendor_matchers: dict[str, VendorMatcher] = {}


class MatchContractorsRequest(BaseModel):
    """Request to match contractors to Procore Directory."""

    project_id: int
    company_id: int


class ConfirmMatchRequest(BaseModel):
    """Request to confirm/override a contractor match."""

    section: str
    vendor_id: int


@router.post("/session/{session_id}/match-contractors")
async def match_contractors(
    session_id: str,
    request: MatchContractorsRequest,
    x_auth_session: str = Header(..., alias="X-Auth-Session"),
):
    """
    Match uploaded contractor names to Procore Directory vendors.

    Requires:
    - RMS session with contractor mapping uploaded
    - Procore auth session (X-Auth-Session header)
    - project_id and company_id in request body

    Returns match results with scores and suggestions.
    """
    # Verify RMS session exists
    if session_id not in _rms_sessions:
        raise HTTPException(status_code=404, detail="RMS session not found")

    # Verify contractor mapping exists
    if session_id not in _contractor_mappings:
        raise HTTPException(
            status_code=400,
            detail="No contractor mapping uploaded. Upload contractor mapping first.",
        )

    # Get Procore auth token
    try:
        access_token = get_token(x_auth_session)
    except HTTPException:
        raise HTTPException(status_code=401, detail="Invalid auth session")

    # Fetch vendors from Procore Directory
    api = ProcoreAPI(access_token, company_id=request.company_id)

    try:
        vendors = await api.get_project_vendors(request.project_id)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch Procore vendors: {str(e)}",
        )

    if not vendors:
        raise HTTPException(
            status_code=400,
            detail="No vendors found in Procore Directory. Add vendors first.",
        )

    # Create matcher and store for later use
    matcher = VendorMatcher(vendors)
    _vendor_matchers[session_id] = matcher

    # Get contractor names from mapping
    lookup = _contractor_mappings[session_id]
    contractor_names = {
        section: info.name for section, info in lookup._lookup.items()
    }

    # Run matching
    results = matcher.match_contractors(contractor_names)

    # Categorize results
    matched = {s: r for s, r in results.items() if r.vendor_id is not None}
    unmatched = {s: r for s, r in results.items() if r.vendor_id is None}

    # Update ContractorLookup with matched vendor IDs
    for section, result in matched.items():
        lookup.set_vendor_id(section, result.vendor_id)

    return {
        "total_contractors": len(results),
        "matched_count": len(matched),
        "unmatched_count": len(unmatched),
        "vendor_count": len(vendors),
        "results": {
            section: {
                "input_name": r.input_name,
                "vendor_id": r.vendor_id,
                "vendor_name": r.vendor_name,
                "match_score": r.match_score,
                "exact_match": r.exact_match,
                "suggestions": [
                    {
                        "vendor_id": s.vendor_id,
                        "vendor_name": s.vendor_name,
                        "score": s.score,
                    }
                    for s in r.suggestions
                ],
            }
            for section, r in results.items()
        },
    }


@router.post("/session/{session_id}/confirm-match")
async def confirm_match(
    session_id: str,
    request: ConfirmMatchRequest,
):
    """
    Confirm or override a contractor-to-vendor match.

    Use this when:
    - Auto-match was wrong, user selects different vendor
    - No auto-match, user manually selects vendor
    """
    if session_id not in _contractor_mappings:
        raise HTTPException(status_code=404, detail="Contractor mapping not found")

    lookup = _contractor_mappings[session_id]

    if request.section not in lookup._lookup:
        raise HTTPException(
            status_code=404,
            detail=f"Section '{request.section}' not in contractor mapping",
        )

    # Update vendor ID
    lookup.set_vendor_id(request.section, request.vendor_id)

    # Get vendor name if we have the matcher
    vendor_name = None
    if session_id in _vendor_matchers:
        vendor = _vendor_matchers[session_id].get_vendor_by_id(request.vendor_id)
        if vendor:
            vendor_name = vendor.name

    return {
        "status": "updated",
        "section": request.section,
        "vendor_id": request.vendor_id,
        "vendor_name": vendor_name,
    }


@router.get("/session/{session_id}/vendors")
async def get_vendors(
    session_id: str,
    x_auth_session: str = Header(..., alias="X-Auth-Session"),
    project_id: int = None,
    company_id: int = None,
):
    """
    Get list of Procore Directory vendors.

    Can be used to show vendor dropdown for manual selection.
    """
    if project_id is None or company_id is None:
        raise HTTPException(
            status_code=400,
            detail="project_id and company_id are required",
        )

    try:
        access_token = get_token(x_auth_session)
    except HTTPException:
        raise HTTPException(status_code=401, detail="Invalid auth session")

    api = ProcoreAPI(access_token, company_id=company_id)

    try:
        vendors = await api.get_project_vendors(project_id)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch vendors: {str(e)}",
        )

    return {
        "count": len(vendors),
        "vendors": [
            {
                "id": v.id,
                "name": v.name,
                "company": v.company,
                "is_active": v.is_active,
            }
            for v in vendors
        ],
    }
