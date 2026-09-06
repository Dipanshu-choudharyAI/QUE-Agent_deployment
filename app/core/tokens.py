"""Validate short-lived Que access tokens minted by Quizzer Backend."""

from __future__ import annotations

from dataclasses import dataclass

import jwt
from jwt.exceptions import InvalidTokenError

from app.core.config import Settings, get_settings

QUE_TOKEN_TYPE = "que_access"
QUE_TOKEN_AUDIENCE = "que-agent"
QUE_TOKEN_ISSUER = "quizzer"


@dataclass(frozen=True)
class QuePrincipal:
    """Authenticated caller for chat endpoints."""

    mode: str  # "user" | "service"
    user_id: str | None = None
    session_id: str | None = None


def decode_que_access_token(token: str, *, settings: Settings | None = None) -> QuePrincipal:
    """Decode a Quizzer-minted Que access JWT.

    Raises ValueError on missing config or invalid/expired token.
    """
    cfg = settings or get_settings()
    secret = (cfg.que_jwt_secret or "").strip()
    if not secret:
        raise ValueError("QUE_JWT_SECRET is not configured")

    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=[cfg.que_jwt_algorithm],
            audience=cfg.que_jwt_audience,
            issuer=cfg.que_jwt_issuer,
            options={"require": ["exp", "sub", "typ"]},
        )
    except InvalidTokenError as exc:
        raise ValueError("Invalid or expired Que access token") from exc

    if payload.get("typ") != QUE_TOKEN_TYPE:
        raise ValueError("Invalid Que access token type")

    user_id = str(payload.get("sub") or "").strip()
    if not user_id:
        raise ValueError("Que access token missing subject")

    sid = payload.get("sid")
    return QuePrincipal(
        mode="user",
        user_id=user_id,
        session_id=str(sid).strip() if sid else None,
    )
