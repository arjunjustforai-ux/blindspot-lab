# Evaluation datasets

| File | Purpose | Size |
|---|---|---|
| `rag_benchmark_v1.jsonl` | Retrieval + grounded-answer benchmark on the demo course | 49 cases (37 answerable, 12 off-material) |
| `question_verification_v1.json` | Adversarial question drafts for the verifier (flawed + sound) | see file |
| `grading_cases_v1.json` | Learner responses with expected grades (numerical parsing, short-answer rubric) | see file |
| `dev_queries_v1.json` | 15 queries used **only** to set the grounding gate thresholds (kept separate from the benchmark) | 15 |

`rag_benchmark_v1.jsonl` fields:

- `case_key`, `category` (factual, diagram, numerical, multi_source, citation_challenge, unsupported)
- `question`, `reference_answer` (null for unsupported)
- `expected_sources`: acceptable source locations. PDF `page`, PPTX `slide`, or video `start`/`end` seconds
  (planned narration segment boundaries from `demo/course-materials/lecture_03_narration.json`; a video
  citation matches if its timestamp falls inside the range ± 3 s).
- `reference_contexts`: short verbatim phrases from the sources that support the reference answer.
- `should_refuse`: true for off-material questions.

The cases were written by the team after reading the demo materials; answers and locations were
checked against the files. The benchmark is small and built on self-authored material, so results
measure this pipeline on this course, not general performance.

## Held-out set

`rag_holdout_v1.jsonl` (15 cases, 4 off-material) was written **after** the tutor pipeline was frozen.
The evaluation runner scores it in every RAG run, so it was seen in a preliminary run, in the run after
the code freeze and in the final run; the changes made between those runs were generic (see the run
history in `docs/EVALUATION.md`) and none targeted its cases. During development we iterated on three generic
failure modes observed on `rag_benchmark_v1` (heading-aware sentence scoring, honouring explicit
source-type requests such as "in the lecture", and a relative relevance cut for extra citations), so
`rag_benchmark_v1` numbers may be optimistic; the held-out numbers are the less biased estimate.
