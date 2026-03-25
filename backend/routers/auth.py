"""Authentication endpoints for Procore OAuth."""
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse
import httpx
import secrets

from config import get_settings
from database import session_store

router = APIRouter()
settings = get_settings()

# In-memory store for OAuth state (short-lived, doesn't need persistence)
_oauth_states: dict[str, bool] = {}


@router.get("/login")
async def login():
    """Initiate Procore OAuth flow."""
    state = secrets.token_urlsafe(32)
    _oauth_states[state] = True

    auth_url = (
        f"{settings.procore_authorize_url}"
        f"?client_id={settings.procore_client_id}"
        f"&response_type=code"
        f"&redirect_uri={settings.backend_url}/auth/callback"
        f"&state={state}"
    )
    return {"auth_url": auth_url, "state": state}


@router.get("/callback")
async def callback(code: str = Query(...), state: str = Query(...)):
    """Handle OAuth callback from Procore."""
    # Verify state
    if state not in _oauth_states:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")
    del _oauth_states[state]

    # Exchange code for token
    async with httpx.AsyncClient() as client:
        response = await client.post(
            settings.procore_auth_url,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": settings.procore_client_id,
                "client_secret": settings.procore_client_secret,
                "redirect_uri": f"{settings.backend_url}/auth/callback",
            },
        )

        if response.status_code != 200:
            raise HTTPException(
                status_code=400,
                detail=f"Failed to exchange code: {response.text}",
            )

        token_data = response.json()

    # Store token in database
    session_id = secrets.token_urlsafe(32)
    session_store.save_session(session_id, token_data)

    # Redirect back to frontend with auth success
    return RedirectResponse(
        url=f"{settings.frontend_url}?auth=success&session_id={session_id}"
    )


@router.post("/refresh")
async def refresh_token(session_id: str):
    """Refresh an expired access token."""
    token_data = session_store.get_session(session_id)
    if not token_data:
        raise HTTPException(status_code=401, detail="Invalid session")

    refresh_token = token_data.get("refresh_token")

    if not refresh_token:
        raise HTTPException(status_code=401, detail="No refresh token available")

    async with httpx.AsyncClient() as client:
        response = await client.post(
            settings.procore_auth_url,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": settings.procore_client_id,
                "client_secret": settings.procore_client_secret,
            },
        )

        if response.status_code != 200:
            raise HTTPException(status_code=401, detail="Failed to refresh token")

        new_token_data = response.json()

    session_store.save_session(session_id, new_token_data)
    return {
        "access_token": new_token_data["access_token"],
        "expires_in": new_token_data.get("expires_in"),
    }


@router.post("/logout")
async def logout(session_id: str):
    """Logout and clear session."""
    session_store.delete_session(session_id)
    return {"status": "logged_out"}


def get_token(session_id: str) -> str:
    """Get access token for a session (used by other routers)."""
    token_data = session_store.get_session(session_id)
    if not token_data:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return token_data["access_token"]
