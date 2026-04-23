"""QAQC Deficiencies upload, analysis, and import endpoints."""
import uuid
import asyncio
import logging
from fastapi import APIRouter, Header, HTTPException, UploadFile, File
from pydantic import BaseModel
from typing import Optional

from services.qaqc_parser import DeficiencyParser
from services.procore_api import ProcoreAPI, RateLimitError
from models.rms import RMSDeficiencyParseResult
from routers.auth import get_token
from config import get_settings
from database import file_job_store

settings = get_settings()

router = APIRouter()
logger = logging.getLogger(__name__)

# In-memory session storage for parsed deficiency data
_qaqc_sessions: dict[str, RMSDeficiencyParseResult] = {}


# === Response Models ===

class QAQCUploadResponse(BaseModel):
    session_id: str
    total_count: int
    open_count: int
    closed_count: int
    locations: list[str]
    project_name: Optional[str] = None
    report_date: Optional[str] = None
    errors: list[str] = []
    warnings: list[str] = []


class QAQCAnalyzeRequest(BaseModel):
    session_id: str
    company_id: int


class ObservationSyncPlan(BaseModel):
    creates: int
    already_exist: int
    total_rms: int
    has_changes: bool
    summary: str
    locations_to_create: list[str] = []
    observation_types: list[dict] = []


class QAQCAnalyzeResponse(BaseModel):
    plan: ObservationSyncPlan
    summary: str
    location_map: dict[str, int | None] = {}  # rms_location → procore_location_id


class QAQCExecuteRequest(BaseModel):
    session_id: str
    company_id: int
    observation_type_id: Optional[int] = None
    create_locations: bool = True
    location_map: dict[str, int | None] = {}


class QAQCExecuteResponse(BaseModel):
    status: str
    job_id: Optional[str] = None


class QAQCJobStatus(BaseModel):
    id: str
    status: str
    total: int
    completed: int
    observations_created: int
    locations_created: int
    errors: list[str]


def _job_to_status(job: dict) -> QAQCJobStatus:
    summary = job.get("result_summary") or {}
    return QAQCJobStatus(
        id=job["id"],
        status=job["status"],
        total=job.get("total_files", 0),
        completed=summary.get("completed", job.get("uploaded_files", 0)),
        observations_created=summary.get("observations_created", 0),
        locations_created=summary.get("locations_created", 0),
        errors=job.get("errors", []),
    )


# === Endpoints ===

@router.post("/upload", response_model=QAQCUploadResponse)
async def upload_qaqc_file(
    file: UploadFile = File(...),
):
    """Upload and parse a QAQC Deficiency Items CSV file."""
    if not file.filename or not file.filename.endswith(".csv"):
        raise HTTPException(
            status_code=400,
            detail="File must be a CSV file (.csv)",
        )

    file_bytes = await file.read()

    parser = DeficiencyParser()
    result = parser.parse(file_bytes)

    if result.errors and result.total_count == 0:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to parse QAQC file: {'; '.join(result.errors)}",
        )

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


@router.post("/projects/{project_id}/analyze", response_model=QAQCAnalyzeResponse)
async def analyze_deficiencies(
    project_id: int,
    request: QAQCAnalyzeRequest,
    x_auth_session: str = Header(..., alias="X-Auth-Session"),
):
    """Compare parsed deficiencies against existing Procore observations and locations."""
    if request.session_id not in _qaqc_sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    parse_result = _qaqc_sessions[request.session_id]

    try:
        access_token = get_token(x_auth_session)
    except HTTPException:
        raise HTTPException(status_code=401, detail="Invalid auth session")

    api = ProcoreAPI(access_token, company_id=request.company_id)

    # Fetch existing observations to check for duplicates by name
    existing_names: set[str] = set()
    try:
        observations = await api.get_observations(project_id)
        existing_names = {o.name.lower() for o in observations}
    except Exception as e:
        logger.warning(f"Failed to fetch existing observations: {e}")

    # Fetch locations for matching
    location_map: dict[str, int | None] = {}
    try:
        procore_locations = await api.get_locations(project_id)
        loc_by_name: dict[str, int] = {
            loc.name.lower().strip(): loc.id for loc in procore_locations
        }

        for rms_location in parse_result.locations:
            rms_lower = rms_location.lower().strip()
            if rms_lower in loc_by_name:
                location_map[rms_location] = loc_by_name[rms_lower]
            else:
                location_map[rms_location] = None
    except Exception as e:
        logger.warning(f"Failed to fetch locations: {e}")

    # Fetch observation types
    observation_types: list[dict] = []
    try:
        types = await api.get_observation_types(project_id)
        observation_types = [
            {"id": t.id, "name": t.name, "category": t.category}
            for t in types
        ]
    except Exception as e:
        logger.warning(f"Failed to fetch observation types: {e}")

    # Count creates vs already existing
    creates = 0
    already_exist = 0
    for d in parse_result.deficiencies:
        obs_name = f"{d.item_number}: {d.description[:100]}"
        if obs_name.lower() in existing_names:
            already_exist += 1
        else:
            creates += 1

    locations_to_create = [loc for loc, lid in location_map.items() if lid is None]

    parts = []
    if creates:
        parts.append(f"{creates} observations to create")
    if already_exist:
        parts.append(f"{already_exist} already exist")
    if locations_to_create:
        parts.append(f"{len(locations_to_create)} locations to create")
    summary = "; ".join(parts) if parts else "No changes needed"

    plan = ObservationSyncPlan(
        creates=creates,
        already_exist=already_exist,
        total_rms=parse_result.total_count,
        has_changes=creates > 0,
        summary=summary,
        locations_to_create=locations_to_create,
        observation_types=observation_types,
    )

    return QAQCAnalyzeResponse(
        plan=plan,
        summary=summary,
        location_map=location_map,
    )


@router.post("/projects/{project_id}/execute", response_model=QAQCExecuteResponse)
async def execute_deficiency_import(
    project_id: int,
    request: QAQCExecuteRequest,
    x_auth_session: str = Header(..., alias="X-Auth-Session"),
):
    """Execute deficiency import as a background job."""
    if request.session_id not in _qaqc_sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    try:
        access_token = get_token(x_auth_session)
    except HTTPException:
        raise HTTPException(status_code=401, detail="Invalid auth session")

    parse_result = _qaqc_sessions[request.session_id]

    job_id = str(uuid.uuid4())
    file_job_store.create_job(
        job_id=job_id,
        project_id=str(project_id),
        company_id=str(request.company_id),
        session_id=x_auth_session,
        manifest=[],
        total_files=parse_result.total_count,
    )

    asyncio.create_task(
        _process_observation_job(
            job_id=job_id,
            project_id=project_id,
            parse_result=parse_result,
            access_token=access_token,
            company_id=request.company_id,
            observation_type_id=request.observation_type_id,
            create_locations=request.create_locations,
            location_map=request.location_map,
        )
    )

    return QAQCExecuteResponse(status="background", job_id=job_id)


async def _process_observation_job(
    job_id: str,
    project_id: int,
    parse_result: RMSDeficiencyParseResult,
    access_token: str,
    company_id: int,
    observation_type_id: int | None,
    create_locations: bool,
    location_map: dict[str, int | None],
):
    """Background job to create observations in Procore."""
    file_job_store.update_progress(job_id, status="running")

    api = ProcoreAPI(access_token, company_id=company_id)
    observations_created = 0
    locations_created = 0
    completed = 0
    errors: list[str] = []

    # Mutable copy of location map
    loc_map = dict(location_map)

    def _update():
        file_job_store.update_progress(
            job_id,
            uploaded_files=completed,
            result_summary={
                "completed": completed,
                "observations_created": observations_created,
                "locations_created": locations_created,
                "errors": len(errors),
            },
        )

    # Phase 1: Create missing locations
    if create_locations:
        for rms_location, loc_id in list(loc_map.items()):
            if loc_id is not None:
                continue
            try:
                new_loc = await api.create_location(project_id, rms_location)
                loc_map[rms_location] = new_loc["id"]
                locations_created += 1
                await asyncio.sleep(1)
            except RateLimitError:
                errors.append(f"Rate limited creating location '{rms_location}'")
                await asyncio.sleep(60)
            except Exception as e:
                errors.append(f"Location '{rms_location}': {e}")
                logger.error(f"Failed to create location: {e}")

    # Phase 2: Create observations
    for deficiency in parse_result.deficiencies:
        try:
            observation_data: dict = {
                "name": f"{deficiency.item_number}: {deficiency.description[:100]}",
                "description": deficiency.description,
                "status": deficiency.procore_status,
                "personal": False,
            }

            if observation_type_id:
                observation_data["type_id"] = observation_type_id

            if deficiency.location:
                location_id = loc_map.get(deficiency.location)
                if location_id:
                    observation_data["location_id"] = location_id

            if deficiency.date_issued:
                observation_data["due_date"] = deficiency.date_issued.isoformat()

            await api.create_observation(project_id, observation_data)
            observations_created += 1
            completed += 1
            _update()
            await asyncio.sleep(1)

        except RateLimitError:
            errors.append(f"Rate limited on {deficiency.item_number}")
            await asyncio.sleep(60)
        except Exception as e:
            errors.append(f"{deficiency.item_number}: {e}")
            logger.error(f"Failed to create observation: {e}")
            completed += 1
            _update()

    file_job_store.update_progress(
        job_id,
        status="completed",
        uploaded_files=completed,
        errors=errors,
        result_summary={
            "completed": completed,
            "observations_created": observations_created,
            "locations_created": locations_created,
            "errors": len(errors),
        },
    )
    logger.info(
        f"QAQC job {job_id} completed: "
        f"{observations_created} observations, {locations_created} locations, "
        f"{len(errors)} errors"
    )


@router.get("/jobs/{job_id}", response_model=QAQCJobStatus)
async def get_qaqc_job_status(job_id: str):
    """Get status of a QAQC import job."""
    job = file_job_store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return _job_to_status(job)


@router.delete("/session/{session_id}")
async def delete_session(session_id: str):
    """Delete a QAQC session."""
    if session_id in _qaqc_sessions:
        del _qaqc_sessions[session_id]
        return {"status": "deleted"}
    raise HTTPException(status_code=404, detail="Session not found")
