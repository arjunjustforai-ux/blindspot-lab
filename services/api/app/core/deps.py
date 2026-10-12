"""Request dependencies: authentication and course-scoped authorization."""

from __future__ import annotations

import uuid
from typing import Annotated

import jwt
from fastapi import Depends, Header
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import APIError, forbidden, not_found
from app.core.security import decode_access_token, decode_supabase_token
from app.db import get_db
from app.models import Course, CourseMembership, User

DB = Annotated[Session, Depends(get_db)]


def _unauthorized(msg: str = "Authentication required") -> APIError:
    return APIError(401, "unauthorized", msg)


def get_current_user(db: DB, authorization: Annotated[str | None, Header()] = None) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise _unauthorized()
    token = authorization.split(" ", 1)[1].strip()
    user: User | None = None
    try:
        payload = decode_access_token(token)
        user = db.get(User, uuid.UUID(payload["sub"]))
    except (jwt.PyJWTError, KeyError, ValueError):
        claims = decode_supabase_token(token)
        if claims and claims.get("sub"):
            user = db.scalar(select(User).where(User.external_subject == claims["sub"]))
            if user is None:
                email = claims.get("email") or f"{claims['sub']}@supabase.local"
                user = User(
                    email=email.lower(),
                    display_name=(claims.get("user_metadata") or {}).get("full_name") or email.split("@")[0],
                    auth_provider="supabase",
                    external_subject=claims["sub"],
                )
                db.add(user)
                db.commit()
    if user is None:
        raise _unauthorized("Invalid or expired session")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def get_membership(db: Session, course_id: uuid.UUID, user: User) -> CourseMembership:
    course = db.get(Course, course_id)
    if course is None:
        raise not_found("Course")
    m = db.scalar(
        select(CourseMembership).where(CourseMembership.course_id == course_id, CourseMembership.user_id == user.id)
    )
    if m is None:
        raise forbidden("You are not a member of this course")
    return m


def require_course(db: Session, course_id: uuid.UUID, user: User, *, manage: bool = False) -> Course:
    """Authorize access to a course. `manage=True` requires owner/instructor role."""
    m = get_membership(db, course_id, user)
    if manage and m.role not in ("owner", "instructor"):
        raise forbidden("Only course owners and instructors can change course materials")
    course = db.get(Course, course_id)
    assert course is not None
    return course
