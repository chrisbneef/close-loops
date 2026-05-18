"""Google OAuth — direct flow, no middleman.

GET /oauth/google/start?user_id=N
  → redirects to Google's consent page with HMAC-signed state encoding user_id

GET /oauth/google/callback?code=...&state=...
  → exchanges code for tokens; stores refresh_token on the User row

Internal Workspace apps skip Google's verification flow, so the consent page
shows no "unverified app" warning. Each cofounder hits /start once in their own
browser (signed into their own Google account); the refresh token stored on
their User row never expires unless explicitly revoked.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from google_auth_oauthlib.flow import Flow
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_session
from app.models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/oauth/google", tags=["oauth"])

# calendar.events covers both read (freebusy + list) and write (insert/update/delete).
SCOPES = ["https://www.googleapis.com/auth/calendar.events"]


def _sign_state(user_id: int, nonce: str, code_verifier: str = "") -> str:
    """Encode user_id + nonce + PKCE code_verifier, then HMAC-sign.

    The verifier rides in the state so /callback can recover it (Google echoes
    `state` back verbatim). Including it in a signed payload is safe for a
    confidential client — the client_secret is what actually authenticates us
    to Google, and PKCE here is just a Google-required protocol step.
    """
    msg = f"{user_id}:{nonce}:{code_verifier}".encode()
    sig = hmac.new(
        settings.google_oauth_client_secret.encode(), msg, hashlib.sha256
    ).hexdigest()[:32]
    return f"{user_id}:{nonce}:{code_verifier}:{sig}"


def _verify_state(state: str) -> tuple[int, str]:
    """Returns (user_id, code_verifier). Raises 400 on tampering / malformed input."""
    parts = state.split(":")
    if len(parts) != 4:
        raise HTTPException(status_code=400, detail="Malformed OAuth state")
    user_id_str, nonce, code_verifier, sig = parts
    expected = hmac.new(
        settings.google_oauth_client_secret.encode(),
        f"{user_id_str}:{nonce}:{code_verifier}".encode(),
        hashlib.sha256,
    ).hexdigest()[:32]
    if not hmac.compare_digest(sig, expected):
        raise HTTPException(status_code=400, detail="OAuth state signature mismatch")
    try:
        return int(user_id_str), code_verifier
    except ValueError:
        raise HTTPException(status_code=400, detail="OAuth state user_id not numeric")


def _build_flow() -> Flow:
    if not settings.google_oauth_client_id or not settings.google_oauth_client_secret:
        raise HTTPException(
            status_code=503,
            detail="Google OAuth not configured — set GOOGLE_OAUTH_CLIENT_ID/_SECRET in backend/.env.",
        )
    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": settings.google_oauth_client_id,
                "client_secret": settings.google_oauth_client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [settings.google_oauth_redirect_uri],
            }
        },
        scopes=SCOPES,
    )
    flow.redirect_uri = settings.google_oauth_redirect_uri
    return flow


@router.get("/start")
def start(
    user_id: int = Query(..., description="Cadence User.id to connect Google Calendar for"),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail=f"user_id={user_id} does not exist")
    if not user.email:
        raise HTTPException(
            status_code=400, detail=f"User {user_id} ({user.name}) has no email set."
        )

    flow = _build_flow()
    # Generate the PKCE code_verifier ourselves and stash it on the flow BEFORE
    # building the URL. The library then computes the code_challenge from it
    # and puts ONLY the challenge in the URL — the verifier is a secret kept
    # for the token exchange. We also encode the verifier in our signed state
    # so /callback can recover it after the redirect round trip.
    # NB: do NOT pass code_verifier= as a kwarg to authorization_url(); the
    # library would forward it as a URL query parameter and Google rejects
    # code_verifier on the auth endpoint (it belongs on /token only).
    code_verifier = secrets.token_urlsafe(32)  # 43-char base64url, valid PKCE verifier
    flow.code_verifier = code_verifier
    state = _sign_state(user_id, secrets.token_urlsafe(16), code_verifier)
    auth_url, _ = flow.authorization_url(
        access_type="offline",        # required to receive a refresh_token
        prompt="consent",             # force re-consent so refresh_token is always returned
        state=state,
        login_hint=user.email,        # nudges Google to suggest the right account
        include_granted_scopes="true",
    )
    logger.info("oauth start user_id=%s email=%s", user_id, user.email)
    return RedirectResponse(auth_url)


@router.get("/callback", response_class=HTMLResponse)
def callback(
    code: str = Query(None),
    state: str = Query(None),
    error: str = Query(None),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    if error:
        return HTMLResponse(
            f"<html><body><h2>OAuth declined</h2><p>Google returned: <code>{error}</code></p></body></html>",
            status_code=400,
        )
    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code or state in callback")

    user_id, code_verifier = _verify_state(state)
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail=f"user_id={user_id} not found after OAuth")

    flow = _build_flow()
    # Restore the PKCE verifier that /start generated; without it Google's
    # token endpoint returns invalid_grant ("Missing code verifier").
    flow.code_verifier = code_verifier
    flow.fetch_token(code=code)
    creds = flow.credentials
    if not creds.refresh_token:
        # This happens if the user previously authorized and Google declined to issue a new
        # refresh_token. They need to revoke in https://myaccount.google.com/permissions and retry.
        raise HTTPException(
            status_code=500,
            detail=(
                "Google didn't return a refresh_token. Revoke Cadence at "
                "https://myaccount.google.com/permissions and try /oauth/google/start again."
            ),
        )

    user.google_refresh_token = creds.refresh_token
    session.commit()
    logger.info("oauth connected user_id=%s email=%s", user_id, user.email)

    return HTMLResponse(
        f"""
        <html><body style="font-family: -apple-system, sans-serif; padding: 3em; max-width: 480px;">
            <h2 style="color: #2d7a3a;">✓ Connected to Google Calendar</h2>
            <p>Cadence can now read and write events for <b>{user.name}</b> ({user.email}).</p>
            <p style="color: #666; font-size: 0.9em;">You can close this tab.</p>
        </body></html>
        """
    )
