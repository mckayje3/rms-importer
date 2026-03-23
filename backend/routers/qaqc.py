"""QAQC Deficiencies upload and import endpoints."""
import uuid
from fastapi import APIRouter, Header, HTTPException, UploadFile, File
from pydantic import BaseModel
from typing import Optional

from services.qaqc_parser import QAQCParser
from services.procore_api import ProcoreAPI
from models.rms import RMSDeficiency, RMSDeficiencyParseResult

router = APIRouter()

# In-memory session storage (use Redis/DB in production)
_qaqc_sessions: dict[str, RMSDeficiencyParseResult] = {}


class QAQCUploadResponse(BaseModel):
    """Response from QAQC file upload."""

    session_id: str
    total_count: int
    open_count: int
    closed_count: int
    locations: list[str]
    project_name: Optional[str] = None
    report_date: Optional[str] = None
    errors: list[str] = []
    warnings: list[str] = []


class LocationMatchResult(BaseModel):
    """Result of matching locations."""

    rms_location: str
    procore_location_id: Optional[int] = None
    procore_location_name: Optional[str] = None
    matched: bool = False
    will_create: bool = False


class LocationMatchSummary(BaseModel):
    """Summary of location matching."""

    total: int
    matched: int
    to_create: int
    results: list[LocationMatchResult]


class ImportRequest(BaseModel):
    """Request to import deficiencies."""

    company_id: int
    observation_type_id: Optional[int] = None
    create_locations: bool = True


class ImportResult(BaseModel):
    """Result of importing deficiencies."""

    total: int
    created: int
    skipped: int
    errors: list[str]


@router.post("/upload", response_model=QAQCUploadResponse)
async def upload_qaqc_file(
    file: UploadFile = File(...),
):
    """
    Upload and parse a QAQC Deficiencies Excel file.

    Returns a session ID to reference the parsed data in subsequent calls.
    """
    # Validate file type
    if not file.filename.endswith(('.xls', '.xlsx')):
        raise HTTPException(
            status_code=400,
            detail="File must be an Excel file (.xls or .xlsx)",
        )

    # Read file
    file_bytes = await file.read()

    # Parse
    parser = QAQCParser()
    result = parser.parse(file_bytes)

    if result.errors and result.total_count == 0:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to parse QAQC file: {'; '.join(result.errors)}",
        )

    # Store in session
    session_id = str(uuid.uuid4())
    _qaqc_sessions[session_id] = result

    return QAQCUploadResponse(
        session_id=session_id,
        total_count=result.total_count,
        open_count=result.open_count,
        closed_count=result.closed_count,
        locations=result.locations,
        project_name=result.project_name,
        report_date=result.report_date.isoformat() if result.report_date else None,
        errors=result.errors,
        warnings=result.warnings,
    )


@router.get("/session/{session_id}/deficiencies")
async def get_deficiencies(session_id: str) -> list[dict]:
    """Get parsed deficiencies from a session."""
    if session_id not in _qaqc_sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    result = _qaqc_sessions[session_id]
    return [
        {
            "item_number": d.item_number,
            "description": d.description[:200] + "..." if len(d.description) > 200 else d.description,
            "location": d.location,
            "status": d.status,
            "procore_status": d.procore_status,
            "date_issued": d.date_issued.isoformat() if d.date_issued else None,
            "age_days": d.age_days,
            "staff": d.staff,
            "is_open": d.is_open,
        }
        for d in result.deficiencies
    ]


@router.post("/session/{session_id}/match-locations")
async def match_locations(
    session_id: str,
    project_id: int,
    company_id: int,
    authorization: str = Header(...),
) -> LocationMatchSummary:
    """
    Match RMS deficiency locations to Procore project locations.

    Returns which locations exist in Procore and which need to be created.
    """
    if session_id not in _qaqc_sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    result = _qaqc_sessions[session_id]

    # Get Procore locations
    token = authorization.replace("Bearer ", "")
    api = ProcoreAPI(token, company_id=company_id)

    try:
        procore_locations = await api.get_locations(project_id)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch Procore locations: {str(e)}",
        )

    # Build lookup (case-insensitive)
    location_lookup = {loc.name.lower(): loc for loc in procore_locations}

    # Match each RMS location
    results = []
    for rms_location in result.locations:
        rms_lower = rms_location.lower()
        matched_loc = location_lookup.get(rms_lower)

        results.append(
            LocationMatchResult(
                rms_location=rms_location,
                procore_location_id=matched_loc.id if matched_loc else None,
                procore_location_name=matched_loc.name if matched_loc else None,
                matched=matched_loc is not None,
                will_create=matched_loc is None,
            )
        )

    matched = sum(1 for r in results if r.matched)

    return LocationMatchSummary(
        total=len(results),
        matched=matched,
        to_create=len(results) - matched,
        results=results,
    )


@router.get("/session/{session_id}/observation-types")
async def get_observation_types(
    session_id: str,
    project_id: int,
    company_id: int,
    authorization: str = Header(...),
) -> list[dict]:
    """Get available observation types for the project."""
    if session_id not in _qaqc_sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    token = authorization.replace("Bearer ", "")
    api = ProcoreAPI(token, company_id=company_id)

    try:
        types = await api.get_observation_types(project_id)
        return [
            {"id": t.id, "name": t.name, "category": t.category}
            for t in types
        ]
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch observation types: {str(e)}",
        )


@router.post("/session/{session_id}/import")
async def import_deficiencies(
    session_id: str,
    project_id: int,
    request: ImportRequest,
    authorization: str = Header(...),
) -> ImportResult:
    """
    Import deficiencies as Procore Observations.

    This will:
    1. Create any missing locations (if create_locations=True)
    2. Create observations for each deficiency
    """
    if session_id not in _qaqc_sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    result = _qaqc_sessions[session_id]
    token = authorization.replace("Bearer ", "")
    api = ProcoreAPI(token, company_id=request.company_id)

    errors = []
    created = 0
    skipped = 0

    # Get existing locations
    try:
        procore_locations = await api.get_locations(project_id)
        location_lookup = {loc.name.lower(): loc.id for loc in procore_locations}
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch locations: {str(e)}",
        )

    # Create missing locations if requested
    if request.create_locations:
        for rms_location in result.locations:
            if rms_location.lower() not in location_lookup:
                try:
                    new_loc = await api.create_location(project_id, rms_location)
                    location_lookup[rms_location.lower()] = new_loc["id"]
                except Exception as e:
                    errors.append(f"Failed to create location '{rms_location}': {str(e)}")

    # Import each deficiency
    for deficiency in result.deficiencies:
        try:
            # Build observation data
            observation_data = {
                "name": f"{deficiency.item_number}: {deficiency.description[:100]}",
                "description": deficiency.description,
                "status": deficiency.procore_status,
            }

            # Set type if specified
            if request.observation_type_id:
                observation_data["type_id"] = request.observation_type_id

            # Set location if available
            if deficiency.location:
                location_id = location_lookup.get(deficiency.location.lower())
                if location_id:
                    observation_data["location_id"] = location_id

            # Create observation
            await api.create_observation(project_id, observation_data)
            created += 1

        except Exception as e:
            errors.append(f"Failed to create observation for {deficiency.item_number}: {str(e)}")
            skipped += 1

    return ImportResult(
        total=result.total_count,
        created=created,
        skipped=skipped,
        errors=errors,
    )


@router.delete("/session/{session_id}")
async def delete_session(session_id: str):
    """Delete a QAQC session."""
    if session_id in _qaqc_sessions:
        del _qaqc_sessions[session_id]
        return {"status": "deleted"}
    raise HTTPException(status_code=404, detail="Session not found")
