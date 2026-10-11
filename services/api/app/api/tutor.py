from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter
from fastapi.responses import Response
from sqlalchemy import select

from app.config import get_settings
from app.core.deps import DB, CurrentUser, require_course
from app.core.errors import conflict, not_found
from app.models import Assessment, AssessmentItem, Concept, Conversation, Question, TutorMessage
from app.schemas import ConversationIn, KnowledgeCheckIn, MessageIn
from app.services.assessment.sessions import view as assessment_view
from app.services.learning.attempts import record_exposure
from app.services.tutor.grounded import answer

router = APIRouter(prefix="/api", tags=["tutor"])


def _msg(m: TutorMessage) -> dict[str, Any]:
    return {"id": str(m.id), "role": m.role, "content": m.content, "grounding_status": m.grounding_status,
            "answer_mode": m.answer_mode, "allow_external": m.allow_external, "citations": m.citations,
            "external_content": m.external_content, "concept_ids": m.concept_ids, "support_score": m.support_score,
            "created_at": m.created_at.isoformat()}


def _conv(db: DB, user: CurrentUser, conversation_id: uuid.UUID) -> Conversation:
    c = db.get(Conversation, conversation_id)
    if c is None or c.user_id != user.id:
        raise not_found("Conversation")
    require_course(db, c.course_id, user)
    return c


@router.get("/courses/{course_id}/conversations")
def list_conversations(course_id: uuid.UUID, db: DB, user: CurrentUser) -> list[dict[str, Any]]:
    require_course(db, course_id, user)
    rows = db.scalars(select(Conversation).where(Conversation.course_id == course_id, Conversation.user_id == user.id)
                      .order_by(Conversation.created_at.desc()))
    return [{"id": str(c.id), "title": c.title, "created_at": c.created_at.isoformat()} for c in rows]


@router.post("/courses/{course_id}/conversations", status_code=201)
def create_conversation(course_id: uuid.UUID, body: ConversationIn, db: DB, user: CurrentUser) -> dict[str, Any]:
    require_course(db, course_id, user)
    c = Conversation(course_id=course_id, user_id=user.id, title=body.title or "New conversation")
    db.add(c)
    db.commit()
    return {"id": str(c.id), "title": c.title, "created_at": c.created_at.isoformat(), "messages": []}


@router.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: uuid.UUID, db: DB, user: CurrentUser) -> dict[str, Any]:
    c = _conv(db, user, conversation_id)
    msgs = db.scalars(select(TutorMessage).where(TutorMessage.conversation_id == c.id).order_by(TutorMessage.created_at))
    s = get_settings()
    return {"id": str(c.id), "course_id": str(c.course_id), "title": c.title, "created_at": c.created_at.isoformat(),
            "messages": [_msg(m) for m in msgs],
            "mode": {"generation": "llm" if s.llm_enabled else "extractive", "model": s.llm_model if s.llm_enabled
                     else None, "external_mode_available": s.llm_enabled}}


@router.delete("/conversations/{conversation_id}", status_code=204, response_class=Response, response_model=None)
def delete_conversation(conversation_id: uuid.UUID, db: DB, user: CurrentUser) -> None:
    c = _conv(db, user, conversation_id)
    db.delete(c)
    db.commit()


@router.post("/conversations/{conversation_id}/messages", status_code=201)
def send_message(conversation_id: uuid.UUID, body: MessageIn, db: DB, user: CurrentUser) -> dict[str, Any]:
    c = _conv(db, user, conversation_id)
    history = [m.content for m in db.scalars(select(TutorMessage).where(
        TutorMessage.conversation_id == c.id, TutorMessage.role == "user").order_by(TutorMessage.created_at))]
    um = TutorMessage(conversation_id=c.id, role="user", content=body.content.strip(), allow_external=body.allow_external)
    db.add(um)
    if c.title == "New conversation":
        c.title = body.content.strip()[:80]
    db.flush()
    a = answer(db, c.course_id, body.content, user_id=user.id, history=history[-3:],
               allow_external=body.allow_external)
    am = TutorMessage(conversation_id=c.id, role="assistant", content=a.content, grounding_status=a.status,
                      answer_mode=a.mode, allow_external=body.allow_external,
                      citations=a.citations + [{**n, "nearest_only": True} for n in a.nearest],
                      external_content=a.external_content, concept_ids=a.concept_ids, support_score=a.support_score,
                      ai_log_id=a.log_id)
    db.add(am)
    db.commit()
    return {"user_message": _msg(um), "assistant_message": _msg(am), "retrieval": a.retrieval}


@router.post("/conversations/{conversation_id}/knowledge-check", status_code=201)
def knowledge_check(conversation_id: uuid.UUID, body: KnowledgeCheckIn, db: DB, user: CurrentUser) -> dict[str, Any]:
    """A scored check on the concept just discussed: the only way tutoring updates mastery."""
    c = _conv(db, user, conversation_id)
    concept_id = body.concept_id
    if concept_id is None and body.message_id is not None:
        m = db.get(TutorMessage, body.message_id)
        if m is None or m.conversation_id != c.id:
            raise not_found("Message")
        concept_id = uuid.UUID(m.concept_ids[0]) if m.concept_ids else None
    if concept_id is None:
        raise conflict("No concept to check yet: ask a grounded question first", code="no_concept")
    concept = db.get(Concept, concept_id)
    if concept is None or concept.course_id != c.course_id:
        raise not_found("Concept")
    if concept.kind == "subconcept" and concept.parent_id:
        concept = db.get(Concept, concept.parent_id)
    from app.services.assessment.selection import select_questions

    picks, log = select_questions(db, user.id, c.course_id, kind="practice", concept_ids=[concept.id], count=1,
                                  difficulty=None, question_types=["mcq", "numerical"])
    if not picks:
        raise conflict("No unseen verified question is available for this concept", code="pool_exhausted")
    a = Assessment(course_id=c.course_id, user_id=user.id, kind="tutor_check", status="in_progress",
                   config={"conversation_id": str(c.id), "concept_ids": [str(concept.id)]}, selection_log=log)
    db.add(a)
    db.flush()
    q: Question = picks[0].question
    db.add(AssessmentItem(assessment_id=a.id, question_id=q.id, position=0, selection_reason=picks[0].reason))
    record_exposure(db, user.id, q.id)
    db.commit()
    return assessment_view(db, a)
