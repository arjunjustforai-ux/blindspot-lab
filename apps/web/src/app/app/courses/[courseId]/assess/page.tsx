"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowRight, CheckCircle2, ClipboardList, Info, PlayCircle, XCircle } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import * as React from "react";
import { toast } from "sonner";
import { FeedbackPanel } from "@/components/learning/feedback";
import { QuestionForm, QuestionMeta } from "@/components/learning/question-form";
import { RecommendationCard } from "@/components/learning/recommendations";
import { PageHeader } from "@/components/shell/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { Tip } from "@/components/ui/tooltip";
import { ApiError, api, errorMessage } from "@/lib/api";
import { useCourseId } from "@/lib/hooks";
import type { Assessment, AssessmentReport, Feedback, GraphNode } from "@/lib/types";
import { HYPOTHESIS_STYLE, cn, pct, timeAgo } from "@/lib/utils";

const KINDS = [
  { v: "diagnostic", label: "Diagnostic check-in", d: "One question per concept, prerequisites first. Best for a new learner." },
  { v: "practice", label: "Adaptive practice", d: "Targets weak concepts and active misconception hypotheses at matched difficulty." },
  { v: "review", label: "Spaced review", d: "Revisits concepts that are due, allowing deliberate repeats." },
  { v: "mock_exam", label: "Mock exam", d: "Mixed scope; harder unseen questions." },
];

function AssessInner() {
  const courseId = useCourseId()!;
  const sp = useSearchParams();
  const router = useRouter();
  const id = sp.get("id");
  return id ? (
    <Runner courseId={courseId} assessmentId={id} onExit={() => router.replace("?")} />
  ) : (
    <Setup courseId={courseId} initialKind={sp.get("kind")} initialConcepts={sp.get("concepts")} initialDifficulty={sp.get("difficulty")} onCreated={(a) => router.replace(`?id=${a}`)} />
  );
}

export default function AssessPage() {
  return (
    <React.Suspense fallback={<LoadingState />}>
      <AssessInner />
    </React.Suspense>
  );
}

function Setup({ courseId, initialKind, initialConcepts, initialDifficulty, onCreated }: { courseId: string; initialKind: string | null; initialConcepts: string | null; initialDifficulty: string | null; onCreated: (id: string) => void }) {
  const qc = useQueryClient();
  const graph = useQuery({ queryKey: ["graph", courseId], queryFn: () => api<{ nodes: GraphNode[] }>(`/api/courses/${courseId}/graph`) });
  const history = useQuery({ queryKey: ["assessments", courseId], queryFn: () => api<{ id: string; kind: string; status: string; created_at: string; score: AssessmentReport["score"] | null }[]>(`/api/courses/${courseId}/assessments`) });
  const [kind, setKind] = React.useState(initialKind ?? "practice");
  const [concepts, setConcepts] = React.useState<string[]>(initialConcepts ? initialConcepts.split(",") : []);
  const [difficulty, setDifficulty] = React.useState<string>(initialDifficulty ?? "");
  const [types, setTypes] = React.useState<string[]>(["mcq", "numerical", "short_answer"]);
  const [count, setCount] = React.useState(6);
  const create = useMutation({
    mutationFn: () =>
      api<Assessment>(`/api/courses/${courseId}/assessments`, {
        method: "POST",
        body: { kind, concept_ids: concepts.length ? concepts : null, difficulty: difficulty ? Number(difficulty) : null, question_types: types, count },
      }),
    onSuccess: (a) => {
      qc.invalidateQueries({ queryKey: ["assessments", courseId] });
      onCreated(a.id);
    },
    onError: (e) => toast.error(e instanceof ApiError && e.code === "pool_exhausted" ? "No unseen verified questions match this scope. Widen the scope or choose spaced review." : errorMessage(e)),
  });
  const concepts_ = graph.data?.nodes.filter((n) => n.kind === "concept") ?? [];

  return (
    <div className="mx-auto max-w-6xl">
      <PageHeader
        eyebrow="Adaptive assessment"
        title="Build an assessment"
        description="Questions are verified before delivery, tagged to a concept, difficulty and source location, and never repeated unless you choose a review. Each answer gets cited feedback; the report identifies weak topics and likely misconceptions."
      />
      <div className="grid gap-4 lg:grid-cols-[1.4fr_1fr]">
        <Card>
          <CardContent className="space-y-5 p-5">
            <div className="grid gap-2 sm:grid-cols-2">
              {KINDS.map((k) => (
                <button key={k.v} onClick={() => setKind(k.v)} className={cn("rounded-xl border p-3 text-left", kind === k.v ? "border-brand/70 bg-brand/10" : "border-line-strong hover:border-brand/40")} data-testid={`kind-${k.v}`}>
                  <div className="text-sm font-semibold">{k.label}</div>
                  <div className="mt-0.5 text-xs text-muted">{k.d}</div>
                </button>
              ))}
            </div>
            {kind !== "diagnostic" && (
              <div className="space-y-2">
                <div className="text-xs font-medium text-muted">Scope (leave empty for all concepts)</div>
                <div className="flex flex-wrap gap-1.5">
                  {concepts_.map((c) => {
                    const on = concepts.includes(c.concept_id);
                    return (
                      <button key={c.concept_id} onClick={() => setConcepts(on ? concepts.filter((x) => x !== c.concept_id) : [...concepts, c.concept_id])} className={cn("rounded-full border px-3 py-1 text-xs", on ? "border-accent bg-accent/15 text-accent" : "border-line-strong text-muted hover:text-fg")}>
                        {c.name}
                      </button>
                    );
                  })}
                </div>
              </div>
            )}
            <div className="grid gap-4 sm:grid-cols-3">
              <label className="space-y-1 text-xs text-muted">
                Difficulty
                <select value={difficulty} onChange={(e) => setDifficulty(e.target.value)} className="block w-full rounded-lg border border-line-strong bg-surface-2 px-2 py-2 text-sm text-fg">
                  <option value="">Adaptive (from mastery)</option>
                  <option value="1">Easy</option>
                  <option value="2">Medium</option>
                  <option value="3">Hard</option>
                </select>
              </label>
              <label className="space-y-1 text-xs text-muted">
                Questions
                <input type="number" min={1} max={20} value={count} onChange={(e) => setCount(Math.max(1, Math.min(20, Number(e.target.value))))} className="block w-full rounded-lg border border-line-strong bg-surface-2 px-2 py-2 text-sm text-fg" />
              </label>
              <div className="space-y-1 text-xs text-muted">
                Types
                <div className="flex flex-wrap gap-1">
                  {[
                    ["mcq", "MCQ"],
                    ["numerical", "Numerical"],
                    ["short_answer", "Short"],
                  ].map(([v, l]) => (
                    <button key={v} onClick={() => setTypes(types.includes(v) ? types.filter((t) => t !== v) : [...types, v])} className={cn("rounded-md border px-2 py-1", types.includes(v) ? "border-brand bg-brand/15 text-brand-soft" : "border-line-strong")}>
                      {l}
                    </button>
                  ))}
                </div>
              </div>
            </div>
            <Button size="lg" onClick={() => create.mutate()} disabled={create.isPending || types.length === 0} data-testid="start-assessment">
              <PlayCircle /> {create.isPending ? "Selecting and verifying questions…" : "Start assessment"}
            </Button>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <ClipboardList className="size-4 text-brand-soft" /> Your assessments
            </CardTitle>
          </CardHeader>
          <CardContent className="divide-y divide-line">
            {history.data?.length === 0 && <p className="text-sm text-muted">None yet.</p>}
            {history.data?.map((h) => (
              <button key={h.id} onClick={() => onCreated(h.id)} className="flex w-full items-center gap-2 py-2 text-left text-sm">
                <Badge variant={h.status === "completed" ? "ok" : "warn"}>{h.kind.replace("_", " ")}</Badge>
                <span className="flex-1 text-muted">{h.score ? `${h.score.correct}/${h.score.answered} correct` : h.status}</span>
                <span className="text-xs text-subtle">{timeAgo(h.created_at)}</span>
              </button>
            ))}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function Runner({ courseId, assessmentId, onExit }: { courseId: string; assessmentId: string; onExit: () => void }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["assessment", assessmentId], queryFn: () => api<Assessment>(`/api/assessments/${assessmentId}`) });
  const [idx, setIdx] = React.useState<number | null>(null);
  const answer = useMutation({
    mutationFn: (p: { question_id: string; response: Record<string, string>; reasoning: string | null; confidence: number | null }) =>
      api<{ feedback: Feedback }>(`/api/assessments/${assessmentId}/answers`, { method: "POST", body: p }),
    onSuccess: () => {
      q.refetch();
      qc.invalidateQueries({ queryKey: ["analytics"] });
    },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const complete = useMutation({
    mutationFn: () => api<{ report: AssessmentReport }>(`/api/assessments/${assessmentId}/complete`, { method: "POST" }),
    onSuccess: () => {
      q.refetch();
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      qc.invalidateQueries({ queryKey: ["assessments", courseId] });
    },
    onError: (e) => toast.error(errorMessage(e)),
  });
  if (q.isLoading) return <LoadingState />;
  if (q.isError) return <ErrorState message={errorMessage(q.error)} onRetry={() => q.refetch()} />;
  const a = q.data!;
  const answered = a.items.filter((i) => i.attempt).length;
  const firstOpen = a.items.findIndex((i) => !i.attempt);
  const cur = idx ?? (firstOpen === -1 ? a.items.length - 1 : firstOpen);
  const item = a.items[cur];

  if (a.status === "completed" && a.report) return <Report a={a} courseId={courseId} onExit={onExit} />;

  return (
    <div className="mx-auto max-w-4xl">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-brand-soft">{a.kind.replace("_", " ")} assessment</div>
          <h1 className="text-xl font-semibold">
            Question {cur + 1} of {a.items.length}
          </h1>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="ghost" size="sm" onClick={onExit}>
            Exit
          </Button>
          <Button variant="outline" size="sm" onClick={() => complete.mutate()} disabled={answered === 0 || complete.isPending} data-testid="finish-assessment">
            Finish &amp; see report
          </Button>
        </div>
      </div>
      <Progress value={(answered / a.items.length) * 100} className="mb-4" />
      <div className="mb-4 flex flex-wrap gap-1.5">
        {a.items.map((it, i) => (
          <button key={it.position} onClick={() => setIdx(i)} aria-label={`Question ${i + 1}`} className={cn("flex size-8 items-center justify-center rounded-lg border text-xs", i === cur ? "border-brand bg-brand/20" : "border-line-strong", it.attempt?.is_correct === true && "text-ok", it.attempt?.is_correct === false && "text-bad")}>
            {it.attempt ? it.attempt.is_correct ? <CheckCircle2 className="size-3.5" /> : <XCircle className="size-3.5" /> : i + 1}
          </button>
        ))}
      </div>
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <QuestionMeta q={item.question} />
            {item.selection_reason && (
              <Tip content={item.selection_reason}>
                <span className="inline-flex cursor-help items-center gap-1 text-xs text-subtle">
                  <Info className="size-3.5" /> Why this question?
                </span>
              </Tip>
            )}
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          {item.attempt ? (
            <>
              <p className="text-[15px] leading-relaxed">{item.question.stem}</p>
              <FeedbackPanel f={item.attempt.feedback} />
              {cur < a.items.length - 1 ? (
                <Button
                  onClick={() => {
                    const nextOpen = a.items.findIndex((it, i) => i > cur && !it.attempt);
                    setIdx(nextOpen === -1 ? cur + 1 : nextOpen);
                  }}
                  data-testid="next-question"
                >
                  Next question <ArrowRight />
                </Button>
              ) : (
                <Button onClick={() => complete.mutate()} disabled={complete.isPending} data-testid="finish-assessment-bottom">
                  Finish &amp; see report <ArrowRight />
                </Button>
              )}
            </>
          ) : (
            <QuestionForm
              q={item.question}
              pending={answer.isPending}
              onSubmit={(p) => {
                setIdx(cur); // stay on this question so its feedback is shown before moving on
                answer.mutate({ question_id: item.question.id, ...p });
              }}
            />
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function Report({ a, courseId, onExit }: { a: Assessment; courseId: string; onExit: () => void }) {
  const r = a.report!;
  return (
    <div className="mx-auto max-w-5xl" data-testid="assessment-report">
      <PageHeader
        eyebrow="Post-assessment report"
        title={`${r.score.correct} of ${r.score.answered} correct (${pct(r.score.accuracy)})`}
        description="Weak topics, likely misconceptions and what to do next, computed from this assessment and your learner model."
        actions={
          <>
            <Button variant="outline" onClick={onExit}>
              New assessment
            </Button>
            <Button asChild>
              <Link href={`/app/courses/${courseId}/progress`}>Open analytics</Link>
            </Button>
          </>
        }
      />
      <div className="grid gap-4 lg:grid-cols-[1.4fr_1fr]">
        <Card>
          <CardHeader>
            <CardTitle>By concept</CardTitle>
          </CardHeader>
          <CardContent>
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-subtle">
                <tr>
                  <th className="pb-2 font-medium">Concept</th>
                  <th className="pb-2 font-medium">Correct</th>
                  <th className="pb-2 font-medium">Mastery estimate</th>
                  <th className="pb-2 font-medium" />
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {r.topics.map((t) => (
                  <tr key={t.concept_id}>
                    <td className="py-2">{t.name}</td>
                    <td className="py-2 font-mono">
                      {t.correct}/{t.answered}
                    </td>
                    <td className="py-2 font-mono">{pct(t.mastery_after)}</td>
                    <td className="py-2 text-right">{t.weak ? <Badge variant="warn">needs work</Badge> : <Badge variant="ok">on track</Badge>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <AlertTriangle className="size-4 text-warn" /> Likely misconceptions
            </CardTitle>
            <CardDescription>Hypotheses supported by answer patterns in this assessment.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            {r.likely_misconceptions.length === 0 && <p className="text-sm text-muted">No answer matched a known misconception pattern.</p>}
            {r.likely_misconceptions.map((h) => (
              <div key={h.misconception_key} className="rounded-xl border border-warn/30 bg-warn/5 p-3">
                <div className="flex items-start justify-between gap-2">
                  <span className="text-sm font-medium">{h.title}</span>
                  <span className={cn("rounded-full border px-2 py-0.5 text-[10px]", HYPOTHESIS_STYLE[h.status]?.cls)}>{HYPOTHESIS_STYLE[h.status]?.label}</span>
                </div>
                <Button variant="warn" size="sm" className="mt-2" asChild>
                  <Link href={`/app/courses/${courseId}/lab?misconception=${h.misconception_key}`}>Investigate in the Blindspot Lab</Link>
                </Button>
              </div>
            ))}
          </CardContent>
        </Card>
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Recommended next</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-2 md:grid-cols-3">
            {r.recommendations.map((rec, i) => (
              <RecommendationCard key={rec.title} courseId={courseId} r={rec} primary={i === 0} />
            ))}
          </CardContent>
        </Card>
      </div>
      <ul className="mt-4 list-disc space-y-1 pl-5 text-xs text-subtle">
        {r.notes.map((n) => (
          <li key={n}>{n}</li>
        ))}
      </ul>
    </div>
  );
}
