# Demo guide

Everything below runs on the real pipeline. The demo course is original synthetic material written for this project (fictional companies and figures, synthesised narration), and every demo learner is a fresh, labelled synthetic account.

## Start

```bash
scripts/setup.sh && scripts/start_dev.sh      # or: docker compose up --build
```

Open http://localhost:3000 and click **Explore the demo course**. This creates a new demo learner enrolled in *Marketing & Business Analytics: Making Better Decisions with Data* (a 9-page PDF primer, an 11-slide deck with a native chart, and a 2-minute narrated lecture video).

## The learner journey (about 6 minutes)

1. **Dashboard.** With no evidence, every concept is *unassessed* and the first recommendation is the diagnostic check-in, with its reason.
2. **Course Studio.** Three sources, each *Ready*, with unit counts by type (text, tables, figures, chart, notes, transcript, video frames) and the processing mode (local models; no external provider). Click **View** on any source to see the extracted units next to the page, slide or video.
3. **Knowledge Explorer.** Topics, concepts and prerequisite arrows (catalogue, heuristic or instructor origin). Click *Contribution margin*: definition, sub-concepts, prerequisites, unlocks, the tagged source passages, verified-question count and your mastery.
4. **Grounded Tutor.** Ask *"Why can a price cut need more extra volume than people expect?"* The answer quotes the lecture, a slide and its speaker notes, with chips `Lecture_03_Price_Cuts.mp4 — 00:00`, `Unit_Economics_for_Marketers.pptx — Slide 5`. Click a chip: the viewer opens at that timestamp or slide with the cited passage highlighted. Under the answer, *Your learner model* shows the concepts involved and suggests the scored knowledge check. Then ask *"How do I set up conversion tracking in Google Analytics 4?"*: the tutor declines and lists the closest material separately.
5. **Blindspot Lab, signature scenario.** Click **Start the scenario** → **Fill in the scripted learner's answer** (25%, "compensates for the price reduction", confidence 4) → **Submit**.
   * Feedback: incorrect; the key is 100%; classification *likely misconception*; source evidence links.
   * *Investigation opened, not a verdict*: five competing explanations with probabilities (preserving revenue instead of contribution ≈ 77% at this point), and *why these priors* (reasoning cues, confidence).
   * The follow-up probe asks which quantity the learner tried to keep constant. Use the scripted response (*total revenue*) → the hypothesis moves to ≈ 91% and *Supported by evidence* (two independent pieces of evidence).
   * **Repair**: the contrast (revenue preservation vs contribution preservation), the worked example on the learner's own numbers (₹40 → ₹20 per unit, so volume must double, vs 25% for revenue), and citations to the primer page, the lecture timestamp and the slide.
   * **Practice** (down-weighted to 0.3: ×0.6 for following a worked example, ×0.5 as a repeat of the same question family) and **Transfer** (a price *increase* with different numbers and a different question family). The scripted learner answers both correctly; the hypothesis becomes *Repaired · revisit pending* with a revisit date, and the side panel shows each mastery update with its weight.
6. **Adaptive Assessment.** Choose *Diagnostic check-in* → **Start**. Each answer gets cited feedback and an error classification; *Why this question?* shows the selection reason. **Finish & see report**: per-concept accuracy and mastery, weak topics, likely misconceptions and recommendations.
7. **Mastery & Progress.** BKT estimate per concept with evidence quality and next review, the trajectory chart (one step per scored observation), sessions, accuracy by type, the hypothesis evidence trail (each likelihood ratio, posterior before and after), and the method card with the formulas and parameters.
8. **Back on the Tutor or Dashboard.** Recommendations now come from the stored evidence (targeted practice, prerequisite-first, spaced review), and tutor answers on concepts with an open hypothesis suggest an investigation.
9. **Evaluation Lab.** The recorded runs: RAGAS context precision and recall, judge-free faithfulness and relevancy substitutes (labelled), citation and refusal accuracy, held-out results, ingestion quality, assessment checks, and the simulated-learner comparison with its assumptions, plus every case-level result.

## Instructor flow (upload)

Sign out → **Create an account** → **New course** → drop a PDF, PPTX or MP4 in the Course Studio. The row moves through *Uploaded → Extracting → Indexing → Ready* from the worker's real job state (the demo PDF takes well under a minute on a laptop CPU, the 2-minute video about a minute). Invalid types, oversized files and exact duplicates are rejected with a message. The knowledge graph and question pool are rebuilt automatically.

## Reset

Demo learners can reset their own progress from the dashboard banner. An operator can remove all demo learners with `scripts/reset_demo.sh`.

## Automated version

`tests/e2e/specs/workflow.spec.ts` drives steps 1–9 in Chromium and writes the screenshots in `docs/screenshots/`; `tests/e2e/specs/upload.spec.ts` covers the instructor upload.

```bash
cd tests/e2e && npm ci && npx playwright test     # app must be running on :3000 / :8000
```
