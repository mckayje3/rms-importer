"""Background sync update job processor.

Handles applying submittal updates to Procore in the background
when the update count is too large for an inline HTTP request.
"""
import asyncio
import json
import logging
from typing import Optional

from database import file_job_store, baseline_store
from services.procore_api import ProcoreAPI, RateLimitError
from routers.auth import get_token

logger = logging.getLogger(__name__)

DELAY_BETWEEN_UPDATES = 2  # seconds


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
    """
    Process sync updates in the background.

    Each update_data entry: {key, procore_id, changes: [{field, old_value, new_value}]}
    """
    from models.mappings import get_status_id

    uploaded_files: dict[str, int] = {}
    updated_keys: list[str] = []
    errors: list[str] = []

    try:
        access_token = get_token(session_id)
        api = ProcoreAPI(access_token, company_id=company_id)

        file_job_store.update_progress(job_id, status="running")

        # Custom field IDs
        PARAGRAPH_FIELD = (
            config_data["custom_fields"]["paragraph"]
            if config_data and "custom_fields" in config_data and "paragraph" in config_data["custom_fields"]
            else "custom_field_598134325870420"
        )
        INFO_FIELD = (
            config_data["custom_fields"]["info"]
            if config_data and "custom_fields" in config_data and "info" in config_data["custom_fields"]
            else "custom_field_598134325871364"
        )
        QA_CODE_FIELD = (
            config_data["custom_fields"]["qa_code"]
            if config_data and "custom_fields" in config_data and "qa_code" in config_data["custom_fields"]
            else "custom_field_598134325871360"
        )
        QC_CODE_FIELD = (
            config_data["custom_fields"]["qc_code"]
            if config_data and "custom_fields" in config_data and "qc_code" in config_data["custom_fields"]
            else "custom_field_598134325871359"
        )
        CUSTOM_FIELD_MAP = {
            "info": INFO_FIELD,
            "paragraph": PARAGRAPH_FIELD,
            "qa_code": QA_CODE_FIELD,
            "qc_code": QC_CODE_FIELD,
        }

        for i, update in enumerate(updates_data):
            try:
                update_data = {}
                custom_fields = {}

                for change in update["changes"]:
                    field = change["field"]
                    value = change["new_value"]

                    if field == "status":
                        status_id = get_status_id(value, config_data)
                        if status_id:
                            update_data["status_id"] = status_id
                    elif field in CUSTOM_FIELD_MAP:
                        custom_fields[CUSTOM_FIELD_MAP[field]] = value
                    else:
                        update_data[field] = value

                if custom_fields:
                    update_data["custom_fields"] = custom_fields

                await api.update_submittal(project_id, update["procore_id"], update_data)
                updated_keys.append(update["key"])
                await asyncio.sleep(DELAY_BETWEEN_UPDATES)

            except RateLimitError as e:
                errors.append(f"Rate limited updating {update['key']}: {str(e)}")
                logger.warning(f"Job {job_id}: rate limited, waiting 5 min")
                await asyncio.sleep(300)
                # Retry once
                try:
                    await api.update_submittal(project_id, update["procore_id"], update_data)
                    updated_keys.append(update["key"])
                except Exception as retry_err:
                    errors.append(f"Retry failed for {update['key']}: {str(retry_err)}")
            except Exception as e:
                errors.append(f"Failed to update {update['key']}: {str(e)}")

            # Update progress
            file_job_store.update_progress(
                job_id,
                uploaded_files=i + 1,
                errors=errors,
            )

        # Update baseline with results
        from services.sync_service import SyncService
        from routers.rms_upload import get_rms_data

        try:
            rms_data = get_rms_data(rms_session_id)
            sync_service = SyncService(str(project_id), str(company_id), config=config_data)
            sync_service.update_baseline_with_results(
                rms_data,
                created_ids,
                updated_keys,
                uploaded_files,
            )
        except Exception as e:
            errors.append(f"Failed to update baseline: {str(e)}")

        # Record in history
        baseline_store.add_sync_history(
            str(project_id),
            "incremental",
            creates=len(created_ids),
            updates=len(updated_keys),
            file_uploads=0,
            errors=errors,
            summary=f"Background: {len(updated_keys)} updates applied",
        )

        summary = {
            "uploaded": len(updated_keys),
            "total": len(updates_data),
            "errors": len(errors),
        }
        final_status = "completed" if updated_keys or not errors else "failed"
        file_job_store.update_progress(
            job_id,
            status=final_status,
            uploaded_files=len(updates_data),
            errors=errors,
            result_summary=summary,
        )

        logger.info(f"Sync job {job_id} {final_status}: {len(updated_keys)}/{len(updates_data)} updates")

    except Exception as e:
        logger.error(f"Sync job {job_id} failed: {e}")
        errors.append(f"Job failed: {e}")
        file_job_store.update_progress(
            job_id,
            status="failed",
            errors=errors,
            result_summary={"uploaded": len(updated_keys), "total": len(updates_data), "errors": len(errors)},
        )
