"""Course and source-file operations shared by the API and the CLI."""

from __future__ import annotations

import hashlib
import mimetypes
import re
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import BinaryIO

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.errors import APIError, bad_request, conflict
from app.models import Course, CourseMembership, IngestionJob, SourceFile, User
from app.services.ingestion.pipeline import enqueue_ingest, enqueue_rebuild
from app.services.storage import get_storage

ALLOWED = {
    ".pdf": ("pdf", {"application/pdf"}),
    ".pptx": ("pptx", {"application/vnd.openxmlformats-officedocument.presentationml.presentation"}),
    ".mp4": ("video", {"video/mp4"}),
    ".m4v": ("video", {"video/mp4", "video/x-m4v"}),
    ".mov": ("video", {"video/quicktime"}),
    ".webm": ("video", {"video/webm"}),
}
MAGIC = {
    "pdf": [b"%PDF-"],
    "pptx": [b"PK\x03\x04"],
    "video": [b"ftyp", b"\x1a\x45\xdf\xa3"],  # ISO-BMFF (mp4/mov) at offset 4, or EBML (webm)
}


def create_course(db: Session, user: User, title: str, description: str | None = None, subject: str | None = None,
                  *, is_demo: bool = False) -> Course:
    c = Course(title=title.strip(), description=description, subject=subject, created_by=user.id, is_demo=is_demo)
    db.add(c)
    db.flush()
    db.add(CourseMembership(course_id=c.id, user_id=user.id, role="owner"))
    db.flush()
    return c


def sanitize_filename(name: str) -> str:
    name = Path(name).name
    name = re.sub(r"[^A-Za-z0-9._ \-()]+", "_", name).strip(" .") or "upload"
    return name[:200]


def _sniff(path: Path, modality: str) -> bool:
    head = path.open("rb").read(16)
    if modality == "video":
        return head[4:8] == b"ftyp" or head.startswith(b"\x1a\x45\xdf\xa3")
    return any(head.startswith(m) for m in MAGIC[modality])


def add_source_from_stream(db: Session, course: Course, user: User | None, filename: str, stream: BinaryIO,
                           content_type: str | None = None) -> SourceFile:
    s = get_settings()
    safe = sanitize_filename(filename)
    ext = Path(safe).suffix.lower()
    if ext not in ALLOWED:
        raise bad_request(f"Unsupported file type '{ext or '?'}'. Upload PDF, PPTX or MP4/MOV/WEBM lecture videos.",
                          code="unsupported_type")
    modality, mimes = ALLOWED[ext]
    limit_mb = s.max_video_mb if modality == "video" else s.max_document_mb
    limit = limit_mb * 1024 * 1024
    h = hashlib.sha256()
    size = 0
    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
        tmp_path = Path(tmp.name)
        while chunk := stream.read(1024 * 1024):
            size += len(chunk)
            if size > limit:
                tmp.close()
                tmp_path.unlink(missing_ok=True)
                raise APIError(413, "file_too_large", f"File exceeds the {limit_mb} MB limit for {modality} uploads")
            h.update(chunk)
            tmp.write(chunk)
    try:
        if size == 0:
            raise bad_request("The uploaded file is empty", code="empty_file")
        if not _sniff(tmp_path, modality):
            raise bad_request(f"File content does not look like a valid {ext} file", code="invalid_file")
        digest = h.hexdigest()
        dup = db.scalar(select(SourceFile).where(SourceFile.course_id == course.id, SourceFile.sha256 == digest))
        if dup is not None:
            raise conflict(f"This file is already in the course as '{dup.filename}'", code="duplicate_source",
                           details={"source_id": str(dup.id)})
        sid = uuid.uuid4()
        key = f"courses/{course.id}/sources/{sid}/original{ext}"
        mime = (content_type if content_type in mimes else None) or mimetypes.guess_type(safe)[0] or sorted(mimes)[0]
        get_storage().put_file(key, tmp_path, mime)
    finally:
        tmp_path.unlink(missing_ok=True)
    src = SourceFile(id=sid, course_id=course.id, uploaded_by=user.id if user else None, filename=safe,
                     modality=modality, mime_type=mime, size_bytes=size, sha256=digest, storage_key=key,
                     status="uploaded", status_detail="Queued for processing")
    db.add(src)
    db.flush()
    enqueue_ingest(db, src)
    db.flush()
    return src


def add_source_from_path(db: Session, course: Course, user: User | None, path: Path) -> SourceFile:
    with path.open("rb") as f:
        return add_source_from_stream(db, course, user, path.name, f)


def delete_source(db: Session, source: SourceFile) -> None:
    course_id = source.course_id
    get_storage().delete_prefix(f"courses/{course_id}/sources/{source.id}")
    db.delete(source)
    db.flush()
    course = db.get(Course, course_id)
    if course is not None:
        course.knowledge_status = "stale"
    enqueue_rebuild(db, course_id)


def reindex_source(db: Session, source: SourceFile) -> IngestionJob:
    running = db.scalar(select(IngestionJob).where(IngestionJob.source_file_id == source.id,
                                                    IngestionJob.status.in_(["queued", "running"])))
    if running:
        raise conflict("This source is already being processed", code="already_processing")
    source.status = "uploaded"
    source.status_detail = "Queued for re-indexing"
    source.error = None
    return enqueue_ingest(db, source)


def copy_course_file(src: Path, dst_dir: Path) -> Path:
    dst_dir.mkdir(parents=True, exist_ok=True)
    out = dst_dir / src.name
    shutil.copyfile(src, out)
    return out
