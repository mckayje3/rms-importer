"""Temporary debug endpoint to diagnose RFI reply 403 errors."""
import logging
import httpx
from fastapi import APIRouter, Header, HTTPException

from routers.auth import get_token
from config import get_settings

settings = get_settings()
router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/projects/{project_id}/debug-reply/{rfi_id}")
async def debug_rfi_reply(
    project_id: int,
    rfi_id: int,
    x_auth_session: str = Header(..., alias="X-Auth-Session"),
    x_company_id: int = Header(..., alias="X-Company-Id"),
):
    """Debug endpoint: try to create a test reply and return full error details."""
    try:
        access_token = get_token(x_auth_session)
    except HTTPException:
        raise HTTPException(status_code=401, detail="Invalid auth session")

    base_url = settings.procore_base_url
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Procore-Company-Id": str(x_company_id),
        "Content-Type": "application/json",
    }

    results = {}

    # 1. Check who we are
    async with httpx.AsyncClient(timeout=30) as client:
        me_resp = await client.get(f"{base_url}/rest/v1.0/me", headers=headers)
        results["me"] = {
            "status": me_resp.status_code,
            "body": me_resp.json() if me_resp.status_code == 200 else me_resp.text[:500],
        }

        # 2. Get RFI detail to see manager/assignee
        rfi_resp = await client.get(
            f"{base_url}/rest/v1.0/projects/{project_id}/rfis/{rfi_id}",
            headers=headers,
        )
        if rfi_resp.status_code == 200:
            rfi_data = rfi_resp.json()
            results["rfi"] = {
                "number": rfi_data.get("number"),
                "status": rfi_data.get("status"),
                "rfi_manager": rfi_data.get("rfi_manager"),
                "assignee": rfi_data.get("assignee"),
                "created_by": rfi_data.get("created_by"),
                "questions_count": len(rfi_data.get("questions", [])),
                "answers": [
                    len(q.get("answers", []))
                    for q in rfi_data.get("questions", [])
                ],
            }
        else:
            results["rfi"] = {"status": rfi_resp.status_code, "body": rfi_resp.text[:500]}

        # 3. Try creating a reply — capture full error
        reply_resp = await client.post(
            f"{base_url}/rest/v1.0/projects/{project_id}/rfis/{rfi_id}/replies",
            headers=headers,
            json={"reply": {"body": "DEBUG TEST — please delete this reply"}},
        )
        results["reply_attempt"] = {
            "status": reply_resp.status_code,
            "headers": dict(reply_resp.headers),
            "body": reply_resp.text[:1000],
        }

        # 4. Also try via v1.1 to compare
        reply_v11_resp = await client.post(
            f"{base_url}/rest/v1.1/projects/{project_id}/rfis/{rfi_id}/replies",
            headers=headers,
            json={"reply": {"body": "DEBUG TEST v1.1 — please delete this reply"}},
        )
        results["reply_v1.1_attempt"] = {
            "status": reply_v11_resp.status_code,
            "body": reply_v11_resp.text[:500],
        }

    return results
