"""Build evaluation/results/RESULTS.md and charts from the latest recorded runs.

Every number comes from evaluation/results/latest_<kind>.json (exported by run_evaluation.py);
nothing is typed in by hand. Run after run_evaluation.py:

    python evaluation/scripts/make_report.py
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

RESULTS = Path(__file__).resolve().parents[1] / "results"

# Validated categorical pair (light surface): slot 1 = Blindspot Lab, slot 2 = comparison.
BLUE, ORANGE = "#2a78d6", "#eb6834"
SURFACE, INK, MUTED, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"


def load(kind: str) -> dict[str, Any] | None:
    p = RESULTS / f"latest_{kind}.json"
    return json.loads(p.read_text()) if p.exists() else None


def pct(v: float | None, nd: int = 1) -> str:
    return "n/a" if v is None else f"{v * 100:.{nd}f}%"


def style(ax: plt.Axes) -> None:
    ax.set_facecolor(SURFACE)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=9, length=0)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def rag_chart(run: dict[str, Any]) -> str:
    m, h = run["summary"]["metrics"], run["summary"].get("holdout", {}).get("metrics", {})
    rows = [("Context precision (RAGAS)", "context_precision"), ("Context recall (RAGAS)", "context_recall"),
            ("Faithfulness (local NLI)", "faithfulness_nli"), ("Retrieval hit rate", "retrieval_hit_rate"),
            ("Citation-location accuracy", "citation_location_accuracy"),
            ("Answer coverage (supported)", "supported_answer_coverage"),
            ("Refusal accuracy (unsupported)", "unsupported_refusal_accuracy")]
    rows = [(lbl, k) for lbl, k in rows if (m.get(k) or {}).get("value") is not None]
    fig, ax = plt.subplots(figsize=(8, 0.55 * len(rows) + 1.2), dpi=160)
    fig.patch.set_facecolor(SURFACE)
    style(ax)
    y = range(len(rows))
    bh = 0.36
    bench = [m[k]["value"] for _, k in rows]
    hold = [(h.get(k) or {}).get("value") for _, k in rows]
    ax.barh([i - bh / 2 - 0.02 for i in y], bench, height=bh, color=BLUE,
            label=f"Benchmark v1 ({run['summary']['n_cases']} cases)")
    if any(v is not None for v in hold):
        ax.barh([i + bh / 2 + 0.02 for i in y], [v or 0 for v in hold], height=bh, color=ORANGE,
                label=f"Held-out v1 ({run['summary']['holdout']['n_cases']} cases)")
    for i, (b, ho) in enumerate(zip(bench, hold)):
        ax.text(b + 0.01, i - bh / 2 - 0.02, f"{b * 100:.0f}%", va="center", fontsize=8, color=INK)
        if ho is not None:
            ax.text(ho + 0.01, i + bh / 2 + 0.02, f"{ho * 100:.0f}%", va="center", fontsize=8, color=INK)
    ax.set_yticks(list(y), [lbl for lbl, _ in rows], color=INK, fontsize=9)
    ax.invert_yaxis()
    ax.set_xlim(0, 1.12)
    ax.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0, decimals=0))
    ax.set_title("Retrieval and grounding", loc="left", fontsize=11, color=INK, fontweight="bold", pad=24)
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1.0), ncol=2, frameon=False, fontsize=8, labelcolor=MUTED)
    fig.tight_layout()
    out = RESULTS / "rag_metrics.png"
    fig.savefig(out, facecolor=SURFACE)
    plt.close(fig)
    return out.name


def personalization_chart(run: dict[str, Any]) -> str:
    s = run["summary"]
    profiles = sorted(s["by_profile"])
    metrics = [("post_test_accuracy", "Held-out post-test accuracy", True),
               ("misconceptions_resolved_rate", "Initial misconceptions resolved", True),
               ("mastery_brier", "Mastery calibration (Brier, lower is better)", False),
               ("exact_repeat_rate", "Exact question repeats (lower is better)", True)]
    fig, axes = plt.subplots(1, len(metrics), figsize=(13, 3.4), dpi=160)
    fig.patch.set_facecolor(SURFACE)
    for ax, (key, title, is_rate) in zip(axes, metrics):
        style(ax)
        ax.grid(axis="x", visible=False)
        ax.grid(axis="y", color=GRID, linewidth=0.8)
        xs = range(len(profiles))
        w = 0.36
        for off, arm, color, lbl in ((-w / 2 - 0.02, "adaptive", BLUE, "Blindspot Lab (adaptive)"),
                                     (w / 2 + 0.02, "baseline", ORANGE, "Random-quiz baseline")):
            vals = [s["by_profile"][p].get(arm, {}).get(key, {}).get("mean") for p in profiles]
            sds = [s["by_profile"][p].get(arm, {}).get(key, {}).get("sd") or 0 for p in profiles]
            ax.bar([x + off for x in xs], [v or 0 for v in vals], width=w, color=color, label=lbl,
                   yerr=sds, error_kw={"elinewidth": 0.8, "ecolor": MUTED, "capsize": 2})
        ax.set_xticks(list(xs), [p.replace("_", "\n", 1).replace("_", " ") for p in profiles], fontsize=8, color=INK)
        ax.set_ylim(bottom=0)
        if is_rate:
            ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0, decimals=0))
        ax.set_title(title, fontsize=9, color=INK, loc="left")
    axes[0].legend(loc="upper left", bbox_to_anchor=(0, -0.22), ncol=2, frameon=False, fontsize=8, labelcolor=MUTED)
    fig.suptitle(f"Simulated learners ({s['learners_per_profile']} per profile, mean ± sd); behaviour under stated "
                 "assumptions, not real-student outcomes", x=0.01, ha="left", fontsize=9, color=MUTED)
    fig.tight_layout()
    out = RESULTS / "personalization.png"
    fig.savefig(out, facecolor=SURFACE, bbox_inches="tight")
    plt.close(fig)
    return out.name


PAIRED = [("post_test_accuracy", "Held-out post-test accuracy", True), ("retention_accuracy", "Retention accuracy", True),
          ("known_gain", "Concepts truly known: gain (end − start)", True),
          ("misconceptions_resolved_rate", "Initial misconceptions resolved", True),
          ("mastery_brier", "Mastery calibration, Brier (negative = adaptive better)", False),
          ("exact_repeat_rate", "Exact question repeats (negative = adaptive better)", True)]


def paired_differences(per: dict[str, Any], n_boot: int = 10_000, seed: int = 7) -> list[str]:
    """Adaptive − baseline per simulated learner (same hidden learner in both arms), with a 95% bootstrap CI."""
    import random

    p = RESULTS / per["results_file"]
    if not p.exists():
        return []
    rows: dict[str, dict[str, dict[str, Any]]] = {}
    for r in json.loads(p.read_text())["results"]:
        learner, arm = r["case_key"].rsplit("-", 1)
        m = dict(r["metrics"])
        if m.get("true_known_end") is not None and m.get("true_known_start") is not None:
            m["known_gain"] = m["true_known_end"] - m["true_known_start"]
        rows.setdefault(learner, {})[arm] = m
    rng = random.Random(seed)
    profiles = sorted({k.rsplit("-", 1)[0] for k in rows})
    out = ["### Paired differences (adaptive − baseline)", "",
           f"Each simulated learner is run through both arms with the same hidden state, so differences are paired. "
           f"Mean difference with a 95% percentile bootstrap interval ({n_boot:,} resamples of learners, seed {seed}); "
           "an interval that excludes 0 indicates a consistent difference under the simulation's assumptions.", "",
           "| Metric | " + " | ".join(profiles) + " |", "|---|" + "---|" * len(profiles)]
    for key, label, is_rate in PAIRED:
        cells = []
        for prof in profiles:
            diffs = [v["adaptive"][key] - v["baseline"][key] for k, v in rows.items()
                     if k.startswith(prof + "-") and "adaptive" in v and "baseline" in v
                     and v["adaptive"].get(key) is not None and v["baseline"].get(key) is not None]
            if len(diffs) < 3:
                cells.append("—")
                continue
            boots = sorted(sum(rng.choice(diffs) for _ in diffs) / len(diffs) for _ in range(n_boot))
            mean, lo, hi = sum(diffs) / len(diffs), boots[int(0.025 * n_boot)], boots[int(0.975 * n_boot) - 1]
            def f(x: float, rate: bool = is_rate) -> str:
                x = 0.0 if abs(x) < 5e-4 else x
                return f"{x * 100:+.1f} pp" if rate else f"{x:+.3f}"
            cells.append(f"{f(mean)} [{f(lo)}, {f(hi)}] (n={len(diffs)})")
        out.append(f"| {label} | " + " | ".join(cells) + " |")
    return out + [""]


def rag_history() -> list[str]:
    """Key metrics of every recorded RAG run in this folder, oldest first."""
    runs = []
    for p in sorted(RESULTS.glob("rag_*.json")):
        d = json.loads(p.read_text())
        runs.append((d.get("finished_at", "")[:16], d["id"][:8], d["summary"]))
    if len(runs) < 2:
        return []
    keys = [("citation_location_accuracy", "citation-location acc."),
            ("answer_with_correct_citation", "answers w/ correct citation"),
            ("context_precision", "context precision"), ("context_recall", "context recall"),
            ("supported_answer_coverage", "answer coverage"), ("unsupported_refusal_accuracy", "refusal accuracy")]
    out = ["### Run history", "", "| Run (finished, UTC) | Set | " + " | ".join(lbl for _, lbl in keys) + " |",
           "|---|---|" + "---|" * len(keys)]
    for when, rid, s in runs:
        for name, m in (("benchmark", s["metrics"]), ("held-out", s.get("holdout", {}).get("metrics", {}))):
            out.append(f"| `{rid}` {when} | {name} | " + " | ".join(pct((m.get(k) or {}).get("value")) for k, _ in keys) + " |")
    return out + ["", "Changes between runs are listed in docs/EVALUATION.md.", ""]


def run_header(run: dict[str, Any]) -> list[str]:
    mi = run.get("model_info") or {}
    models = ", ".join(f"{k}: `{v}`" for k, v in mi.items() if v and k in ("embedding", "reranker", "llm",
                                                                              "transcription", "generation"))
    return [f"- Run `{run['id']}` finished {run['finished_at']}; dataset `{run['dataset']}` {run['dataset_version']}"
            + (f"; seed {run['seed']}" if run.get("seed") is not None else ""),
            f"- Models: {models or 'n/a'}",
            f"- Case-level results: `{run.get('results_file', 'n/a')}`", ""]


def metric_row(name: str, m: dict[str, Any] | None, hold: dict[str, Any] | None = None) -> str:
    m = m or {}
    v = "unavailable" if m.get("value") is None else pct(m["value"])
    hv = "" if hold is None else ("unavailable" if (hold or {}).get("value") is None else pct(hold["value"]))
    note = m.get("unavailable_reason") or " · ".join(x for x in (m.get("framework"), m.get("variant")) if x)
    return f"| {name} | {v} |" + (f" {hv} |" if hold is not None else "") + f" {note} |"


def main() -> None:
    rag, ass, per = load("rag"), load("assessment"), load("personalization")
    md = ["# Evaluation results", "",
          "Generated by `evaluation/scripts/make_report.py` from the latest recorded runs in this folder. "
          "Re-run with `python evaluation/scripts/run_evaluation.py` then this script. Methodology and caveats: "
          "[docs/EVALUATION.md](../../docs/EVALUATION.md).", ""]
    if rag:
        s, m = rag["summary"], rag["summary"]["metrics"]
        h = s.get("holdout", {}).get("metrics", {})
        md += ["## 1. Retrieval, grounding and citations", ""] + run_header(rag)
        md += [f"Benchmark: {s['n_cases']} cases ({s['n_answerable']} answerable, {s['n_unsupported']} off-material). "
               f"Held-out: {s.get('holdout', {}).get('n_cases', 0)} cases written after the pipeline was frozen "
               "(the less biased estimate).", "", f"![RAG metrics]({rag_chart(rag)})", "",
               "| Metric | Benchmark | Held-out | Framework / note |", "|---|---|---|---|"]
        names = {"context_precision": "Context precision", "context_recall": "Context recall",
                 "faithfulness": "Faithfulness (LLM judge)", "answer_relevancy": "Answer relevancy (LLM judge)",
                 "faithfulness_nli": "Faithfulness (local NLI substitute)",
                 "answer_relevancy_embed": "Answer relevancy (embedding substitute)",
                 "retrieval_hit_rate": "Retrieval hit rate @k", "mrr": "MRR @k", "source_recall": "Source recall @k",
                 "citation_location_accuracy": "Citation-location accuracy",
                 "answer_with_correct_citation": "Answers citing a correct location",
                 "supported_answer_coverage": "Answer coverage on supported questions",
                 "false_refusal_rate": "False refusal rate (lower is better)",
                 "unsupported_refusal_accuracy": "Refusal accuracy on unsupported questions"}
        md += [metric_row(names.get(k, k), m[k], h.get(k, {})) for k in m]
        md += ["", "Pass rate by category (benchmark): " + ", ".join(
            f"{k.replace('_', ' ')} {v['passed']}/{v['n']}" for k, v in s["by_category"].items()), ""]
        md += rag_history()
        ing = s.get("ingestion")
        if ing:
            md += ["### Ingestion quality", "", "| Source | Check | Value |", "|---|---|---|"]
            for fn, info in ing["sources"].items():
                for k in ("page_coverage", "slide_coverage", "video_span_coverage", "asr_wer"):
                    if k in info:
                        md.append(f"| {fn} | {k.replace('_', ' ')} | {pct(info[k])} |")
                if "transcription_model" in info:
                    md.append(f"| {fn} | transcription model | `{info['transcription_model']}` "
                              f"({info.get('asr_reference_words', '?')} reference words) |")
            md += [f"| all | units with page/slide/timestamp provenance | {pct(ing['units_with_provenance'])} |", ""]
        md += ["Limitations recorded with this run:", ""] + [f"- {x}" for x in rag["limitations"]] + [""]
    if ass:
        s = ass["summary"]
        md += ["## 2. Assessment quality", ""] + run_header(ass)
        md += ["| Check | Result |", "|---|---|",
               f"| Generated questions passing verification | {s['pool']['verified']}/{s['pool']['total']} "
               f"({pct(s['pool']['valid_question_rate'])}) |",
               f"| Computed answer keys passing independent plug-back | {pct(s['answer_keys']['plug_back_pass_rate'])} "
               f"of {s['answer_keys']['template_questions']} |",
               f"| Verifier: deliberately flawed drafts caught | {pct(s['verifier']['flaw_detection_rate'])} "
               f"of {s['verifier']['flawed']} |",
               f"| Verifier: sound drafts wrongly rejected | {pct(s['verifier']['false_rejection_rate'])} "
               f"of {s['verifier']['sound']} |",
               f"| Cited source tagged to the question's concept | {pct(s['source_tags']['source_concept_agreement'])} |",
               f"| Numerical grading accuracy (labelled responses) | {pct(s['numeric_grading']['accuracy'])} "
               f"of {s['numeric_grading']['n']} |",
               f"| Short-answer grading accuracy (local rubric) | {pct(s['short_answer_grading']['accuracy'])} of "
               f"{s['short_answer_grading']['n']}; {pct(s['short_answer_grading']['flagged_for_review'])} flagged |",
               f"| Exact repeats across {s['repetition']['sessions']} adaptive assessments | "
               f"{pct(s['repetition']['adaptive_exact_repeat_rate'])} (uniform random: "
               f"{pct(s['repetition']['random_exact_repeat_rate'])}) |", "",
               "Pool composition: " + ", ".join(f"{k} {v}" for k, v in s["pool"]["by_type"].items()) + "; difficulty "
               + ", ".join(f"{k}: {v}" for k, v in sorted(s["pool"]["by_difficulty"].items())) + ".", "",
               "Limitations recorded with this run:", ""] + [f"- {x}" for x in ass["limitations"]] + [""]
    if per:
        s = per["summary"]
        md += ["## 3. Personalization (simulated learners)", ""] + run_header(per)
        md += [f"{s['learners_per_profile']} simulated learners per profile, {s['posttest_items']} held-out post-test "
               "items, same interaction budget for both arms. **These are simulations under hand-set assumptions, not "
               "evidence of learning gains for real students.**", "",
               f"![Personalization]({personalization_chart(per)})", ""]
        keys = ["post_test_accuracy", "retention_accuracy", "misconceptions_resolved_rate", "true_known_end",
                "mastery_brier", "weak_concept_identification_accuracy", "gap_precision", "gap_recall",
                "exact_repeat_rate", "family_repeat_rate", "targeting_precision", "blindspot_sessions", "probes"]
        profiles = sorted(s["by_profile"])
        md += ["| Metric | " + " | ".join(f"{p} adaptive | {p} baseline" for p in profiles) + " |",
               "|---|" + "---|" * (2 * len(profiles))]
        for k in keys:
            cells = []
            for p in profiles:
                for arm in ("adaptive", "baseline"):
                    v = s["by_profile"][p].get(arm, {}).get(k)
                    if not v:
                        cells.append("—")
                    elif k in ("mastery_brier", "blindspot_sessions", "probes"):
                        cells.append(f"{v['mean']:.2f} ± {v['sd']:.2f}")
                    else:
                        cells.append(f"{v['mean'] * 100:.1f}% ± {v['sd'] * 100:.1f}")
            md.append(f"| {k.replace('_', ' ')} | " + " | ".join(cells) + " |")
        md += [""] + paired_differences(per)
        md += ["Profiles: " + "; ".join(f"`{k}` {v}" for k, v in s["profiles"].items()) + ".", "",
               "Simulation assumptions:", ""]
        md += [f"- {k.replace('_', ' ')}: {v}" for k, v in s["assumptions"].items()]
        md += ["", "Limitations recorded with this run:", ""] + [f"- {x}" for x in per["limitations"]] + [""]
    (RESULTS / "RESULTS.md").write_text("\n".join(md))
    print(f"wrote {RESULTS / 'RESULTS.md'}")


if __name__ == "__main__":
    main()
