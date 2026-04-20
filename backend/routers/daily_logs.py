"""Daily log upload, analysis, and import endpoints."""
import uuid
import asyncio
import logging
from fastapi import APIRouter, Header, HTTPException, UploadFile, File
from pydantic import BaseModel
from typing import Optional

from services.daily_log_parser import DailyLogParser
from services.procore_api import ProcoreAPI, RateLimitError
from models.daily_log import DailyLogParseResult, DailyLogSyncPlan
from routers.auth import get_token
from config import get_settings
from database import file_job_store

settings = get_settings()

router = APIRouter()
logger = logging.getLogger(__name__)

# In-memory session storage for parsed daily log data
_daily_log_sessions: dict[str, DailyLogParseResult] = {}


# === Response Models ===

class DailyLogUploadResponse(BaseModel):
    session_id: str
    equipment_count: int
    labor_count: int
    narrative_count: int
    date_count: int
    errors: list[str] = []
    warnings: list[str] = []


class DailyLogAnalyzeRequest(BaseModel):
    session_id: str
    company_id: int


class DailyLogAnalyzeResponse(BaseModel):
    plan: DailyLogSyncPlan
    summary: str
    vendor_map: dict[str, int | None] = {}  # employer → vendor_id (None if unmatched)


class DailyLogExecuteRequest(BaseModel):
    session_id: str
    company_id: int
    apply_equipment: bool = True
    apply_labor: bool = True
    apply_narratives: bool = True
    vendor_map: dict[str, int | None] = {}  # employer → vendor_id


class DailyLogExecuteResponse(BaseModel):
    status: str
    job_id: Optional[str] = None


class DailyLogJobStatus(BaseModel):
    id: str
    status: str
    total: int
    completed: int
    equipment_created: int
    labor_created: int
    narratives_created: int
    errors: list[str]


def _job_to_status(job: dict) -> DailyLogJobStatus:
    summary = job.get("result_summary") or {}
    return DailyLogJobStatus(
        id=job["id"],
        status=job["status"],
        total=job.get("total_files", 0),
        completed=summary.get("completed", job.get("uploaded_files", 0)),
        equipment_created=summary.get("equipment_created", 0),
        labor_created=summary.get("labor_created", 0),
        narratives_created=summary.get("narratives_created", 0),
        errors=job.get("errors", []),
    )


# === Endpoints ===

@router.post("/upload", response_model=DailyLogUploadResponse)
async def upload_daily_log_files(
    equipment_file: Optional[UploadFile] = File(None),
    labor_file: Optional[UploadFile] = File(None),
    narrative_file: Optional[UploadFile] = File(None),
):
    """Upload and parse daily log CSV files (at least one required)."""
    equipment_bytes = await equipment_file.read() if equipment_file else None
    labor_bytes = await labor_file.read() if labor_file else None
    narrative_bytes = await narrative_file.read() if narrative_file else None

    if not any([equipment_bytes, labor_bytes, narrative_bytes]):
        raise HTTPException(status_code=400, detail="At least one CSV file is required")

    parser = DailyLogParser()
    result = parser.parse(equipment_bytes, labor_bytes, narrative_bytes)

    if result.errors and not any([result.equipment, result.labor, result.narratives]):
        raise HTTPException(
            status_code=400,
            detail=f"Failed to parse files: {'; '.join(result.errors)}",
        )

    session_id = str(uuid.uuid4())
    _daily_log_sessions[session_id] = result

    return DailyLogUploadResponse(
        session_id=session_id,
        equipment_count=result.equipment_count,
        labor_count=result.labor_count,
        narrative_count=result.narrative_count,
        date_count=len(result.dates_found),
        errors=result.errors,
        warnings=result.warnings,
    )


@router.post("/projects/{project_id}/analyze", response_model=DailyLogAnalyzeResponse)
async def analyze_daily_logs(
    project_id: int,
    request: DailyLogAnalyzeRequest,
    x_auth_session: str = Header(..., alias="X-Auth-Session"),
):
    """Compare parsed daily logs against existing Procore entries."""
    if request.session_id not in _daily_log_sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    parse_result = _daily_log_sessions[request.session_id]

    try:
        access_token = get_token(x_auth_session)
    except HTTPException:
        raise HTTPException(status_code=401, detail="Invalid auth session")

    api = ProcoreAPI(access_token, company_id=request.company_id)

    # Fetch vendors for labor matching
    vendor_map: dict[str, int | None] = {}
    if parse_result.labor:
        try:
            vendors = await api.get_project_vendors(project_id)
            vendor_by_name: dict[str, int] = {}
            for v in vendors:
                vendor_by_name[v.name.lower().strip()] = v.id

            unique_employers = set(e.employer for e in parse_result.labor)
            for employer in unique_employers:
                emp_lower = employer.lower().strip()
                # Try exact match first
                if emp_lower in vendor_by_name:
                    vendor_map[employer] = vendor_by_name[emp_lower]
                    continue
                # Try substring match
                matched = False
                for vname, vid in vendor_by_name.items():
                    if emp_lower in vname or vname in emp_lower:
                        vendor_map[employer] = vid
                        matched = True
                        break
                if not matched:
                    vendor_map[employer] = None
        except Exception as e:
            logger.warning(f"Failed to fetch vendors: {e}")

    # Count creates (simplified — no duplicate detection for MVP)
    equipment_creates = len(parse_result.equipment)
    labor_creates = len(parse_result.labor)
    narrative_creates = len(parse_result.narratives)
    total = equipment_creates + labor_creates + narrative_creates

    unmatched = [emp for emp, vid in vendor_map.items() if vid is None]

    parts = []
    if equipment_creates:
        parts.append(f"{equipment_creates} equipment")
    if labor_creates:
        parts.append(f"{labor_creates} labor")
    if narrative_creates:
        parts.append(f"{narrative_creates} narratives")
    summary = f"{total} entries to create: {', '.join(parts)}" if parts else "No entries to sync"

    if unmatched:
        summary += f" ({len(unmatched)} unmatched vendor{'s' if len(unmatched) != 1 else ''})"

    plan = DailyLogSyncPlan(
        equipment_creates=equipment_creates,
        labor_creates=labor_creates,
        narrative_creates=narrative_creates,
        total_creates=total,
        has_changes=total > 0,
        summary=summary,
        unmatched_vendors=unmatched,
    )

    return DailyLogAnalyzeResponse(plan=plan, summary=summary, vendor_map=vendor_map)


@router.post("/projects/{project_id}/execute", response_model=DailyLogExecuteResponse)
async def execute_daily_log_import(
    project_id: int,
    request: DailyLogExecuteRequest,
    x_auth_session: str = Header(..., alias="X-Auth-Session"),
):
    """Execute daily log import as a background job."""
    if request.session_id not in _daily_log_sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    try:
        access_token = get_token(x_auth_session)
    except HTTPException:
        raise HTTPException(status_code=401, detail="Invalid auth session")

    parse_result = _daily_log_sessions[request.session_id]

    total = 0
    if request.apply_equipment:
        total += len(parse_result.equipment)
    if request.apply_labor:
        total += len(parse_result.labor)
    if request.apply_narratives:
        total += len(parse_result.narratives)

    job_id = str(uuid.uuid4())
    file_job_store.create_job(
        job_id=job_id,
        project_id=str(project_id),
        company_id=str(request.company_id),
        session_id=x_auth_session,
        manifest=[],
        total_files=total,
    )

    asyncio.create_task(
        _process_daily_log_job(
            job_id=job_id,
            project_id=project_id,
            parse_result=parse_result,
            access_token=access_token,
            company_id=request.company_id,
            apply_equipment=request.apply_equipment,
            apply_labor=request.apply_labor,
            apply_narratives=request.apply_narratives,
            vendor_map=request.vendor_map,
        )
    )

    return DailyLogExecuteResponse(status="background", job_id=job_id)


async def _process_daily_log_job(
    job_id: str,
    project_id: int,
    parse_result: DailyLogParseResult,
    access_token: str,
    company_id: int,
    apply_equipment: bool,
    apply_labor: bool,
    apply_narratives: bool,
    vendor_map: dict[str, int | None],
):
    """Background job to create daily log entries in Procore."""
    file_job_store.update_progress(job_id, status="running")

    api = ProcoreAPI(access_token, company_id=company_id)
    equipment_created = 0
    labor_created = 0
    narratives_created = 0
    completed = 0
    errors = []

    def _update():
        file_job_store.update_progress(
            job_id,
            uploaded_files=completed,
            result_summary={
                "completed": completed,
                "equipment_created": equipment_created,
                "labor_created": labor_created,
                "narratives_created": narratives_created,
                "errors": len(errors),
            },
        )

    # Phase 1: Equipment
    if apply_equipment:
        for entry in parse_result.equipment:
            try:
                await api.create_equipment_log(project_id, {
                    "date": entry.date.isoformat(),
                    "hours_idle": entry.idle_hours,
                    "hours_operating": entry.operating_hours,
                    "notes": f"{entry.description} (S/N: {entry.serial_number})",
                })
                equipment_created += 1
                completed += 1
                _update()
                await asyncio.sleep(1)
            except RateLimitError:
                errors.append(f"Rate limited on equipment {entry.item}")
                await asyncio.sleep(60)
            except Exception as e:
                errors.append(f"Equipment {entry.item} ({entry.date}): {e}")
                logger.error(f"Failed to create equipment log: {e}")

    # Phase 2: Labor / Manpower
    if apply_labor:
        for entry in parse_result.labor:
            try:
                data: dict = {
                    "date": entry.date.isoformat(),
                    "num_workers": entry.num_employees,
                    "num_hours": str(entry.hours),
                    "notes": entry.labor_classification,
                }
                vendor_id = vendor_map.get(entry.employer)
                if vendor_id:
                    data["vendor_id"] = vendor_id

                await api.create_manpower_log(project_id, data)
                labor_created += 1
                completed += 1
                _update()
                await asyncio.sleep(1)
            except RateLimitError:
                errors.append(f"Rate limited on labor {entry.employer}")
                await asyncio.sleep(60)
            except Exception as e:
                errors.append(f"Labor {entry.employer} ({entry.date}): {e}")
                logger.error(f"Failed to create manpower log: {e}")

    # Phase 3: Narratives / Notes
    if apply_narratives:
        for entry in parse_result.narratives:
            try:
                data: dict = {
                    "date": entry.dated.isoformat(),
                    "comment": entry.narrative_text,
                }
                # TODO: Map narrative_type to custom field LOV entry ID
                # For now, prepend type to comment
                if entry.narrative_type:
                    data["comment"] = f"[{entry.narrative_type}]\n\n{entry.narrative_text}"

                await api.create_notes_log(project_id, data)
                narratives_created += 1
                completed += 1
                _update()
                await asyncio.sleep(1)
            except RateLimitError:
                errors.append(f"Rate limited on narrative {entry.narrative_id}")
                await asyncio.sleep(60)
            except Exception as e:
                errors.append(f"Narrative {entry.narrative_id} ({entry.dated}): {e}")
                logger.error(f"Failed to create notes log: {e}")

    file_job_store.update_progress(
        job_id,
        status="completed",
        uploaded_files=completed,
        errors=errors,
        result_summary={
            "completed": completed,
            "equipment_created": equipment_created,
            "labor_created": labor_created,
            "narratives_created": narratives_created,
            "errors": len(errors),
        },
    )
    logger.info(
        f"Daily log job {job_id} completed: "
        f"{equipment_created} equipment, {labor_created} labor, "
        f"{narratives_created} narratives, {len(errors)} errors"
    )


@router.get("/jobs/{job_id}", response_model=DailyLogJobStatus)
async def get_daily_log_job_status(job_id: str):
    """Get status of a daily log import job."""
    job = file_job_store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return _job_to_status(job)


@router.delete("/session/{session_id}")
async def delete_session(session_id: str):
    """Delete a daily log session."""
    if session_id in _daily_log_sessions:
        del _daily_log_sessions[session_id]
        return {"status": "deleted"}
    raise HTTPException(status_code=404, detail="Session not found")
