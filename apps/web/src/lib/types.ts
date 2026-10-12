// Shapes of the API responses used by the UI.

export interface User {
  id: string;
  email: string;
  display_name: string;
  auth_provider: string;
  is_demo: boolean;
}

export interface TokenOut {
  access_token: string;
  user: User;
}

export interface Recommendation {
  type: "diagnostic_assessment" | "blindspot_session" | "practice" | "review" | "assessment" | "mock_exam";
  priority: number;
  title: string;
  rationale: string;
  concept_ids: string[];
  misconception_key?: string;
  difficulty?: number | null;
}

export interface Course {
  id: string;
  title: string;
  description: string | null;
  subject: string | null;
  is_demo: boolean;
  knowledge_status: string;
  knowledge_built_at: string | null;
  created_at: string;
  role: "owner" | "instructor" | "student";
  sources: number;
  concepts: number;
  verified_questions: number;
  mastery: { assessed: number; mean: number | null };
  recommendations?: Recommendation[];
}

export interface Source {
  id: string;
  course_id: string;
  filename: string;
  modality: "pdf" | "pptx" | "video";
  mime_type: string;
  size_bytes: number;
  status: "uploaded" | "extracting" | "indexing" | "ready" | "failed";
  status_detail: string | null;
  error: string | null;
  page_count: number | null;
  slide_count: number | null;
  duration_seconds: number | null;
  created_at: string;
  updated_at: string;
  metadata: Record<string, unknown>;
}

export interface Job {
  id: string;
  source_file_id: string | null;
  kind: string;
  status: string;
  stage: string | null;
  progress: number;
  attempts: number;
  error: string | null;
  created_at: string;
}

export interface Unit {
  id: string;
  source_id: string;
  filename: string;
  modality: string;
  order_index: number;
  heading: string | null;
  section_path: string[];
  content: string;
  page: number | null;
  slide: number | null;
  start: number | null;
  end: number | null;
  anchor: string;
  bbox: number[] | null;
  is_generated: boolean;
  image_url: string | null;
  extraction_meta: Record<string, unknown>;
  segments: { start: number; end: number; text: string; confidence: number | null }[] | null;
  concepts?: { concept_id: string; name: string; kind: string; primary: boolean; relevance: number; method: string }[];
  relevance?: number;
  primary?: boolean;
}

export interface Citation {
  id: string;
  unit_id: string;
  source_id: string;
  course_id: string;
  filename: string;
  source_modality: string;
  unit_modality: string;
  page: number | null;
  slide: number | null;
  start: number | null;
  end: number | null;
  label: string;
  heading: string | null;
  excerpt: string;
  is_generated: boolean;
  has_image: boolean;
  support: number | null;
  link: string;
  nearest_only?: boolean;
}

export interface MasteryView {
  concept_id: string;
  name: string;
  kind: string;
  parent_id: string | null;
  p_mastery: number | null;
  label: "unassessed" | "emerging" | "developing" | "proficient" | "mastered";
  n_observations: number;
  n_correct: number;
  effective_evidence: number;
  evidence_quality: "low" | "medium" | "high";
  distinct_questions: number;
  last_observation_at: string | null;
  next_review_at: string | null;
  review_due: boolean;
  stale: boolean;
}

export interface GraphNode extends MasteryView {
  description: string | null;
  origin: string;
  review_status: string;
  catalog_key: string | null;
  units: number;
  questions: number;
  order_index: number;
}

export interface GraphEdge {
  id: string;
  concept_id: string;
  prerequisite_id: string;
  origin: string;
  confidence: number;
  rationale: string | null;
  review_status: string;
}

export interface PublicQuestion {
  id: string;
  concept_id: string;
  question_type: "mcq" | "numerical" | "short_answer";
  difficulty: number;
  stem: string;
  options: { id: string; text: string }[];
  answer_unit: string | null;
  assumptions: string | null;
  origin: string;
  template_key: string | null;
  family: string | null;
  concept_name?: string;
}

export interface Classification {
  category: string;
  label: string;
  summary: string;
  candidates: {
    misconception_key: string;
    title: string;
    pattern: string;
    distribution: Record<string, number>;
    labels: Record<string, string>;
    adjustments: string[];
  }[];
  evidence: { kind: string; summary?: string; misconception_key?: string; cues?: string[] }[];
}

export interface Feedback {
  is_correct: boolean | null;
  score: number | null;
  needs_review: boolean;
  correct_answer: { option_id?: string; text?: string; value?: number; unit?: string; key_points?: string[] };
  explanation: string;
  worked_steps: string[];
  assumptions: string | null;
  citations: Citation[];
  classification: Classification;
  misconception_alert: {
    misconception_key: string;
    title: string;
    status: string;
    posterior: number;
    evidence_count: number;
    message: string;
  } | null;
  mastery: { concept_id: string; name: string | null; before: number | null; after: number | null; weight: number; weight_reasons: string[] } | null;
  grading: { method: string; detail: Record<string, unknown> };
}

export interface AssessmentItem {
  position: number;
  selection_reason: string | null;
  question: PublicQuestion;
  attempt: null | {
    id: string;
    response: Record<string, string>;
    reasoning: string | null;
    confidence: number | null;
    is_correct: boolean | null;
    score: number | null;
    feedback: Feedback;
  };
}

export interface AssessmentReport {
  score: { answered: number; correct: number; accuracy: number };
  topics: {
    concept_id: string;
    name: string;
    answered: number;
    correct: number;
    accuracy: number;
    mastery_after: number | null;
    weak: boolean;
    classifications: Record<string, number>;
  }[];
  weak_topics: string[];
  likely_misconceptions: Hypothesis[];
  recommendations: Recommendation[];
  notes: string[];
}

export interface Assessment {
  id: string;
  course_id: string;
  kind: string;
  status: string;
  config: Record<string, unknown>;
  items: AssessmentItem[];
  report: AssessmentReport | null;
  created_at: string;
  completed_at: string | null;
}

export interface Hypothesis {
  hypothesis_id?: string;
  id?: string;
  misconception_key: string;
  title: string;
  description?: string;
  status: string;
  posterior: number;
  evidence_count: number;
  concept_id: string | null;
  revisit_at: string | null;
  updated_at: string;
  evidence?: { kind: string; summary: string; likelihood_ratio: number; posterior_before: number; posterior_after: number; at: string }[];
}

export interface TimelineEvent {
  type: "question" | "answer" | "hypotheses" | "probe" | "probe_answer" | "conclusion" | "repair" | "note" | "complete";
  at: string;
  role?: "diagnostic" | "practice" | "transfer";
  question_id?: string;
  question?: PublicQuestion;
  feedback?: Feedback;
  response?: Record<string, string>;
  reasoning?: string | null;
  confidence?: number | null;
  distribution?: Record<string, number>;
  before?: Record<string, number>;
  after?: Record<string, number>;
  note?: string;
  text?: string;
  probe?: { id: string; key: string; type: string; prompt: string; options: { id: string; text: string }[]; answered: boolean; eig_bits?: number };
  probe_id?: string;
  response_key?: string;
  eig_bits?: number;
  leading_label?: string;
  leading_p?: number;
  misconception_posterior?: number;
  status?: string;
  intervention?: {
    id: string;
    content: {
      explanation: { contrast: string; key_rule: string | null; provenance: string; generated?: { text: string; model: string } | null };
      worked_example: { stem: string; steps: string[]; answer: number; unit: string; contrast: { misconception_answer: number; label: string } | null; note: string } | null;
    };
    citations: Citation[];
  };
  transfer_correct?: boolean;
}

export interface DiagnosticSession {
  id: string;
  course_id: string;
  concept: { id: string; name: string | null };
  stage: "answer" | "probing" | "repair" | "practice" | "transfer" | "completed";
  outcome: string | null;
  is_demo_script: boolean;
  scenario: null | {
    key: string;
    scripted_answer: Record<string, string>;
    scripted_reasoning: string;
    scripted_confidence: number;
    scripted_probe_answers: Record<string, Record<string, string>>;
    scripted_followup: null | { value?: string; option_id?: string; reasoning: string };
    label: string;
  };
  hypotheses: { misconception_key: string; title: string; labels: Record<string, string>; distribution: Record<string, number>; asked: string[]; adjustments: string[] }[];
  hypothesis: null | {
    misconception_key: string;
    title: string;
    status: string;
    posterior: number;
    evidence_count: number;
    revisit_at: string | null;
    description: string;
    competing: { key: string; label: string; description: string }[];
  };
  timeline: TimelineEvent[];
  pending: null | {
    type: "answer_question" | "answer_probe" | "continue_repair" | "answer_practice" | "answer_transfer";
    question?: PublicQuestion;
    probe?: { id: string; prompt: string; type: string; options: { id: string; text: string }[] };
  };
  mastery_change: null | { concept: string; before: number; after: number; steps: { source: string; correct: boolean; weight: number; p_after: number }[] };
  created_at: string;
  completed_at: string | null;
}

export interface TutorMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  grounding_status: "grounded" | "refused" | "external" | "error" | "n/a";
  answer_mode: string | null;
  allow_external: boolean;
  citations: Citation[];
  external_content: string | null;
  concept_ids: string[];
  support_score: number | null;
  learner_context: LearnerContext;
  created_at: string;
}

export interface LearnerContext {
  concepts?: { concept_id: string; name: string; p_mastery: number | null; label: MasteryView["label"]; evidence_quality: string }[];
  hypotheses?: { misconception_key: string; title: string; status: string; posterior: number; concept_id: string }[];
  weak_prerequisites?: { concept_id: string; name: string; p_mastery: number }[];
  suggestion?: { type: "blindspot_session" | "practice" | "knowledge_check"; text: string; misconception_key?: string; concept_id?: string };
}

export interface Conversation {
  id: string;
  course_id: string;
  title: string;
  created_at: string;
  messages: TutorMessage[];
  mode: { generation: "llm" | "extractive"; model: string | null; external_mode_available: boolean };
}

export interface Analytics {
  concepts: MasteryView[];
  topics: { topic_id: string; name: string; p_mastery: number | null; concepts: number; assessed_concepts: number }[];
  history: Record<string, { t: string; p_before: number; p_after: number; correct: boolean; weight: number; source: string }[]>;
  accuracy: { concept_id: string; name: string; answered: number; correct: number; accuracy: number | null; by_type: Record<string, { answered: number; correct: number }> }[];
  sessions: { session_key: string; label: string; kind: string; at: string; observations: number; correct: number; mean_mastery_assessed: number | null; concepts_assessed: number; delta: Record<string, number> }[];
  hypotheses: Hypothesis[];
  recent: { at: string; question: string; concept: string | null; context: string; is_correct: boolean | null; classification: string | null; question_type: string }[];
  retention: { revisit_attempts: number; revisit_correct: number; revisit_accuracy: number | null; definition: string; due_reviews: string[] };
  recommendations: Recommendation[];
  method: {
    model: string;
    parameters: { p_init: number; p_transit: number; guess_by_type: Record<string, number>; slip_by_difficulty: Record<string, number> };
    evidence_weighting: Record<string, string>;
    labels: Record<string, string>;
    caveats: string[];
  };
  totals: { attempts: number; correct: number; assessed_concepts: number; concepts: number };
}

export interface EvalRun {
  id: string;
  kind: "rag" | "assessment" | "personalization";
  status: string;
  course_id: string | null;
  dataset_name: string | null;
  dataset_version: string | null;
  config: Record<string, unknown>;
  model_info: Record<string, unknown>;
  prompt_version: string | null;
  seed: number | null;
  summary: Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
  limitations: string[];
  progress: number;
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  n_results: number | null;
}

export interface EvalResult {
  id: string;
  case_key: string;
  category: string | null;
  metrics: Record<string, unknown>;
  output: Record<string, unknown>;
  passed: boolean | null;
}
