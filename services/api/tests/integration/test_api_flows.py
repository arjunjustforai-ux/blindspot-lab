"""API workflows end to end against the ingested demo course."""

import io
import uuid

from sqlalchemy import func, select

from app.config import REPO_ROOT
from app.core.security import create_access_token
from app.db import SessionLocal
from app.models import ContentUnit, EvaluationResult, EvaluationRun, MasteryHistory, Question, QuestionExposure, User

from .conftest import auth, register

PDF = REPO_ROOT / "demo" / "course-materials" / "Marketing_Analytics_Primer.pdf"


def test_health_and_ready(client, database):
    assert client.get("/api/health").json()["status"] == "ok"
    ready = client.get("/api/ready").json()
    assert ready["status"] == "ready" and ready["checks"]["database"] == "ok"
    assert ready["checks"]["ai_mode"]["external_processing"] is False


def test_auth_required_and_structured_errors(client, database):
    r = client.get("/api/courses")
    assert r.status_code == 401 and r.json()["error"]["code"]
    r = client.post("/api/auth/login", json={"email": "nobody@example.com", "password": "nope-nope"})
    assert r.status_code == 401


def test_upload_lifecycle_dedupe_validation_and_delete(client, database):
    from app.worker import drain

    h = register(client, "Instructor")
    course = client.post("/api/courses", json={"title": "Upload test"}, headers=h).json()
    cid = course["id"]
    bad = client.post(f"/api/courses/{cid}/sources", headers=h,
                      files={"file": ("notes.txt", io.BytesIO(b"hello"), "text/plain")})
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "unsupported_type"
    fake = client.post(f"/api/courses/{cid}/sources", headers=h,
                       files={"file": ("fake.pdf", io.BytesIO(b"not really a pdf"), "application/pdf")})
    assert fake.status_code == 400

    up = client.post(f"/api/courses/{cid}/sources", headers=h,
                     files={"file": (PDF.name, PDF.read_bytes(), "application/pdf")})
    assert up.status_code == 201, up.text
    src = up.json()
    assert src["status"] == "uploaded"
    jobs = client.get(f"/api/courses/{cid}/jobs", headers=h).json()
    assert any(j["kind"] == "ingest_source" and j["status"] == "queued" for j in jobs)

    drain()
    s = client.get(f"/api/sources/{src['id']}", headers=h).json()
    assert s["status"] == "ready" and s["page_count"] == 9
    units = client.get(f"/api/sources/{src['id']}/units", headers=h).json()["units"]
    assert units and all(u["page"] for u in units)

    dup = client.post(f"/api/courses/{cid}/sources", headers=h,
                      files={"file": ("copy.pdf", PDF.read_bytes(), "application/pdf")})
    assert dup.status_code == 409

    # Another user cannot see this private course or its sources
    other = register(client, "Outsider")
    assert client.get(f"/api/courses/{cid}", headers=other).status_code in (403, 404)
    assert client.get(f"/api/sources/{src['id']}/units", headers=other).status_code in (403, 404)

    # Signed media URLs work for members and are rejected when tampered with
    view = client.get(f"/api/sources/{src['id']}/view", headers=h).json()
    assert client.get(view["file_url"]).status_code == 200
    assert client.get(view["file_url"].replace("sig=", "sig=0")).status_code == 403

    assert client.delete(f"/api/sources/{src['id']}", headers=h).status_code == 204
    with SessionLocal() as db:
        n = db.scalar(select(func.count(ContentUnit.id)).where(ContentUnit.source_file_id == uuid.UUID(src["id"])))
    assert n == 0


def test_tutor_grounded_answer_cites_sources_and_refuses_off_topic(client, demo_course_id, demo_learner):
    conv = client.post(f"/api/courses/{demo_course_id}/conversations", json={}, headers=demo_learner).json()
    r = client.post(f"/api/conversations/{conv['id']}/messages", headers=demo_learner,
                    json={"content": "What is break-even ROAS and why isn't a ROAS above 1 enough?"})
    assert r.status_code == 201
    a = r.json()["assistant_message"]
    assert a["grounding_status"] == "grounded"
    cites = [c for c in a["citations"] if not c.get("nearest_only")]
    assert cites and all(c["page"] or c["slide"] or c["start"] is not None for c in cites)
    assert all(f"[{c['id']}]" in a["content"] for c in cites)

    off = client.post(f"/api/conversations/{conv['id']}/messages", headers=demo_learner,
                      json={"content": "What is the boiling point of water at sea level in Kelvin?"}).json()
    assert off["assistant_message"]["grounding_status"] == "refused"

    # Outside knowledge cannot be switched on without a configured generative model
    ext = client.post(f"/api/conversations/{conv['id']}/messages", headers=demo_learner,
                      json={"content": "Explain contribution margin", "allow_external": True}).json()
    assert ext["assistant_message"]["external_content"] in (None, "")


def test_diagnostic_assessment_persists_attempts_and_mastery(client, demo_course_id, demo_learner):
    a = client.post(f"/api/courses/{demo_course_id}/assessments", json={"kind": "diagnostic"}, headers=demo_learner)
    assert a.status_code == 201, a.text
    a = a.json()
    qids = [it["question"]["id"] for it in a["items"]]
    assert len(qids) == len(set(qids)) == 6
    used_as_evidence = 0
    for it in a["items"]:
        q = it["question"]
        resp = {"option_id": q["options"][0]["id"]} if q["question_type"] == "mcq" else (
            {"value": "10"} if q["question_type"] == "numerical" else {"text": "Contribution is price minus variable cost."})
        r = client.post(f"/api/assessments/{a['id']}/answers", headers=demo_learner,
                        json={"question_id": q["id"], "response": resp, "confidence": 3})
        assert r.status_code == 201, r.text
        fb = r.json()["feedback"]
        assert fb["explanation"] and "classification" in fb
        # Answers whose grading is flagged for review are deliberately not used as mastery evidence
        if fb["needs_review"] or fb["is_correct"] is None:
            assert fb["mastery"] is None or fb["mastery"]["weight"] == 0
        else:
            used_as_evidence += 1
    rep = client.post(f"/api/assessments/{a['id']}/complete", headers=demo_learner).json()["report"]
    assert rep["score"]["answered"] == 6 and len(rep["topics"]) == 6 and rep["recommendations"]

    me = client.get("/api/auth/me", headers=demo_learner).json()
    with SessionLocal() as db:
        hist = db.scalar(select(func.count(MasteryHistory.id)).where(MasteryHistory.user_id == uuid.UUID(me["id"])))
        exp = db.scalar(select(func.count(QuestionExposure.id)).where(QuestionExposure.user_id == uuid.UUID(me["id"])))
    assert hist == used_as_evidence >= 4 and exp >= 6

    # A second practice assessment does not repeat the questions already seen
    b = client.post(f"/api/courses/{demo_course_id}/assessments", json={"kind": "practice", "count": 6},
                    headers=demo_learner).json()
    assert not set(qids) & {it["question"]["id"] for it in b["items"]}

    an = client.get(f"/api/courses/{demo_course_id}/analytics", headers=demo_learner).json()
    assert an["totals"]["attempts"] == 6 and an["totals"]["assessed_concepts"] == used_as_evidence


def test_signature_blindspot_loop(client, demo_course_id, demo_learner):
    s = client.post(f"/api/courses/{demo_course_id}/diagnostics", json={"scenario": "contribution_price_cut"},
                    headers=demo_learner).json()
    sc = s["scenario"]
    s = client.post(f"/api/diagnostics/{s['id']}/answer", headers=demo_learner,
                    json={"response": sc["scripted_answer"], "reasoning": sc["scripted_reasoning"],
                          "confidence": sc["scripted_confidence"]}).json()
    answer_fb = next(e for e in s["timeline"] if e["type"] == "answer")["feedback"]
    assert answer_fb["is_correct"] is False
    assert answer_fb["classification"]["category"] == "likely_misconception"
    assert s["stage"] == "probing" and s["hypothesis"]["status"] in ("suspected", "supported")

    for _ in range(3):
        if s["stage"] != "probing":
            break
        probe = s["pending"]["probe"]
        key = next(e["probe"]["key"] for e in s["timeline"] if e["type"] == "probe" and e["probe"]["id"] == probe["id"])
        s = client.post(f"/api/diagnostics/{s['id']}/probe", headers=demo_learner,
                        json={"probe_id": probe["id"], "response": sc["scripted_probe_answers"][key]}).json()
    assert s["stage"] == "repair"
    assert s["hypothesis"]["status"] == "supported" and s["hypothesis"]["posterior"] >= 0.75
    repair = next(e for e in s["timeline"] if e["type"] == "repair")["intervention"]
    assert repair["citations"] and repair["content"]["worked_example"]["answer"] == 100

    s = client.post(f"/api/diagnostics/{s['id']}/continue", headers=demo_learner).json()
    for _ in range(4):
        if s["stage"] == "completed":
            break
        f = s["scenario"]["scripted_followup"]
        resp = {k: v for k, v in f.items() if k in ("value", "option_id")}
        s = client.post(f"/api/diagnostics/{s['id']}/answer", headers=demo_learner, json={"response": resp}).json()
    assert s["stage"] == "completed"
    assert s["hypothesis"]["status"] == "resolving" and s["hypothesis"]["revisit_at"]
    # Probe answers are never mastery evidence; the practice item right after the worked example is down-weighted
    sources = [st["source"] for st in s["mastery_change"]["steps"]]
    assert "probe" not in sources and sources[0] == "diagnostic"
    practice = [st for st in s["mastery_change"]["steps"] if st["source"] == "practice"]
    assert practice and all(st["weight"] < 1 for st in practice)


def test_prerequisite_edits_reject_cycles(client, demo_course_id):
    with SessionLocal() as db:
        instructor = db.scalar(select(User).where(User.email == "demo-instructor@blindspot.local"))
    h = auth(create_access_token(instructor.id))
    g = client.get(f"/api/courses/{demo_course_id}/graph", headers=h).json()
    edge = next(e for e in g["edges"] if e["review_status"] != "rejected")
    r = client.post(f"/api/courses/{demo_course_id}/prerequisites", headers=h,
                    json={"concept_id": edge["prerequisite_id"], "prerequisite_id": edge["concept_id"]})
    assert r.status_code in (400, 409, 422) and "cycle" in r.text.lower()


def test_students_cannot_edit_the_knowledge_graph(client, demo_course_id, demo_learner):
    g = client.get(f"/api/courses/{demo_course_id}/graph", headers=demo_learner).json()
    cid = next(n["concept_id"] for n in g["nodes"] if n["kind"] == "concept")
    assert client.patch(f"/api/concepts/{cid}", json={"name": "Hacked"}, headers=demo_learner).status_code == 403


def test_evaluation_run_is_persisted_once(demo_course_id):
    from app.services.evaluation.runner import create_and_execute

    out = create_and_execute("assessment", export=False)
    with SessionLocal() as db:
        run = db.get(EvaluationRun, uuid.UUID(out["id"]))
        n = db.scalar(select(func.count(EvaluationResult.id)).where(EvaluationResult.run_id == run.id))
        distinct = db.scalar(select(func.count(func.distinct(EvaluationResult.case_key)))
                             .where(EvaluationResult.run_id == run.id))
        verified = db.scalar(select(func.count(Question.id)).where(Question.verification_status == "verified"))
    assert run.status == "succeeded" and run.summary["pool"]["total"] > 0 and run.limitations
    assert n == distinct == len(out["results"]) > 0
    assert verified > 0


def test_tutor_responds_to_learner_state(client, demo_course_id, demo_learner):
    conv = client.post(f"/api/courses/{demo_course_id}/conversations", json={}, headers=demo_learner).json()
    q = {"content": "Why can a price cut need more extra volume than people expect?"}
    fresh = client.post(f"/api/conversations/{conv['id']}/messages", headers=demo_learner, json=q).json()
    ctx = fresh["assistant_message"]["learner_context"]
    assert ctx["concepts"] and all(c["p_mastery"] is None for c in ctx["concepts"])
    assert ctx["suggestion"]["type"] == "knowledge_check"

    # The scripted 25% answer opens a misconception hypothesis; the tutor now points to an investigation.
    s = client.post(f"/api/courses/{demo_course_id}/diagnostics", json={"scenario": "contribution_price_cut"},
                    headers=demo_learner).json()
    sc = s["scenario"]
    client.post(f"/api/diagnostics/{s['id']}/answer", headers=demo_learner,
                json={"response": sc["scripted_answer"], "reasoning": sc["scripted_reasoning"], "confidence": 4})
    after = client.post(f"/api/conversations/{conv['id']}/messages", headers=demo_learner, json=q).json()
    ctx = after["assistant_message"]["learner_context"]
    assert ctx["hypotheses"] and ctx["hypotheses"][0]["misconception_key"] == "contribution_vs_revenue"
    assert ctx["suggestion"]["type"] == "blindspot_session"
    # Grounding is unchanged by learner state: same sources, same answer text
    assert after["assistant_message"]["content"] == fresh["assistant_message"]["content"]
