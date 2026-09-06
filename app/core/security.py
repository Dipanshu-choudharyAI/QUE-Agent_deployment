"""Authentication for QUE endpoints.

Two accepted credentials (either one is enough):

1. ``Authorization: Bearer <que_access JWT>`` — browser → QUE (minted by Quizzer)
2. ``X-Que-Service-Key`` — server → QUE (future tools / internal callers)

Never put the service key in the browser.
"""

from __future__ import annotations

import hmac

from fastapi import Header, HTTPException, status

from app.core.config import get_settings
from app.core.tokens import QuePrincipal, decode_que_access_token

SERVICE_KEY_HEADER = "X-Que-Service-Key"


def require_chat_auth(
    authorization: str | None = Header(default=None),
    x_que_service_key: str | None = Header(default=None, alias=SERVICE_KEY_HEADER),
) -> QuePrincipal:
    """Accept a Que access JWT or the shared service key."""
    cfg = get_settings()

    if cfg.allow_insecure_local_no_auth and cfg.is_local:
        return QuePrincipal(mode="service", user_id=None)

    bearer = _bearer_token(authorization)
    if bearer:
        try:
            return decode_que_access_token(bearer, settings=cfg)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired Que access token",
            ) from exc

    expected = cfg.que_service_key
    provided = (x_que_service_key or "").strip()
    if expected and provided and hmac.compare_digest(provided, expected):
        return QuePrincipal(mode="service", user_id=None)

    if not expected and not (cfg.que_jwt_secret or "").strip():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service authentication is not configured",
        )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing credentials",
    )


# Back-compat alias used by older imports / docs.
require_service_key = require_chat_auth


def _bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, credentials = authorization.partition(" ")
    if scheme.lower() != "bearer":
        return None
    token = credentials.strip()
    return token or None
