"""FastAPI application entrypoint."""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import Response

from app.api import auth, courses, knowledge, learning, media, system, tutor
from app.config import get_settings
from app.core.errors import install_error_handlers
from app.logging_setup import configure_logging

log = logging.getLogger("blindspot.api")
_stop = threading.Event()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    s = get_settings()
    t = None
    if s.run_worker_in_process:
        from app.worker import run_forever

        t = threading.Thread(target=run_forever, args=(_stop,), name="worker", daemon=True)
        t.start()
        log.info("in-process worker started")
    yield
    _stop.set()


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(
        title="Blindspot Lab API",
        version="1.0.0",
        description="Source-grounded multimodal learning platform: ingestion, grounded tutoring, verified adaptive "
        "assessment, misconception diagnosis and repair, Bayesian knowledge tracing and evaluation.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware, allow_origins=s.cors_origins, allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"], allow_headers=["Authorization", "Content-Type"],
    )

    @app.middleware("http")
    async def request_log(request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        t0 = time.perf_counter()
        response: Response = await call_next(request)
        ms = int((time.perf_counter() - t0) * 1000)
        response.headers["x-request-id"] = rid
        if not request.url.path.startswith("/api/media"):
            log.info("request", extra={"rid": rid, "method": request.method, "path": request.url.path,
                                       "status": response.status_code, "ms": ms})
        return response

    install_error_handlers(app)
    for r in (system.router, auth.router, courses.router, media.router, knowledge.router, tutor.router,
              learning.router):
        app.include_router(r)
    return app


app = create_app()
