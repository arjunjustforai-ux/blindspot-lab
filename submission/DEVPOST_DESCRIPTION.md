# Blindspot Lab

**Understand what you don't understand.**

*Track D: Personalized Tutoring & Adaptive Learning*

## Inspiration

Every one of us has passed a quiz we didn't really understand. In marketing and business analytics the pattern is very specific: you can recite "contribution margin is price minus variable cost" and still answer a price-cut question as if keeping *revenue* constant were the goal. A score of 0/1 doesn't tell you that, and an AI chatbot that re-explains the formula doesn't either. We wanted a study companion that asks the question a good teaching assistant asks: *why* did you get that wrong, and is it fixed?

## The problem

Students study from lecture videos, readings and slides spread across places. Generic chatbots answer from outside the course and can't show where a claim comes from. Generic quiz generators repeat themselves, can't vouch for their answer keys, and treat every wrong answer the same, so a learner with a deep misconception and a learner who mistyped a number get the same feedback.

## What we built

A working web application (Next.js + FastAPI + PostgreSQL/pgvector) that:

1. **Ingests real course files without preprocessing.** A 9-page PDF primer, an 11-slide deck with a native chart, and a narrated MP4 lecture become 67 content units, each tied to its page, slide or sentence-level video timestamp. Tables, figure labels (OCR), chart data series and speaker notes are extracted, and the lecture is transcribed locally with Whisper.
2. **Builds the course's concept map**: topics, concepts and sub-concepts, with every unit tagged and prerequisite edges that instructors can review (cycles are refused).
3. **Answers from the sources only.** Hybrid retrieval (vectors + full text + a cross-encoder) feeds a tutor whose citation chips open the PDF page with the passage highlighted, the slide, or the video at the cited sentence. Questions the material doesn't cover are declined, with the nearest passages shown separately; outside knowledge appears only in a labelled box, when the learner asks for it and a model is configured.
4. **Assesses adaptively with verified questions.** 19 parametric templates and a 33-item bank produce MCQ, numerical and short-answer questions tagged with concept, difficulty and source. Computed answer keys must pass an independent plug-back check; duplicates and unsupported premises are rejected; seen questions are never re-served unless the learner asks for a review.
5. **Runs the Blindspot loop.** A wrong answer is classified (slip, misconception, misread, missing prerequisite, guess…) into a probability distribution. The system asks the single follow-up question with the highest expected information gain, updates by Bayes' rule, then repairs: a contrast between what the misconception computes and what the concept requires, a worked example on the learner's own numbers, and citations to the primer page, the slide and the lecture moment. Then practice, then a transfer problem from a *different* question family. Only transfer success marks the misconception "repaired, revisit pending".
6. **Keeps an inspectable learner model.** Per-concept Bayesian Knowledge Tracing with evidence weights: repeated paraphrases, scaffolded practice and right-answer-wrong-reasoning count for less, and probe answers count for nothing. Every update is stored with its weight and reason; recommendations come with a written rationale; tutor answers show what the learner model believes about the concepts just discussed.
7. **Measures itself.** An Evaluation Lab shows recorded runs with every case inspectable.

## How it works (the signature scenario)

A product sells for ₹100, costs ₹60 to make, and the price drops to ₹80. What volume increase keeps total contribution unchanged? The scripted demo learner answers **25%** ("that compensates for the price reduction").

* Grading: wrong; the key is **100%** (contribution per unit falls from ₹40 to ₹20, so volume must double). 25% is exactly what keeping *revenue* constant would need, which is this misconception's signature answer.
* Classification: *likely misconception*; competing explanations remain open: ≈77% revenue-instead-of-contribution, plus misread target, missing prerequisite, no systematic reasoning, arithmetic slip.
* Probe: "Which quantity were you trying to keep the same?" → *total revenue* → 91%, and the status becomes *supported by evidence* (two independent pieces of evidence; it is never "confirmed").
* Repair with citations to the PDF, the slide and the lecture, practice, and a transfer question about a price *increase* with different numbers. The mastery estimate moves 25% → 14% → 26% → 77%, each step with its evidence weight shown.

Only the learner's answers are scripted; grading, classification, probing, retrieval and mastery updates are computed live, and the UI says so.

## Distinctive innovation

* Treating a wrong answer as **hypotheses to test**, choosing the follow-up by **expected information gain**, and refusing to call anything confirmed.
* **Repair verified by transfer** to a structurally different problem, not by asking the same question again.
* **Evidence-weighted BKT** that can't be inflated by paraphrased repeats or scaffolded practice.
* **Provenance down to the sentence** in a lecture video, and answer keys checked by plug-back rather than trusted from a generator.
* **Local-first**: the whole system runs on CPU with open models; an LLM is an optional upgrade, not a dependency.

## Technology stack

Next.js 15, React 19, TypeScript, Tailwind CSS 4, TanStack Query, Recharts, React Flow, react-pdf · FastAPI, SQLAlchemy 2, Alembic, PostgreSQL 16 + pgvector · PyMuPDF, python-pptx, LibreOffice, FFmpeg, faster-whisper, Tesseract · bge-small embeddings, MiniLM cross-encoder, DeBERTa-v3 NLI · RAGAS 0.4.3 · pytest, Vitest, Playwright, GitHub Actions · Docker, Render/Railway/Vercel configurations.

## Evaluation (what we actually measured)

On our synthetic demo course, in local mode (no judge model available to us):

* **Retrieval and grounding** (RAGAS 0.4.3 + pipeline metrics), on a 49-case benchmark and a 15-case held-out set written after we froze the tutor: context precision 91.0% / 86.4%, context recall 67.9% / 68.5%, citation-location accuracy 83.8% / 88.3%, answers with a correct citation 100% / 90.9%, off-material refusal 16/16. RAGAS faithfulness and answer relevancy need an LLM judge and are reported as *unavailable*; our labelled substitutes are NLI faithfulness 99.3% / 100% (near 100% by construction, since local answers are quotes) and embedding relevancy ≈ 80%.
* **Ingestion**: 100% page and slide coverage, every unit anchored, lecture transcript word error rate 9.1%.
* **Assessment**: 97/97 pool questions verified; 64/64 computed keys pass plug-back; the verifier caught 12/12 deliberately flawed drafts and rejected 0/6 sound ones; 0% exact repeats over six adaptive assessments vs 17.6% for random selection.
* **Personalization** with simulated learners (3 profiles × 15, paired with a random-quiz baseline on the same budget, 95% bootstrap intervals): post-test accuracy +17.6 pp [+6.7, +28.1] for the learner with misconceptions; smaller, uncertain gains for strong and weak-prerequisite learners; repeats down about 16–19 pp; but **worse mastery calibration** than the baseline arm. These are simulations under our own assumptions, not evidence about real students.

Everything is reproducible with one command and inspectable case by case.

## Challenges we ran into

* **Timestamps that looked right but weren't.** Whisper returned one segment per 30-second window on our lecture, so video citations opened up to half a minute early. We now split segments into sentences using word timings, which raised citation-location accuracy on both test sets; we report the runs before and after.
* **A verifier that rejected good questions.** Our first option-distinctness check treated MCQ options that differ mainly in their numbers as duplicates and rejected valid bank items. Numbers now count as distinguishing, and a labelled adversarial set of flawed and sound drafts keeps the verifier honest in both directions.
* **Mastery that moved too fast.** One early session took a concept from 15% to 94%. Evidence weighting and more conservative parameters fixed that, and the simulation now shows where calibration is still weak.
* **Honest evaluation without a judge model.** We kept the RAGAS LLM metrics wired in (they run with a key), marked them unavailable, and added clearly labelled judge-free substitutes rather than presenting a substitute as RAGAS.
* **Our own race condition.** The evaluation CLI and the background worker once executed the same run twice; we found it because the Evaluation Lab showed every case twice.

## Accomplishments we're proud of

* The full loop works end to end on real files: upload → cited answer → assessment → misconception probe → cited repair → transfer → saved evidence → personalized next step, covered by integration tests against a real database and nine Playwright browser tests, with CI green on GitHub.
* Every number in our submission comes from a recorded run you can open.

## What we learned

Grounding is mostly retrieval and refusal discipline, not prompting. Learner models are easy to make confident and hard to make calibrated. And the most useful thing an evaluation did for us was show where we were wrong.

## Commercial potential

The first customers we would talk to are marketing and business-analytics educators, business-school programmes and analytics-training providers, whose quiz data shows *that* learners struggle but not *why*. A plausible path is a limited institutional pilot, then cohort- or learner-based licensing, if pilots show that diagnosis agrees with instructors and that transfer results improve. We think the durable value is in instructor-reviewed misconception libraries, validated assessment items and learning evidence, not in using an LLM. These are hypotheses we have not validated with customers yet.

## What's next

* Pilot with an instructor: compare the engine's diagnoses with expert judgement, and fit BKT parameters to real data.
* Generative mode with a configured model: paraphrased explanations, LLM-judge RAGAS metrics, figure descriptions.
* Instructor tools: misconception-catalogue editor and review queues; LMS integration.
* Track D extras we didn't reach: flashcards and audio briefs for weak topics, a study schedule, Hindi explanations.
