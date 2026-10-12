"""Retrieval + grounded-generation evaluation on the team-built benchmark.

Runs the production tutor pipeline (`tutor.grounded.answer`) on every case and scores:

  Framework metrics (RAGAS 0.4, non-LLM variants, always computed):
    context_precision  NonLLMContextPrecisionWithReference
    context_recall     NonLLMContextRecall
    (reference contexts = the content units at the annotated source locations)
  Framework metrics needing a judge LLM (RAGAS Faithfulness / ResponseRelevancy):
    computed only when LLM_PROVIDER=openai; otherwise reported as unavailable.
  Judge-free substitutes (clearly labelled):
    faithfulness_nli        share of answer statements entailed by the cited contexts
                            (local DeBERTa-v3 NLI cross-encoder)
    answer_relevancy_embed  cosine(question, answer) with the course embedding model
  Pipeline metrics:
    retrieval_hit_rate@k, mrr@k, source_recall@k, citation_location_accuracy,
    supported_answer_coverage, unsupported_refusal_accuracy, false_refusal_rate
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
import warnings
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import REPO_ROOT, get_settings
from app.models import ContentUnit, SourceFile
from app.services.ai.embeddings import cosine, get_embedder
from app.services.ai.reranker import get_reranker
from app.services.ai.text import normalize_ws, split_sentences
from app.services.tutor.grounded import ANSWER_PROMPT_VERSION, GATE_COVERAGE, GATE_LOGIT, answer

DATASET = REPO_ROOT / "evaluation" / "datasets" / "rag_benchmark_v1.jsonl"
DATASET_VERSION = "v1"
VIDEO_TOLERANCE_S = 3.0


def load_cases(path: Path = DATASET) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def matches(expected: dict[str, Any], filename: str, page: int | None, slide: int | None, start: float | None,
            end: float | None = None) -> bool:
    if expected["file"] != filename:
        return False
    if "page" in expected:
        return page == expected["page"]
    if "slide" in expected:
        return slide == expected["slide"]
    if start is None:
        return False
    lo, hi = expected["start"] - VIDEO_TOLERANCE_S, expected["end"] + VIDEO_TOLERANCE_S
    if end is not None and end > start:  # a retrieved transcript unit spans [start, end]
        return start <= hi and end >= lo
    return lo <= start <= hi


def _reference_units(db: Session, course_id: uuid.UUID, expected: list[dict[str, Any]]) -> list[str]:
    out = []
    for e in expected:
        q = select(ContentUnit).join(SourceFile, SourceFile.id == ContentUnit.source_file_id).where(
            ContentUnit.course_id == course_id, SourceFile.filename == e["file"], ContentUnit.is_generated.is_(False))
        if "page" in e:
            q = q.where(ContentUnit.page_number == e["page"])
        elif "slide" in e:
            q = q.where(ContentUnit.slide_number == e["slide"])
        else:
            q = q.where(ContentUnit.start_seconds <= e["end"] + VIDEO_TOLERANCE_S,
                        ContentUnit.end_seconds >= e["start"] - VIDEO_TOLERANCE_S)
        out.extend(u.content for u in db.scalars(q))
    return out


def _ragas_nonllm(question: str, retrieved: list[str], references: list[str]) -> dict[str, float | None]:
    if not references:
        return {"context_precision": None, "context_recall": None}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        from ragas.dataset_schema import SingleTurnSample
        from ragas.metrics import NonLLMContextPrecisionWithReference, NonLLMContextRecall

        sample = SingleTurnSample(user_input=question, retrieved_contexts=retrieved or [""],
                                  reference_contexts=references)
        cp = asyncio.run(NonLLMContextPrecisionWithReference().single_turn_ascore(sample))
        cr = asyncio.run(NonLLMContextRecall().single_turn_ascore(sample))
    return {"context_precision": round(float(cp), 4), "context_recall": round(float(cr), 4)}


def _statements(text: str) -> list[str]:
    body = re.sub(r"\[S\d+\]", "", text)
    body = re.sub(r"^From your course materials \(quoted directly\):", "", body.strip())
    lines = [ln.strip("> ").strip() for ln in body.split("\n")]
    # Claims only: data lines quoted from tables, charts and figure OCR are excluded (an NLI model
    # cannot judge "| 25% | 4.0x |"-style fragments).
    lines = [ln for ln in lines if ln and not ln.lower().startswith(
        ("related figure", "[figure on", "_note", "text and labels read", "series '", "chart on slide", "table on slide"))
        and "|" not in ln]
    out: list[str] = []
    for ln in lines:
        out.extend(s for s in split_sentences(ln) if len(s.split()) >= 3)
    return out[:12]


def evaluate(db: Session, course_id: uuid.UUID, *, k: int = 6, use_nli: bool = True,
             progress=None, dataset: Path = DATASET) -> tuple[dict[str, Any], list[dict[str, Any]]]:  # noqa: ANN001
    s = get_settings()
    cases = load_cases(dataset)
    emb = get_embedder()
    nli = None
    if use_nli:
        from app.services.evaluation.nli import get_nli

        nli = get_nli()
    results: list[dict[str, Any]] = []
    for i, case in enumerate(cases):
        if progress:
            progress(i / len(cases))
        out = answer(db, course_id, case["question"])
        hits = out.retrieval.get("hits", [])
        retrieved_units = [db.get(ContentUnit, uuid.UUID(h["unit_id"])) for h in hits[:k]]
        retrieved_ctx = [u.content for u in retrieved_units if u is not None]
        exp = case["expected_sources"]
        rank = None
        for r, h in enumerate(hits[:k], start=1):
            u = retrieved_units[r - 1]
            if any(matches(e, h["source"], h["page"], h["slide"], h["start"], u.end_seconds if u else None)
                   for e in exp):
                rank = r
                break
        src_hits = [any(matches(e, h["source"], h["page"], h["slide"], h["start"],
                                (retrieved_units[j].end_seconds if retrieved_units[j] else None))
                        for j, h in enumerate(hits[:k])) for e in exp]
        cites = out.citations
        cite_ok = [any(matches(e, c["filename"], c["page"], c["slide"], c["start"]) for e in exp) for c in cites]
        grounded = out.status == "grounded"
        cited_ctx: list[str] = []
        for c in cites:
            u = db.get(ContentUnit, uuid.UUID(c["unit_id"]))
            if u is not None:
                cited_ctx.append(u.content)
        m: dict[str, Any] = {"status": out.status, "top_logit": out.retrieval.get("top_logit"),
                             "coverage": out.retrieval.get("coverage")}
        if case["should_refuse"]:
            m["refused_correctly"] = not grounded
            passed = not grounded
        else:
            m["answered"] = grounded
            m["retrieval_hit"] = rank is not None
            m["reciprocal_rank"] = round(1.0 / rank, 4) if rank else 0.0
            m["source_recall"] = round(sum(src_hits) / len(src_hits), 4) if src_hits else None
            m["citation_location_accuracy"] = round(sum(cite_ok) / len(cite_ok), 4) if (grounded and cites) else None
            m["any_citation_correct"] = bool(grounded and any(cite_ok))
            refs = _reference_units(db, course_id, exp)
            m.update(_ragas_nonllm(case["question"], retrieved_ctx, refs))
            if grounded:
                stmts = _statements(out.content)
                if nli is not None and stmts:
                    scores = [nli.entailment(cited_ctx, st) for st in stmts]
                    m["faithfulness_nli"] = round(sum(1 for x in scores if x >= 0.5) / len(scores), 4)
                    m["faithfulness_nli_mean_entailment"] = round(sum(scores) / len(scores), 4)
                answer_text = " ".join(stmts) or normalize_ws(out.content)
                m["answer_relevancy_embed"] = round(cosine(emb.embed_query(case["question"]),
                                                           emb.embed_documents([answer_text])[0]), 4)
            passed = bool(grounded and rank is not None and any(cite_ok))
        results.append({
            "case_key": case["case_key"], "category": case["category"], "metrics": m, "passed": passed,
            "output": {"question": case["question"], "answer": out.content, "status": out.status, "mode": out.mode,
                       "citations": [{"label": c["label"], "unit_id": c["unit_id"], "page": c["page"],
                                      "slide": c["slide"], "start": c["start"]} for c in cites],
                       "nearest": [n["label"] for n in out.nearest],
                       "retrieved": [{"source": h["source"], "page": h["page"], "slide": h["slide"],
                                      "start": h["start"], "rerank_logit": h["rerank_logit"]} for h in hits[:k]],
                       "expected_sources": exp, "reference_answer": case["reference_answer"],
                       "cited_contexts": [c[:1500] for c in cited_ctx]},
        })

    answerable = [r for r in results if r["category"] != "unsupported"]
    unsupported = [r for r in results if r["category"] == "unsupported"]

    def mean(key: str, rows: list[dict[str, Any]]) -> float | None:
        vals = [r["metrics"][key] for r in rows if r["metrics"].get(key) is not None]
        return round(sum(vals) / len(vals), 4) if vals else None

    answered = [r for r in answerable if r["metrics"].get("answered")]
    summary: dict[str, Any] = {
        "dataset": dataset.name,
        "n_cases": len(results), "n_answerable": len(answerable), "n_unsupported": len(unsupported),
        "metrics": {
            "context_precision": {"value": mean("context_precision", answerable), "framework": "RAGAS 0.4.3",
                                  "variant": "NonLLMContextPrecisionWithReference"},
            "context_recall": {"value": mean("context_recall", answerable), "framework": "RAGAS 0.4.3",
                               "variant": "NonLLMContextRecall"},
            "faithfulness": {"value": None, "framework": "RAGAS", "variant": "Faithfulness (LLM judge)",
                             "unavailable_reason": "No judge LLM configured (LLM_PROVIDER=local)"},
            "answer_relevancy": {"value": None, "framework": "RAGAS", "variant": "ResponseRelevancy (LLM judge)",
                                 "unavailable_reason": "No judge LLM configured (LLM_PROVIDER=local)"},
            "faithfulness_nli": {"value": mean("faithfulness_nli", answered),
                                 "variant": "share of answer statements entailed by cited contexts "
                                 "(local NLI cross-encoder, threshold 0.5)", "n": len(answered)},
            "answer_relevancy_embed": {"value": mean("answer_relevancy_embed", answered),
                                       "variant": "cosine(question, answer) with bge-small embeddings",
                                       "n": len(answered)},
            "retrieval_hit_rate": {"value": mean("retrieval_hit", [{"metrics": {"retrieval_hit": float(
                r["metrics"]["retrieval_hit"])}} for r in answerable]), "k": k},
            "mrr": {"value": mean("reciprocal_rank", answerable), "k": k},
            "source_recall": {"value": mean("source_recall", answerable), "k": k},
            "citation_location_accuracy": {"value": mean("citation_location_accuracy", answered),
                                           "definition": "share of citations in grounded answers whose page/slide/"
                                           "timestamp matches an annotated location"},
            "answer_with_correct_citation": {"value": round(sum(1 for r in answerable if r["metrics"].get(
                "any_citation_correct")) / len(answerable), 4) if answerable else None},
            "supported_answer_coverage": {"value": round(len(answered) / len(answerable), 4) if answerable else None},
            "false_refusal_rate": {"value": round(1 - len(answered) / len(answerable), 4) if answerable else None},
            "unsupported_refusal_accuracy": {"value": round(sum(1 for r in unsupported if r["metrics"][
                "refused_correctly"]) / len(unsupported), 4) if unsupported else None},
        },
        "by_category": {},
        "config": {"k": k, "gate_logit": GATE_LOGIT, "gate_coverage": GATE_COVERAGE, "answer_mode": "llm" if
                   s.llm_enabled else "extractive", "prompt_version": ANSWER_PROMPT_VERSION,
                   "video_tolerance_s": VIDEO_TOLERANCE_S},
        "models": {"embedding": get_embedder().name, "reranker": get_reranker().name if get_reranker() else None,
                   "nli": nli.name if nli else None, "llm": s.llm_model if s.llm_enabled else None},
    }
    for cat in sorted({r["category"] for r in results}):
        rows = [r for r in results if r["category"] == cat]
        summary["by_category"][cat] = {"n": len(rows), "passed": sum(1 for r in rows if r["passed"])}
    if s.llm_enabled:
        summary["metrics"].update(_ragas_llm_metrics(results))
    return summary, results


def _ragas_llm_metrics(results: list[dict[str, Any]]) -> dict[str, Any]:
    """RAGAS Faithfulness + ResponseRelevancy with the configured OpenAI-compatible model as judge.

    Implemented for deployments with a key; not executed in the repository's recorded runs.
    """
    s = get_settings()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            from langchain_openai import ChatOpenAI, OpenAIEmbeddings
            from ragas import EvaluationDataset, evaluate
            from ragas.embeddings import LangchainEmbeddingsWrapper
            from ragas.llms import LangchainLLMWrapper
            from ragas.metrics import Faithfulness, ResponseRelevancy

            llm = LangchainLLMWrapper(ChatOpenAI(model=s.effective_verifier_model, base_url=s.openai_base_url,
                                                 api_key=s.openai_api_key, temperature=0))
            emb = LangchainEmbeddingsWrapper(OpenAIEmbeddings(model=s.openai_embedding_model,
                                                              base_url=s.openai_base_url, api_key=s.openai_api_key))
            rows = [{"user_input": r["output"]["question"], "response": r["output"]["answer"],
                     "retrieved_contexts": r["output"]["cited_contexts"] or [""]}
                    for r in results if r["metrics"].get("answered")]
            ds = EvaluationDataset.from_list(rows)
            res = evaluate(ds, metrics=[Faithfulness(llm=llm), ResponseRelevancy(llm=llm, embeddings=emb)])
            df = res.to_pandas()
            return {"faithfulness": {"value": round(float(df["faithfulness"].mean()), 4), "framework": "RAGAS",
                                     "variant": "Faithfulness (LLM judge)", "judge": s.effective_verifier_model},
                    "answer_relevancy": {"value": round(float(df["answer_relevancy"].mean()), 4),
                                         "framework": "RAGAS", "variant": "ResponseRelevancy (LLM judge)",
                                         "judge": s.effective_verifier_model}}
    except Exception as e:  # noqa: BLE001
        return {"faithfulness": {"value": None, "unavailable_reason": f"RAGAS LLM evaluation failed: {e}"},
                "answer_relevancy": {"value": None, "unavailable_reason": f"RAGAS LLM evaluation failed: {e}"}}
