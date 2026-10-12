"""The demo pack is ingested by the real pipeline with page, slide and timestamp provenance."""

from sqlalchemy import func, select

from app.db import SessionLocal
from app.models import Concept, ConceptPrerequisite, ContentUnit, Question, SourceFile
from app.services.knowledge.graph import is_acyclic


def _sources(course_id):
    with SessionLocal() as db:
        return {s.filename: s for s in db.scalars(select(SourceFile).where(SourceFile.course_id == course_id))}


def _units(source_id):
    with SessionLocal() as db:
        return list(db.scalars(select(ContentUnit).where(ContentUnit.source_file_id == source_id)
                               .order_by(ContentUnit.order_index)))


def test_all_sources_ready(demo_course_id):
    src = _sources(demo_course_id)
    assert set(src) == {"Marketing_Analytics_Primer.pdf", "Unit_Economics_for_Marketers.pptx", "Lecture_03_Price_Cuts.mp4"}
    assert all(s.status == "ready" for s in src.values()), {k: (s.status, s.error) for k, s in src.items()}


def test_pdf_units_have_pages_tables_and_figures(demo_course_id):
    pdf = _sources(demo_course_id)["Marketing_Analytics_Primer.pdf"]
    units = _units(pdf.id)
    assert pdf.page_count == 9
    assert all(u.page_number and 1 <= u.page_number <= 9 for u in units)
    kinds = {u.modality for u in units}
    assert {"pdf_text", "pdf_table", "pdf_figure"} <= kinds
    assert {u.page_number for u in units} == set(range(1, 10))
    fig = next(u for u in units if u.modality == "pdf_figure")
    assert fig.image_storage_key and fig.bbox
    assert any("₹" in u.content for u in units if u.modality == "pdf_table")
    assert all(u.embedding is not None for u in units)


def test_pptx_units_have_slides_notes_and_chart(demo_course_id):
    deck = _sources(demo_course_id)["Unit_Economics_for_Marketers.pptx"]
    units = _units(deck.id)
    assert deck.slide_count == 11
    assert all(u.slide_number and 1 <= u.slide_number <= 11 for u in units)
    kinds = {u.modality for u in units}
    assert {"slide_text", "slide_notes", "slide_chart"} <= kinds
    chart = next(u for u in units if u.modality == "slide_chart")
    assert "Break-even" in chart.content or "ROAS" in chart.content


def test_video_units_have_timestamps_segments_and_frames(demo_course_id):
    vid = _sources(demo_course_id)["Lecture_03_Price_Cuts.mp4"]
    units = _units(vid.id)
    assert 120 < vid.duration_seconds < 140
    transcript = [u for u in units if u.modality == "transcript"]
    frames = [u for u in units if u.modality == "video_frame"]
    assert transcript and frames
    for u in transcript:
        segs = u.extraction_meta["segments"]
        assert u.start_seconds == segs[0]["start"] and u.end_seconds == segs[-1]["end"]
        assert all(s["start"] < s["end"] for s in segs)
    assert all(f.image_storage_key and f.start_seconds is not None for f in frames)
    text = " ".join(u.content for u in transcript).lower()
    assert "contribution margin" in text and "rupees" in text
    assert vid.metadata_json.get("asr_vocabulary_prompt")


def test_knowledge_graph_is_acyclic_and_covers_units(demo_course_id):
    with SessionLocal() as db:
        concepts = list(db.scalars(select(Concept).where(Concept.course_id == demo_course_id)))
        edges = [(e.prerequisite_id, e.concept_id) for e in db.scalars(
            select(ConceptPrerequisite).where(ConceptPrerequisite.course_id == demo_course_id))]
        n_q = db.scalar(select(func.count(Question.id)).where(Question.course_id == demo_course_id,
                                                              Question.verification_status == "verified"))
    assert len([c for c in concepts if c.kind == "concept"]) == 6
    assert is_acyclic([c.id for c in concepts], edges)
    assert n_q >= 40
