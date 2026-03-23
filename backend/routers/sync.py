"""Sync endpoints for incremental RMS to Procore updates."""
import os
import asyncio
from pathlib import Path
from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel
from typing import Optional

from services.sync_service import SyncService
from services.procore_api import ProcoreAPI
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
from config import get_settings

router = APIRouter()


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

    import logging
    logger = logging.getLogger(__name__)
    logger.warning(f"Sync analyze: session has {rms_data.submittal_count} submittals, {len(rms_data.transmittal_entries)} log entries, {len(rms_data.transmittal_report)} report entries")

    # Create sync service and analyze
    service = SyncService(str(project_id), str(request.company_id))
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

    # Create services
    sync_service = SyncService(str(project_id), str(company_id))
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
    # Custom field IDs for Procore
    PARAGRAPH_FIELD = "custom_field_598134325870420"
    INFO_FIELD = "custom_field_598134325871364"

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

                await asyncio.sleep(1)  # Rate limit: ~3600 calls/hour

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

                    # Map field names to Procore API fields
                    if field in ["qa_code", "qc_code", "info"]:
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

            # Upload to each target submittal
            uploaded_to_any = False
            for submittal_key in file_action.submittal_keys:
                procore_id = key_to_procore_id.get(submittal_key)
                if not procore_id:
                    errors.append(f"No Procore ID for {submittal_key}, skipping file {file_action.filename}")
                    continue

                try:
                    prostore_id = await api.upload_file_to_submittal(
                        project_id, procore_id, file_path
                    )
                    if prostore_id:
                        uploaded_to_any = True
                    await asyncio.sleep(1)  # Rate limit protection
                except Exception as e:
                    errors.append(f"Failed to upload {file_action.filename} to {submittal_key}: {str(e)}")

            if uploaded_to_any:
                uploaded_files[file_action.filename] = 1  # Track as uploaded

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

    return SyncExecuteResponse(
        status="completed" if not errors else "partial",
        created=len(created_ids),
        updated=len(updated_keys),
        files_uploaded=len(uploaded_files),
        flagged=flagged_count,
        errors=errors,
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
