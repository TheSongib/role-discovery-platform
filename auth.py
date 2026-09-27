"""Cognito-backed admin authentication for state-changing API operations.

The public dashboard intentionally allows anonymous reads. Administrative
actions use Cognito's authorization-code flow with PKCE and keep the resulting
ID token in a Secure, HttpOnly cookie so browser JavaScript never handles AWS
tokens.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
import secrets
from datetime import datetime, timezone
from functools import lru_cache
from urllib.parse import urlencode

import jwt
import requests
from fastapi import HTTPException, Request, Response, status
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
REFRESH_COOKIE = "jobtracker_admin_refresh"
STATE_COOKIE = "jobtracker_oauth_state"
VERIFIER_COOKIE = "jobtracker_oauth_verifier"
NONCE_COOKIE = "jobtracker_oauth_nonce"
OAUTH_COOKIE_PATH = "/api/auth"
REFRESH_COOKIE_PATH = "/api"
SESSION_MAX_AGE_SECONDS = 60 * 60
REFRESH_MAX_AGE_SECONDS = 30 * 24 * 60 * 60

logger = logging.getLogger(__name__)


class _RefreshFailed(Exception):
    """Raised when Cognito cannot renew the browser's admin session."""


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


def _set_session_cookie(response: Response, id_token: str, claims: dict) -> None:
    expires_at = int(claims["exp"])
    remaining_lifetime = expires_at - int(datetime.now(timezone.utc).timestamp())
    response.set_cookie(
        SESSION_COOKIE,
        id_token,
        max_age=max(1, min(SESSION_MAX_AGE_SECONDS, remaining_lifetime)),
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )


def _set_refresh_cookie(response: Response, refresh_token: str) -> None:
    response.set_cookie(
        REFRESH_COOKIE,
        refresh_token,
        max_age=REFRESH_MAX_AGE_SECONDS,
        httponly=True,
        secure=True,
        samesite="lax",
        path=REFRESH_COOKIE_PATH,
    )


def clear_auth_cookies(response: Response) -> None:
    """Expire both browser credentials using their original cookie paths."""
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_COOKIE_PATH)


def _refresh_admin_session(request: Request, response: Response) -> dict:
    refresh_token = request.cookies.get(REFRESH_COOKIE, "")
    if not refresh_token:
        raise _RefreshFailed("Refresh cookie is missing")

    try:
        token_response = requests.post(
            f"{COGNITO_DOMAIN}/oauth2/token",
            data={
                "grant_type": "refresh_token",
                "client_id": COGNITO_CLIENT_ID,
                "refresh_token": refresh_token,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=10,
        )
    except requests.RequestException as exc:
        raise _RefreshFailed("Cognito token refresh request failed") from exc

    if not token_response.ok:
        raise _RefreshFailed("Cognito rejected the refresh token")

    try:
        token_payload = token_response.json()
        id_token = token_payload["id_token"]
        claims = _decode_id_token(id_token)
    except (KeyError, ValueError, jwt.PyJWTError) as exc:
        raise _RefreshFailed("Cognito returned an invalid refreshed session") from exc

    _set_session_cookie(response, id_token, claims)
    rotated_refresh_token = token_payload.get("refresh_token")
    if rotated_refresh_token:
        _set_refresh_cookie(response, rotated_refresh_token)
    return claims


def _clear_failed_session(request: Request) -> None:
    # Dependencies that raise HTTPException don't reliably carry cookies from
    # the injected Response. The API middleware observes this flag and applies
    # the same cleanup to the final error response.
    request.state.clear_auth_cookies = True


def _admin_claims_from_request(
    request: Request,
    response: Response,
    *,
    required: bool,
) -> dict | None:
    if not AUTH_ENABLED:
        # Preserve the frictionless local-development workflow. Production
        # explicitly sets AUTH_ENABLED=true in the Kubernetes ConfigMap.
        return {
            "sub": "local-development",
            "cognito:groups": [COGNITO_ADMIN_GROUP],
        }

    token = request.cookies.get(SESSION_COOKIE, "")
    refresh_token = request.cookies.get(REFRESH_COOKIE, "")
    if not token and not refresh_token:
        if required:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Admin login required",
            )
        return None

    try:
        if token:
            try:
                claims = _decode_id_token(token)
            except jwt.ExpiredSignatureError:
                claims = _refresh_admin_session(request, response)
        else:
            # Browsers remove the one-hour ID-token cookie at expiration, so a
            # surviving refresh cookie must also trigger silent renewal.
            claims = _refresh_admin_session(request, response)
    except (jwt.PyJWTError, _RefreshFailed):
        _clear_failed_session(request)
        if required:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Admin session expired; sign in again",
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


def optional_admin(request: Request, response: Response) -> dict | None:
    """Return verified admin claims or ``None`` for an anonymous viewer."""
    return _admin_claims_from_request(request, response, required=False)


def require_admin(request: Request, response: Response) -> dict:
    """Require a Cognito admin session and a same-origin browser mutation."""
    claims = _admin_claims_from_request(request, response, required=True)
    if AUTH_ENABLED and request.method not in {"GET", "HEAD", "OPTIONS"}:
        origin = request.headers.get("origin", "").rstrip("/")
        if origin != PUBLIC_BASE_URL:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cross-origin administrative request rejected",
            )
    return claims


def auth_status(request: Request, response: Response) -> dict:
    claims = optional_admin(request, response)
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
    token_payload = token_response.json()
    id_token = token_payload.get("id_token", "")
    refresh_token = token_payload.get("refresh_token", "")
    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Cognito did not return a refresh token",
        )
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

    response = RedirectResponse(f"{PUBLIC_BASE_URL}/", 303)
    _set_session_cookie(response, id_token, claims)
    _set_refresh_cookie(response, refresh_token)
    for cookie_name in (STATE_COOKIE, VERIFIER_COOKIE, NONCE_COOKIE):
        response.delete_cookie(cookie_name, path=OAUTH_COOKIE_PATH)
    return response


def logout(request: Request) -> RedirectResponse:
    refresh_token = request.cookies.get(REFRESH_COOKIE, "")
    if AUTH_ENABLED and COGNITO_DOMAIN and COGNITO_CLIENT_ID and refresh_token:
        try:
            revoke_response = requests.post(
                f"{COGNITO_DOMAIN}/oauth2/revoke",
                data={
                    "token": refresh_token,
                    "client_id": COGNITO_CLIENT_ID,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=10,
            )
            if not revoke_response.ok:
                logger.warning("Cognito rejected refresh-token revocation during logout")
        except requests.RequestException:
            # Local logout must still complete if Cognito is temporarily
            # unreachable. The token will expire and rotation limits replay.
            logger.warning("Cognito refresh-token revocation request failed")

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
    clear_auth_cookies(response)
    return response
