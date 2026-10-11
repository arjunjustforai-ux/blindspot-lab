"""Loads the instructor-reviewable concept ontology and misconception catalogue."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import MisconceptionDefinition

DATA = Path(__file__).resolve().parents[2] / "data"


@lru_cache
def ontology() -> dict[str, Any]:
    return json.loads((DATA / "concept_ontology.json").read_text())


@lru_cache
def misconception_catalog() -> dict[str, Any]:
    return json.loads((DATA / "misconception_catalog.json").read_text())


def catalog_entry(key: str) -> dict[str, Any] | None:
    return next((e for e in misconception_catalog()["entries"] if e["key"] == key), None)


def ontology_concept(key: str) -> dict[str, Any] | None:
    return next((c for c in ontology()["concepts"] if c["key"] == key), None)


def sync_misconception_definitions(db: Session) -> dict[str, MisconceptionDefinition]:
    """Upsert catalogue entries into the database (version-aware)."""
    cat = misconception_catalog()
    existing = {m.key: m for m in db.scalars(select(MisconceptionDefinition))}
    out: dict[str, MisconceptionDefinition] = {}
    for e in cat["entries"]:
        m = existing.get(e["key"])
        if m is None:
            m = MisconceptionDefinition(key=e["key"])
            db.add(m)
        m.title = e["title"]
        m.description = e["description"]
        m.concept_keys = e["concept_keys"]
        m.detection_cues = e.get("detection_cues", [])
        m.competing_interpretations = e.get("competing_interpretations", [])
        m.diagnostic_probes = e.get("diagnostic_probes", [])
        m.repair = e.get("repair", {})
        m.support_query = e["support_query"]
        m.version = cat.get("version", 1)
        m.review_status = "draft"
        out[e["key"]] = m
    db.flush()
    return out
