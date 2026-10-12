# Evaluation

**Source of truth:** [evaluation/results/RESULTS.md](../evaluation/results/RESULTS.md), generated from the recorded run files in `evaluation/results/` (and visible, case by case, in the app's Evaluation Lab). Numbers quoted below are copied from those files; if they ever disagree, the files win.

## How to reproduce

```bash
cd services/api && set -a && . ../../.env && set +a
.venv/bin/python ../../evaluation/scripts/run_evaluation.py --kinds rag assessment personalization --learners-per-profile 15
.venv/bin/python ../../evaluation/scripts/make_report.py
```

Each run is stored in `evaluation_runs` / `evaluation_results` with its dataset version, model identifiers, prompt version, seed and every case-level output, and exported to `evaluation/results/<kind>_<timestamp>.json`. Runs can also be queued from the Evaluation Lab. Approximate CPU time: RAG ~1–2 min, assessment ~5 s, personalization ~11 min (45 learners × 2 arms).

## 1. Retrieval, grounding and citations

**Framework.** RAGAS 0.4.3. `NonLLMContextPrecisionWithReference` and `NonLLMContextRecall` are always computed; the reference contexts are the content units at each case's annotated source locations. RAGAS `Faithfulness` and `ResponseRelevancy` need a judge LLM: they run automatically when `LLM_PROVIDER=openai` and a key are configured, and are otherwise reported as **unavailable** (that is the case for the recorded runs). Two judge-free substitutes are reported and labelled as such: NLI faithfulness (share of answer statements entailed by the cited contexts, using the local `cross-encoder/nli-deberta-v3-xsmall` with SummaC-style sentence windows, threshold 0.5) and embedding answer relevancy (cosine of question and answer).

**Test sets** (`evaluation/datasets/`, written by the team after reading the demo materials):

| Set | Cases | Composition |
|---|---|---|
| `rag_benchmark_v1` | 49 | 17 factual, 6 diagram/figure/table, 6 numerical, 4 multi-source, 4 citation challenges (the answer is in exactly one modality), 12 off-material |
| `rag_holdout_v1` | 15 | 7 factual, 3 diagram, 1 numerical, 4 off-material; written after the tutor pipeline was frozen |
| `dev_queries_v1` | 15 | used only to set the grounding-gate thresholds; never scored |

Each case lists acceptable source locations (PDF page, slide, or video seconds from the narration plan, matched within ±3 s), a reference answer and reference phrases, or `should_refuse`.

**Pipeline metrics.** Retrieval hit rate / MRR / source recall at k = 6 (an annotated location among the retrieved units); citation-location accuracy (share of citations in grounded answers whose page, slide or timestamp matches an annotated location); answers with a correct citation (share of answerable questions answered with at least one correct citation); answer coverage and false refusal rate on answerable questions; refusal accuracy on off-material questions.

**Final results** (run `bc8674bc`, local mode):

| Metric | Benchmark (49) | Held-out (15) |
|---|---|---|
| RAGAS context precision | 91.0% | 86.4% |
| RAGAS context recall | 67.9% | 68.5% |
| RAGAS faithfulness / answer relevancy (LLM judge) | unavailable | unavailable |
| Faithfulness, local NLI substitute | 99.3% | 100.0% |
| Answer relevancy, embedding substitute | 79.8% | 80.5% |
| Retrieval hit rate @6 | 100.0% | 100.0% |
| Citation-location accuracy | 83.8% | 88.3% |
| Answers with a correct citation | 100.0% | 90.9% |
| Answer coverage (supported questions) | 100.0% | 90.9% |
| Refusal accuracy (off-material) | 100.0% (12/12) | 100.0% (4/4) |

**Reading these numbers.**
* The NLI faithfulness is near 100% largely by construction: local-mode answers are verbatim quotes. It confirms that the composer quotes what it cites; it says nothing about whether the quotes fully answer the question (embedding relevancy ≈ 80% and context recall ≈ 68% are the more informative signals).
* Context recall is limited because answers quote a few sentences, while the reference phrases sometimes span several units.
* The held-out failure is a false refusal on a table lookup ("which channel has the highest average order value?"): the table is retrieved, but no sentence states the comparison, so the extractive composer cannot quote one.
* The benchmark was used while fixing generic pipeline problems, so its numbers are optimistic; the held-out set is the better estimate but is small (11 answerable questions).

**Ingestion quality** (same run): page coverage 100% (9/9 pages), slide coverage 100% (11/11), every unit carries a page/slide/timestamp anchor, and the lecture transcript has a word error rate of 9.1% against the 351-word narration script synthesised into the MP4 (`faster-whisper base.en` with the on-screen vocabulary prompt; without the prompt it was 10.0%, and `small.en` reached 7.4% in a side experiment).

### Run history and changes

| When (UTC, 2026-10-12) | What |
|---|---|
| 2026-10-11, preliminary | Development runs, including the held-out set. Discarded: the CLI and the API worker both executed the same queued run, duplicating case rows. Fixed (CLI runs are created as already running; result writes are idempotent). |
| 00:51, run `2f367559` | First run after the code freeze. |
| change | Video citations were opening up to ~30 s early: Whisper had emitted one segment per 30-second decoding window on this audio. Transcripts are now split into sentence-level segments using Whisper's word timings (`ai/transcription.py`). Generic change; no benchmark or held-out case was edited. |
| 01:07, run `bc8674bc` | Final run (above). Citation-location accuracy 76.1% → 83.8% (benchmark) and 85.0% → 88.3% (held-out); answers with a correct citation 89.2% → 100% and 81.8% → 90.9%. Other metrics within ±3 points. |

Because the held-out set was scored before that change, it is not strictly unseen for it; we report both runs (the report's *Run history* table is generated from the run files).

## 2. Assessment quality

Run `3eb45a8b` (seed 7) on the demo course's verified pool and two labelled datasets:

| Check | Result |
|---|---|
| Generated questions passing verification | 97/97 in the pool |
| Computed answer keys passing the independent plug-back check | 64/64 template questions |
| Verifier catches deliberately flawed drafts (`question_verification_v1`: three wrong numeric keys, duplicate options, key not among the options, unsupported premise, a cited unit that does not exist, an exact duplicate, an unclear stem, a numerical item without tolerance, an MCQ with two options, an off-topic premise) | 12/12 |
| Verifier wrongly rejects sound drafts | 0/6 |
| Question's cited source is tagged to its concept | 99.0% |
| Numerical grading vs labels (`grading_cases_v1`) | 17/18 (number words such as "four and a half" are not parsed) |
| Short-answer grading vs labels (local rubric) | 14/15; 20% of answers flagged for review; one partially correct answer passed |
| Exact question repeats over 6 consecutive adaptive assessments | 0% (uniform random selection from the same pool: 17.6%) |

The verification and grading sets are small and self-authored; bank answer keys are author-provided.

## 3. Personalization with simulated learners

`services/api/app/services/evaluation/personalization.py`. Each simulated learner has a hidden ground truth (which of the six concepts it knows, which catalogued misconceptions it holds) and answers through an explicit response model: slip 0.10 (+0.03 per difficulty level), uniform MCQ guessing, 5% numeric guessing, the misconception's signature answer with probability 0.8 when it holds that misconception. It learns from feedback with fixed probabilities (0.12 per feedback, 0.03 without prerequisites, 0.30 from a worked example), fixes a misconception with probability 0.08 after generic feedback and 0.6 after a targeted repair, and forgets with probability 0.03 per session. Three profiles: **A** strong, **B** mixed with selected misconceptions, **C** weak prerequisites; 15 learners each.

Two arms with the **same hidden learner** and the same budget (5 sessions × 8 interactions; probe answers count against the adaptive budget; both arms show feedback after every answer):
* **Adaptive**: the real code paths: diagnostic onboarding, recommender, adaptive selection, Blindspot investigations (probe → repair → practice → transfer), BKT updates.
* **Baseline**: a generic quiz of uniformly random verified questions (repeats across sessions allowed, as in a static bank), no diagnosis or targeting.

Outcomes are measured on 14 held-out post-test items never served during learning, plus a retention test after a simulated delay (two sessions without practice, with forgetting applied each time). Everything runs against the real database inside a savepoint that is rolled back per learner.

**Results** (run `cc2270df`, seed 2026). Paired adaptive − baseline differences with 95% percentile bootstrap intervals over learners:

| Metric | A strong | B mixed | C weak prerequisites |
|---|---|---|---|
| Held-out post-test accuracy | +3.3 pp [−6.2, +13.8] | **+17.6 pp [+6.7, +28.1]** | +11.4 pp [−1.9, +23.8] |
| Retention accuracy | +2.4 pp [−8.1, +13.8] | +7.1 pp [−0.5, +14.3] | +15.7 pp [0.0, +28.6] |
| Concepts truly known: gain | +7.8 pp [−1.1, +17.8] | **+12.2 pp [+4.4, +20.0]** | +17.8 pp [−1.1, +33.3] |
| Initial misconceptions resolved | +30.0 pp [0.0, +70.0] (n = 5) | +18.8 pp [−7.3, +43.7] | **+24.4 pp [+6.5, +42.9]** |
| Mastery calibration, Brier (lower is better) | +0.047 [−0.024, +0.115] | +0.048 [−0.070, +0.156] | **+0.096 [+0.032, +0.166]** (worse) |
| Exact question repeats | **−16.2 pp [−19.2, −13.0]** | **−18.7 pp [−20.0, −17.0]** | **−15.7 pp [−17.8, −13.5]** |

Bold: the interval excludes zero. The per-arm means, weak-concept identification, misconception precision/recall, targeting precision and probe counts are in RESULTS.md.

**Reading these numbers.**
* Under these assumptions, the adaptive loop most clearly helps the learner with misconceptions (B) and resolves more misconceptions for the learner with weak prerequisites (C); for the strong learner (A) differences are small and uncertain. Question repetition is consistently near zero.
* The adaptive arm is **worse** on mastery calibration and on weak-concept identification and misconception recall. We think this is because it concentrates its budget on weak concepts and investigations and so observes the concepts a learner already knows less often; we have not tested that explanation.
* The baseline is deliberately simple (a random quiz), not a strong adaptive competitor, and the results depend on the simulation's hand-set learning probabilities, in particular the assumption that a targeted repair fixes a misconception far more often (0.6) than generic feedback (0.08). **These are not evidence of learning gains for real students.**
