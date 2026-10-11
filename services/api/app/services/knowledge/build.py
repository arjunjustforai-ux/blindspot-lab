"""Course knowledge model construction.

Runs after ingestion (as a `rebuild_knowledge` job):
  1. Activate catalogue concepts that the course's own sources support.
  2. Derive additional concepts from document structure (headings, slide titles).
  3. Tag every content unit to concepts (similarity + alias + heading evidence).
  4. Propose prerequisite edges (catalogue, structural heuristics, optional LLM),
     rejecting any edge that would create a cycle.
  5. Activate misconceptions whose concepts are supported by retrieved sources.
  6. Build the verified question pool for the course.
"""

from __future__ import annotations

import logging
import re
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

import numpy as np
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import (
    Concept,
    ConceptPrerequisite,
    ConceptSource,
    ContentUnit,
    Course,
    CourseMisconception,
    IngestionJob,
    SourceFile,
)
from app.services.ai import llm
from app.services.ai.embeddings import get_embedder
from app.services.ai.text import normalize_ws, split_sentences
from app.services.knowledge import graph
from app.services.knowledge.catalog import misconception_catalog, ontology, sync_misconception_definitions

log = logging.getLogger(__name__)

SKIP_HEADINGS = re.compile(
    r"^(about this|contents|table of contents|glossary|references|bibliography|index|appendix|summary|key takeaways|"
    r"acknowledg|preface|introduction$|slide \d+)",
    re.IGNORECASE,
)
MISCONCEPTION_MIN_LOGIT = -3.5


def slugify(s: str) -> str:
    s = re.sub(r"^[\d.\s]+", "", s.lower())
    s = re.sub(r"^(chapter|section|lecture|part)\s+\d+[.:]?\s*", "", s)
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:120] or "concept"


def clean_heading(h: str) -> str:
    h = re.sub(r"^(chapter|section|part)\s+\d+[.:]?\s*", "", h.strip(), flags=re.IGNORECASE)
    return re.sub(r"^\d+(\.\d+)*\s+", "", h).strip()


def _alias_re(aliases: list[str]) -> re.Pattern[str] | None:
    al = [a for a in aliases if a]
    if not al:
        return None
    return re.compile(r"(?<![a-z0-9])(" + "|".join(re.escape(a.lower()) for a in al) + r")(?![a-z0-9])")


def _set_progress(job_id: uuid.UUID | None, stage: str, frac: float) -> None:
    if not job_id:
        return
    with SessionLocal() as db:
        j = db.get(IngestionJob, job_id)
        if j:
            j.stage, j.progress = stage[:60], frac
            db.commit()


def rebuild_course_knowledge(course_id: uuid.UUID, job_id: uuid.UUID | None = None) -> dict[str, Any]:
    with SessionLocal() as db:
        course = db.get(Course, course_id)
        if course is None:
            raise ValueError("course not found")
        course.knowledge_status = "building"
        db.commit()

    _set_progress(job_id, "Identifying concepts", 0.05)
    with SessionLocal() as db:
        stats = _build_concepts_and_tags(db, course_id)
        db.commit()
    _set_progress(job_id, "Proposing prerequisites", 0.35)
    with SessionLocal() as db:
        stats["prerequisites"] = _build_prerequisites(db, course_id)
        db.commit()
    _set_progress(job_id, "Activating misconception catalogue", 0.45)
    with SessionLocal() as db:
        stats["misconceptions"] = _activate_misconceptions(db, course_id)
        db.commit()
    _set_progress(job_id, "Building verified question pool", 0.55)
    from app.services.assessment.supply import ensure_question_pool

    with SessionLocal() as db:
        stats["questions"] = ensure_question_pool(db, course_id)
        db.commit()
    with SessionLocal() as db:
        course = db.get(Course, course_id)
        assert course is not None
        course.knowledge_status = "ready"
        course.knowledge_built_at = datetime.now(UTC)
        db.commit()
    log.info("knowledge rebuilt", extra={"course_id": str(course_id), **{k: str(v) for k, v in stats.items()}})
    return stats


# ---------------------------------------------------------------------------


def _ready_units(db: Session, course_id: uuid.UUID) -> list[tuple[ContentUnit, SourceFile]]:
    return list(
        db.execute(
            select(ContentUnit, SourceFile)
            .join(SourceFile, SourceFile.id == ContentUnit.source_file_id)
            .where(ContentUnit.course_id == course_id, SourceFile.status == "ready")
            .order_by(SourceFile.created_at, ContentUnit.order_index)
        ).all()
    )


def _upsert_concept(db: Session, course_id: uuid.UUID, existing: dict[str, Concept], **kw: Any) -> Concept:
    slug = kw["slug"]
    c = existing.get(slug)
    if c is None:
        c = Concept(course_id=course_id, **kw)
        db.add(c)
        existing[slug] = c
    else:
        for k, v in kw.items():
            if k in ("review_status",) and c.review_status != "proposed":
                continue  # keep instructor decisions
            if k == "name" and c.origin == "instructor":
                continue
            setattr(c, k, v)
        c.updated_at = datetime.now(UTC)
    return c


def _build_concepts_and_tags(db: Session, course_id: uuid.UUID) -> dict[str, Any]:
    rows = _ready_units(db, course_id)
    units = [u for u, _ in rows]
    existing = {c.slug: c for c in db.scalars(select(Concept).where(Concept.course_id == course_id))}
    onto = ontology()
    texts_lower = [((u.heading or "") + " " + u.content).lower() for u in units]
    headings_lower = [(u.heading or "").lower() for u in units]

    # 1. catalogue activation --------------------------------------------------
    active: list[dict[str, Any]] = []
    for oc in onto["concepts"]:
        rx = _alias_re(oc["strong_aliases"])
        if rx is None:
            continue
        unit_hits = sum(1 for t in texts_lower if rx.search(t))
        heading_hits = sum(1 for h in set(headings_lower) if rx.search(h))
        if unit_hits >= 2 or heading_hits >= 1:
            active.append({**oc, "_support": unit_hits})

    topic_objs: dict[str, Concept] = {}
    concept_by_key: dict[str, Concept] = {}
    for t in onto["topics"]:
        if not any(c["topic"] == t["key"] for c in active):
            continue
        topic_objs[t["key"]] = _upsert_concept(
            db, course_id, existing, slug=f"topic-{slugify(t['name'])}", name=t["name"], kind="topic",
            description=t["description"], catalog_key=t["key"], origin="catalog", aliases=[], order_index=0,
        )
    db.flush()
    for oc in sorted(active, key=lambda c: c["order"]):
        c = _upsert_concept(
            db, course_id, existing, slug=slugify(oc["name"]), name=oc["name"], kind="concept",
            description=oc["description"], catalog_key=oc["key"], origin="catalog", aliases=oc["aliases"],
            order_index=oc["order"], parent_id=topic_objs[oc["topic"]].id,
        )
        concept_by_key[oc["key"]] = c
    db.flush()
    for oc in active:
        for sc in oc.get("subconcepts", []):
            rx = _alias_re(sc["aliases"])
            if rx and sum(1 for t in texts_lower if rx.search(t)) >= 1:
                _upsert_concept(
                    db, course_id, existing, slug=slugify(sc["name"]), name=sc["name"], kind="subconcept",
                    description=None, catalog_key=sc["key"], origin="catalog", aliases=sc["aliases"],
                    order_index=oc["order"] * 10, parent_id=concept_by_key[oc["key"]].id,
                )
    db.flush()

    # 2. structural concepts from headings ----------------------------------
    all_concepts = [c for c in existing.values() if c.kind != "topic"]
    alias_res = {c.id: _alias_re([c.name.lower(), *[a.lower() for a in (c.aliases or [])]]) for c in all_concepts}
    heading_order: dict[str, int] = {}
    heading_parent: dict[str, str | None] = {}
    for u in units:
        sp = u.section_path or []
        if u.modality.startswith("pdf") and len(sp) >= 1:
            for lvl, h in enumerate(sp[:2]):
                heading_order.setdefault(h, len(heading_order))
                heading_parent.setdefault(h, sp[0] if lvl == 1 else None)
        elif u.modality == "slide_text" and u.heading:
            heading_order.setdefault(u.heading, len(heading_order))
            heading_parent.setdefault(u.heading, (sp[0] if sp else None))

    structural_added = 0
    if not active:  # no catalogue domain match: structure drives the model
        for h, order in sorted(heading_order.items(), key=lambda x: x[1]):
            name = clean_heading(h)
            if not name or SKIP_HEADINGS.match(name) or len(name) < 4:
                continue
            parent_h = heading_parent.get(h)
            if parent_h is None:
                # top-level heading (or deck title) -> topic
                _upsert_concept(db, course_id, existing, slug=f"topic-{slugify(name)}", name=name, kind="topic",
                                description=None, origin="heading", aliases=[], order_index=order)
                continue
        db.flush()
        topics_by_name = {c.name: c for c in existing.values() if c.kind == "topic"}
        for h, order in sorted(heading_order.items(), key=lambda x: x[1]):
            parent_h = heading_parent.get(h)
            name = clean_heading(h)
            if parent_h is None or not name or SKIP_HEADINGS.match(name) or len(name) < 4:
                continue
            parent = topics_by_name.get(clean_heading(parent_h))
            if parent is None:
                parent = _upsert_concept(db, course_id, existing, slug=f"topic-{slugify(parent_h)}",
                                         name=clean_heading(parent_h) or parent_h, kind="topic", description=None,
                                         origin="heading", aliases=[], order_index=order)
                topics_by_name[parent.name] = parent
                db.flush()
            _upsert_concept(db, course_id, existing, slug=slugify(name), name=name, kind="concept",
                            description=None, origin="heading", aliases=[name.lower()], order_index=order,
                            parent_id=parent.id)
            structural_added += 1
        db.flush()

    concepts = [c for c in existing.values() if c.kind in ("concept", "subconcept") and c.review_status != "rejected"]
    if not concepts:
        # Last resort: one concept per source so every unit can still be tagged.
        for _, sf in rows:
            name = sf.filename.rsplit(".", 1)[0].replace("_", " ")
            _upsert_concept(db, course_id, existing, slug=slugify(name), name=name, kind="concept",
                            description=None, origin="heading", aliases=[], order_index=0)
        db.flush()
        concepts = [c for c in existing.values() if c.kind in ("concept", "subconcept")]

    # descriptions for structural concepts (extractive: first sentences under the heading)
    for c in concepts:
        if c.description:
            continue
        rx = alias_res.get(c.id) or _alias_re([c.name.lower()])
        for u in units:
            if (u.heading and clean_heading(u.heading).lower() == c.name.lower()) or (rx and rx.search(u.content.lower())):
                sents = split_sentences(u.content)
                if sents:
                    c.description = " ".join(sents[:2])[:600]
                    break

    # 3. embeddings & tagging -------------------------------------------------
    embedder = get_embedder()
    vecs = embedder.embed_documents([f"{c.name}. {c.description or ''} {' '.join(c.aliases or [])}" for c in concepts])
    for c, v in zip(concepts, vecs):
        c.embedding = v
    db.flush()

    unit_ids = [u.id for u in units]
    if unit_ids:
        db.execute(delete(ConceptSource).where(ConceptSource.content_unit_id.in_(unit_ids),
                                               ConceptSource.method != "instructor"))
    cmat = np.array(vecs, dtype=np.float32)
    rxs = {c.id: _alias_re([c.name.lower(), *[a.lower() for a in (c.aliases or []) if len(a) > 3]]) for c in concepts}
    main = [i for i, c in enumerate(concepts) if c.kind == "concept"]
    subs = [i for i, c in enumerate(concepts) if c.kind == "subconcept"]
    tag_count = 0
    for u in units:
        if u.embedding is None:
            continue
        uvec = np.array(u.embedding, dtype=np.float32)
        sims = cmat @ uvec
        low = ((u.heading or "") + " " + u.content).lower()
        head_low = (u.heading or "").lower()
        scores = {}
        methods = {}
        for i, c in enumerate(concepts):
            sc = float(sims[i])
            m = "similarity"
            rx = rxs.get(c.id)
            if rx and rx.search(low):
                sc += 0.08
                m = "alias"
            if rx and head_low and rx.search(head_low):
                sc += 0.08
                m = "heading"
            scores[i], methods[i] = sc, m
        pool = main or subs
        best = max(pool, key=lambda i: scores[i])
        chosen = {best}
        for i in pool:
            if i != best and scores[i] >= scores[best] - 0.04 and scores[i] >= 0.62:
                chosen.add(i)
        for i in subs:
            if methods[i] in ("alias", "heading") and scores[i] >= 0.6:
                chosen.add(i)
        for i in chosen:
            db.add(ConceptSource(concept_id=concepts[i].id, content_unit_id=u.id, relevance=round(scores[i], 4),
                                 method=methods[i], is_primary=(i == best)))
            tag_count += 1
    db.flush()
    return {"catalog_concepts": len(active), "structural_concepts": structural_added,
            "concepts": len(concepts), "units_tagged": len(units), "tags": tag_count}


def _build_prerequisites(db: Session, course_id: uuid.UUID) -> dict[str, int]:
    concepts = list(db.scalars(select(Concept).where(Concept.course_id == course_id, Concept.kind == "concept")))
    by_key = {c.catalog_key: c for c in concepts if c.catalog_key}
    edges_rows = list(db.scalars(select(ConceptPrerequisite).where(ConceptPrerequisite.course_id == course_id)))
    edges = {(e.prerequisite_id, e.concept_id) for e in edges_rows if e.review_status != "rejected"}
    rejected = {(e.prerequisite_id, e.concept_id) for e in edges_rows if e.review_status == "rejected"}
    added = skipped_cycle = 0

    def add(p: Concept, c: Concept, origin: str, conf: float, why: str) -> None:
        nonlocal added, skipped_cycle
        pair = (p.id, c.id)
        if pair in edges or pair in rejected or p.id == c.id:
            return
        if graph.would_create_cycle(edges, pair):
            skipped_cycle += 1
            return
        db.add(ConceptPrerequisite(course_id=course_id, concept_id=c.id, prerequisite_id=p.id, origin=origin,
                                   confidence=conf, rationale=why, review_status="proposed"))
        edges.add(pair)
        added += 1

    onto = {c["key"]: c for c in ontology()["concepts"]}
    for key, c in by_key.items():
        for pk in onto.get(key, {}).get("prerequisites", []):
            if pk in by_key:
                add(by_key[pk], c, "catalog", 0.8,
                    f"Catalogue: '{by_key[pk].name}' is defined as a prerequisite of '{c.name}'.")

    # Structural heuristic for non-catalogue concepts: an earlier concept whose name is
    # mentioned in a later concept's tagged units is proposed as a prerequisite.
    structural = [c for c in concepts if not c.catalog_key]
    if structural:
        tagged: dict[uuid.UUID, list[str]] = defaultdict(list)
        for cs, u in db.execute(
            select(ConceptSource, ContentUnit).join(ContentUnit, ContentUnit.id == ConceptSource.content_unit_id)
            .where(ConceptSource.concept_id.in_([c.id for c in structural]), ConceptSource.is_primary.is_(True))
        ).all():
            tagged[cs.concept_id].append(u.content.lower())
        ordered = sorted(structural, key=lambda c: c.order_index)
        for i, later in enumerate(ordered):
            for earlier in ordered[:i]:
                rx = _alias_re([earlier.name.lower()])
                mentions = sum(1 for t in tagged.get(later.id, []) if rx and rx.search(t))
                if mentions >= 1:
                    add(earlier, later, "heuristic", min(0.4 + 0.1 * mentions, 0.7),
                        f"'{earlier.name}' appears earlier and is referenced {mentions}x in '{later.name}' material.")

    if llm.llm_available() and len(concepts) >= 2:
        try:
            _llm_prerequisites(db, course_id, concepts, add)
        except (llm.LLMError, llm.LLMUnavailable) as e:
            log.warning("LLM prerequisite proposal failed: %s", e)
    db.flush()
    all_nodes = [c.id for c in concepts]
    assert graph.is_acyclic(all_nodes, edges), "prerequisite graph must be acyclic"
    return {"added": added, "skipped_cycle": skipped_cycle, "total": len(edges)}


def _llm_prerequisites(db: Session, course_id: uuid.UUID, concepts: list[Concept], add) -> None:
    listing = "\n".join(f"{i + 1}. {c.name}: {normalize_ws(c.description or '')[:200]}" for i, c in enumerate(concepts))
    data, _ = llm.chat(
        [
            {"role": "system", "content": "You map prerequisite relationships between course concepts. Only use the "
             "concept list provided. " + llm.UNTRUSTED_NOTICE},
            {"role": "user", "content": f"<source>\n{listing}\n</source>\nReturn JSON {{\"edges\": [{{\"prerequisite\": "
             "int, \"concept\": int, \"rationale\": str, \"confidence\": number 0-1}}]}} listing only direct, "
             "necessary prerequisites (at most 2 per concept)."},
        ],
        operation="propose_prerequisites", prompt_version="prereq-v1", course_id=course_id, max_tokens=600,
    )
    for e in (data or {}).get("edges", [])[:30]:
        try:
            p, c = concepts[int(e["prerequisite"]) - 1], concepts[int(e["concept"]) - 1]
        except (KeyError, ValueError, IndexError, TypeError):
            continue
        conf = float(e.get("confidence", 0.5))
        if conf >= 0.5:
            add(p, c, "llm", min(conf, 0.9), str(e.get("rationale", ""))[:500])


def _activate_misconceptions(db: Session, course_id: uuid.UUID) -> dict[str, int]:
    from app.services.retrieval.hybrid import retrieve

    defs = sync_misconception_definitions(db)
    concepts = {c.catalog_key: c for c in db.scalars(select(Concept).where(Concept.course_id == course_id,
                                                                             Concept.kind == "concept"))}
    rows = {r.misconception_id: r for r in db.scalars(select(CourseMisconception).where(
        CourseMisconception.course_id == course_id))}
    n_active = 0
    for e in misconception_catalog()["entries"]:
        md = defs[e["key"]]
        row = rows.get(md.id) or CourseMisconception(course_id=course_id, misconception_id=md.id)
        db.add(row)
        cks = [k for k in e["concept_keys"] if k in concepts]
        if not cks:
            row.active, row.reason, row.supporting_unit_ids, row.support_score = (
                False, "The related concept is not covered by this course's sources.", [], 0.0)
            continue
        row.concept_id = concepts[cks[0]].id
        res = retrieve(db, course_id, e["support_query"], k=4)
        strong = [h for h in res.hits if (h.rerank_logit or -99) >= MISCONCEPTION_MIN_LOGIT]
        row.supporting_unit_ids = [str(h.unit.id) for h in strong[:3]]
        row.support_score = round(max((h.support for h in res.hits), default=0.0), 4)
        row.active = bool(strong)
        row.reason = (f"Supported by {len(strong)} retrieved source unit(s)." if strong
                      else "Retrieved sources do not clearly support the distinction this entry targets.")
        n_active += int(row.active)
    db.flush()
    return {"active": n_active, "catalogue": len(defs)}
