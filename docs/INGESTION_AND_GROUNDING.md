# Ingestion and grounding

## 1. Ingestion (no manual preprocessing)

An instructor drops PDF, PPTX or video files on the Course Studio. Each file becomes an `ingestion_jobs` row processed by the worker; status moves *uploaded → extracting → indexing → ready* (or *failed* with the error kept and a retry button). Code: `services/api/app/services/ingestion/`.

Every extracted **content unit** carries exactly the anchor its medium supports, enforced by a database check constraint:

| Source | Unit types | Anchor | How |
|---|---|---|---|
| PDF (`pdf.py`) | `pdf_text`, `pdf_table`, `pdf_figure`, `pdf_ocr` | page number (+ bbox for figures) | PyMuPDF text blocks; section headings inferred from font size/weight and kept as `section_path`; text chunks never cross a page. Tables via PyMuPDF table detection, serialised as Markdown. Embedded figures: region crop, nearest caption, Tesseract OCR (upscaled, with a currency-symbol repair and noise filter). Image-only pages fall back to OCR with mean confidence recorded. |
| PPTX (`pptx.py`) | `slide_text`, `slide_table`, `slide_chart`, `slide_figure`, `slide_notes` | slide number (1-based) | python-pptx for titles, body text (including grouped shapes), tables and **native chart data read from the chart XML** (exact categories and series values, not OCR), pictures via OCR, and speaker notes. Slide previews rendered through LibreOffice → PDF → PNG for the viewer. |
| Video (`video.py`) | `transcript`, `video_frame` | start/end seconds | FFmpeg extracts 16 kHz mono audio; keyframes come from scene-change detection (1 fps, threshold 0.02, ≥ 4 s apart) and are OCR'd and de-duplicated. The OCR'd on-screen terms and the title form a vocabulary prompt for **faster-whisper** (`base.en`, CPU int8). Whisper segments are grouped into ~30–60 s units; each unit keeps every segment's exact start, end and confidence, so citations can open the segment that supports a sentence. |

**Figures and diagrams.** In local mode, figures contribute their caption and OCR'd labels (for example the axis labels and annotations of the break-even chart, or the numbers in a waterfall figure); chart slides contribute exact data series. When a vision-capable model is configured, each figure also gets a generated description stored as a *separate* unit flagged `is_generated` (at most `MAX_VISION_CALLS_PER_SOURCE` per file), so generated text is never mixed with extracted text and the UI labels it.

**Chunking and indexing.** Paragraphs are packed into 50–170-word chunks on sentence boundaries; each unit is embedded with `BAAI/bge-small-en-v1.5` (384-d, local) into a pgvector HNSW index, and a generated `tsvector` column feeds a GIN full-text index. Content hashes de-duplicate repeated units.

**Untrusted content.** Extracted text that looks like an instruction to the model ("ignore previous instructions…") is flagged in the unit's metadata; in generative mode every prompt wraps sources in an explicit notice that they are data, not instructions.

**Ingestion quality on the demo pack** is measured in every RAG evaluation run (`services/api/app/services/evaluation/ingestion.py`): page and slide coverage, share of units with provenance, and transcript word error rate against the narration script that was synthesised into the MP4. Current values are in [evaluation/results/RESULTS.md](../evaluation/results/RESULTS.md).

## 2. Knowledge model: topics, concepts, prerequisites

`services/api/app/services/knowledge/build.py` runs after every ingestion:

1. **Catalogue activation.** A reviewable domain ontology (`app/data/concept_ontology.json`: 3 topics, 6 concepts, 13 sub-concepts for marketing and business analytics) is activated only for concepts the course's own sources support (alias and embedding evidence).
2. **Structural concepts.** Headings and slide titles that are not covered by the catalogue become additional concepts (`origin = structure`), so courses outside the catalogue still get a concept map.
3. **Tagging.** Every content unit is tagged to concepts and sub-concepts by alias matches, heading context and embedding similarity, with the method and relevance stored (`concept_sources`). The Knowledge Explorer reports tagging coverage (all 67 units on the demo course).
4. **Prerequisites.** Catalogue edges, a structural heuristic for non-catalogue concepts (an earlier concept that a later one keeps referring to), and, in generative mode, model-proposed edges with a rationale. Any edge that would create a cycle is rejected (`knowledge/graph.py`); every edge has an origin, confidence and review status, and instructors can approve, reject or add edges in the Knowledge Explorer.
5. **Misconception activation** and **question-pool build** (see [MASTERY_AND_MISCONCEPTIONS.md](MASTERY_AND_MISCONCEPTIONS.md)).

## 3. Retrieval

`services/api/app/services/retrieval/hybrid.py`, always scoped to one course:

1. Embed the query; take the top 24 units by pgvector cosine distance.
2. Take the top 24 by PostgreSQL full-text rank (OR of stemmed content terms).
3. Fuse the lists with reciprocal-rank fusion (k = 60).
4. Rerank the fused candidates with a local cross-encoder (`Xenova/ms-marco-MiniLM-L-6-v2`, ONNX); the raw logit is kept as the relevance score.
5. If the question names a source type ("in the lecture", "on the slides", "in the primer"), units of that modality get a +1.5 logit bonus.

## 4. Grounded answers and refusal

`services/api/app/services/tutor/grounded.py`:

* **Grounding gate.** The best unit must reach a reranker logit of −0.85 (about 0.30 relevance probability). When the best logit is below 3.0, at least 34% of the question's content terms (ignoring words such as "lecture" or "according") must also appear in the top units. Otherwise the tutor **declines**, says that the material does not cover the question, and shows the closest passages separately, labelled as "shown for transparency, not as an answer".
* **Local extractive mode (default).** Candidate sentences from the top units are scored by the cross-encoder with their section heading as context; up to 4 sentences are quoted verbatim if each scores ≥ −1.0 and within 5 logits of the best. Tables, charts and figures are quoted whole; bare titles are skipped. Transcript sentences cite the start of the Whisper segment in which they begin. Because the text is quoted, it cannot go beyond the sources.
* **Generative mode (with a configured model).** The model receives the numbered retrieved passages, must return JSON with `supported`, the answer, and the passage ids it used. Citation markers are validated against the ids actually provided; an answer with no valid citation is withheld and replaced by a refusal. Unsupported answers become refusals.
* **Outside knowledge** is only available in generative mode, only when the learner switches it on, and is returned in a separate, labelled field ("not verified against your sources") that is never cited. In local mode the switch is disabled and says why.

## 5. Citations

`services/api/app/services/tutor/citations.py` builds one citation per cited unit: file, modality, page / slide / timestamp label (`Primer.pdf — Page 3`, `Deck.pptx — Slide 5`, `Lecture.mp4 — 00:41`), excerpt, and a deep link `/app/courses/{course}/sources/{source}?unit=…&page=…|slide=…|t=…`. The source viewer then:

* PDF: renders the page with react-pdf and highlights the cited text in the text layer;
* PPTX: shows the rendered slide preview and its extracted units;
* video: seeks to the timestamp, highlights the cited transcript segment, and lists the keyframes.

Media are delivered through signed, expiring URLs, and course membership is re-checked on each request.

## 6. Learner state beside the answer

Grounding never depends on the learner. Separately, each grounded answer stores a `learner_context` (`tutor/learner_context.py`): the learner's mastery of the concepts the answer drew on, any open misconception hypothesis on those concepts, weak prerequisites, and one suggested next step (investigate the hypothesis, practise the prerequisite, or take the scored knowledge check). An integration test checks that the suggestion changes when a hypothesis opens while the answer text stays identical.
