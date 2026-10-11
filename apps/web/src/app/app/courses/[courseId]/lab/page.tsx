"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowRight,
  BookOpen,
  Check,
  FlaskConical,
  GitBranch,
  HelpCircle,
  Lightbulb,
  Microscope,
  PlayCircle,
  Repeat,
  ScanSearch,
  Sparkles,
  Target,
  TrendingUp,
  Wand2,
} from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import * as React from "react";
import { toast } from "sonner";
import { CitationChip } from "@/components/learning/citations";
import { FeedbackPanel } from "@/components/learning/feedback";
import { QuestionForm, QuestionMeta, type AnswerPayload } from "@/components/learning/question-form";
import { PageHeader } from "@/components/shell/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { api, errorMessage } from "@/lib/api";
import { useCourseId } from "@/lib/hooks";
import type { DiagnosticSession, GraphNode, TimelineEvent } from "@/lib/types";
import { HYPOTHESIS_STYLE, cn, pct, timeAgo } from "@/lib/utils";

const STEPS = [
  { key: "answer", label: "Diagnose", icon: HelpCircle },
  { key: "probing", label: "Investigate", icon: Microscope },
  { key: "repair", label: "Explain", icon: Lightbulb },
  { key: "practice", label: "Repair", icon: Repeat },
  { key: "transfer", label: "Transfer", icon: GitBranch },
  { key: "completed", label: "Update", icon: TrendingUp },
];

const HYP_COLORS: Record<string, string> = {
  misconception: "#fbbf24",
  calculation_error: "#22d3ee",
  misread_question: "#818cf8",
  missing_prerequisite: "#f87171",
  guess: "#64708a",
};

function LabInner() {
  const courseId = useCourseId()!;
  const sp = useSearchParams();
  const router = useRouter();
  const sessionId = sp.get("session");
  const setSession = (id: string | null) => router.replace(id ? `?session=${id}` : "?", { scroll: false });
  return sessionId ? <SessionView courseId={courseId} sessionId={sessionId} onExit={() => setSession(null)} /> : <StartPanel courseId={courseId} preselect={sp.get("misconception")} onStarted={setSession} />;
}

export default function LabPage() {
  return (
    <React.Suspense fallback={<LoadingState />}>
      <LabInner />
    </React.Suspense>
  );
}

// -------------------------------------------------------------------------------------------------

function StartPanel({ courseId, preselect, onStarted }: { courseId: string; preselect: string | null; onStarted: (id: string) => void }) {
  const qc = useQueryClient();
  const mis = useQuery({
    queryKey: ["misconceptions", courseId],
    queryFn: () => api<{ catalogue_status: string; entries: { key: string; title: string; description: string; active: boolean; reason: string; concept: string | null }[] }>(`/api/courses/${courseId}/misconceptions`),
  });
  const graph = useQuery({ queryKey: ["graph", courseId], queryFn: () => api<{ nodes: GraphNode[] }>(`/api/courses/${courseId}/graph`) });
  const past = useQuery({ queryKey: ["diagnostics", courseId], queryFn: () => api<{ id: string; stage: string; outcome: string | null; is_demo_script: boolean; created_at: string; misconception_key: string | null }[]>(`/api/courses/${courseId}/diagnostics`) });
  const start = useMutation({
    mutationFn: (body: Record<string, string>) => api<DiagnosticSession>(`/api/courses/${courseId}/diagnostics`, { method: "POST", body }),
    onSuccess: (s) => {
      qc.invalidateQueries({ queryKey: ["diagnostics", courseId] });
      onStarted(s.id);
    },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const [concept, setConcept] = React.useState("");
  const pre = mis.data?.entries.find((e) => e.key === preselect);

  return (
    <div className="mx-auto max-w-7xl">
      <PageHeader
        eyebrow="Blindspot Diagnostic Lab"
        title={
          <span className="flex items-center gap-3">
            <ScanSearch className="size-7 text-warn" /> Find the blindspot, then prove it&apos;s gone
          </span>
        }
        description="Answer a realistic business problem and explain your reasoning. A wrong answer opens competing hypotheses; a discriminating follow-up question tests them before any repair, and a structurally different transfer problem checks whether understanding actually moved."
      />

      {pre && (
        <div className="mb-4 flex flex-col gap-3 rounded-2xl border border-warn/40 bg-warn/10 p-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <div className="text-sm font-semibold text-warn">Recommended investigation: {pre.title}</div>
            <div className="text-xs text-muted">{pre.description}</div>
          </div>
          <Button variant="warn" onClick={() => start.mutate({ misconception_key: pre.key })} disabled={start.isPending}>
            <Microscope /> Start investigation
          </Button>
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-[1.3fr_1fr]">
        <Card className="relative overflow-hidden">
          <div className="glow-indigo pointer-events-none absolute inset-0 opacity-70" />
          <CardHeader className="relative">
            <Badge variant="warn" className="w-fit">
              <Sparkles className="size-3" /> Signature scenario
            </Badge>
            <CardTitle className="mt-2 text-lg">The contribution-margin price cut</CardTitle>
            <CardDescription>
              A company sells a product for ₹100 with a ₹60 variable cost and plans to cut the price to ₹80. What volume increase keeps total contribution the same? Includes an optional scripted learner answer for repeatable demos; grading, probing, retrieval and mastery updates are all computed live.
            </CardDescription>
          </CardHeader>
          <CardContent className="relative">
            <Button size="lg" onClick={() => start.mutate({ scenario: "contribution_price_cut" })} disabled={start.isPending} data-testid="start-scenario">
              <PlayCircle /> Start the scenario
            </Button>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Investigate a concept</CardTitle>
            <CardDescription>The lab picks a verified question whose wrong answers map to known misconceptions.</CardDescription>
          </CardHeader>
          <CardContent className="flex gap-2">
            <select value={concept} onChange={(e) => setConcept(e.target.value)} aria-label="Concept" className="flex-1 rounded-lg border border-line-strong bg-surface-2 px-2.5 text-sm">
              <option value="">Choose a concept…</option>
              {graph.data?.nodes
                .filter((n) => n.kind === "concept")
                .map((n) => (
                  <option key={n.concept_id} value={n.concept_id}>
                    {n.name}
                  </option>
                ))}
            </select>
            <Button disabled={!concept || start.isPending} onClick={() => start.mutate({ concept_id: concept })}>
              Start <ArrowRight />
            </Button>
          </CardContent>
        </Card>
      </div>

      <Card className="mt-4">
        <CardHeader>
          <CardTitle>Misconception catalogue for this course</CardTitle>
          <CardDescription>{mis.data?.catalogue_status}</CardDescription>
        </CardHeader>
        <CardContent>
          {mis.isLoading && <LoadingState />}
          <div className="grid gap-2 md:grid-cols-2">
            {mis.data?.entries.map((e) => (
              <div key={e.key} className={cn("rounded-xl border p-3", e.active ? "border-line bg-surface-2/60" : "border-dashed border-line opacity-60")}>
                <div className="flex items-start justify-between gap-2">
                  <div className="text-sm font-medium">{e.title}</div>
                  {e.active ? (
                    <Button size="sm" variant="outline" onClick={() => start.mutate({ misconception_key: e.key })} disabled={start.isPending}>
                      Investigate
                    </Button>
                  ) : (
                    <Badge variant="muted">inactive</Badge>
                  )}
                </div>
                <p className="mt-1 text-xs text-muted">{e.description}</p>
                <p className="mt-1 text-[11px] text-subtle">
                  {e.concept ? `${e.concept} · ` : ""}
                  {e.reason}
                </p>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {past.data && past.data.length > 0 && (
        <Card className="mt-4">
          <CardHeader>
            <CardTitle>Your investigations</CardTitle>
          </CardHeader>
          <CardContent className="divide-y divide-line">
            {past.data.map((s) => (
              <button key={s.id} onClick={() => onStarted(s.id)} className="flex w-full items-center gap-3 py-2 text-left text-sm hover:text-fg">
                <Badge variant={s.stage === "completed" ? "ok" : "warn"}>{s.stage}</Badge>
                <span className="flex-1 truncate text-muted">
                  {s.misconception_key ?? "concept check"} {s.outcome ? `· ${s.outcome}` : ""} {s.is_demo_script ? "· scripted scenario" : ""}
                </span>
                <span className="text-xs text-subtle">{timeAgo(s.created_at)}</span>
              </button>
            ))}
          </CardContent>
        </Card>
      )}
    </div>
  );
}

// -------------------------------------------------------------------------------------------------

function SessionView({ courseId, sessionId, onExit }: { courseId: string; sessionId: string; onExit: () => void }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["diag", sessionId], queryFn: () => api<DiagnosticSession>(`/api/diagnostics/${sessionId}`) });
  const update = (s: DiagnosticSession) => {
    qc.setQueryData(["diag", sessionId], s);
    qc.invalidateQueries({ queryKey: ["analytics"] });
    qc.invalidateQueries({ queryKey: ["dashboard"] });
  };
  const answer = useMutation({
    mutationFn: (p: AnswerPayload) => api<DiagnosticSession>(`/api/diagnostics/${sessionId}/answer`, { method: "POST", body: p }),
    onSuccess: update,
    onError: (e) => toast.error(errorMessage(e)),
  });
  const probe = useMutation({
    mutationFn: (p: { probe_id: string; response: Record<string, string> }) => api<DiagnosticSession>(`/api/diagnostics/${sessionId}/probe`, { method: "POST", body: p }),
    onSuccess: update,
    onError: (e) => toast.error(errorMessage(e)),
  });
  const cont = useMutation({
    mutationFn: () => api<DiagnosticSession>(`/api/diagnostics/${sessionId}/continue`, { method: "POST" }),
    onSuccess: update,
    onError: (e) => toast.error(errorMessage(e)),
  });
  const bottom = React.useRef<HTMLDivElement>(null);
  React.useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [q.data?.timeline.length]);

  if (q.isLoading) return <LoadingState />;
  if (q.isError) return <ErrorState message={errorMessage(q.error)} onRetry={() => q.refetch()} />;
  const s = q.data!;
  const stageIdx = STEPS.findIndex((x) => x.key === s.stage);
  const busy = answer.isPending || probe.isPending || cont.isPending;
  const pendingQ = s.pending?.question;
  const scripted = s.scenario;
  const isMain = s.pending?.type === "answer_question";

  return (
    <div className="mx-auto max-w-7xl">
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-warn">Blindspot investigation</div>
          <h1 className="text-xl font-semibold tracking-tight">{s.concept.name}</h1>
        </div>
        <Button variant="ghost" size="sm" onClick={onExit}>
          All investigations
        </Button>
      </div>

      <ol className="mb-6 grid grid-cols-3 gap-2 sm:grid-cols-6" aria-label="Progress">
        {STEPS.map((st, i) => {
          const done = i < stageIdx || s.stage === "completed";
          const now = i === stageIdx && s.stage !== "completed";
          return (
            <li key={st.key} className={cn("flex items-center gap-2 rounded-xl border px-3 py-2 text-xs", done ? "border-ok/40 bg-ok/10 text-ok" : now ? "pulse-ring border-brand/60 bg-brand/15 text-fg" : "border-line text-subtle")}>
              {done ? <Check className="size-3.5" /> : <st.icon className="size-3.5" />}
              <span className="font-medium">{st.label}</span>
            </li>
          );
        })}
      </ol>

      {scripted && (
        <div className="mb-4 flex items-start gap-3 rounded-xl border border-accent/30 bg-accent/5 p-3 text-xs text-muted">
          <Wand2 className="mt-0.5 size-4 shrink-0 text-accent" /> {scripted.label}
        </div>
      )}

      <div className="grid gap-4 xl:grid-cols-[1.55fr_1fr]">
        <div className="space-y-4">
          {s.timeline.map((e, i) => (
            <TimelineCard key={i} e={e} s={s} onContinue={() => cont.mutate()} busy={busy} />
          ))}

          {pendingQ && (
            <Card className="border-brand/50">
              <CardHeader>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <CardTitle>{isMain ? "Your answer" : s.pending?.type === "answer_practice" ? "Targeted practice" : "Transfer problem"}</CardTitle>
                  <QuestionMeta q={pendingQ} />
                </div>
                {s.pending?.type === "answer_transfer" && <CardDescription>A different question family, context and numbers: does the corrected understanding transfer?</CardDescription>}
              </CardHeader>
              <CardContent>
                <ScriptedForm
                  q={pendingQ}
                  onSubmit={(p) => answer.mutate(p)}
                  pending={answer.isPending}
                  scripted={isMain && scripted ? { value: scripted.scripted_answer.value, option_id: scripted.scripted_answer.option_id, reasoning: scripted.scripted_reasoning, confidence: scripted.scripted_confidence } : undefined}
                />
              </CardContent>
            </Card>
          )}

          {s.pending?.type === "answer_probe" && s.pending.probe && (
            <ProbeForm
              probe={s.pending.probe}
              busy={probe.isPending}
              scripted={scripted?.scripted_probe_answers}
              probeKey={[...s.timeline].reverse().find((e) => e.type === "probe")?.probe?.key}
              onSubmit={(response) => probe.mutate({ probe_id: s.pending!.probe!.id, response })}
            />
          )}

          {s.stage === "completed" && <CompleteCard s={s} courseId={courseId} />}
          <div ref={bottom} />
        </div>

        <aside className="space-y-4 xl:sticky xl:top-6 xl:h-fit">
          <HypothesisPanel s={s} />
          {s.mastery_change && (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <TrendingUp className="size-4 text-accent" /> Mastery evidence this session
                </CardTitle>
                <CardDescription>BKT estimate for {s.mastery_change.concept}</CardDescription>
              </CardHeader>
              <CardContent className="space-y-2">
                <div className="flex items-baseline gap-2 font-mono text-sm">
                  <span className="text-muted">{pct(s.mastery_change.before)}</span>
                  <ArrowRight className="size-3.5 text-subtle" />
                  <span className="text-lg font-semibold text-fg">{pct(s.mastery_change.after)}</span>
                </div>
                {s.mastery_change.steps.map((st, i) => (
                  <div key={i} className="flex items-center justify-between rounded-lg bg-surface-2 px-3 py-1.5 text-xs">
                    <span className="capitalize text-muted">{st.source}</span>
                    <span className={st.correct ? "text-ok" : "text-bad"}>{st.correct ? "correct" : "incorrect"}</span>
                    <span className="text-subtle">weight {st.weight}</span>
                    <span className="font-mono">{pct(st.p_after)}</span>
                  </div>
                ))}
                <p className="text-[11px] text-subtle">Probe answers test explanations, so they are not counted as mastery evidence. Practice right after a worked example is down-weighted.</p>
              </CardContent>
            </Card>
          )}
        </aside>
      </div>
    </div>
  );
}

function ScriptedForm({ q, onSubmit, pending, scripted }: { q: NonNullable<DiagnosticSession["pending"]>["question"] & object; onSubmit: (p: AnswerPayload) => void; pending: boolean; scripted?: { value?: string; option_id?: string; reasoning: string; confidence: number } }) {
  const [fill, setFill] = React.useState<typeof scripted | undefined>(undefined);
  return (
    <div className="space-y-3">
      {scripted && !fill && (
        <Button variant="outline" size="sm" onClick={() => setFill(scripted)} data-testid="fill-scripted">
          <Wand2 /> Fill in the scripted learner&apos;s answer
        </Button>
      )}
      <QuestionForm q={q} onSubmit={onSubmit} pending={pending} initial={fill ? { value: fill.value, option_id: fill.option_id, reasoning: fill.reasoning, confidence: fill.confidence } : undefined} />
    </div>
  );
}

function ProbeForm({ probe, onSubmit, busy, scripted, probeKey }: { probe: { id: string; prompt: string; type: string; options: { id: string; text: string }[] }; onSubmit: (r: Record<string, string>) => void; busy: boolean; scripted?: Record<string, Record<string, string>>; probeKey?: string }) {
  const [opt, setOpt] = React.useState("");
  const [val, setVal] = React.useState("");
  const script = probeKey ? scripted?.[probeKey] : undefined;
  return (
    <Card className="border-warn/50">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-warn">
          <Microscope className="size-4" /> Follow-up question
        </CardTitle>
        <CardDescription>Chosen because it best discriminates between the explanations still in play. There is no penalty: it tests the explanation, not your mastery.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <p className="text-[15px]">{probe.prompt}</p>
        {script && (
          <Button variant="outline" size="sm" onClick={() => (script.option_id ? setOpt(script.option_id) : setVal(script.value ?? ""))} data-testid="fill-scripted-probe">
            <Wand2 /> Use the scripted learner&apos;s response
          </Button>
        )}
        {probe.type === "mcq" ? (
          <div className="space-y-2">
            {probe.options.map((o) => (
              <label key={o.id} className={cn("flex cursor-pointer items-start gap-3 rounded-xl border px-3.5 py-2.5 text-sm", opt === o.id ? "border-warn/70 bg-warn/10" : "border-line-strong hover:border-warn/40")}>
                <input type="radio" name="probe" checked={opt === o.id} onChange={() => setOpt(o.id)} className="mt-1 accent-[#fbbf24]" />
                <span>{o.text}</span>
              </label>
            ))}
          </div>
        ) : (
          <input value={val} onChange={(e) => setVal(e.target.value)} aria-label="Your answer" placeholder="Number" className="h-10 w-48 rounded-lg border border-line-strong bg-surface-2 px-3 text-sm" />
        )}
        <Button variant="warn" disabled={busy || (probe.type === "mcq" ? !opt : !val)} onClick={() => onSubmit(probe.type === "mcq" ? { option_id: opt } : { value: val })} data-testid="submit-probe">
          Submit response
        </Button>
      </CardContent>
    </Card>
  );
}

function DistBars({ dist, labels, before }: { dist: Record<string, number>; labels: Record<string, string>; before?: Record<string, number> }) {
  const keys = Object.keys(dist).sort((a, b) => dist[b] - dist[a]);
  return (
    <div className="space-y-2">
      {keys.map((k) => (
        <div key={k} className="space-y-1">
          <div className="flex justify-between gap-2 text-xs">
            <span className={k === "misconception" ? "font-medium text-warn" : "text-muted"}>{labels[k] ?? k}</span>
            <span className="font-mono text-fg">
              {before && <span className="mr-1 text-subtle">{pct(before[k])} →</span>}
              {pct(dist[k])}
            </span>
          </div>
          <div className="h-1.5 overflow-hidden rounded-full bg-surface-3">
            <div className="h-full rounded-full transition-all duration-700" style={{ width: `${dist[k] * 100}%`, background: HYP_COLORS[k] ?? "#818cf8" }} />
          </div>
        </div>
      ))}
    </div>
  );
}

function HypothesisPanel({ s }: { s: DiagnosticSession }) {
  const hs = s.hypotheses[0];
  const h = s.hypothesis;
  return (
    <Card className="border-warn/30">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Target className="size-4 text-warn" /> Hypotheses
        </CardTitle>
        <CardDescription>Competing explanations for this answer, updated by Bayes&apos; rule after each probe. Model probabilities from hand-set priors, not a validated diagnosis.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {!hs && <p className="text-sm text-muted">{s.stage === "answer" ? "Hypotheses appear after you answer." : "No misconception hypothesis was opened for this answer."}</p>}
        {hs && <DistBars dist={hs.distribution} labels={hs.labels} />}
        {h && (
          <div className="space-y-2 rounded-xl border border-line bg-surface-2/60 p-3">
            <div className="flex items-start justify-between gap-2">
              <span className="text-sm font-semibold">{h.title}</span>
              <span className={cn("shrink-0 rounded-full border px-2 py-0.5 text-[10px]", HYPOTHESIS_STYLE[h.status]?.cls)} data-testid="hypothesis-status">
                {HYPOTHESIS_STYLE[h.status]?.label ?? h.status}
              </span>
            </div>
            <p className="text-xs text-muted">{h.description}</p>
            <div className="flex gap-3 text-[11px] text-subtle">
              <span>posterior {h.posterior.toFixed(2)}</span>
              <span>{h.evidence_count} evidence item(s)</span>
              {h.revisit_at && <span>revisit {new Date(h.revisit_at).toLocaleDateString()}</span>}
            </div>
          </div>
        )}
        {hs && hs.adjustments.length > 0 && (
          <div className="space-y-1">
            <div className="text-[11px] font-semibold uppercase tracking-wider text-subtle">Why these priors</div>
            <ul className="list-disc space-y-0.5 pl-4 text-[11px] text-muted">
              {hs.adjustments.map((a) => (
                <li key={a}>{a}</li>
              ))}
            </ul>
          </div>
        )}
        <p className="text-[11px] text-subtle">Status rules: suspected ≥ 0.35; supported needs ≥ 0.75 and at least two independent pieces of evidence. A single error never yields more than “suspected”.</p>
      </CardContent>
    </Card>
  );
}

function TimelineCard({ e, s, onContinue, busy }: { e: TimelineEvent; s: DiagnosticSession; onContinue: () => void; busy: boolean }) {
  const hs = s.hypotheses[0];
  if (e.type === "question" && e.question && !(s.pending?.question?.id === e.question.id)) {
    return (
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <CardTitle className="capitalize">{e.role === "diagnostic" ? "Diagnostic problem" : e.role === "practice" ? "Targeted practice" : "Transfer problem"}</CardTitle>
            <QuestionMeta q={e.question} />
          </div>
        </CardHeader>
        <CardContent>
          <p className="text-[15px] leading-relaxed">{e.question.stem}</p>
        </CardContent>
      </Card>
    );
  }
  if (e.type === "answer" && e.feedback) {
    return (
      <Card>
        <CardContent className="space-y-3 p-5">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className="text-muted">You answered</span>
            <span className="rounded-md bg-surface-3 px-2 py-0.5 font-mono">{e.response?.value ?? e.response?.option_id?.toUpperCase() ?? e.response?.text}</span>
            {e.confidence && <Badge variant="muted">confidence {e.confidence}/5</Badge>}
          </div>
          {e.reasoning && <p className="rounded-lg border-l-2 border-line-strong pl-3 text-sm italic text-muted">“{e.reasoning}”</p>}
          <FeedbackPanel f={e.feedback} />
        </CardContent>
      </Card>
    );
  }
  if (e.type === "hypotheses" && hs) {
    return (
      <Card className="border-warn/30 bg-warn/[0.03]">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-warn">
            <Microscope className="size-4" /> Investigation opened, not a verdict
          </CardTitle>
          <CardDescription>The answer matches a known misconception pattern, but a slip, a misreading or a missing prerequisite could produce it too.</CardDescription>
        </CardHeader>
        <CardContent>
          <DistBars dist={e.distribution ?? {}} labels={hs.labels} />
        </CardContent>
      </Card>
    );
  }
  if (e.type === "probe_answer" && hs) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Probe answered: evidence updated</CardTitle>
          {e.note && <CardDescription>{e.note}</CardDescription>}
        </CardHeader>
        <CardContent>
          <DistBars dist={e.after ?? {}} before={e.before} labels={hs.labels} />
        </CardContent>
      </Card>
    );
  }
  if (e.type === "probe" && e.probe?.answered) {
    return (
      <div className="rounded-xl border border-line bg-surface-2/50 px-4 py-3 text-sm">
        <span className="text-xs font-semibold uppercase tracking-wider text-warn">Follow-up</span>
        <p className="mt-1">{e.probe.prompt}</p>
        {e.eig_bits !== undefined && <p className="mt-1 text-[11px] text-subtle">Selected for the highest expected information gain ({e.eig_bits.toFixed(2)} bits).</p>}
      </div>
    );
  }
  if (e.type === "conclusion") {
    return (
      <div className="rounded-xl border border-brand/30 bg-brand/5 px-4 py-3 text-sm" data-testid="conclusion">
        <FlaskConical className="mr-2 inline size-4 text-brand-soft" />
        {e.text}
      </div>
    );
  }
  if (e.type === "note") {
    return <div className="rounded-xl border border-line bg-surface-2/50 px-4 py-3 text-sm text-muted">{e.text}</div>;
  }
  if (e.type === "repair" && e.intervention) {
    const c = e.intervention.content;
    return (
      <Card className="border-brand/40" data-testid="repair-card">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Lightbulb className="size-4 text-brand-soft" /> Explanation and repair
          </CardTitle>
          <CardDescription>{c.explanation.provenance}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-[15px] leading-relaxed">{c.explanation.contrast}</p>
          {c.explanation.key_rule && <div className="rounded-lg border border-brand/30 bg-brand/10 px-3 py-2 font-mono text-sm text-brand-soft">{c.explanation.key_rule}</div>}
          {c.explanation.generated?.text && (
            <div className="rounded-lg border border-line bg-surface-2 p-3 text-sm">
              <div className="mb-1 text-[11px] text-subtle">Model explanation ({c.explanation.generated.model}), restricted to the cited sources</div>
              {c.explanation.generated.text}
            </div>
          )}
          {c.worked_example && (
            <div className="grid gap-3 md:grid-cols-2">
              <div className="rounded-xl border border-ok/30 bg-ok/5 p-3">
                <div className="mb-1 text-xs font-semibold text-ok">Preserving contribution (correct)</div>
                <ol className="list-decimal space-y-0.5 pl-4 text-sm">
                  {c.worked_example.steps.map((st) => (
                    <li key={st}>{st}</li>
                  ))}
                </ol>
              </div>
              {c.worked_example.contrast && (
                <div className="rounded-xl border border-warn/30 bg-warn/5 p-3">
                  <div className="mb-1 text-xs font-semibold text-warn">What the misconception computes</div>
                  <p className="text-sm">
                    <span className="font-mono">{c.worked_example.contrast.misconception_answer}{c.worked_example.unit === "%" ? "%" : ""}</span>: {c.worked_example.contrast.label}.
                  </p>
                </div>
              )}
            </div>
          )}
          <div className="space-y-1.5">
            <div className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-subtle">
              <BookOpen className="size-3.5" /> In your course materials
            </div>
            {e.intervention.citations.map((ci) => (
              <div key={ci.unit_id} className="rounded-lg border border-line bg-surface-2/60 p-2.5">
                <CitationChip c={ci} />
                <p className="mt-1.5 line-clamp-3 text-xs text-muted">“{ci.excerpt}”</p>
              </div>
            ))}
          </div>
          {s.stage === "repair" && (
            <Button onClick={onContinue} disabled={busy} data-testid="continue-repair">
              I&apos;ve read this, give me a practice problem <ArrowRight />
            </Button>
          )}
        </CardContent>
      </Card>
    );
  }
  return null;
}

function CompleteCard({ s, courseId }: { s: DiagnosticSession; courseId: string }) {
  const transfer = [...s.timeline].reverse().find((e) => e.type === "answer" && e.role === "transfer");
  return (
    <Card className="border-ok/40 bg-ok/[0.04]" data-testid="session-complete">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-ok">
          <Check className="size-4" /> Investigation complete
        </CardTitle>
        <CardDescription>
          {transfer?.feedback?.is_correct
            ? "You solved a structurally different transfer problem. The hypothesis is marked as repaired and scheduled for a later revisit before it can be considered resolved."
            : transfer
              ? "The transfer problem was not solved yet, so the hypothesis stays open and will be recommended again."
              : "Session finished."}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-wrap gap-2">
        <Button asChild>
          <Link href={`/app/courses/${courseId}/progress`}>
            See it in your analytics <ArrowRight />
          </Link>
        </Button>
        <Button variant="outline" asChild>
          <Link href={`/app/courses/${courseId}/assess`}>Take an adaptive assessment</Link>
        </Button>
      </CardContent>
    </Card>
  );
}
