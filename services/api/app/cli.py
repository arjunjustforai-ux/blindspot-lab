"""Operational CLI.

  python -m app.cli seed-demo            # create demo course + ingest the demo pack via the real pipeline
  python -m app.cli worker               # run the background worker
  python -m app.cli drain                # process all queued jobs once, then exit
  python -m app.cli rebuild <course_id>  # rebuild the knowledge model for a course
  python -m app.cli reset-demo           # delete demo learner accounts and their activity
"""

from __future__ import annotations

import argparse
import sys
import uuid

from sqlalchemy import delete, select

from app.config import REPO_ROOT
from app.db import SessionLocal
from app.logging_setup import configure_logging
from app.models import Course, IngestionJob, SourceFile, User

DEMO_TITLE = "Marketing & Business Analytics: Making Better Decisions with Data"
DEMO_FILES = ["Marketing_Analytics_Primer.pdf", "Unit_Economics_for_Marketers.pptx", "Lecture_03_Price_Cuts.mp4"]
SYSTEM_EMAIL = "demo-instructor@blindspot.local"


def ensure_system_instructor(db) -> User:
    u = db.scalar(select(User).where(User.email == SYSTEM_EMAIL))
    if u is None:
        u = User(email=SYSTEM_EMAIL, display_name="Demo Instructor (synthetic account)", auth_provider="system",
                 is_demo=True)
        db.add(u)
        db.flush()
    return u


def find_demo_course(db) -> Course | None:
    return db.scalar(select(Course).where(Course.is_demo.is_(True)).order_by(Course.created_at))


def seed_demo(process: bool = True) -> uuid.UUID:
    from app.services.courses import add_source_from_path, create_course
    from app.worker import drain

    with SessionLocal() as db:
        instructor = ensure_system_instructor(db)
        course = find_demo_course(db)
        if course is None:
            course = create_course(
                db, instructor, DEMO_TITLE,
                description="Original synthetic demonstration unit: a PDF primer, a slide deck and a narrated "
                "lecture video on revenue, contribution margin, ROAS, CAC/CLV, causation and decisions under "
                "changing assumptions. All companies and figures are fictional.",
                subject="Marketing and Business Analytics", is_demo=True,
            )
        existing = {s.filename for s in db.scalars(select(SourceFile).where(SourceFile.course_id == course.id))}
        for name in DEMO_FILES:
            if name in existing:
                continue
            path = REPO_ROOT / "demo" / "course-materials" / name
            if not path.exists():
                print(f"missing demo file {path}; run demo/scripts/build_course_pack.py", file=sys.stderr)
                continue
            add_source_from_path(db, course, instructor, path)
        db.commit()
        course_id = course.id
    if process:
        n = drain()
        print(f"processed {n} job(s)")
    with SessionLocal() as db:
        for s in db.scalars(select(SourceFile).where(SourceFile.course_id == course_id)):
            print(f"  {s.filename:40s} {s.status:10s} {s.status_detail or ''} {s.error or ''}")
        failed = db.scalars(select(IngestionJob).where(IngestionJob.course_id == course_id,
                                                       IngestionJob.status == "failed")).all()
        for j in failed:
            print(f"  FAILED job {j.kind}: {j.error}", file=sys.stderr)
    print(f"demo course id: {course_id}")
    return course_id


def reset_demo() -> None:
    with SessionLocal() as db:
        n = db.execute(delete(User).where(User.is_demo.is_(True), User.auth_provider == "demo")).rowcount
        db.commit()
    print(f"deleted {n} demo learner account(s) and their activity")


def main(argv: list[str] | None = None) -> None:
    configure_logging()
    ap = argparse.ArgumentParser(prog="blindspot")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("seed-demo")
    p.add_argument("--no-process", action="store_true")
    sub.add_parser("worker")
    sub.add_parser("drain")
    p = sub.add_parser("rebuild")
    p.add_argument("course_id")
    sub.add_parser("reset-demo")
    args = ap.parse_args(argv)
    if args.cmd == "seed-demo":
        seed_demo(process=not args.no_process)
    elif args.cmd == "worker":
        from app.worker import run_forever

        run_forever()
    elif args.cmd == "drain":
        from app.worker import drain

        print(f"processed {drain()} job(s)")
    elif args.cmd == "rebuild":
        from app.services.knowledge.build import rebuild_course_knowledge

        print(rebuild_course_knowledge(uuid.UUID(args.course_id)))
    elif args.cmd == "reset-demo":
        reset_demo()


if __name__ == "__main__":
    main()
