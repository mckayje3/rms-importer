"""RFI upload, analysis, and import endpoints."""
import uuid
import asyncio
import logging
from fastapi import APIRouter, Header, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from typing import Optional

from services.rfi_parser import RFIParser
from services.procore_api import ProcoreAPI, RateLimitError
from models.rfi import RFIParseResult, RFICreateAction, RFIResponseAction, RFISyncPlan
from routers.auth import get_token
from config import get_settings
from database import file_job_store

settings = get_settings()

router = APIRouter()
logger = logging.getLogger(__name__)

# In-memory session storage for parsed RFI data
_rfi_sessions: dict[str, RFIParseResult] = {}

# Cache: project_id → {rfi_number→procore_id, attached_filenames set}
# Populated during analyze, consumed by filter-files and upload-files
_rfi_cache: dict[int, dict] = {}


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
    apply_response_updates: bool = True
    response_updates: list[dict] = []  # From analyze plan


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
    responses_added: int = 0
    errors: list[str]


def _job_to_rfi_status(job: dict) -> RFIJobStatus:
    """Convert a file_job_store job dict to RFIJobStatus."""
    summary = job.get("result_summary") or {}
    return RFIJobStatus(
        id=job["id"],
        status=job["status"],
        total=job.get("total_files", 0),
        created=summary.get("created", job.get("uploaded_files", 0)),
        replies_added=summary.get("replies_added", 0),
        responses_added=summary.get("responses_added", 0),
        errors=job.get("errors", []),
    )


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

    try:
        access_token = get_token(x_auth_session)
    except HTTPException:
        raise HTTPException(status_code=401, detail="Invalid auth session")

    api = ProcoreAPI(access_token, company_id=request.company_id)

    try:
        existing_rfis = await api.get_rfis(project_id)
    except Exception as e:
        logger.warning(f"Failed to fetch existing RFIs: {e}")
        existing_rfis = []

    # Build lookup and cache attachment info for file filtering
    existing_by_number: dict[int, object] = {}
    rfi_lookup: dict[int, int] = {}  # number → procore_id
    attached_files: set[str] = set()

    for r in existing_rfis:
        if r.number is not None:
            try:
                num = int(r.number)
                existing_by_number[num] = r
                rfi_lookup[num] = r.id
            except (ValueError, TypeError):
                pass

    # Check Documents folder for already-uploaded RFI files.
    # The RFI list endpoint doesn't include attachments, so we check
    # the upload folder instead — files there were uploaded by previous runs.
    try:
        existing_docs = await api.list_folder_files(
            project_id, settings.procore_upload_folder_id
        )
        import re
        for name in existing_docs:
            if re.match(r"RFI-\d+", name):
                attached_files.add(name)
        logger.info(f"Found {len(attached_files)} RFI files already in Documents folder")
    except Exception as e:
        logger.warning(f"Failed to check Documents folder for existing files: {e}")

    # Cache for filter-files, upload-files, and execute endpoints
    _rfi_cache[project_id] = {
        "rfi_lookup": rfi_lookup,
        "attached_files": attached_files,
    }

    creates = []
    response_updates = []
    already_exist = 0

    # Collect existing RFIs that have an answered RMS counterpart — we'll
    # fetch their detail to check whether answers already exist in Procore.
    need_response_check: list[tuple] = []  # (rms_rfi, procore_rfi)

    for rfi in parse_result.rfis:
        if rfi.number in existing_by_number:
            already_exist += 1
            procore_rfi = existing_by_number[rfi.number]
            # Skip closed RFIs — they likely have responses already,
            # and the API blocks replies on closed RFIs anyway
            if rfi.is_answered and rfi.response_body and procore_rfi.status != "closed":
                need_response_check.append((rfi, procore_rfi))
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

    # Check existing RFIs for missing responses (requires detail calls)
    if need_response_check:
        logger.info(f"Checking {len(need_response_check)} existing RFIs for missing responses")
        for rms_rfi, procore_rfi in need_response_check:
            try:
                detail = await api._get(
                    f"/rest/v1.0/projects/{project_id}/rfis/{procore_rfi.id}",
                )
                questions = detail.get("questions", [])
                has_answer = any(
                    bool(q.get("answers"))
                    for q in questions
                )
                if not has_answer:
                    response_updates.append(RFIResponseAction(
                        rfi_number=rms_rfi.rfi_number,
                        number=rms_rfi.number,
                        procore_rfi_id=procore_rfi.id,
                        response_body=rms_rfi.response_body,
                        date_answered=rms_rfi.date_answered,
                    ))
                await asyncio.sleep(1)
            except Exception as e:
                logger.warning(f"Failed to check RFI {rms_rfi.rfi_number} for answers: {e}")

    has_changes = len(creates) > 0 or len(response_updates) > 0
    parts = []
    if creates:
        parts.append(f"{len(creates)} to create")
    if response_updates:
        parts.append(f"{len(response_updates)} responses to add")
    up_to_date = already_exist - len(response_updates)
    if up_to_date > 0:
        parts.append(f"{up_to_date} up to date")
    summary = f"{parse_result.total_count} RFIs in RMS: {', '.join(parts)}" if parts else "No RFIs to sync"

    plan = RFISyncPlan(
        creates=creates,
        response_updates=response_updates,
        already_exist=already_exist,
        total_rms=parse_result.total_count,
        has_changes=has_changes,
        summary=summary,
    )

    return RFIAnalyzeResponse(plan=plan, summary=summary)


async def _get_rfi_manager_id(api: ProcoreAPI, project_id: int) -> Optional[int]:
    """Get the RFI manager ID for the project."""
    try:
        me = await api._get("/rest/v1.0/me")
        if me and me.get("id"):
            return me["id"]
    except Exception as e:
        logger.warning(f"Failed to get current user via /me: {e}")

    try:
        raw = await api._get(
            f"/rest/v1.0/projects/{project_id}/rfis",
            params={"per_page": 1},
        )
        if raw and len(raw) > 0:
            mgr = raw[0].get("rfi_manager")
            if mgr and mgr.get("id"):
                return mgr["id"]
    except Exception as e:
        logger.warning(f"Failed to get rfi_manager from existing RFIs: {e}")

    return None


@router.post("/projects/{project_id}/execute", response_model=RFIExecuteResponse)
async def execute_rfi_import(
    project_id: int,
    request: RFIExecuteRequest,
    x_auth_session: str = Header(..., alias="X-Auth-Session"),
):
    """Execute RFI import as a background job."""
    if request.session_id not in _rfi_sessions:
        raise HTTPException(status_code=404, detail="Session not found")

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

    existing_by_number: dict[int, object] = {}
    for r in existing_rfis:
        if r.number is not None:
            try:
                existing_by_number[int(r.number)] = r
            except (ValueError, TypeError):
                pass

    rfi_manager_id = await _get_rfi_manager_id(api, project_id)
    if not rfi_manager_id:
        raise HTTPException(
            status_code=400,
            detail="Could not determine RFI Manager.",
        )

    # Count how many will actually be created + response updates
    to_create = sum(1 for rfi in parse_result.rfis if rfi.number not in existing_by_number)
    response_update_count = len(request.response_updates) if request.apply_response_updates else 0
    total_operations = to_create + response_update_count

    # Create database-backed job (same pattern as submittal sync)
    job_id = str(uuid.uuid4())
    file_job_store.create_job(
        job_id=job_id,
        project_id=str(project_id),
        company_id=str(request.company_id),
        session_id=x_auth_session,
        manifest=[],
        total_files=total_operations,
    )

    asyncio.create_task(
        _process_rfi_job(
            job_id=job_id,
            project_id=project_id,
            parse_result=parse_result,
            existing_by_number=existing_by_number,
            access_token=access_token,
            company_id=request.company_id,
            rfi_manager_id=rfi_manager_id,
            apply_creates=request.apply_creates,
            apply_replies=request.apply_replies,
            apply_response_updates=request.apply_response_updates,
            response_updates=request.response_updates,
        )
    )

    return RFIExecuteResponse(
        status="background",
        created=0,
        replies_added=0,
        errors=[],
        job_id=job_id,
    )


@router.post("/projects/{project_id}/execute-with-files", response_model=RFIExecuteResponse)
async def execute_rfi_import_with_files(
    project_id: int,
    request_json: str = Form(...),
    response_files: list[UploadFile] = File(default=[]),
    x_auth_session: str = Header(..., alias="X-Auth-Session"),
):
    """Execute RFI import with response file attachments."""
    import os
    import re
    import tempfile

    request = RFIExecuteRequest.model_validate_json(request_json)

    if request.session_id not in _rfi_sessions:
        raise HTTPException(status_code=404, detail="Session not found")

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

    existing_by_number: dict[int, object] = {}
    for r in existing_rfis:
        if r.number is not None:
            try:
                existing_by_number[int(r.number)] = r
            except (ValueError, TypeError):
                pass

    rfi_manager_id = await _get_rfi_manager_id(api, project_id)
    if not rfi_manager_id:
        raise HTTPException(
            status_code=400,
            detail="Could not determine RFI Manager.",
        )

    # Save response files to temp dir and build map: rfi_number → [temp_paths]
    temp_dir = tempfile.mkdtemp(prefix="rfi_response_files_")
    response_file_map: dict[int, list[str]] = {}

    for f in response_files:
        filename = os.path.basename(f.filename or "")
        match = re.match(r"RFI-(\d+)\s*Response", filename, re.IGNORECASE)
        if match:
            rfi_num = int(match.group(1))
            temp_path = os.path.join(temp_dir, filename)
            content = await f.read()
            with open(temp_path, "wb") as fh:
                fh.write(content)
            response_file_map.setdefault(rfi_num, []).append(temp_path)

    logger.info(f"Saved {sum(len(v) for v in response_file_map.values())} response files for {len(response_file_map)} RFIs")

    # Count operations
    to_create = sum(1 for rfi in parse_result.rfis if rfi.number not in existing_by_number)
    response_update_count = len(request.response_updates) if request.apply_response_updates else 0
    total_operations = to_create + response_update_count

    job_id = str(uuid.uuid4())
    file_job_store.create_job(
        job_id=job_id,
        project_id=str(project_id),
        company_id=str(request.company_id),
        session_id=x_auth_session,
        manifest=[],
        total_files=total_operations,
    )

    asyncio.create_task(
        _process_rfi_job(
            job_id=job_id,
            project_id=project_id,
            parse_result=parse_result,
            existing_by_number=existing_by_number,
            access_token=access_token,
            company_id=request.company_id,
            rfi_manager_id=rfi_manager_id,
            apply_creates=request.apply_creates,
            apply_replies=request.apply_replies,
            apply_response_updates=request.apply_response_updates,
            response_updates=request.response_updates,
            response_file_map=response_file_map,
            temp_dir=temp_dir,
        )
    )

    return RFIExecuteResponse(
        status="background",
        created=0,
        replies_added=0,
        errors=[],
        job_id=job_id,
    )


async def _upload_response_files(
    api: ProcoreAPI,
    project_id: int,
    rfi_number: int,
    response_file_map: dict[int, list[str]],
    errors: list[str],
) -> list[int]:
    """Upload response files for an RFI and return prostore_file_ids."""
    prostore_ids = []
    if not response_file_map or rfi_number not in response_file_map:
        return prostore_ids

    for file_path in response_file_map[rfi_number]:
        try:
            pid = await api.upload_file(project_id, file_path)
            prostore_ids.append(pid)
            await asyncio.sleep(2)
        except Exception as e:
            import os
            fname = os.path.basename(file_path)
            errors.append(f"File upload {fname}: {str(e)}")
            logger.error(f"Failed to upload response file {file_path}: {e}")

    return prostore_ids


async def _process_rfi_job(
    job_id: str,
    project_id: int,
    parse_result: RFIParseResult,
    existing_by_number: dict,
    access_token: str,
    company_id: int,
    rfi_manager_id: int,
    apply_creates: bool,
    apply_replies: bool,
    apply_response_updates: bool = False,
    response_updates: list[dict] | None = None,
    response_file_map: dict[int, list[str]] | None = None,
    temp_dir: str | None = None,
):
    """Background job to create RFIs and add responses in Procore."""
    file_job_store.update_progress(job_id, status="running")

    api = ProcoreAPI(access_token, company_id=company_id)
    created = 0
    replies_added = 0
    responses_added = 0
    errors = []
    completed_ops = 0

    def _update_progress():
        file_job_store.update_progress(
            job_id,
            uploaded_files=completed_ops,
            result_summary={
                "created": created,
                "replies_added": replies_added,
                "responses_added": responses_added,
                "errors": len(errors),
            },
        )

    try:
        # Phase 1: Create new RFIs
        if apply_creates:
            for rfi in parse_result.rfis:
                if rfi.number in existing_by_number:
                    continue

                try:
                    rfi_data = {
                        "subject": rfi.subject,
                        "number": str(rfi.number),
                        "rfi_manager_id": rfi_manager_id,
                        "assignee_ids": [rfi_manager_id],
                        "question": {"body": rfi.question_body},
                    }

                    if rfi.date_requested:
                        rfi_data["due_date"] = rfi.date_requested.isoformat()

                    result = await api.create_rfi(project_id, rfi_data)
                    created += 1
                    completed_ops += 1
                    logger.info(f"Created RFI {rfi.rfi_number} (Procore ID: {result.get('id')})")
                    _update_progress()

                    if apply_replies and rfi.response_body and rfi.is_answered:
                        try:
                            rfi_id = result["id"]
                            # Upload response files if available
                            prostore_ids = await _upload_response_files(
                                api, project_id, rfi.number, response_file_map, errors
                            )
                            reply_data: dict = {
                                "body": rfi.response_body,
                                "official": True,
                            }
                            if prostore_ids:
                                reply_data["prostore_file_ids"] = prostore_ids
                            await api.create_rfi_reply(project_id, rfi_id, reply_data)
                            replies_added += 1
                        except Exception as e:
                            errors.append(f"Reply for {rfi.rfi_number}: {str(e)}")

                    await asyncio.sleep(2)

                except RateLimitError as e:
                    errors.append(f"Rate limited on {rfi.rfi_number}: {str(e)}")
                    await asyncio.sleep(60)
                except Exception as e:
                    errors.append(f"Failed to create {rfi.rfi_number}: {str(e)}")
                    logger.error(f"Error creating RFI {rfi.rfi_number}: {e}")

        # Phase 2: Add responses to existing RFIs
        if apply_response_updates and response_updates:
            for update in response_updates:
                rfi_number = update.get("rfi_number", "?")
                procore_rfi_id = update.get("procore_rfi_id")
                response_body = update.get("response_body")
                number = update.get("number")

                if not procore_rfi_id or not response_body:
                    continue

                try:
                    # Upload response files if available
                    prostore_ids = await _upload_response_files(
                        api, project_id, number, response_file_map, errors
                    ) if number else []

                    reply_data: dict = {
                        "body": response_body,
                        "official": True,
                    }
                    if prostore_ids:
                        reply_data["prostore_file_ids"] = prostore_ids

                    await api.create_rfi_reply(project_id, procore_rfi_id, reply_data)
                    responses_added += 1
                    completed_ops += 1
                    logger.info(f"Added response and closed {rfi_number} (Procore ID: {procore_rfi_id})")
                    _update_progress()

                    await asyncio.sleep(2)
                except RateLimitError as e:
                    errors.append(f"Rate limited on response for {rfi_number}: {str(e)}")
                    await asyncio.sleep(60)
                except Exception as e:
                    errors.append(f"Failed to add response to {rfi_number}: {str(e)}")
                    logger.error(f"Error adding response to {rfi_number}: {e}")

    finally:
        # Clean up temp files
        if temp_dir:
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)

    file_job_store.update_progress(
        job_id,
        status="completed",
        uploaded_files=completed_ops,
        errors=errors,
        result_summary={
            "created": created,
            "replies_added": replies_added,
            "responses_added": responses_added,
            "errors": len(errors),
        },
    )
    logger.info(
        f"RFI import job {job_id} completed: "
        f"{created} created, {replies_added} replies, {responses_added} responses, {len(errors)} errors"
    )


class RFIFilterFilesRequest(BaseModel):
    """Request to filter RFI files."""
    filenames: list[str]


class RFIFilterFilesResponse(BaseModel):
    """Response from filtering RFI files."""
    new_files: list[str]
    already_attached: list[str]
    unmapped_files: list[str]
    total_checked: int


@router.post("/projects/{project_id}/filter-files", response_model=RFIFilterFilesResponse)
async def filter_rfi_files(
    project_id: int,
    request: RFIFilterFilesRequest,
    x_auth_session: str = Header(..., alias="X-Auth-Session"),
):
    """Check which files are new vs already attached to RFIs.

    Uses cached data from the analyze step — no Procore API calls.
    If cache is missing (user skipped analyze), fetches fresh data.
    """
    import re

    try:
        get_token(x_auth_session)
    except HTTPException:
        raise HTTPException(status_code=401, detail="Invalid auth session")

    cache = _rfi_cache.get(project_id)
    if not cache:
        # No cache — need to tell user to run analyze first, or fetch now
        # For robustness, return all as new (they'll be checked during upload)
        rfi_files = []
        unmapped = []
        for fn in request.filenames:
            if re.match(r"RFI-\d+", fn):
                rfi_files.append(fn)
            else:
                unmapped.append(fn)
        return RFIFilterFilesResponse(
            new_files=rfi_files,
            already_attached=[],
            unmapped_files=unmapped,
            total_checked=len(request.filenames),
        )

    rfi_lookup = cache["rfi_lookup"]
    attached_files = cache["attached_files"]

    new_files = []
    already_attached = []
    unmapped = []

    for fn in request.filenames:
        match = re.match(r"RFI-(\d+)", fn)
        if not match:
            unmapped.append(fn)
            continue

        rfi_num = int(match.group(1))
        if rfi_num not in rfi_lookup:
            unmapped.append(fn)
            continue

        if fn in attached_files:
            already_attached.append(fn)
        else:
            new_files.append(fn)

    return RFIFilterFilesResponse(
        new_files=new_files,
        already_attached=already_attached,
        unmapped_files=unmapped,
        total_checked=len(request.filenames),
    )


@router.get("/jobs/{job_id}", response_model=RFIJobStatus)
async def get_rfi_job_status(job_id: str):
    """Get status of an RFI import job."""
    job = file_job_store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return _job_to_rfi_status(job)


@router.post("/projects/{project_id}/upload-files")
async def upload_rfi_files(
    project_id: int,
    files: list[UploadFile] = File(...),
    x_auth_session: str = Header(..., alias="X-Auth-Session"),
    x_company_id: int = Header(..., alias="X-Company-Id"),
):
    """Upload files and attach them to matching RFIs."""
    import os
    import re
    import tempfile

    try:
        access_token = get_token(x_auth_session)
    except HTTPException:
        raise HTTPException(status_code=401, detail="Invalid auth session")

    # Use cached RFI lookup from analyze step (avoids burning API calls)
    cache = _rfi_cache.get(project_id)
    if cache:
        rfi_lookup = cache["rfi_lookup"]
    else:
        # No cache — fetch fresh (slower, costs API calls)
        api = ProcoreAPI(access_token, company_id=x_company_id)
        try:
            existing_rfis = await api.get_rfis(project_id)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to fetch RFIs: {e}")

        rfi_lookup: dict[int, int] = {}
        for r in existing_rfis:
            if r.number is not None:
                try:
                    rfi_lookup[int(r.number)] = r.id
                except (ValueError, TypeError):
                    pass

    temp_dir = tempfile.mkdtemp(prefix="rfi_files_")
    manifest = []
    unmapped = 0

    for file in files:
        filename = os.path.basename(file.filename or "")
        if not filename:
            continue

        match = re.match(r"RFI-(\d+)", filename)
        if not match:
            unmapped += 1
            continue

        rfi_num = int(match.group(1))
        procore_rfi_id = rfi_lookup.get(rfi_num)
        if not procore_rfi_id:
            unmapped += 1
            continue

        temp_path = os.path.join(temp_dir, filename)
        content = await file.read()
        with open(temp_path, "wb") as f:
            f.write(content)

        manifest.append({
            "filename": filename,
            "temp_path": temp_path,
            "rfi_number": rfi_num,
            "procore_rfi_id": procore_rfi_id,
        })

    if not manifest:
        raise HTTPException(
            status_code=400,
            detail=f"No files matched existing RFIs. {unmapped} file(s) could not be mapped.",
        )

    # Database-backed job (same pattern as submittal file uploads)
    job_id = str(uuid.uuid4())
    file_job_store.create_job(
        job_id=job_id,
        project_id=str(project_id),
        company_id=str(x_company_id),
        session_id=x_auth_session,
        manifest=[{"filename": m["filename"], "rfi_number": m["rfi_number"]} for m in manifest],
        total_files=len(manifest),
    )

    asyncio.create_task(
        _process_rfi_file_job(
            job_id=job_id,
            project_id=project_id,
            manifest=manifest,
            access_token=access_token,
            company_id=x_company_id,
            temp_dir=temp_dir,
        )
    )

    return {
        "job_id": job_id,
        "status": "background",
        "total_files": len(manifest),
        "unmapped_files": unmapped,
    }


async def _process_rfi_file_job(
    job_id: str,
    project_id: int,
    manifest: list[dict],
    access_token: str,
    company_id: int,
    temp_dir: str,
):
    """Background job to upload files and attach to RFIs."""
    import shutil

    file_job_store.update_progress(job_id, status="running")

    api = ProcoreAPI(access_token, company_id=company_id)
    uploaded = 0
    errors = []

    try:
        for item in manifest:
            try:
                prostore_file_id = await api.upload_file(
                    project_id, item["temp_path"]
                )
                await asyncio.sleep(2)

                await asyncio.sleep(2)  # Spike limit: pause before attach

                await api.attach_file_to_rfi(
                    project_id, item["procore_rfi_id"], prostore_file_id
                )
                uploaded += 1
                logger.info(f"Attached {item['filename']} to RFI-{item['rfi_number']:04d}")

                file_job_store.update_progress(
                    job_id,
                    uploaded_files=uploaded,
                    result_summary={"uploaded": uploaded, "total": len(manifest), "errors": len(errors)},
                )

                await asyncio.sleep(5)  # Cooldown between files
            except RateLimitError as e:
                errors.append(f"Rate limited on {item['filename']}: {e}")
                await asyncio.sleep(60)
            except Exception as e:
                errors.append(f"Failed {item['filename']}: {e}")
                logger.error(f"Error uploading {item['filename']}: {e}")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    file_job_store.update_progress(
        job_id,
        status="completed",
        uploaded_files=uploaded,
        errors=errors,
        result_summary={"uploaded": uploaded, "total": len(manifest), "errors": len(errors)},
    )
    logger.info(
        f"RFI file job {job_id} completed: {uploaded} attached, {len(errors)} errors"
    )


@router.delete("/session/{session_id}")
async def delete_session(session_id: str):
    """Delete an RFI session."""
    if session_id in _rfi_sessions:
        del _rfi_sessions[session_id]
        return {"status": "deleted"}
    raise HTTPException(status_code=404, detail="Session not found")
