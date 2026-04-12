"""RFI upload, analysis, and import endpoints."""
import uuid
import asyncio
import logging
from fastapi import APIRouter, Header, HTTPException, UploadFile, File
from pydantic import BaseModel
from typing import Optional

from services.rfi_parser import RFIParser
from services.procore_api import ProcoreAPI, RateLimitError
from models.rfi import RFIParseResult, RFICreateAction, RFISyncPlan
from routers.auth import get_token

router = APIRouter()
logger = logging.getLogger(__name__)

# In-memory session storage
_rfi_sessions: dict[str, RFIParseResult] = {}

# In-memory job tracking for RFI imports
_rfi_jobs: dict[str, dict] = {}


class RFIUploadResponse(BaseModel):
    """Response from RFI file upload."""

    session_id: str
    total_count: int
    answered_count: int
    outstanding_count: int
    errors: list[str] = []
    warnings: list[str] = []


class RFIAnalyzeRequest(BaseModel):
    """Request to analyze RFIs against Procore."""

    session_id: str
    company_id: int


class RFIAnalyzeResponse(BaseModel):
    """Response from RFI analysis."""

    plan: RFISyncPlan
    summary: str


class RFIExecuteRequest(BaseModel):
    """Request to execute RFI import."""

    session_id: str
    company_id: int
    apply_creates: bool = True
    apply_replies: bool = True


class RFIExecuteResponse(BaseModel):
    """Response from RFI import execution."""

    status: str
    created: int
    replies_added: int
    errors: list[str]
    job_id: Optional[str] = None


class RFIJobStatus(BaseModel):
    """Status of an RFI import job."""

    id: str
    status: str  # "queued", "running", "completed", "failed"
    total: int
    created: int
    replies_added: int
    errors: list[str]


@router.post("/upload", response_model=RFIUploadResponse)
async def upload_rfi_file(
    file: UploadFile = File(...),
):
    """Upload and parse an RFI Report CSV file."""
    if not file.filename.endswith((".csv", ".CSV")):
        raise HTTPException(
            status_code=400,
            detail="File must be a CSV file (.csv)",
        )

    file_bytes = await file.read()

    parser = RFIParser()
    result = parser.parse(file_bytes)

    if result.errors and result.total_count == 0:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to parse RFI file: {'; '.join(result.errors)}",
        )

    session_id = str(uuid.uuid4())
    _rfi_sessions[session_id] = result

    return RFIUploadResponse(
        session_id=session_id,
        total_count=result.total_count,
        answered_count=result.answered_count,
        outstanding_count=result.outstanding_count,
        errors=result.errors,
        warnings=result.warnings,
    )


@router.get("/session/{session_id}/items")
async def get_rfi_items(session_id: str) -> list[dict]:
    """Get parsed RFIs from a session."""
    if session_id not in _rfi_sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    result = _rfi_sessions[session_id]
    return [
        {
            "rfi_number": r.rfi_number,
            "number": r.number,
            "subject": r.subject,
            "date_requested": r.date_requested.isoformat() if r.date_requested else None,
            "date_received": r.date_received.isoformat() if r.date_received else None,
            "date_answered": r.date_answered.isoformat() if r.date_answered else None,
            "requester_name": r.requester_name,
            "responder_name": r.responder_name,
            "is_answered": r.is_answered,
            "question_preview": r.question_body[:200] + "..." if len(r.question_body) > 200 else r.question_body,
            "has_response": r.response_body is not None,
        }
        for r in result.rfis
    ]


@router.post("/projects/{project_id}/analyze", response_model=RFIAnalyzeResponse)
async def analyze_rfis(
    project_id: int,
    request: RFIAnalyzeRequest,
    x_auth_session: str = Header(..., alias="X-Auth-Session"),
):
    """Compare parsed RFIs against existing Procore RFIs."""
    if request.session_id not in _rfi_sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    parse_result = _rfi_sessions[request.session_id]

    # Get auth token (same pattern as sync router)
    try:
        access_token = get_token(x_auth_session)
    except HTTPException:
        raise HTTPException(status_code=401, detail="Invalid auth session")

    api = ProcoreAPI(access_token, company_id=request.company_id)

    # Fetch existing RFIs from Procore
    try:
        existing_rfis = await api.get_rfis(project_id)
    except Exception as e:
        logger.warning(f"Failed to fetch existing RFIs: {e}")
        existing_rfis = []

    # Build lookup by RFI number
    existing_by_number = {r.number: r for r in existing_rfis if r.number is not None}

    creates = []
    already_exist = 0

    for rfi in parse_result.rfis:
        if rfi.number in existing_by_number:
            already_exist += 1
            continue

        creates.append(RFICreateAction(
            rfi_number=rfi.rfi_number,
            number=rfi.number,
            subject=rfi.subject,
            question_body=rfi.question_body,
            response_body=rfi.response_body,
            date_requested=rfi.date_requested,
            date_received=rfi.date_received,
            date_answered=rfi.date_answered,
            is_answered=rfi.is_answered,
        ))

    has_changes = len(creates) > 0
    parts = []
    if creates:
        parts.append(f"{len(creates)} to create")
    if already_exist:
        parts.append(f"{already_exist} already in Procore")
    summary = f"{parse_result.total_count} RFIs in RMS: {', '.join(parts)}" if parts else "No RFIs to sync"

    plan = RFISyncPlan(
        creates=creates,
        already_exist=already_exist,
        total_rms=parse_result.total_count,
        has_changes=has_changes,
        summary=summary,
    )

    return RFIAnalyzeResponse(plan=plan, summary=summary)


@router.post("/projects/{project_id}/execute", response_model=RFIExecuteResponse)
async def execute_rfi_import(
    project_id: int,
    request: RFIExecuteRequest,
    x_auth_session: str = Header(..., alias="X-Auth-Session"),
):
    """Execute RFI import as a background job."""
    if request.session_id not in _rfi_sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    # Validate auth (same pattern as sync router)
    try:
        access_token = get_token(x_auth_session)
    except HTTPException:
        raise HTTPException(status_code=401, detail="Invalid auth session")

    parse_result = _rfi_sessions[request.session_id]
    api = ProcoreAPI(access_token, company_id=request.company_id)

    try:
        existing_rfis = await api.get_rfis(project_id)
    except Exception:
        existing_rfis = []

    existing_by_number = {r.number: r for r in existing_rfis if r.number is not None}

    # Create background job
    job_id = str(uuid.uuid4())
    _rfi_jobs[job_id] = {
        "id": job_id,
        "status": "queued",
        "total": parse_result.total_count,
        "created": 0,
        "replies_added": 0,
        "errors": [],
    }

    # Launch background task
    asyncio.create_task(
        _process_rfi_job(
            job_id=job_id,
            project_id=project_id,
            parse_result=parse_result,
            existing_by_number=existing_by_number,
            access_token=access_token,
            company_id=request.company_id,
            apply_creates=request.apply_creates,
            apply_replies=request.apply_replies,
        )
    )

    return RFIExecuteResponse(
        status="background",
        created=0,
        replies_added=0,
        errors=[],
        job_id=job_id,
    )


async def _process_rfi_job(
    job_id: str,
    project_id: int,
    parse_result: RFIParseResult,
    existing_by_number: dict,
    access_token: str,
    company_id: int,
    apply_creates: bool,
    apply_replies: bool,
):
    """Background job to create RFIs in Procore."""
    job = _rfi_jobs[job_id]
    job["status"] = "running"

    api = ProcoreAPI(access_token, company_id=company_id)

    for rfi in parse_result.rfis:
        if rfi.number in existing_by_number:
            continue

        if not apply_creates:
            continue

        try:
            # Build RFI data
            rfi_data = {
                "subject": rfi.subject,
                "number": str(rfi.number),
                "question_body": rfi.question_body,
            }

            if rfi.date_requested:
                rfi_data["due_date"] = rfi.date_requested.isoformat()

            # Create as Draft first (fewest required fields).
            # Status will be adjusted once we confirm Procore's
            # accepted values and required fields for Open/Closed.
            rfi_data["status"] = "draft"

            # Create the RFI
            created = await api.create_rfi(project_id, rfi_data)
            job["created"] += 1
            logger.info(f"Created RFI {rfi.rfi_number} (Procore ID: {created.get('id')})")

            # Add government response as a reply if present
            if apply_replies and rfi.response_body and rfi.is_answered:
                try:
                    rfi_id = created["id"]
                    await api.create_rfi_reply(project_id, rfi_id, {
                        "body": rfi.response_body,
                    })
                    job["replies_added"] += 1
                except Exception as e:
                    job["errors"].append(f"Reply for {rfi.rfi_number}: {str(e)}")

            # Rate limit delay
            await asyncio.sleep(2)

        except RateLimitError as e:
            job["errors"].append(f"Rate limited on {rfi.rfi_number}: {str(e)}")
            # Wait longer and continue
            await asyncio.sleep(60)
        except Exception as e:
            job["errors"].append(f"Failed to create {rfi.rfi_number}: {str(e)}")
            logger.error(f"Error creating RFI {rfi.rfi_number}: {e}")

    job["status"] = "completed"
    logger.info(
        f"RFI import job {job_id} completed: "
        f"{job['created']} created, {job['replies_added']} replies, "
        f"{len(job['errors'])} errors"
    )


@router.get("/jobs/{job_id}", response_model=RFIJobStatus)
async def get_rfi_job_status(job_id: str):
    """Get status of an RFI import job."""
    if job_id not in _rfi_jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    return RFIJobStatus(**_rfi_jobs[job_id])


@router.get("/projects/{project_id}/debug")
async def debug_rfis(
    project_id: int,
    company_id: int,
    x_auth_session: str = Header(..., alias="X-Auth-Session"),
):
    """
    Debug endpoint: fetch one existing RFI raw from Procore,
    then attempt to create a test Draft RFI and capture the
    full error response. Deletes the test RFI if created.
    """
    try:
        access_token = get_token(x_auth_session)
    except HTTPException:
        raise HTTPException(status_code=401, detail="Invalid auth session")

    api = ProcoreAPI(access_token, company_id=company_id)
    result = {"existing_rfi_sample": None, "create_attempt": None}

    # 1. Fetch one existing RFI raw
    try:
        raw = await api._get(
            f"/rest/v1.0/projects/{project_id}/rfis",
            params={"per_page": 1},
        )
        if raw:
            result["existing_rfi_sample"] = raw[0]
    except Exception as e:
        result["existing_rfi_sample"] = f"Error: {e}"

    # 2. Try multiple create variants to find what works
    import httpx

    rfi_manager_id = None
    if isinstance(result["existing_rfi_sample"], dict):
        mgr = result["existing_rfi_sample"].get("rfi_manager")
        if mgr:
            rfi_manager_id = mgr.get("id")

    # Try several variants
    variants = {
        "v1.1_minimal": {
            "url": f"{api.base_url}/rest/v1.1/projects/{project_id}/rfis",
            "body": {"rfi": {"subject": "API TEST - DELETE ME", "rfi_manager_id": rfi_manager_id}},
        },
        "v1.0_no_questions": {
            "url": f"{api.base_url}/rest/v1.0/projects/{project_id}/rfis",
            "body": {"rfi": {"subject": "API TEST - DELETE ME", "rfi_manager_id": rfi_manager_id, "assignee_ids": [rfi_manager_id]}},
        },
        "v1.0_with_number": {
            "url": f"{api.base_url}/rest/v1.0/projects/{project_id}/rfis",
            "body": {"rfi": {"subject": "API TEST - DELETE ME", "number": "999", "rfi_manager_id": rfi_manager_id, "assignee_ids": [rfi_manager_id]}},
        },
        "v1.0_question_body": {
            "url": f"{api.base_url}/rest/v1.0/projects/{project_id}/rfis",
            "body": {"rfi": {"subject": "API TEST - DELETE ME", "number": "998", "rfi_manager_id": rfi_manager_id, "assignee_ids": [rfi_manager_id], "question": {"body": "Test question"}}},
        },
    }

    result["create_attempts"] = {}
    for name, variant in variants.items():
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    variant["url"],
                    headers={**api._headers(), "Content-Type": "application/json"},
                    json=variant["body"],
                    timeout=30.0,
                )
                attempt = {
                    "status_code": resp.status_code,
                    "request_body": variant["body"],
                }
                if resp.status_code < 500:
                    attempt["response"] = resp.json()
                else:
                    attempt["response"] = resp.text
                if resp.status_code in (200, 201):
                    attempt["SUCCESS"] = True
                    created_id = resp.json().get("id")
                    if created_id:
                        attempt["created_id"] = created_id
                result["create_attempts"][name] = attempt
        except Exception as e:
            result["create_attempts"][name] = {"error": str(e), "request_body": variant["body"]}
        # Small delay between attempts
        import asyncio
        await asyncio.sleep(1)

    return result


@router.delete("/session/{session_id}")
async def delete_session(session_id: str):
    """Delete an RFI session."""
    if session_id in _rfi_sessions:
        del _rfi_sessions[session_id]
        return {"status": "deleted"}
    raise HTTPException(status_code=404, detail="Session not found")
