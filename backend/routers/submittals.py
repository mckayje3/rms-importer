"""Submittal-related endpoints."""
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
from typing import Optional

from services.procore_api import ProcoreAPI
from services.matching import MatchingService
from services.spec_matcher import SpecMatcher
from models.procore import ProcoreSubmittal
from models.matching import MatchResult, MatchingSummary, ImportMode
from routers.rms_upload import get_rms_data

router = APIRouter()


@router.get("/projects/{project_id}/submittals", response_model=list[ProcoreSubmittal])
async def list_submittals(
    project_id: int,
    company_id: int,
    authorization: str = Header(...),
):
    """List all submittals for a project."""
    token = authorization.replace("Bearer ", "")
    api = ProcoreAPI(token, company_id=company_id)
    return await api.get_submittals(project_id)


@router.post("/projects/{project_id}/analyze")
async def analyze_for_import(
    project_id: int,
    company_id: int,
    rms_session_id: str,  # Reference to uploaded RMS data
    authorization: str = Header(...),
) -> MatchingSummary:
    """
    Analyze RMS data against Procore project.

    Returns matching summary and recommended import mode.
    """
    token = authorization.replace("Bearer ", "")
    api = ProcoreAPI(token, company_id=company_id)

    # Get Procore submittals
    procore_submittals = await api.get_submittals(project_id)

    # Get RMS data from session (uploaded earlier)
    # TODO: Retrieve from session storage
    rms_data = None  # Placeholder

    if rms_data is None:
        raise HTTPException(status_code=400, detail="RMS data not found. Upload files first.")

    # Run matching
    matching_service = MatchingService()
    summary = matching_service.analyze(rms_data, procore_submittals)

    return summary


class CheckSpecsRequest(BaseModel):
    """Request to check spec section availability."""
    rms_session_id: str
    company_id: int


@router.post("/projects/{project_id}/check-specs")
async def check_spec_sections(
    project_id: int,
    request: CheckSpecsRequest,
    authorization: str = Header(...),
):
    """
    Check which RMS spec sections exist in Procore.

    Returns:
    - matched: RMS sections that have corresponding Procore spec sections
    - unmatched: RMS sections with no Procore equivalent (will be created without spec link)

    Note: Procore API doesn't support creating spec sections programmatically.
    Unmatched sections can only be linked after manual creation in Procore.
    """
    # Get RMS data
    try:
        rms_data = get_rms_data(request.rms_session_id)
    except HTTPException:
        raise HTTPException(
            status_code=400,
            detail="RMS session not found. Upload RMS files first.",
        )

    # Get RMS spec sections
    rms_sections = [s.section for s in rms_data.submittals]

    # Get Procore spec sections
    token = authorization.replace("Bearer ", "")
    api = ProcoreAPI(token, company_id=request.company_id)

    try:
        procore_sections = await api.get_spec_sections(project_id)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch Procore spec sections: {str(e)}",
        )

    # Run matching
    matcher = SpecMatcher(procore_sections)
    summary = matcher.match_all(rms_sections)

    return summary.to_dict()


@router.post("/projects/{project_id}/import")
async def import_submittals(
    project_id: int,
    company_id: int,
    rms_session_id: str,
    mode: ImportMode,
    authorization: str = Header(...),
):
    """
    Import submittals from RMS to Procore.

    Mode determines behavior:
    - full_migration: Create all submittals
    - sync_from_rms: Update existing, create new
    - reconcile: Apply user's conflict resolutions
    """
    token = authorization.replace("Bearer ", "")
    api = ProcoreAPI(token, company_id=company_id)

    # TODO: Implement import logic
    # This will be a long-running operation, consider background tasks

    return {"status": "started", "message": "Import started"}
