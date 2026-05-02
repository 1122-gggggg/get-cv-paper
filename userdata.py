"""Google ID-token auth + Postgres user-data sync.

Exposes an APIRouter that owns /api/me/* and a require_user dependency.
DB pool is lazy and the schema migration runs once on first acquire.
"""
from __future__ import annotations

import json as _json
import logging
import os
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
DATABASE_URL = os.environ.get("DATABASE_URL", "")
MAX_USER_DATA_BYTES = 512 * 1024  # 512KB per user

_db_pool: Any = None

router = APIRouter()


async def _get_pool() -> Any:
    global _db_pool
    if _db_pool is not None:
        return _db_pool
    if not DATABASE_URL:
        raise HTTPException(status_code=503, detail="DATABASE_URL not set")
    import asyncpg
    _db_pool = await asyncpg.create_pool(
        DATABASE_URL,
        min_size=1,
        max_size=5,
        ssl="require",
        statement_cache_size=0,
    )
    async with _db_pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_data (
                google_sub TEXT PRIMARY KEY,
                email TEXT,
                name TEXT,
                data JSONB NOT NULL DEFAULT '{}'::jsonb,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
    return _db_pool


def _verify_id_token(token: str) -> dict:
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=503, detail="GOOGLE_CLIENT_ID not set")
    try:
        from google.oauth2 import id_token as gid_token
        from google.auth.transport import requests as g_requests
        return gid_token.verify_oauth2_token(
            token, g_requests.Request(), GOOGLE_CLIENT_ID
        )
    except Exception as e:
        logger.warning("ID token verify failed: %s", e)
        raise HTTPException(status_code=401, detail="invalid token")


async def require_user(authorization: str | None = Header(default=None)) -> dict:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    return _verify_id_token(authorization.split(None, 1)[1].strip())


class UserDataPut(BaseModel):
    data: dict = Field(default_factory=dict)


@router.get("/api/me/data")
async def get_my_data(user: dict = Depends(require_user)):
    pool = await _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT data FROM user_data WHERE google_sub = $1", user["sub"]
        )
    return {
        "user": {
            "email": user.get("email"),
            "name": user.get("name"),
            "picture": user.get("picture"),
        },
        "data": (row["data"] if row else {}) or {},
    }


@router.put("/api/me/data")
async def put_my_data(body: UserDataPut, user: dict = Depends(require_user)):
    payload = _json.dumps(body.data)
    if len(payload.encode("utf-8")) > MAX_USER_DATA_BYTES:
        raise HTTPException(status_code=413, detail="user data too large")
    pool = await _get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO user_data (google_sub, email, name, data, updated_at)
            VALUES ($1, $2, $3, $4::jsonb, now())
            ON CONFLICT (google_sub) DO UPDATE
              SET email = EXCLUDED.email,
                  name = EXCLUDED.name,
                  data = EXCLUDED.data,
                  updated_at = now()
            """,
            user["sub"],
            user.get("email"),
            user.get("name"),
            payload,
        )
    return {"ok": True}


@router.get("/api/me/config")
def get_auth_config():
    return {"google_client_id": GOOGLE_CLIENT_ID}
