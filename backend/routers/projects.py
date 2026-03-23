"""Project-related endpoints."""
from fastapi import APIRouter, Header, HTTPException
from typing import Optional

from services.procore_api import ProcoreAPI
from models.procore import ProcoreProject, ProcoreCompany, ProcoreStats
from routers.auth import get_token

router = APIRouter()


@router.get("/companies", response_model=list[ProcoreCompany])
async def list_companies(
    x_auth_session: str = Header(..., alias="X-Auth-Session"),
):
    """List companies the user has access to."""
    token = get_token(x_auth_session)
    api = ProcoreAPI(token)
    return await api.get_companies()


@router.get("/companies/{company_id}/projects", response_model=list[ProcoreProject])
async def list_projects(
    company_id: int,
    x_auth_session: str = Header(..., alias="X-Auth-Session"),
):
    """List projects for a company."""
    token = get_token(x_auth_session)
    api = ProcoreAPI(token, company_id=company_id)
    return await api.get_projects()


@router.get("/projects/{project_id}/stats", response_model=ProcoreStats)
async def get_project_stats(
    project_id: int,
    company_id: int,
    x_auth_session: str = Header(..., alias="X-Auth-Session"),
):
    """Get submittal statistics for a project (for auto-detection)."""
    token = get_token(x_auth_session)
    api = ProcoreAPI(token, company_id=company_id)
    return await api.get_submittal_stats(project_id)
