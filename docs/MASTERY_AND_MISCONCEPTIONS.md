# Assessment, learner model and misconception engine

All parameters below are **design assumptions** chosen by the team, not values fitted to student data. They live as named constants in the code cited next to each section, so they can be inspected and changed.

## 1. Verified, adaptive assessment

### Question sources (`services/assessment/`)
* **Parametric templates** (`templates.py`, 19 templates over the six concepts): a seeded generator picks realistic numbers and contexts, computes the key, writes the worked steps, and records **misconception signatures**: the exact answer each misconception predicts (for the signature scenario, 25% is what "preserve revenue" gives; the key is 100%).
* **Course question bank** (`demo/course-materials/question_bank.json`, 33 items, 4 held out for evaluation): MCQ, short-answer (with rubric key points) and numerical items, each anchored to source passages.
* **Definitional items** extracted from the sources (MCQ/short answer), and, in generative mode, model-drafted questions.

### Verification (`verification.py`): nothing reaches a learner unless it passes
`schema` (type-specific fields complete) · `answer_key` (template keys must pass an **independent plug-back** that substitutes the answer into the problem's defining condition, e.g. "new contribution × new volume = old contribution", rather than re-running the formula, in `plugback.py`) · `signatures` (misconception answers differ from the key) · `options_distinct` (≥ 3 distinct MCQ options, one keyed) · `clarity` · `source_support` (retrieved or anchored course units support the premise; stored as `question_sources`) · `duplicate_exact` (content hash) and `duplicate_near` (embedding cosine ≥ 0.985 against the pool) · `llm_verifier` (generative mode: a second model answers blind and must agree with the key and judge it unambiguous). The full report is stored on the question.

Each question carries concept, sub-concept, difficulty (1–3), type, family, source locations, signatures and origin; the UI shows them on every item.

### Selection (`selection.py`)
Diagnostic: one item per concept in prerequisite order. Adaptive: concepts weighted towards low mastery, open misconception hypotheses and due reviews; difficulty targeted from the current estimate; **never** an item the learner has already seen (exposures table) unless the learner chooses a review; unseen items from an already-practised **family** are down-ranked (paraphrase control); items carrying a signature for an open hypothesis are preferred; fresh template items are generated and verified when the pool runs dry. Every item stores its selection reason ("Why this question?").

### Grading and feedback (`grading.py`, `learning/attempts.py`)
* MCQ: deterministic. Numerical: parser for `₹1,25,000`, `25%`, `1.5 lakh`, `3k`, negatives; absolute or relative tolerance; a fraction for a percent answer (0.25 for 25%) is accepted and reported.
* Short answer: local rubric scoring (key-point keyword groups + embedding similarity, contradiction patterns); borderline scores are **flagged for review** and are not used as mastery evidence. With a model configured, an LLM grader judges each rubric point against the sources and its result is flagged for review when its stated confidence is below 0.6; it falls back to the local scorer on any error. (This path has not been exercised in the recorded runs, which use local mode.)
* Feedback: verdict, key, worked steps, explanation, cited source passages, the error classification, any misconception alert, and the mastery change with the evidence weight and why.
* Post-assessment report: per-concept accuracy and mastery after, weak topics, likely misconceptions (hypotheses, with status), and recommendations.

## 2. Learner model: evidence-weighted Bayesian Knowledge Tracing

Code: `services/learner/bkt.py`, `mastery.py`. One BKT state per learner per concept.

* Prior P(L₀) = 0.25, learning P(T) = 0.10. Guess G by type: MCQ 0.20 (capped at 1/number of options), numerical 0.10, short answer 0.12. Slip S by difficulty: 0.08 / 0.12 / 0.18.
* Update with an evidence weight w ∈ [0, 1] that tempers the likelihoods:

  P(L | correct) = P(L)(1−S)ʷ / [P(L)(1−S)ʷ + (1−P(L))Gʷ]
  P(L | wrong) = P(L)Sʷ / [P(L)Sʷ + (1−P(L))(1−G)ʷ]
  P(L′) = P(L | obs) + (1 − P(L | obs)) · T · w

  With w = 1 this is standard BKT.
* **Evidence weights** (`mastery.evidence_weight`): same question family seen before ×0.5 per earlier attempt; identical question re-seen ×0.3; practice right after a worked example of the same structure ×0.6; a correct answer whose reasoning matches misconception cues ×0.4; grading flagged for review → 0 (not used). Probe answers in a Blindspot session test an explanation, not mastery, and are never mastery evidence.
* Every update is stored in `mastery_history` (before, after, weight, reasons, source), which drives the trajectory chart and the "why" text in feedback.
* Labels: unassessed (no evidence) · emerging < 0.4 · developing < 0.7 · proficient ≥ 0.7 · mastered ≥ 0.9 with ≥ 3 distinct questions. Evidence quality from the effective (weighted) observation count: low < 1.5, medium < 4, high.
* Review timing (BKT does not model forgetting, so it is scheduled separately): next review after 12 h (p < 0.6), 1 day (< 0.8), 3 days (< 0.95), 7 days.

**Tutoring and the learner model.** A conversation updates mastery only through scored evidence: each grounded answer offers a one-question knowledge check on the concept discussed, graded and weighted like any other answer. Reading or asking is not treated as evidence of mastery. In the other direction, each grounded answer reports the learner's state for the concepts it covers and suggests a next step (see [INGESTION_AND_GROUNDING.md §6](INGESTION_AND_GROUNDING.md)).

**New learners.** With no evidence the dashboard's first recommendation is the diagnostic check-in (one question per concept, prerequisites first); every concept starts at the uncertain prior and is shown as unassessed, not as a low score.

### Recommender (`services/learner/recommender.py`)
Ranked activities with a written rationale, highest priority first: (1) no evidence → diagnostic; (2) a suspected/supported hypothesis with posterior ≥ 0.5 and new evidence since its last investigation → Blindspot investigation; (3) weak concept whose prerequisite is weak → practise the prerequisite; (4) weakest concept with ready prerequisites → practice at matched difficulty; (5) review due, stale (> 14 days), or 12+ scored answers on other concepts since it was last seen (interleaving) → spaced review; (6) unassessed concepts → short assessment; (7) everything proficient → mixed mock exam.

## 3. Misconception engine (the Blindspot loop)

Code: `services/diagnosis/` (`classifier.py`, `hypotheses.py`, `store.py`, `engine.py`); catalogue: `app/data/misconception_catalog.json`.

### Catalogue
Ten misconceptions written by the team for this domain (contribution vs revenue, ROAS above 1 as profitable, revenue growth as profit growth, correlation as causation, conversion rate vs absolute conversions, percentage points vs percent change, mean vs median for skewed data, CAC alone or revenue-based CLV, statistical vs practical significance, average total cost for incremental decisions). Each entry has detection cues, correct-reasoning cues, competing interpretations, one or two **diagnostic probes with likelihood tables** P(response | hypothesis), and a repair template (contrast, key rule, worked-example template, transfer templates, support query). It is **not** an externally validated diagnostic instrument; misconceptions are activated for a course only when its sources support them.

### Step 1: classify the answer
Seven categories: correct and supported · correct with questionable reasoning · calculation error · likely misconception · missing prerequisite · incomplete or ambiguous · insufficient evidence. Evidence: whether a numerical answer matches a signature (tolerance-based), MCQ distractor signatures, near-miss checks (within 6% of the key, off by 10/100/1000, sign flip → calculation error), reasoning cues, self-reported confidence, and weak prerequisites. This yields a prior over five hypotheses {misconception, calculation error, misread question, missing prerequisite, guess} from a pattern table (`classifier.PRIORS`), adjusted by likelihood ratios (misconception cue ×2.0, correct-reasoning cue ×0.5, confident error ×1.4, weak prerequisite ×2.0) and by the learner's history for that misconception (odds shift, bounded to ×0.33–×3).

### Step 2: investigate with a discriminating probe
The engine chooses the probe with the highest **expected information gain** over the current hypothesis distribution (entropy reduction, in bits) and asks it only if the gain is ≥ 0.08 bits; at most two probes. The learner's response updates the distribution by Bayes' rule using the probe's likelihood table. A hypothesis is never "confirmed": its status is **suspected** (posterior ≥ 0.35), **supported** (≥ 0.75 *and* at least two independent pieces of evidence), **unresolved** (≥ 0.15) or **rejected**, later **resolving** (repaired, revisit pending) and **resolved**.

### Step 3: repair, practice, transfer, revisit
* **Repair**: a contrastive explanation (what the misconception computes vs what the concept requires, with the key rule), a worked example on the learner's own numbers showing both answers, and citations to the course passages retrieved for the misconception's support query (PDF page, slide, lecture timestamp). In generative mode an additional short explanation may be generated from those passages and is labelled as generated.
* **Practice**: a fresh item of the same structure. Its evidence weight is ×0.6 because it follows a worked example and ×0.5 because it repeats the diagnostic item's question family, so 0.3 in the signature scenario; a wrong answer gets one more attempt.
* **Transfer**: an item from a *different* question family, context and numbers (for the signature scenario, a price *increase* asking for the maximum acceptable volume loss).
* **Learner-level evidence** (`store.py`, odds updates against a base rate of 0.20): a signature answer on a numerical item ×6.0, on an MCQ ×2.5, cues only ×1.6; avoiding the trap on a signature-carrying item ×0.5 (×0.4 inside an investigation); transfer success ×0.3 and status → resolving with a revisit after 3 days; transfer failure ×2.0. Every piece of evidence is stored with its likelihood ratio and the posterior before and after, and shown in the analytics evidence trail.

### The signature scenario
Price ₹100 → ₹80, variable cost ₹60. Correct: contribution per unit falls from ₹40 to ₹20, so volume must rise by 100%. The scripted demo learner answers 25% ("compensates for the price reduction", confidence 4). The engine computes the classification, the hypothesis distribution, the probe choice, the repair citations and the mastery updates live; only the learner's responses are scripted, and the UI says so. The integration test `test_signature_blindspot_loop` checks the whole sequence against the API.
