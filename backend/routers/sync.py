"""Sync endpoints for incremental RMS to Procore updates."""
import os
import asyncio
import json
import logging
import shutil
import tempfile
import uuid
from fastapi import APIRouter, HTTPException, Header, UploadFile, File, Form
from pydantic import BaseModel, ValidationError
from typing import Optional

from services.sync_service import SyncService
from services.procore_api import ProcoreAPI
from models.sync import (
    SyncPlan,
    SyncAnalysisResponse,
    SyncExecuteRequest,
    SyncExecuteResponse,
    BaselineInfo,
)
from routers.rms_upload import get_rms_data
from routers.auth import get_token
from database import baseline_store, file_job_store
from database import project_config_store

router = APIRouter()
logger = logging.getLogger(__name__)


class AnalyzeRequest(BaseModel):
    """Request to analyze RMS data for sync."""
    session_id: str
    project_id: int
    company_id: int
    file_list: list[str] = []  # List of filenames in RMS Files folder


@router.get("/projects/{project_id}/baseline")
async def get_baseline_info(
    project_id: int,
) -> BaselineInfo:
    """
    Get information about the stored baseline for a project.

    Returns whether a baseline exists, last sync date, and counts.
    """
    service = SyncService(str(project_id), "")
    return service.get_baseline_info()


@router.delete("/projects/{project_id}/baseline")
async def delete_baseline(
    project_id: int,
) -> dict:
    """
    Delete the stored baseline for a project.

    Use this to reset and do a fresh full migration.
    """
    deleted = baseline_store.delete_baseline(str(project_id))
    return {
        "status": "deleted" if deleted else "not_found",
        "project_id": project_id,
    }


class BootstrapRequest(BaseModel):
    """Request to bootstrap a baseline from existing Procore data."""
    session_id: str
    company_id: int


@router.post("/projects/{project_id}/bootstrap")
async def bootstrap_baseline(
    project_id: int,
    request: BootstrapRequest,
    x_auth_session: str = Header(..., alias="X-Auth-Session"),
):
    """
    Bootstrap a baseline by matching RMS data against existing Procore submittals.

    Use this when the project was migrated via PowerShell scripts and doesn't
    have a web-app baseline yet. Matches by spec section + item number + revision.
    No submittals are created or modified — only the baseline is saved.
    """
    try:
        access_token = get_token(x_auth_session)
    except HTTPException:
        raise HTTPException(status_code=401, detail="Invalid auth session")

    try:
        rms_data = get_rms_data(request.session_id)
    except HTTPException:
        raise HTTPException(status_code=404, detail="RMS session not found. Upload RMS files first.")

    # Load project config
    _project_config = project_config_store.get_config(str(project_id))
    _config_data = _project_config["config_data"] if _project_config else None

    # Fetch all existing Procore submittals
    api = ProcoreAPI(access_token, company_id=request.company_id)
    procore_submittals = await api.get_submittals(project_id)

    # Build lookup: (section, item_no, revision) -> procore_id
    procore_lookup: dict[str, int] = {}
    for sub in procore_submittals:
        if sub.specification_section:
            key = f"{sub.specification_section.number}|{sub.number}|{sub.revision}"
            procore_lookup[key] = sub.id

    logger.warning(f"Bootstrap: {len(procore_submittals)} Procore submittals, {len(procore_lookup)} unique keys")

    # Build RMS data into stored format and match against Procore
    service = SyncService(str(project_id), str(request.company_id), config=_config_data)
    from services.date_lookup import DateLookup
    date_lookup = DateLookup(rms_data.transmittal_report)
    info_lookup = service._build_info_lookup(rms_data)
    rms_submittals = service._rms_to_stored_format(rms_data, date_lookup, info_lookup)

    # Match RMS keys to Procore IDs
    matched = 0
    unmatched = 0
    procore_ids: dict[str, int] = {}
    for key in rms_submittals:
        if key in procore_lookup:
            procore_ids[key] = procore_lookup[key]
            matched += 1
        else:
            unmatched += 1

    logger.warning(f"Bootstrap: matched={matched}, unmatched={unmatched}")

    # Fetch existing files from Procore Documents folder
    uploaded_files: dict[str, int] = {}
    try:
        import re as _re
        from config import get_settings
        settings = get_settings()
        if settings.procore_upload_folder_id:
            filenames = await api.list_folder_files(project_id, settings.procore_upload_folder_id)
            for name in filenames:
                # Store both original and cleaned name (strip timestamp prefix from PS uploads)
                uploaded_files[name] = 1
                cleaned = _re.sub(r"^\d{8}_\d{6}_", "", name)
                if cleaned != name:
                    uploaded_files[cleaned] = 1
            logger.warning(f"Bootstrap: found {len(filenames)} files in upload folder ({len(uploaded_files)} with cleaned names)")
    except Exception as e:
        logger.warning(f"Bootstrap: failed to list existing files: {e}")

    # Save baseline
    service.save_baseline(rms_data, procore_ids, uploaded_files)

    return {
        "status": "bootstrapped",
        "matched": matched,
        "unmatched": unmatched,
        "total_rms": len(rms_submittals),
        "total_procore": len(procore_submittals),
        "files_found": len(uploaded_files),
    }


@router.post("/projects/{project_id}/analyze")
async def analyze_sync(
    project_id: int,
    request: AnalyzeRequest,
) -> SyncAnalysisResponse:
    """
    Analyze RMS data against stored baseline.

    Returns a sync plan showing what will be created, updated, or flagged.
    If no baseline exists, returns a full migration plan.
    """
    # Get parsed RMS data from session
    try:
        rms_data = get_rms_data(request.session_id)
    except HTTPException:
        raise HTTPException(
            status_code=404,
            detail="RMS session not found. Upload RMS files first.",
        )

    file_list = request.file_list or []

    logger.warning(f"Sync analyze: session has {rms_data.submittal_count} submittals, {len(rms_data.transmittal_report)} report entries")

    # Load project config for status mapping
    _project_config = project_config_store.get_config(str(project_id))
    _config_data = _project_config["config_data"] if _project_config else None

    # Create sync service and analyze
    service = SyncService(str(project_id), str(request.company_id), config=_config_data)
    baseline_info = service.get_baseline_info()
    plan = service.analyze(rms_data, file_list)

    logger.warning(f"Sync plan: {plan.summary}, creates={len(plan.creates)}, updates={len(plan.updates)}, flags={len(plan.flags)}")

    return SyncAnalysisResponse(
        baseline=baseline_info,
        plan=plan,
        summary=plan.summary,
    )


@router.post("/projects/{project_id}/execute")
async def execute_sync(
    project_id: int,
    request: SyncExecuteRequest,
    x_auth_session: str = Header(..., alias="X-Auth-Session"),
    company_id: int = Header(..., alias="X-Company-Id"),
) -> SyncExecuteResponse:
    """
    Execute the sync plan in the background.

    Creates a background job and returns immediately with a job_id.
    The job handles creates, updates, file uploads, and baseline updates.
    Poll /file-jobs/{job_id} for progress.
    """
    # Validate auth
    try:
        get_token(x_auth_session)
    except HTTPException:
        raise HTTPException(status_code=401, detail="Invalid auth session")

    # Validate RMS session exists
    try:
        rms_data = get_rms_data(request.session_id)
    except HTTPException:
        raise HTTPException(
            status_code=404,
            detail="RMS session not found. Upload RMS files first.",
        )

    # Load project config
    _project_config = project_config_store.get_config(str(project_id))
    _config_data = _project_config["config_data"] if _project_config else None

    # Generate the plan to count total operations
    sync_service = SyncService(str(project_id), str(company_id), config=_config_data)

    plan = sync_service.analyze(
        rms_data,
        repair_custom_fields=request.repair_custom_fields,
    )

    # Count total operations for progress tracking. This endpoint is the
    # legacy "no files" entry point; /execute-all handles files.
    total_ops = 0
    if request.apply_creates:
        total_ops += len(plan.creates)
    if request.apply_updates:
        total_ops += len(plan.updates)

    if total_ops == 0:
        # Nothing to do — return immediately
        return SyncExecuteResponse(
            status="completed",
            created=0,
            updated=0,
            files_uploaded=0,
            flagged=len(plan.flags),
            errors=[],
            baseline_updated=True,
            update_job_id=None,
        )

    # Create background job
    from services.sync_job import process_sync_job

    job_id = str(uuid.uuid4())
    file_job_store.create_job(
        job_id=job_id,
        project_id=str(project_id),
        company_id=str(company_id),
        session_id=x_auth_session,
        manifest=[],  # Not needed — job rebuilds plan from RMS data
        total_files=total_ops,
        job_type="submittals",
    )

    asyncio.create_task(process_sync_job(
        job_id=job_id,
        project_id=project_id,
        company_id=company_id,
        session_id=x_auth_session,
        rms_session_id=request.session_id,
        config_data=_config_data,
        apply_creates=request.apply_creates,
        apply_updates=request.apply_updates,
        apply_date_updates=request.apply_date_updates,
        repair_custom_fields=request.repair_custom_fields,
    ))

    logger.info(
        f"Sync job {job_id} created: {len(plan.creates)} creates, "
        f"{len(plan.updates)} updates, {len(plan.file_uploads)} files"
    )

    return SyncExecuteResponse(
        status="background",
        created=0,
        updated=0,
        files_uploaded=0,
        flagged=len(plan.flags),
        errors=[],
        baseline_updated=False,
        update_job_id=job_id,
    )


@router.get("/projects/{project_id}/history")
async def get_sync_history(
    project_id: int,
    limit: int = 10,
) -> dict:
    """Get sync history for a project."""
    history = baseline_store.get_sync_history(str(project_id), limit)
    return {
        "project_id": project_id,
        "history": history,
    }


@router.get("/projects/{project_id}/flagged")
async def get_flagged_items(
    project_id: int,
    include_resolved: bool = False,
) -> dict:
    """Get items flagged for review (removed from RMS)."""
    items = baseline_store.get_flagged_items(str(project_id), include_resolved)
    return {
        "project_id": project_id,
        "count": len(items),
        "items": items,
    }


class ResolveFlagRequest(BaseModel):
    """Request to resolve a flagged item."""
    resolution: str  # "closed_in_procore", "re_added_to_rms", "ignore"


@router.post("/projects/{project_id}/flagged/{item_id}/resolve")
async def resolve_flagged_item(
    project_id: int,
    item_id: int,
    request: ResolveFlagRequest,
) -> dict:
    """Mark a flagged item as resolved."""
    success = baseline_store.resolve_flagged_item(item_id, request.resolution)
    return {
        "status": "resolved" if success else "not_found",
        "item_id": item_id,
        "resolution": request.resolution,
    }


class AddFilesRequest(BaseModel):
    """Request to add existing filenames to the baseline."""
    filenames: list[str]


@router.post("/projects/{project_id}/add-existing-files")
async def add_existing_files(
    project_id: int,
    request: AddFilesRequest,
) -> dict:
    """Add filenames to the baseline as already-uploaded (no actual upload)."""
    baseline = baseline_store.get_baseline(str(project_id))
    if not baseline:
        raise HTTPException(status_code=404, detail="No baseline found for this project")

    data = baseline["data"]
    added = 0
    for filename in request.filenames:
        if filename not in data.get("files", {}):
            data.setdefault("files", {})[filename] = {
                "filename": filename,
                "attached_to": [],
                "uploaded": True,
                "procore_file_id": None,
            }
            added += 1

    baseline_store.save_baseline(
        str(project_id),
        baseline["company_id"],
        data,
    )

    return {
        "status": "ok",
        "added": added,
        "already_existed": len(request.filenames) - added,
        "total_files": len(data.get("files", {})),
    }


# === File Upload Endpoints ===


class FileFilterRequest(BaseModel):
    """Request to filter filenames against baseline."""
    session_id: str
    filenames: list[str]


@router.post("/projects/{project_id}/filter-files")
async def filter_files(
    project_id: int,
    request: FileFilterRequest,
) -> dict:
    """
    Check which files are new vs already uploaded.

    A file is "already uploaded" only when the baseline has it AND its
    `attached_to` set covers every submittal the Transmittal Log maps it to.
    A file with the right name in the baseline but missing some attachments
    (e.g. a new revision added after the file was first uploaded) is treated
    as "new" so the sync job re-runs the upload+attach phase for it. The
    upload itself is cheap — Procore returns the existing prostore_file_id
    via the dedupe path — and the per-submittal attach call is idempotent.

    No Procore API calls — fast, local-only operation.
    """
    # Get baseline
    baseline = baseline_store.get_baseline(str(project_id))
    baseline_files: dict[str, dict] = {}
    if baseline and baseline.get("data", {}).get("files"):
        baseline_files = baseline["data"]["files"]

    # Get RMS data for file mapping
    try:
        rms_data = get_rms_data(request.session_id)
    except HTTPException:
        raise HTTPException(
            status_code=404,
            detail="RMS session not found. Upload RMS files first.",
        )

    _project_config = project_config_store.get_config(str(project_id))
    _config_data = _project_config["config_data"] if _project_config else None
    sync_service = SyncService(str(project_id), "", config=_config_data)

    # Map every requested filename against the Transmittal Log; the result
    # tells us which submittals each file is expected to attach to.
    file_to_keys = sync_service.map_files_to_submittals(
        request.filenames, rms_data,
    )

    new_files: list[str] = []
    already_uploaded: list[str] = []
    unmapped_files: list[str] = []
    for f in request.filenames:
        expected_keys = file_to_keys.get(f)
        if not expected_keys:
            unmapped_files.append(f)
            continue
        baseline_entry = baseline_files.get(f)
        if not baseline_entry:
            new_files.append(f)
            continue
        attached_to = set(baseline_entry.get("attached_to") or [])
        if set(expected_keys).issubset(attached_to):
            already_uploaded.append(f)
        else:
            # File is in Procore but missing some attachments — re-run it.
            new_files.append(f)

    return {
        "new_files": new_files,
        "already_uploaded": already_uploaded,
        "unmapped_files": unmapped_files,
        "total_checked": len(request.filenames),
    }


@router.post("/projects/{project_id}/execute-all")
async def execute_sync_with_files(
    project_id: int,
    request_json: str = Form(...),
    files: list[UploadFile] = File(default=[]),
    x_auth_session: str = Header(..., alias="X-Auth-Session"),
    company_id: int = Header(..., alias="X-Company-Id"),
) -> SyncExecuteResponse:
    """
    Execute a sync plan with attached file uploads in one orchestrated job.

    Phase order: creates → upload+attach files → updates → save baseline.
    Files are saved to a temp dir up front; the background job streams them
    to Procore and cleans up when done.
    """
    try:
        get_token(x_auth_session)
    except HTTPException:
        raise HTTPException(status_code=401, detail="Invalid auth session")

    try:
        request = SyncExecuteRequest(**json.loads(request_json))
    except (json.JSONDecodeError, ValidationError) as e:
        raise HTTPException(status_code=400, detail=f"Invalid request_json: {e}")

    try:
        rms_data = get_rms_data(request.session_id)
    except HTTPException:
        raise HTTPException(
            status_code=404,
            detail="RMS session not found. Upload RMS files first.",
        )

    _project_config = project_config_store.get_config(str(project_id))
    _config_data = _project_config["config_data"] if _project_config else None

    sync_service = SyncService(str(project_id), str(company_id), config=_config_data)
    plan = sync_service.analyze(rms_data, repair_custom_fields=request.repair_custom_fields)

    # Save uploaded file bytes to a temp dir for the background job to consume.
    temp_dir = tempfile.mkdtemp(prefix="rms_unified_") if files else None
    saved_files: list[dict] = []
    if files:
        try:
            for upload_file in files:
                filename = os.path.basename(upload_file.filename)
                file_path = os.path.join(temp_dir, filename)
                content = await upload_file.read()
                with open(file_path, "wb") as f:
                    f.write(content)
                saved_files.append({"filename": filename, "temp_path": file_path})
        except Exception as e:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise HTTPException(status_code=500, detail=f"Failed to save files: {e}")

    # Map filenames to submittal keys; drop unmapped files (they have nowhere to attach).
    manifest: list[dict] = []
    if saved_files:
        filenames = [f["filename"] for f in saved_files]
        file_to_keys = sync_service.map_files_to_submittals(filenames, rms_data)
        for item in saved_files:
            keys = file_to_keys.get(item["filename"], [])
            if keys:
                manifest.append({
                    "filename": item["filename"],
                    "temp_path": item["temp_path"],
                    "submittal_keys": keys,
                })

    total_ops = 0
    if request.apply_creates:
        total_ops += len(plan.creates)
    if request.apply_updates:
        total_ops += len(plan.updates)
    total_ops += len(manifest)

    if total_ops == 0:
        if temp_dir:
            shutil.rmtree(temp_dir, ignore_errors=True)
        return SyncExecuteResponse(
            status="completed",
            created=0,
            updated=0,
            files_uploaded=0,
            flagged=len(plan.flags),
            errors=[],
            baseline_updated=True,
            update_job_id=None,
        )

    from services.sync_job import process_sync_job

    job_id = str(uuid.uuid4())
    file_job_store.create_job(
        job_id=job_id,
        project_id=str(project_id),
        company_id=str(company_id),
        session_id=x_auth_session,
        manifest=manifest,
        total_files=total_ops,
        job_type="submittals",
    )

    asyncio.create_task(process_sync_job(
        job_id=job_id,
        project_id=project_id,
        company_id=company_id,
        session_id=x_auth_session,
        rms_session_id=request.session_id,
        config_data=_config_data,
        apply_creates=request.apply_creates,
        apply_updates=request.apply_updates,
        apply_date_updates=request.apply_date_updates,
        repair_custom_fields=request.repair_custom_fields,
        file_manifest=manifest,
    ))

    logger.info(
        f"Unified sync job {job_id} created: {len(plan.creates)} creates, "
        f"{len(plan.updates)} updates, {len(manifest)} files "
        f"(skipped {len(saved_files) - len(manifest)} unmapped)"
    )

    return SyncExecuteResponse(
        status="background",
        created=0,
        updated=0,
        files_uploaded=0,
        flagged=len(plan.flags),
        errors=[],
        baseline_updated=False,
        update_job_id=job_id,
    )


@router.get("/projects/{project_id}/file-jobs/{job_id}")
async def get_file_job_status(
    project_id: int,
    job_id: str,
) -> dict:
    """Get the status of a file upload job."""
    job = file_job_store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job["project_id"] != str(project_id):
        raise HTTPException(status_code=404, detail="Job not found")

    return {
        "id": job["id"],
        "status": job["status"],
        "total_files": job["total_files"],
        "uploaded_files": job["uploaded_files"],
        "errors": job["errors"],
        "created_at": job["created_at"],
        "started_at": job["started_at"],
        "completed_at": job["completed_at"],
        "result_summary": job["result_summary"],
        "job_type": job.get("job_type"),
    }


@router.get("/projects/{project_id}/file-jobs")
async def list_file_jobs(
    project_id: int,
    limit: int = 10,
) -> dict:
    """List recent file upload jobs for a project."""
    jobs = file_job_store.get_jobs_for_project(str(project_id), limit)
    return {
        "project_id": project_id,
        "jobs": jobs,
    }
