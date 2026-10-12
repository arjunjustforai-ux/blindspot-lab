from __future__ import annotations

import secrets

from fastapi import APIRouter
from sqlalchemy import select

from app.cli import find_demo_course
from app.config import get_settings
from app.core.deps import DB, CurrentUser
from app.core.errors import APIError, conflict
from app.core.security import create_access_token, hash_password, verify_password
from app.models import CourseMembership, User
from app.schemas import LoginIn, RegisterIn, TokenOut, UserOut

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _token(user: User) -> TokenOut:
    return TokenOut(access_token=create_access_token(user.id), user=UserOut.model_validate(user))


def _join_demo_course(db: DB, user: User) -> None:
    course = find_demo_course(db)
    if course is None:
        return
    exists = db.scalar(select(CourseMembership).where(CourseMembership.course_id == course.id,
                                                      CourseMembership.user_id == user.id))
    if exists is None:
        db.add(CourseMembership(course_id=course.id, user_id=user.id, role="student"))


@router.post("/register", response_model=TokenOut, status_code=201)
def register(body: RegisterIn, db: DB) -> TokenOut:
    email = body.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise conflict("An account with this email already exists", code="email_taken")
    u = User(email=email, display_name=body.display_name.strip(), password_hash=hash_password(body.password),
             auth_provider="local")
    db.add(u)
    db.flush()
    _join_demo_course(db, u)  # every learner can explore the demonstration course
    db.commit()
    return _token(u)


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, db: DB) -> TokenOut:
    u = db.scalar(select(User).where(User.email == body.email.lower()))
    if u is None or not verify_password(body.password, u.password_hash):
        raise APIError(401, "invalid_credentials", "Incorrect email or password")
    return _token(u)


@router.post("/demo", response_model=TokenOut, status_code=201)
def demo_login(db: DB) -> TokenOut:
    """Create a fresh, clearly-labelled demo learner (no history) enrolled in the demo course."""
    if not get_settings().demo_enabled:
        raise APIError(403, "demo_disabled", "Demo access is disabled on this deployment")
    tag = secrets.token_hex(4)
    u = User(email=f"demo-{tag}@demo.blindspot.local", display_name=f"Demo learner {tag[:4].upper()}",
             auth_provider="demo", is_demo=True)
    db.add(u)
    db.flush()
    _join_demo_course(db, u)
    db.commit()
    return _token(u)


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser) -> User:
    return user
