"""Background file upload job processor.

Handles uploading files to Procore and attaching them to submittals.
Runs as an asyncio task so the user doesn't have to wait.
"""
import asyncio
import json
import logging
import shutil
from pathlib import Path
from typing import Optional

from database import file_job_store, baseline_store
from services.procore_api import ProcoreAPI, RateLimitError
from routers.auth import get_token

logger = logging.getLogger(__name__)

DELAY_BETWEEN_FILES = 2  # seconds


async def process_file_job(job_id: str) -> None:
    """
    Process a file upload job in the background.

    For each file in the manifest:
    1. Upload to Procore Documents (4 API calls)
    2. Attach to each target submittal (2 API calls each)
    3. Update progress in DB

    Updates baseline when complete. Cleans up temp files.
    """
    job = file_job_store.get_job(job_id)
    if not job:
        logger.error(f"File job {job_id} not found")
        return

    manifest = job["file_manifest"]
    project_id = int(job["project_id"])
    company_id = int(job["company_id"])
    session_id = job["session_id"]
    temp_dir = None

    # Track results
    uploaded_count = 0
    errors: list[str] = []
    uploaded_files: dict[str, int] = {}  # filename -> prostore_file_id

    try:
        # Get auth token
        access_token = get_token(session_id)
        api = ProcoreAPI(access_token, company_id=company_id)

        file_job_store.update_progress(job_id, status="running")

        # Resolve submittal keys to Procore IDs from baseline
        baseline = baseline_store.get_baseline(str(project_id))
        key_to_procore_id: dict[str, int] = {}
        if baseline and baseline.get("data", {}).get("submittals"):
            for key, sub in baseline["data"]["submittals"].items():
                if sub.get("procore_id"):
                    key_to_procore_id[key] = sub["procore_id"]

        # Determine temp dir from first file
        if manifest:
            temp_dir = str(Path(manifest[0]["temp_path"]).parent)

        for i, item in enumerate(manifest):
            filename = item["filename"]
            temp_path = item["temp_path"]
            submittal_keys = item["submittal_keys"]

            try:
                # Upload file to Procore Documents
                prostore_file_id = await api.upload_file(project_id, temp_path)
                await asyncio.sleep(DELAY_BETWEEN_FILES)

                # Attach to each target submittal
                attached_count = 0
                for key in submittal_keys:
                    procore_id = key_to_procore_id.get(key)
                    if procore_id:
                        await api.attach_file_to_submittal(
                            project_id, procore_id, prostore_file_id
                        )
                        attached_count += 1
                        await asyncio.sleep(DELAY_BETWEEN_FILES)
                    else:
                        errors.append(
                            f"{filename}: no Procore ID for submittal key {key}"
                        )

                uploaded_files[filename] = prostore_file_id
                uploaded_count += 1

                logger.info(
                    f"Job {job_id}: uploaded {filename} "
                    f"({uploaded_count}/{len(manifest)}, "
                    f"attached to {attached_count} submittals)"
                )

            except RateLimitError as e:
                errors.append(f"{filename}: rate limited — {e}")
                logger.warning(f"Job {job_id}: rate limited on {filename}, waiting 5 min")
                await asyncio.sleep(300)
                # Retry once
                try:
                    prostore_file_id = await api.upload_file(project_id, temp_path)
                    for key in submittal_keys:
                        procore_id = key_to_procore_id.get(key)
                        if procore_id:
                            await api.attach_file_to_submittal(
                                project_id, procore_id, prostore_file_id
                            )
                            await asyncio.sleep(DELAY_BETWEEN_FILES)
                    uploaded_files[filename] = prostore_file_id
                    uploaded_count += 1
                    # Remove the rate limit error since retry succeeded
                    errors = [e for e in errors if not e.startswith(f"{filename}:")]
                except Exception as retry_err:
                    errors.append(f"{filename}: retry failed — {retry_err}")

            except Exception as e:
                errors.append(f"{filename}: {e}")
                logger.error(f"Job {job_id}: error uploading {filename}: {e}")

            # Update progress after each file
            file_job_store.update_progress(
                job_id,
                uploaded_files=uploaded_count,
                errors=errors,
            )

        # Update baseline with uploaded files
        if uploaded_files and baseline:
            data = baseline["data"]
            if "files" not in data:
                data["files"] = {}
            for filename, file_id in uploaded_files.items():
                data["files"][filename] = {
                    "filename": filename,
                    "uploaded": True,
                    "procore_file_id": file_id,
                }
            baseline_store.save_baseline(
                str(project_id), str(company_id), data
            )

        # Final status
        summary = {
            "uploaded": uploaded_count,
            "total": len(manifest),
            "errors": len(errors),
        }
        final_status = "completed" if uploaded_count > 0 or not errors else "failed"
        file_job_store.update_progress(
            job_id,
            status=final_status,
            uploaded_files=uploaded_count,
            errors=errors,
            result_summary=summary,
        )

        logger.info(
            f"Job {job_id} {final_status}: "
            f"{uploaded_count}/{len(manifest)} files, {len(errors)} errors"
        )

    except Exception as e:
        logger.error(f"Job {job_id} failed: {e}")
        errors.append(f"Job failed: {e}")
        file_job_store.update_progress(
            job_id,
            status="failed",
            errors=errors,
            result_summary={"uploaded": uploaded_count, "total": len(manifest), "errors": len(errors)},
        )

    finally:
        # Clean up temp directory
        if temp_dir and Path(temp_dir).exists():
            try:
                shutil.rmtree(temp_dir)
                logger.info(f"Job {job_id}: cleaned up temp dir {temp_dir}")
            except Exception as e:
                logger.warning(f"Job {job_id}: failed to clean temp dir: {e}")
