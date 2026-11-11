"""security-platform.auth.google_oauth — Google Sign-In via OAuth2."""

from __future__ import annotations

import os
from typing import Any, Dict, Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from pydantic import BaseModel

from db import get_conn, put_conn
from jwt import create_access_token, decode_access_token

router = APIRouter(prefix="/auth", tags=["Auth"])

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
GOOGLE_REDIRECT_URI = os.getenv(
    "GOOGLE_REDIRECT_URI", "http://localhost:8000/auth/google/callback"
)
GOOGLE_AUTH_URI = "https://accounts.google.com/o/oauth2/auth"
GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"


class GoogleCallback(BaseModel):
    code: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    tenant_id: str
    email: str


def _require_google_env() -> None:
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        raise HTTPException(
            status_code=500,
            detail="Google OAuth not configured: set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET",
        )


@router.get("/google/authorize")
async def google_authorize() -> RedirectResponse:
    """Redirect the user to Google's OAuth2 consent screen."""
    _require_google_env()
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
        "prompt": "consent",
    }
    return RedirectResponse(url=f"{GOOGLE_AUTH_URI}?{urlencode(params)}")


@router.get("/google/callback")
async def google_callback(code: str = Query(...)) -> TokenResponse:
    """Exchange the authorization code for an ID token, verify it, and issue a session JWT."""
    _require_google_env()

    # Exchange code for tokens
    token_data = {
        "code": code,
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "grant_type": "authorization_code",
    }
    try:
        resp = google_requests.Request().__class__()  # type: ignore[attr-defined]
    except Exception:  # pragma: no cover - fallback handled below
        resp = None

    import urllib.request
    import json as _json

    data = urlencode(token_data).encode("utf-8")
    req = urllib.request.Request(
        GOOGLE_TOKEN_URI,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            token_json = _json.loads(r.read().decode("utf-8"))
    except Exception as exc:  # pragma: no cover - network/Google failure
        raise HTTPException(status_code=502, detail=f"Google token exchange failed: {exc}")

    id_token_value = token_json.get("id_token")
    if not id_token_value:
        raise HTTPException(status_code=400, detail="No id_token in Google response")

    # Verify the ID token signature and audience
    try:
        user_info = id_token.verify_oauth2_token(
            id_token_value, google_requests.Request(), GOOGLE_CLIENT_ID
        )
    except Exception as exc:  # pragma: no cover - invalid token
        raise HTTPException(status_code=401, detail=f"Invalid Google ID token: {exc}")

    email = user_info.get("email")
    google_sub = user_info.get("sub")
    if not email or not google_sub:
        raise HTTPException(status_code=400, detail="Google profile missing email/sub")

    # Find or create tenant + user
    tenant_id = _get_or_create_tenant_for_google(google_sub, email)
    user_id = _get_or_create_user(tenant_id, email, google_sub)

    access_token = create_access_token(subject=user_id, tenant_id=tenant_id, email=email)
    return TokenResponse(
        access_token=access_token, tenant_id=tenant_id, email=email
    )


def _get_or_create_tenant_for_google(google_sub: str, email: str) -> str:
    """Return an existing tenant id for this Google sub, or create a new one."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM tenants WHERE name = %s LIMIT 1",
                (f"google:{google_sub}",),
            )
            row = cur.fetchone()
            if row:
                return str(row[0])
            cur.execute(
                "INSERT INTO tenants (name, api_key_prefix, api_key_hash, is_active) "
                "VALUES (%s, %s, %s, TRUE) RETURNING id",
                (f"google:{google_sub}", "google", __import__("hashlib").sha256(google_sub.encode()).hexdigest()[:32]),
            )
            return str(cur.fetchone()[0])
    finally:
        put_conn(conn)


def _get_or_create_user(tenant_id: str, email: str, google_sub: str) -> str:
    """Return an existing user id, or create one linked to the tenant."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM users WHERE google_sub = %s LIMIT 1", (google_sub,)
            )
            row = cur.fetchone()
            if row:
                return str(row[0])
            cur.execute(
                "INSERT INTO users (tenant_id, email, google_sub) VALUES (%s, %s, %s) RETURNING id",
                (tenant_id, email, google_sub),
            )
            return str(cur.fetchone()[0])
    finally:
        put_conn(conn)


def get_current_user(request: Request) -> Dict[str, Any]:
    """Dependency: extract and verify the Bearer JWT from Authorization header."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    token = auth[len("Bearer "):]
    payload = decode_access_token(token)
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return {
        "user_id": payload.get("sub"),
        "tenant_id": payload.get("tenant_id"),
        "email": payload.get("email"),
    }


def get_current_user_optional(request: Request) -> Optional[Dict[str, Any]]:
    """Optional dependency: return JWT payload if a valid Bearer token is present, else None."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    token = auth[len("Bearer "):]
    payload = decode_access_token(token)
    if payload is None:
        return None
    return {
        "user_id": payload.get("sub"),
        "tenant_id": payload.get("tenant_id"),
        "email": payload.get("email"),
    }
