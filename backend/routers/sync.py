"""Sync endpoints for incremental RMS to Procore updates."""
import os
import asyncio
import logging
from pathlib import Path
from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel
from typing import Optional

from services.sync_service import SyncService
from services.procore_api import ProcoreAPI, RateLimitError
from models.sync import (
    SyncPlan,
    SyncAnalysisResponse,
    SyncExecuteRequest,
    SyncExecuteResponse,
    BaselineInfo,
    SyncMode,
)
from routers.rms_upload import get_rms_data
from routers.auth import get_token
from database import baseline_store
from database import project_config_store
from config import get_settings
from models.mappings import get_status_id

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

    # Build file list: use provided list, or scan RMS_FILES_PATH if configured
    file_list = request.file_list
    if not file_list:
        settings = get_settings()
        if settings.rms_files_path and os.path.isdir(settings.rms_files_path):
            file_list = [
                f for f in os.listdir(settings.rms_files_path)
                if os.path.isfile(os.path.join(settings.rms_files_path, f))
                and not f.startswith("~$")
            ]

    logger.warning(f"Sync analyze: session has {rms_data.submittal_count} submittals, {len(rms_data.transmittal_entries)} log entries, {len(rms_data.transmittal_report)} report entries")

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
    Execute the sync plan.

    Creates new submittals, updates existing ones, and uploads files.
    Updates the stored baseline after successful completion.
    """
    # Get auth token
    try:
        access_token = get_token(x_auth_session)
    except HTTPException:
        raise HTTPException(status_code=401, detail="Invalid auth session")

    # Get RMS data
    try:
        rms_data = get_rms_data(request.session_id)
    except HTTPException:
        raise HTTPException(
            status_code=404,
            detail="RMS session not found. Upload RMS files first.",
        )

    # Load project-specific config (falls back to defaults if not configured)
    _project_config = project_config_store.get_config(str(project_id))
    _config_data = _project_config["config_data"] if _project_config else None

    # Create services
    sync_service = SyncService(str(project_id), str(company_id), config=_config_data)
    api = ProcoreAPI(access_token, company_id=company_id)

    # Build file list for plan generation
    settings = get_settings()
    file_list: list[str] = []
    if settings.rms_files_path and os.path.isdir(settings.rms_files_path):
        file_list = [
            f for f in os.listdir(settings.rms_files_path)
            if os.path.isfile(os.path.join(settings.rms_files_path, f))
            and not f.startswith("~$")
        ]

    # Generate the plan
    plan = sync_service.analyze(rms_data, file_list)

    # Track results
    created_ids: dict[str, int] = {}
    updated_keys: list[str] = []
    uploaded_files: dict[str, int] = {}
    errors: list[str] = []

    # Execute creates

    # Custom field IDs — from project config or Dobbins defaults
    PARAGRAPH_FIELD = (
        _config_data["custom_fields"]["paragraph"]
        if _config_data and "custom_fields" in _config_data and "paragraph" in _config_data["custom_fields"]
        else "custom_field_598134325870420"
    )
    INFO_FIELD = (
        _config_data["custom_fields"]["info"]
        if _config_data and "custom_fields" in _config_data and "info" in _config_data["custom_fields"]
        else "custom_field_598134325871364"
    )

    # Procore submittal type name -> id mapping (fetched lazily)
    type_id_cache: dict[str, int] = {}
    spec_section_cache: dict[str, int] = {}

    if request.apply_creates and plan.creates:
        # Pre-fetch Procore submittals to build spec section and type lookups
        try:
            existing_submittals = await api.get_submittals(project_id)
            for sub in existing_submittals:
                if sub.specification_section:
                    spec_section_cache[sub.specification_section.number] = sub.specification_section.id
        except Exception:
            pass  # Will create without spec section if lookup fails

        # Sort: revision 0 first so parents exist before revisions
        sorted_creates = sorted(plan.creates, key=lambda c: (c.section, c.item_no, c.revision))

        for create in sorted_creates:
            try:
                # Build submittal data
                submittal_data: dict = {
                    "number": create.item_no,
                    "title": create.title,
                    "revision": create.revision,
                }

                # Add spec section
                if create.section in spec_section_cache:
                    submittal_data["specification_section_id"] = spec_section_cache[create.section]

                # For revisions, link to parent via source_submittal_log_id
                if create.revision > 0:
                    parent_key = f"{create.section}|{create.item_no}|0"
                    parent_id = created_ids.get(parent_key)
                    if not parent_id:
                        # Look up from baseline
                        baseline_data = baseline_store.get_baseline(str(project_id))
                        if baseline_data:
                            parent_sub = baseline_data["data"]["submittals"].get(parent_key)
                            if parent_sub:
                                parent_id = parent_sub.get("procore_id")
                    if parent_id:
                        submittal_data["source_submittal_log_id"] = parent_id

                # Add type (inherit from parent for revisions — already set on CreateAction)
                if create.type:
                    submittal_data["submittal_type"] = create.type

                # Add custom fields (Paragraph, Info — inherited from parent for revisions)
                custom_fields = {}
                if create.paragraph:
                    custom_fields[PARAGRAPH_FIELD] = create.paragraph
                if create.info:
                    custom_fields[INFO_FIELD] = create.info
                if custom_fields:
                    submittal_data["custom_fields"] = custom_fields

                result = await api.create_submittal(project_id, submittal_data)
                if result and "id" in result:
                    created_ids[create.key] = result["id"]

                await asyncio.sleep(2)  # Rate limit protection

            except RateLimitError as e:
                errors.append(f"Rate limited creating {create.key}: {str(e)}")
                break  # Stop creating — no point continuing if rate limited
            except Exception as e:
                errors.append(f"Failed to create {create.key}: {str(e)}")

    # Execute updates
    if request.apply_updates and plan.updates:
        for update in plan.updates:
            try:
                # Build update payload from changes
                update_data = {}
                custom_fields = {}

                for change in update.changes:
                    field = change.field
                    value = change.new_value

                    if field == "status":
                        # Status requires status_id for the Procore API
                        status_id = get_status_id(value, _config_data)
                        if status_id:
                            update_data["status_id"] = status_id
                        else:
                            logger.warning(f"No status_id found for '{value}' on {update.key}, skipping status update")
                    elif field in ["qa_code", "qc_code", "info"]:
                        # Custom fields
                        custom_fields[field] = value
                    elif field == "contractor_prepared":
                        update_data["custom_fields"] = update_data.get("custom_fields", {})
                        # TODO: Map to actual custom field ID
                    else:
                        update_data[field] = value

                if custom_fields:
                    update_data["custom_fields"] = custom_fields

                await api.update_submittal(project_id, update.procore_id, update_data)
                updated_keys.append(update.key)
                await asyncio.sleep(2)  # Rate limit protection

            except RateLimitError as e:
                errors.append(f"Rate limited updating {update.key}: {str(e)}")
                break
            except Exception as e:
                errors.append(f"Failed to update {update.key}: {str(e)}")

    # Execute file uploads
    if request.apply_file_uploads and plan.file_uploads and settings.rms_files_path:
        # Build a lookup from submittal key to procore_id (from baseline + newly created)
        baseline = baseline_store.get_baseline(str(project_id))
        baseline_subs = baseline["data"]["submittals"] if baseline else {}

        key_to_procore_id: dict[str, int] = {}
        for key, sub in baseline_subs.items():
            if sub.get("procore_id"):
                key_to_procore_id[key] = sub["procore_id"]
        # Add newly created submittals
        for key, pid in created_ids.items():
            key_to_procore_id[key] = pid

        for file_action in plan.file_uploads:
            file_path = os.path.join(settings.rms_files_path, file_action.filename)
            if not os.path.isfile(file_path):
                errors.append(f"File not found: {file_action.filename}")
                continue

            # Resolve target Procore IDs
            target_ids = []
            for submittal_key in file_action.submittal_keys:
                procore_id = key_to_procore_id.get(submittal_key)
                if not procore_id:
                    errors.append(f"No Procore ID for {submittal_key}, skipping file {file_action.filename}")
                else:
                    target_ids.append(procore_id)

            if not target_ids:
                continue

            # Upload file ONCE (steps 1-4: S3 + create doc + get prostore ID)
            try:
                prostore_file_id = await api.upload_file(project_id, file_path)
                await asyncio.sleep(2)  # Rate limit protection
            except RateLimitError as e:
                errors.append(f"Rate limited uploading {file_action.filename}: {str(e)}")
                break  # Stop all uploads
            except Exception as e:
                errors.append(f"Failed to upload {file_action.filename}: {str(e)}")
                continue

            # Attach to ALL target submittals (steps 5-6 only: GET + PATCH each)
            attached_any = False
            hit_rate_limit = False
            for procore_id in target_ids:
                try:
                    await api.attach_file_to_submittal(
                        project_id, procore_id, prostore_file_id
                    )
                    attached_any = True
                    await asyncio.sleep(2)  # Rate limit protection
                except RateLimitError as e:
                    errors.append(f"Rate limited attaching {file_action.filename}: {str(e)}")
                    hit_rate_limit = True
                    break
                except Exception as e:
                    errors.append(f"Failed to attach {file_action.filename} to submittal {procore_id}: {str(e)}")

            if attached_any:
                uploaded_files[file_action.filename] = 1  # Track as uploaded

            if hit_rate_limit:
                break  # Stop all uploads

    # Flag deleted items
    flagged_count = 0
    for flag in plan.flags:
        baseline_store.flag_item(
            str(project_id),
            flag.key,
            flag.procore_id,
            flag.reason,
        )
        flagged_count += 1

    # Update baseline with results
    if plan.mode == SyncMode.FULL_MIGRATION:
        sync_service.save_baseline(rms_data, created_ids, uploaded_files)
    else:
        sync_service.update_baseline_with_results(
            rms_data,
            created_ids,
            updated_keys,
            uploaded_files,
        )

    # Record in history
    baseline_store.add_sync_history(
        str(project_id),
        plan.mode.value,
        creates=len(created_ids),
        updates=len(updated_keys),
        file_uploads=len(uploaded_files),
        errors=errors,
        summary=plan.summary,
    )

    # Determine status
    was_rate_limited = api.rate_limit_hits > 0
    rate_limit_errors = [e for e in errors if "Rate limited" in e]
    other_errors = [e for e in errors if "Rate limited" not in e]

    if rate_limit_errors and not other_errors:
        status = "rate_limited"
    elif errors:
        status = "partial"
    else:
        status = "completed"

    rate_limit_msg = None
    if was_rate_limited:
        rate_limit_msg = (
            f"Hit Procore rate limit {api.rate_limit_hits} time(s). "
            f"{len(rate_limit_errors)} operation(s) failed after retries. "
            "Run sync again to resume where it left off."
        )

    return SyncExecuteResponse(
        status=status,
        created=len(created_ids),
        updated=len(updated_keys),
        files_uploaded=len(uploaded_files),
        flagged=flagged_count,
        errors=errors,
        rate_limited=was_rate_limited,
        rate_limit_message=rate_limit_msg,
        baseline_updated=True,
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
