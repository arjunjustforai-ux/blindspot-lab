# Limitations

What Blindspot Lab does not do, or has not shown yet. Items marked *(measured)* are visible in the recorded evaluation results.

## Evidence and validation
* **No real learners.** The personalization results come from simulated learners whose response and learning behaviour we specified ourselves. They show how the system behaves under those assumptions, not that it improves learning. Real-student validation (diagnosis agreement with instructors, transfer-test gains) has not been done.
* **Hand-set parameters.** BKT parameters, evidence weights, classifier priors, likelihood ratios, probe likelihood tables and status thresholds are design assumptions, not fitted to data.
* **The misconception catalogue is ours.** Ten entries written by the team for one domain. It is not an externally validated diagnostic instrument, and a "supported" hypothesis is model evidence, not a diagnosis.
* **Small, team-built benchmarks.** The RAG benchmark (49 cases) was used while fixing pipeline problems, so it is optimistic. The held-out set (15 cases) was written later and is the fairer estimate, but it is small, and it has been scored before two later changes (see the run history in [EVALUATION.md](EVALUATION.md)); neither change targeted its cases. All test sets cover one synthetic course.

## Grounding and generation
* **Local mode quotes rather than explains.** Without an API key, answers are verbatim sentences selected from the sources. They cannot paraphrase, combine steps or adapt their wording, and they sometimes include a tangential sentence. The local NLI faithfulness score is close to 100% largely *because* the answers are quotes *(measured)*.
* **Generative paths are untested here.** Generative answers, the blind verifier for generated questions, figure descriptions with a vision model, the LLM short-answer grader and the RAGAS LLM-judge metrics (faithfulness, answer relevancy) are implemented behind an OpenAI-compatible interface but were not exercised in the recorded runs because no key was available. Those two RAGAS metrics are reported as *unavailable*, with labelled judge-free substitutes.
* **Citation granularity.** Video citations open the sentence (start time from Whisper word timings); PDF and slide citations open the page or slide and highlight the cited unit, not an exact character span. Citation-location accuracy is below the answer-level rate *(measured)* because answers often cite a correct location plus an additional, non-annotated one.
* **Source-type hints are soft.** "In the lecture…" boosts video units but does not exclude others, so such answers can also quote the primer or slides.
* **False refusals happen.** One held-out question about a table value ("which channel has the highest average order value?") is refused *(measured)*: the table unit is retrieved, but no sentence states the comparison, so the extractive composer cannot quote an answer.

## Ingestion
* **Figures without a vision model** contribute captions, OCR'd labels and native chart data only; OCR misreads some symbols on charts (for example the ₹ glyph) and cannot describe a diagram's shape.
* **Speech recognition** (`faster-whisper base.en`) has a word error rate of about 9% on the synthesised narration *(measured)* and hears "break-even ROAS" as "breakeven rose". On this audio Whisper emitted one segment per 30-second window; sentence-level timestamps are recovered from its word timings. Real classroom audio, accents and non-English speech are untested. `small.en` measured 7.4% on the same audio at twice the time and is a configuration option.
* **Concepts outside the catalogue** come from document structure (headings, slide titles) with heuristic prerequisites. They work, but are shallower than the catalogue concepts, and the Blindspot investigation only exists for catalogued misconceptions.
* English only. No scanned-handwriting support beyond OCR of page images.

## Assessment and learner model
* Numerical grading does not parse number words ("twenty-five") *(measured)*. The local short-answer rubric can pass a partially correct answer; borderline scores are flagged for review and excluded from mastery *(measured)*.
* BKT does not model forgetting; review dates are scheduled separately. There is no IRT calibration of item difficulty; difficulty is the template's or author's label.
* Tutoring updates mastery only through the scored knowledge check offered under each answer; free conversation is not treated as evidence.
* In the simulation, the learner model's **calibration (Brier score) is worse** than in the random-quiz arm for all three profiles (the 95% interval excludes zero for the weak-prerequisite profile), and weak-concept identification and misconception recall are lower *(measured)*. Our working explanation, not yet tested: the adaptive arm spends its budget on weak concepts and investigations, so it observes the concepts a learner already knows less often than a uniform quiz does.

## Product and operations
* Not deployed. Dockerfiles, Compose, Render/Railway/Vercel configurations are prepared; images were not built in the development environment, and Supabase storage has not been tested against a live project.
* CPU inference: a 90-minute lecture takes several minutes to transcribe; one worker processes jobs sequentially (more workers can be added).
* No rate limiting on authentication endpoints and no e-mail verification; the access token is kept in `localStorage` (no raw HTML is rendered, which limits XSS exposure). LMS integration (LTI), SSO and instructor review queues are not built.
* Optional Track D enhancements not implemented: flashcards/audio briefs, Hindi or mixed-language interaction, audio tutoring. A study schedule exists only as per-concept review dates and spaced-review recommendations.
* Accessibility has not been audited; forms use labels, charts have text equivalents in tables, and motion respects `prefers-reduced-motion`.
