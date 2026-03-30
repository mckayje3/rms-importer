"""Project setup endpoints for configuring per-project settings."""
from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel
from typing import Optional

from services.procore_api import ProcoreAPI
from routers.auth import get_token
from database import project_config_store
from models.mappings import QA_STATUS_MAP, SD_TYPE_MAP

router = APIRouter()


class SaveConfigRequest(BaseModel):
    """Request to save project configuration."""
    company_id: str
    config_data: dict


@router.get("/projects/{project_id}/discover")
async def discover_project(
    project_id: int,
    company_id: int,
    x_auth_session: str = Header(..., alias="X-Auth-Session"),
):
    """
    Discover Procore project configuration.

    Fetches custom fields, statuses, and types from the project
    to help the user configure mappings. Returns suggested defaults.
    """
    try:
        access_token = get_token(x_auth_session)
    except HTTPException:
        raise HTTPException(status_code=401, detail="Invalid auth session")

    api = ProcoreAPI(access_token, company_id=company_id)

    # Fetch custom fields and statuses from Procore
    custom_fields = await api.get_custom_fields_for_submittals(project_id)
    statuses = await api.get_submittal_statuses(project_id)

    # Check if config already exists
    existing = project_config_store.get_config(str(project_id))

    # Auto-suggest custom field mappings based on label matching
    suggested_fields = {}
    for cf in custom_fields:
        label_lower = cf["label"].lower()
        if "paragraph" in label_lower:
            suggested_fields["paragraph"] = cf["field_key"]
        elif "info" in label_lower and "paragraph" not in label_lower:
            suggested_fields["info"] = cf["field_key"]

    # Build suggested config with defaults
    suggested_config = {
        "status_mode": "qa_code",
        "status_map": dict(QA_STATUS_MAP),
        "sd_type_map": dict(SD_TYPE_MAP),
        "custom_fields": suggested_fields,
        "setup_completed": True,
    }

    return {
        "custom_fields": custom_fields,
        "statuses": statuses,
        "has_existing_config": existing is not None,
        "existing_config": existing["config_data"] if existing else None,
        "suggested_config": suggested_config,
    }


@router.get("/projects/{project_id}/config")
async def get_config(project_id: int):
    """Get saved project configuration."""
    config = project_config_store.get_config(str(project_id))
    if not config:
        raise HTTPException(status_code=404, detail="No configuration found for this project")
    return config


@router.post("/projects/{project_id}/config")
async def save_config(project_id: int, request: SaveConfigRequest):
    """Save project configuration."""
    project_config_store.save_config(
        project_id=str(project_id),
        company_id=request.company_id,
        config_data=request.config_data,
    )
    return {"status": "saved", "project_id": project_id}


@router.delete("/projects/{project_id}/config")
async def delete_config(project_id: int):
    """Delete project configuration (for reconfiguration)."""
    deleted = project_config_store.delete_config(str(project_id))
    if not deleted:
        raise HTTPException(status_code=404, detail="No configuration found to delete")
    return {"status": "deleted", "project_id": project_id}
