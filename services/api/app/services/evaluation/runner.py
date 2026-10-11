"""Evaluation run orchestration, persistence and export.

`execute_run(run_id)` is called by the worker for queued runs (UI/API) and by the CLI.
Every run stores: dataset + version, configuration, model identifiers, prompt
version, seed, timestamps, summary metrics, case-level results and limitations,
both in the database and as JSON under evaluation/results/.
"""

from __future__ import annotations

import json
import platform
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.config import REPO_ROOT, get_settings
from app.db import SessionLocal
from app.models import Course, EvaluationResult, EvaluationRun
from app.services.ai.embeddings import get_embedder
from app.services.ai.reranker import get_reranker

RESULTS_DIR = REPO_ROOT / "evaluation" / "results"

LIMITATIONS = {
    "rag": [
        "Small, self-authored benchmark on a self-authored synthetic course; results describe this pipeline on this "
        "material, not general performance.",
        "RAGAS LLM-judge metrics (faithfulness, answer relevancy) need a configured judge model; in local mode they "
        "are reported as unavailable and judge-free substitutes are shown and labelled as such.",
        "Faithfulness of the local extractive answer mode is high by construction (answers are verbatim quotes); the "
        "NLI check verifies that, it does not show that the selected quotes fully answer the question.",
        "rag_benchmark_v1 was used while fixing pipeline issues; rag_holdout_v1 was written after freezing the "
        "pipeline and is the less biased estimate.",
        "Video locations are annotated from the planned narration timing (±3 s tolerance), not hand-checked "
        "against every Whisper segment.",
    ],
    "assessment": [
        "Bank answer keys are author-provided; the adversarial set tests the verifier's checks, not every key.",
        "Short-answer grading in local mode is a transparent keyword + embedding rubric scorer; it is weaker than an "
        "LLM or human grader and flags borderline answers for review.",
        "Repetition is measured for one simulated learner over six assessments.",
    ],
    "personalization": [
        "Simulated learners follow explicit, hand-set response and learning assumptions; outcomes depend on them and "
        "are not evidence of learning gains for real students.",
        "Both strategies show feedback after every answer; the baseline is a generic random quiz, not a strong "
        "commercial adaptive system.",
        "Probe answers count against the adaptive strategy's interaction budget, which is conservative.",
    ],
}


def _now() -> datetime:
    return datetime.now(UTC)


def model_info() -> dict[str, Any]:
    s = get_settings()
    rr = get_reranker()
    return {"embedding": get_embedder().name, "reranker": rr.name if rr else None,
            "transcription": f"{s.transcription_provider}:{s.whisper_model}",
            "llm": s.llm_model if s.llm_enabled else None, "llm_provider": s.llm_provider,
            "python": platform.python_version()}


def _progress(run_id: uuid.UUID):  # noqa: ANN202
    def f(x: float) -> None:
        with SessionLocal() as db:
            r = db.get(EvaluationRun, run_id)
            if r:
                r.progress = round(min(max(x, 0.0), 1.0), 3)
                db.commit()
    return f


def execute_run(run_id: uuid.UUID, *, learners_per_profile: int = 15, export: bool = True) -> dict[str, Any]:
    from app.services.evaluation import assessment as assess_eval
    from app.services.evaluation import personalization as pers_eval
    from app.services.evaluation import rag as rag_eval

    with SessionLocal() as db:
        run = db.get(EvaluationRun, run_id)
        assert run is not None
        kind, course_id = run.kind, run.course_id
        if course_id is None:
            c = db.scalar(select(Course).where(Course.is_demo.is_(True)))
            course_id = c.id if c else None
        if course_id is None:
            raise RuntimeError("no course to evaluate")
        run.status, run.started_at, run.course_id = "running", run.started_at or _now(), course_id
        run.model_info = model_info()
        db.commit()

    prog = _progress(run_id)
    extra: dict[str, Any] = {}
    with SessionLocal() as db:
        if kind == "rag":
            summary, results = rag_eval.evaluate(db, course_id, progress=lambda x: prog(0.7 * x))
            hold_path = rag_eval.REPO_ROOT / "evaluation" / "datasets" / "rag_holdout_v1.jsonl"
            if hold_path.exists():
                hs, hr = rag_eval.evaluate(db, course_id, dataset=hold_path, progress=lambda x: prog(0.7 + 0.3 * x))
                for r in hr:
                    r["category"] = "holdout:" + r["category"]
                results += hr
                extra["holdout"] = hs
            dataset, version, prompt_version, seed = "rag_benchmark", "v1", rag_eval.ANSWER_PROMPT_VERSION, None
        elif kind == "assessment":
            summary, results = assess_eval.evaluate(db, course_id)
            dataset, version, prompt_version, seed = "question_verification+grading", "v1", None, 7
        else:
            summary, results = pers_eval.evaluate(db, course_id, learners_per_profile=learners_per_profile,
                                                  progress=prog)
            dataset, version, prompt_version, seed = "simulated_learners", "v1", None, summary.get("seed")
        db.rollback()  # evaluation side effects (simulated users, generated questions) are discarded
    summary = {**summary, **extra}

    with SessionLocal() as db:
        run = db.get(EvaluationRun, run_id)
        assert run is not None
        run.summary = summary
        run.dataset_name, run.dataset_version, run.prompt_version, run.seed = dataset, version, prompt_version, seed
        run.config = {"course_id": str(course_id), **({"learners_per_profile": learners_per_profile}
                                                        if kind == "personalization" else {})}
        run.limitations = LIMITATIONS[kind]
        for r in results:
            db.add(EvaluationResult(run_id=run_id, case_key=r["case_key"], category=r.get("category"),
                                    metrics=_jsonable(r.get("metrics", {})), output=_jsonable(r.get("output", {})),
                                    passed=r.get("passed")))
        run.status, run.progress, run.finished_at = "succeeded", 1.0, _now()
        db.commit()
        out = {"id": str(run.id), "kind": kind, "dataset": dataset, "dataset_version": version,
               "model_info": run.model_info, "prompt_version": prompt_version, "seed": seed,
               "started_at": run.started_at.isoformat() if run.started_at else None,
               "finished_at": run.finished_at.isoformat(), "config": run.config, "summary": summary,
               "limitations": run.limitations, "results": _jsonable(results)}
    if export:
        export_run(out)
    return out


def _jsonable(x: Any) -> Any:
    return json.loads(json.dumps(x, default=str))


def export_run(out: dict[str, Any]) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = out["finished_at"][:19].replace(":", "").replace("-", "")
    path = RESULTS_DIR / f"{out['kind']}_{stamp}.json"
    path.write_text(json.dumps(out, indent=1, ensure_ascii=False))
    latest = RESULTS_DIR / f"latest_{out['kind']}.json"
    latest.write_text(json.dumps({k: v for k, v in out.items() if k != "results"} | {"results_file": path.name},
                                 indent=1, ensure_ascii=False))
    return path


def create_and_execute(kind: str, *, learners_per_profile: int = 15) -> dict[str, Any]:
    with SessionLocal() as db:
        c = db.scalar(select(Course).where(Course.is_demo.is_(True)))
        r = EvaluationRun(kind=kind, status="queued", course_id=c.id if c else None)
        db.add(r)
        db.commit()
        rid = r.id
    return execute_run(rid, learners_per_profile=learners_per_profile)
