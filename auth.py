"""Cognito-backed admin authentication for state-changing API operations.

The public dashboard intentionally allows anonymous reads. Administrative
actions use Cognito's authorization-code flow with PKCE and keep the resulting
ID token in a Secure, HttpOnly cookie so browser JavaScript never handles AWS
tokens.
"""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
from datetime import datetime, timezone
from functools import lru_cache
from urllib.parse import urlencode

import jwt
import requests
from fastapi import HTTPException, Request, status
from fastapi.responses import RedirectResponse
from jwt import PyJWKClient


AUTH_ENABLED = os.getenv("AUTH_ENABLED", "false").lower() in {"1", "true", "yes"}
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:5173").rstrip("/")
COGNITO_REGION = os.getenv("COGNITO_REGION", "")
COGNITO_USER_POOL_ID = os.getenv("COGNITO_USER_POOL_ID", "")
COGNITO_CLIENT_ID = os.getenv("COGNITO_CLIENT_ID", "")
COGNITO_DOMAIN = os.getenv("COGNITO_DOMAIN", "").rstrip("/")
COGNITO_ADMIN_GROUP = os.getenv("COGNITO_ADMIN_GROUP", "admins")

SESSION_COOKIE = "jobtracker_admin_session"
STATE_COOKIE = "jobtracker_oauth_state"
VERIFIER_COOKIE = "jobtracker_oauth_verifier"
NONCE_COOKIE = "jobtracker_oauth_nonce"
OAUTH_COOKIE_PATH = "/api/auth"


def _require_configuration() -> None:
    if not AUTH_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is not enabled",
        )
    required = {
        "COGNITO_REGION": COGNITO_REGION,
        "COGNITO_USER_POOL_ID": COGNITO_USER_POOL_ID,
        "COGNITO_CLIENT_ID": COGNITO_CLIENT_ID,
        "COGNITO_DOMAIN": COGNITO_DOMAIN,
        "PUBLIC_BASE_URL": PUBLIC_BASE_URL,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Authentication configuration is incomplete: {', '.join(missing)}",
        )


def _callback_url() -> str:
    return f"{PUBLIC_BASE_URL}/api/auth/callback"


def _issuer() -> str:
    return (
        f"https://cognito-idp.{COGNITO_REGION}.amazonaws.com/"
        f"{COGNITO_USER_POOL_ID}"
    )


@lru_cache(maxsize=1)
def _jwks_client() -> PyJWKClient:
    return PyJWKClient(f"{_issuer()}/.well-known/jwks.json", cache_keys=True)


def _decode_id_token(token: str) -> dict:
    signing_key = _jwks_client().get_signing_key_from_jwt(token)
    claims = jwt.decode(
        token,
        signing_key.key,
        algorithms=["RS256"],
        audience=COGNITO_CLIENT_ID,
        issuer=_issuer(),
        options={"require": ["exp", "iat", "iss", "aud", "token_use"]},
    )
    if claims.get("token_use") != "id":
        raise jwt.InvalidTokenError("Expected a Cognito ID token")
    return claims


def _admin_claims_from_request(request: Request, *, required: bool) -> dict | None:
    if not AUTH_ENABLED:
        # Preserve the frictionless local-development workflow. Production
        # explicitly sets AUTH_ENABLED=true in the Kubernetes ConfigMap.
        return {
            "sub": "local-development",
            "cognito:groups": [COGNITO_ADMIN_GROUP],
        }

    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        if required:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Admin login required",
            )
        return None

    try:
        claims = _decode_id_token(token)
    except jwt.PyJWTError:
        if required:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Admin session is invalid or expired",
            )
        return None

    groups = claims.get("cognito:groups") or []
    if COGNITO_ADMIN_GROUP not in groups:
        if required:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Administrator group membership required",
            )
        return None
    return claims


def optional_admin(request: Request) -> dict | None:
    """Return verified admin claims or ``None`` for an anonymous viewer."""
    return _admin_claims_from_request(request, required=False)


def require_admin(request: Request) -> dict:
    """Require a Cognito admin session and a same-origin browser mutation."""
    claims = _admin_claims_from_request(request, required=True)
    if AUTH_ENABLED and request.method not in {"GET", "HEAD", "OPTIONS"}:
        origin = request.headers.get("origin", "").rstrip("/")
        if origin != PUBLIC_BASE_URL:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cross-origin administrative request rejected",
            )
    return claims


def auth_status(request: Request) -> dict:
    claims = optional_admin(request)
    return {
        "enabled": AUTH_ENABLED,
        "authenticated": claims is not None and AUTH_ENABLED,
        "can_manage": claims is not None,
        "username": (claims or {}).get("cognito:username"),
    }


def begin_login() -> RedirectResponse:
    _require_configuration()
    state_value = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()
    ).rstrip(b"=").decode("ascii")
    query = urlencode(
        {
            "response_type": "code",
            "client_id": COGNITO_CLIENT_ID,
            "redirect_uri": _callback_url(),
            "scope": "openid email",
            "state": state_value,
            "nonce": nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )
    response = RedirectResponse(f"{COGNITO_DOMAIN}/oauth2/authorize?{query}", 302)
    cookie_options = {
        "max_age": 600,
        "httponly": True,
        "secure": True,
        "samesite": "lax",
        "path": OAUTH_COOKIE_PATH,
    }
    response.set_cookie(STATE_COOKIE, state_value, **cookie_options)
    response.set_cookie(VERIFIER_COOKIE, verifier, **cookie_options)
    response.set_cookie(NONCE_COOKIE, nonce, **cookie_options)
    return response


def finish_login(request: Request, code: str, state_value: str) -> RedirectResponse:
    _require_configuration()
    expected_state = request.cookies.get(STATE_COOKIE, "")
    verifier = request.cookies.get(VERIFIER_COOKIE, "")
    expected_nonce = request.cookies.get(NONCE_COOKIE, "")
    if not expected_state or not secrets.compare_digest(expected_state, state_value):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid OAuth state",
        )
    if not verifier or not expected_nonce:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OAuth login cookie is missing or expired",
        )

    token_response = requests.post(
        f"{COGNITO_DOMAIN}/oauth2/token",
        data={
            "grant_type": "authorization_code",
            "client_id": COGNITO_CLIENT_ID,
            "code": code,
            "redirect_uri": _callback_url(),
            "code_verifier": verifier,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=10,
    )
    if not token_response.ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Cognito rejected the authorization code",
        )
    id_token = token_response.json().get("id_token", "")
    try:
        claims = _decode_id_token(id_token)
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Cognito returned an invalid identity token",
        ) from exc
    if not secrets.compare_digest(str(claims.get("nonce", "")), expected_nonce):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid identity-token nonce",
        )
    if COGNITO_ADMIN_GROUP not in (claims.get("cognito:groups") or []):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator group membership required",
        )

    expires_at = int(claims["exp"])
    max_age = max(1, min(3600, expires_at - int(datetime.now(timezone.utc).timestamp())))
    response = RedirectResponse(f"{PUBLIC_BASE_URL}/", 303)
    response.set_cookie(
        SESSION_COOKIE,
        id_token,
        max_age=max_age,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )
    for cookie_name in (STATE_COOKIE, VERIFIER_COOKIE, NONCE_COOKIE):
        response.delete_cookie(cookie_name, path=OAUTH_COOKIE_PATH)
    return response


def logout() -> RedirectResponse:
    if not AUTH_ENABLED or not COGNITO_DOMAIN or not COGNITO_CLIENT_ID:
        response = RedirectResponse(f"{PUBLIC_BASE_URL}/", 303)
    else:
        query = urlencode(
            {
                "client_id": COGNITO_CLIENT_ID,
                "logout_uri": f"{PUBLIC_BASE_URL}/",
            }
        )
        response = RedirectResponse(f"{COGNITO_DOMAIN}/logout?{query}", 303)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response
