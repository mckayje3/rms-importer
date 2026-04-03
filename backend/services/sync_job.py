"""Background sync job processor.

Handles all sync operations (creates, updates, file uploads) in the background
so the HTTP request can return immediately with a job ID for polling.
"""
import asyncio
import logging
from typing import Optional

from database import file_job_store, baseline_store
from services.procore_api import ProcoreAPI, RateLimitError
from routers.auth import get_token

logger = logging.getLogger(__name__)

DELAY_BETWEEN_CALLS = 2  # seconds


def _get_custom_field(config_data: Optional[dict], field_name: str, default: str) -> str:
    """Get a custom field ID from config or fall back to default."""
    if config_data and "custom_fields" in config_data and field_name in config_data["custom_fields"]:
        return config_data["custom_fields"][field_name]
    return default


async def process_sync_job(
    job_id: str,
    project_id: int,
    company_id: int,
    session_id: str,
    rms_session_id: str,
    config_data: Optional[dict],
    apply_creates: bool = True,
    apply_updates: bool = True,
    apply_date_updates: bool = True,
    apply_file_uploads: bool = True,
) -> None:
    """
    Process the entire sync (creates + updates + files) in the background.

    Progress is tracked via file_job_store — the frontend polls for updates.
    """
    from models.mappings import get_status_id
    from services.sync_service import SyncService
    from services.spec_matcher import SpecMatcher
    from routers.rms_upload import get_rms_data
    created_ids: dict[str, int] = {}
    updated_keys: list[str] = []
    uploaded_files: dict[str, int] = {}
    errors: list[str] = []
    ops_completed = 0

    try:
        access_token = get_token(session_id)
        api = ProcoreAPI(access_token, company_id=company_id)
        rms_data = get_rms_data(rms_session_id)

        file_job_store.update_progress(job_id, status="running")

        # Rebuild the plan
        sync_service = SyncService(str(project_id), str(company_id), config=config_data)
        plan = sync_service.analyze(rms_data)

        # Custom field IDs
        PARAGRAPH_FIELD = _get_custom_field(config_data, "paragraph", "custom_field_598134325870420")
        INFO_FIELD = _get_custom_field(config_data, "info", "custom_field_598134325871364")
        QA_CODE_FIELD = _get_custom_field(config_data, "qa_code", "custom_field_598134325871360")
        QC_CODE_FIELD = _get_custom_field(config_data, "qc_code", "custom_field_598134325871359")
        CUSTOM_FIELD_MAP = {
            "info": INFO_FIELD,
            "paragraph": PARAGRAPH_FIELD,
            "qa_code": QA_CODE_FIELD,
            "qc_code": QC_CODE_FIELD,
        }

        # === CREATES ===
        if apply_creates and plan.creates:
            spec_matcher = None
            try:
                procore_sections = await api.get_spec_sections(project_id)
                spec_matcher = SpecMatcher(procore_sections)
                logger.info(f"Job {job_id}: loaded {len(procore_sections)} spec sections")
            except Exception as e:
                logger.warning(f"Job {job_id}: failed to load spec sections: {e}")

            sorted_creates = sorted(plan.creates, key=lambda c: (c.section, c.item_no, c.revision))

            for create in sorted_creates:
                try:
                    submittal_data: dict = {
                        "number": create.item_no,
                        "title": create.title,
                        "revision": create.revision,
                    }

                    if spec_matcher and create.section:
                        spec_id = spec_matcher.get_section_id(create.section)
                        if spec_id:
                            submittal_data["specification_section_id"] = spec_id

                    if create.revision > 0:
                        parent_key = f"{create.section}|{create.item_no}|0"
                        parent_id = created_ids.get(parent_key)
                        if not parent_id:
                            baseline_data = baseline_store.get_baseline(str(project_id))
                            if baseline_data:
                                parent_sub = baseline_data["data"]["submittals"].get(parent_key)
                                if parent_sub:
                                    parent_id = parent_sub.get("procore_id")
                        if parent_id:
                            submittal_data["source_submittal_log_id"] = parent_id

                    if create.type:
                        submittal_data["submittal_type"] = create.type

                    if create.status:
                        status_id = get_status_id(create.status, config_data)
                        if status_id:
                            submittal_data["status_id"] = status_id

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

                    await asyncio.sleep(DELAY_BETWEEN_CALLS)

                except RateLimitError as e:
                    errors.append(f"Rate limited creating {create.key}: {str(e)}")
                    logger.warning(f"Job {job_id}: rate limited on create, waiting 5 min")
                    await asyncio.sleep(300)
                    # Retry once
                    try:
                        result = await api.create_submittal(project_id, submittal_data)
                        if result and "id" in result:
                            created_ids[create.key] = result["id"]
                    except Exception as retry_err:
                        errors.append(f"Retry failed for create {create.key}: {str(retry_err)}")
                except Exception as e:
                    errors.append(f"Failed to create {create.key}: {str(e)}")

                ops_completed += 1
                file_job_store.update_progress(job_id, uploaded_files=ops_completed, errors=errors)

        # Save baseline after creates so progress isn't lost if the job dies during updates
        if created_ids:
            try:
                from models.sync import SyncMode
                if plan.mode == SyncMode.FULL_MIGRATION:
                    sync_service.save_baseline(rms_data, created_ids, uploaded_files)
                else:
                    sync_service.update_baseline_with_results(
                        rms_data, created_ids, updated_keys, uploaded_files,
                    )
                logger.info(f"Job {job_id}: baseline saved after {len(created_ids)} creates")
            except Exception as e:
                logger.warning(f"Job {job_id}: failed to save baseline after creates: {e}")

        # === UPDATES ===
        DATE_FIELDS = {"government_received", "government_returned"}
        if apply_updates and plan.updates:
            for update in plan.updates:
                # Filter out date changes if date updates are disabled
                changes = update.changes
                if not apply_date_updates:
                    changes = [c for c in changes if c.field not in DATE_FIELDS]
                if not changes:
                    ops_completed += 1
                    file_job_store.update_progress(job_id, uploaded_files=ops_completed, errors=errors)
                    continue

                try:
                    update_data = {}
                    custom_fields = {}

                    for change in changes:
                        field = change.field
                        value = change.new_value

                        if field == "status":
                            status_id = get_status_id(value, config_data)
                            if status_id:
                                update_data["status_id"] = status_id
                            else:
                                logger.warning(f"No status_id for '{value}' on {update.key}")
                        elif field in CUSTOM_FIELD_MAP:
                            custom_fields[CUSTOM_FIELD_MAP[field]] = value
                        else:
                            update_data[field] = value

                    if custom_fields:
                        update_data["custom_fields"] = custom_fields

                    await api.update_submittal(project_id, update.procore_id, update_data)
                    updated_keys.append(update.key)
                    await asyncio.sleep(DELAY_BETWEEN_CALLS)

                except RateLimitError as e:
                    errors.append(f"Rate limited updating {update.key}: {str(e)}")
                    logger.warning(f"Job {job_id}: rate limited on update, waiting 5 min")
                    await asyncio.sleep(300)
                    try:
                        await api.update_submittal(project_id, update.procore_id, update_data)
                        updated_keys.append(update.key)
                    except Exception as retry_err:
                        errors.append(f"Retry failed for {update.key}: {str(retry_err)}")
                except Exception as e:
                    errors.append(f"Failed to update {update.key}: {str(e)}")

                ops_completed += 1
                file_job_store.update_progress(job_id, uploaded_files=ops_completed, errors=errors)

                # Save baseline every 50 successful updates so progress isn't lost
                if len(updated_keys) > 0 and len(updated_keys) % 50 == 0:
                    try:
                        sync_service.update_baseline_with_results(
                            rms_data, created_ids, updated_keys, uploaded_files,
                        )
                        logger.info(f"Job {job_id}: baseline checkpoint at {len(updated_keys)} updates")
                    except Exception as e:
                        logger.warning(f"Job {job_id}: baseline checkpoint failed: {e}")

        # === FLAG DELETED ITEMS ===
        for flag in plan.flags:
            baseline_store.flag_item(str(project_id), flag.key, flag.procore_id, flag.reason)

        # === UPDATE BASELINE ===
        try:
            from models.sync import SyncMode
            if plan.mode == SyncMode.FULL_MIGRATION:
                sync_service.save_baseline(rms_data, created_ids, uploaded_files)
            else:
                sync_service.update_baseline_with_results(
                    rms_data, created_ids, updated_keys, uploaded_files,
                )
        except Exception as e:
            errors.append(f"Failed to update baseline: {str(e)}")

        # Record in history
        baseline_store.add_sync_history(
            str(project_id),
            plan.mode.value,
            creates=len(created_ids),
            updates=len(updated_keys),
            file_uploads=len(uploaded_files),
            errors=errors,
            summary=f"{len(created_ids)} created, {len(updated_keys)} updated, {len(uploaded_files)} files",
        )

        summary = {
            "created": len(created_ids),
            "updated": len(updated_keys),
            "files": len(uploaded_files),
            "uploaded": ops_completed,
            "total": ops_completed,
            "errors": len(errors),
        }
        final_status = "completed" if (created_ids or updated_keys or uploaded_files or not errors) else "failed"
        file_job_store.update_progress(
            job_id,
            status=final_status,
            uploaded_files=ops_completed,
            errors=errors,
            result_summary=summary,
        )

        logger.info(
            f"Sync job {job_id} {final_status}: "
            f"{len(created_ids)} created, {len(updated_keys)} updated, {len(uploaded_files)} files"
        )

    except Exception as e:
        logger.error(f"Sync job {job_id} failed: {e}")
        errors.append(f"Job failed: {e}")
        file_job_store.update_progress(
            job_id,
            status="failed",
            errors=errors,
            result_summary={
                "created": len(created_ids),
                "updated": len(updated_keys),
                "files": len(uploaded_files),
                "uploaded": ops_completed,
                "total": 0,
                "errors": len(errors),
            },
        )


# Keep old function for backwards compatibility with any in-flight jobs
async def process_sync_updates(
    job_id: str,
    project_id: int,
    company_id: int,
    session_id: str,
    updates_data: list[dict],
    config_data: Optional[dict],
    created_ids: dict[str, int],
    rms_session_id: str,
) -> None:
    """Legacy: process only updates. Kept for in-flight jobs."""
    await process_sync_job(
        job_id=job_id,
        project_id=project_id,
        company_id=company_id,
        session_id=session_id,
        rms_session_id=rms_session_id,
        config_data=config_data,
        apply_creates=False,
        apply_updates=True,
        apply_file_uploads=False,
    )
