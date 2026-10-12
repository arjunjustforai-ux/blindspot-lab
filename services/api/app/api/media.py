"""Signed media delivery (PDF pages, slide previews, figure crops, video with HTTP range support)."""

from __future__ import annotations

import mimetypes
import uuid

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse
from sqlalchemy import select

from app.core.errors import APIError
from app.core.security import verify_media
from app.db import SessionLocal
from app.models import CourseMembership
from app.services.storage import get_storage

router = APIRouter(prefix="/api/media", tags=["media"])


@router.get("/{key:path}")
def media(key: str, exp: int = Query(...), uid: str = Query(...), sig: str = Query(...)) -> FileResponse:
    if not verify_media(key, uid, exp, sig):
        raise APIError(403, "invalid_signature", "Media link is invalid or has expired")
    parts = key.split("/")
    if len(parts) < 3 or parts[0] != "courses":
        raise APIError(404, "not_found", "Media not found")
    try:
        course_id, user_id = uuid.UUID(parts[1]), uuid.UUID(uid)
    except ValueError as e:
        raise APIError(404, "not_found", "Media not found") from e
    with SessionLocal() as db:  # membership is re-checked so revoked access cannot reuse old links
        ok = db.scalar(select(CourseMembership.id).where(CourseMembership.course_id == course_id,
                                                         CourseMembership.user_id == user_id))
    if not ok:
        raise APIError(403, "forbidden", "No access to this course")
    path = get_storage().local_path(key)
    if not path.exists():
        raise APIError(404, "not_found", "Media not found")
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return FileResponse(path, media_type=mime, headers={"Cache-Control": "private, max-age=3600",
                                                        "X-Content-Type-Options": "nosniff"})
