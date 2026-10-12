"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, ChevronDown, FlaskConical, Info, Loader2, Play, XCircle } from "lucide-react";
import * as React from "react";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { toast } from "sonner";
import { PageHeader } from "@/components/shell/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/states";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Tip } from "@/components/ui/tooltip";
import { api, errorMessage } from "@/lib/api";
import type { EvalResult, EvalRun } from "@/lib/types";
import { cn, pct, timeAgo } from "@/lib/utils";

/* eslint-disable @typescript-eslint/no-explicit-any */
const TT = { contentStyle: { background: "#16223a", border: "1px solid #2a3a5c", borderRadius: 8, fontSize: 12 }, labelStyle: { color: "#93a0bb" } };

export default function EvaluationPage() {
  const qc = useQueryClient();
  const runs = useQuery({
    queryKey: ["eval-runs"],
    queryFn: () => api<EvalRun[]>("/api/evaluation/runs"),
    refetchInterval: (q) => ((q.state.data ?? []).some((r) => r.status === "queued" || r.status === "running") ? 3000 : false),
  });
  const queue = useMutation({
    mutationFn: (kind: string) => api<EvalRun>("/api/evaluation/runs", { method: "POST", body: { kind } }),
    onSuccess: () => {
      toast.success("Evaluation queued; the worker will run it in the background.");
      qc.invalidateQueries({ queryKey: ["eval-runs"] });
    },
    onError: (e) => toast.error(errorMessage(e)),
  });
  if (runs.isLoading) return <LoadingState />;
  if (runs.isError) return <ErrorState message={errorMessage(runs.error)} onRetry={() => runs.refetch()} />;
  const all = runs.data ?? [];
  const latest = (k: string) => all.find((r) => r.kind === k && r.status === "succeeded");
  const active = all.filter((r) => r.status === "queued" || r.status === "running");

  return (
    <div className="mx-auto max-w-7xl">
      <PageHeader
        eyebrow="Evaluation Lab"
        title={
          <span className="flex items-center gap-3">
            <FlaskConical className="size-7 text-accent" /> Measured, with methods and limits
          </span>
        }
        description="Every number here comes from a recorded evaluation run stored in the database, with its dataset version, models, seed and case-level outputs. Nothing is hard-coded. Metrics that need a judge model we don't have are marked unavailable, and judge-free substitutes are labelled as such."
        actions={
          <div className="flex flex-wrap gap-2">
            {(["rag", "assessment", "personalization"] as const).map((k) => (
              <Button key={k} variant="outline" size="sm" onClick={() => queue.mutate(k)} disabled={queue.isPending || active.some((r) => r.kind === k)}>
                <Play /> Run {k}
              </Button>
            ))}
          </div>
        }
      />
      {active.map((r) => (
        <div key={r.id} className="mb-3 flex items-center gap-3 rounded-xl border border-brand/40 bg-brand/10 p-3 text-sm">
          <Loader2 className="size-4 animate-spin text-brand-soft" />
          <span className="capitalize">{r.kind} evaluation {r.status}</span>
          <Progress value={r.progress * 100} className="max-w-xs" />
          <span className="font-mono text-xs text-muted">{pct(r.progress)}</span>
        </div>
      ))}
      <Tabs defaultValue="rag">
        <TabsList>
          <TabsTrigger value="rag">Retrieval &amp; grounding</TabsTrigger>
          <TabsTrigger value="assessment">Assessment quality</TabsTrigger>
          <TabsTrigger value="personalization">Personalization</TabsTrigger>
          <TabsTrigger value="runs">Runs &amp; method</TabsTrigger>
        </TabsList>
        <TabsContent value="rag">{latest("rag") ? <RagTab run={latest("rag")!} /> : <NoRun kind="retrieval" />}</TabsContent>
        <TabsContent value="assessment">{latest("assessment") ? <AssessTab run={latest("assessment")!} /> : <NoRun kind="assessment" />}</TabsContent>
        <TabsContent value="personalization">{latest("personalization") ? <PersTab run={latest("personalization")!} /> : <NoRun kind="personalization" />}</TabsContent>
        <TabsContent value="runs">
          <RunsTab runs={all} />
        </TabsContent>
      </Tabs>
    </div>
  );
}

function NoRun({ kind }: { kind: string }) {
  return <EmptyState title={`No ${kind} evaluation recorded yet`}>Use the Run buttons above, or run evaluation/scripts/run_evaluation.py.</EmptyState>;
}

function RunMeta({ run }: { run: EvalRun }) {
  return (
    <div className="mb-4 flex flex-wrap items-center gap-2 text-xs text-muted">
      <Badge variant="ok">run {run.id.slice(0, 8)}</Badge>
      <span>finished {timeAgo(run.finished_at)}</span>
      {run.dataset_name && (
        <Badge variant="muted">
          {run.dataset_name} {run.dataset_version}
        </Badge>
      )}
      {Object.entries(run.model_info)
        .filter(([k, v]) => v && ["embedding", "reranker", "llm"].includes(k))
        .map(([k, v]) => (
          <Badge key={k} variant="muted">
            {k}: {String(v)}
          </Badge>
        ))}
      {run.seed !== null && <Badge variant="muted">seed {run.seed}</Badge>}
      <span>{run.n_results} case-level results</span>
    </div>
  );
}

function Metric({ label, m, hint }: { label: string; m: any; hint?: string }) {
  const v = m?.value;
  return (
    <Card data-testid="metric-card">
      <CardContent className="p-4">
        <div className="flex items-start justify-between gap-2">
          <div className="text-xs font-medium text-muted">{label}</div>
          {(m?.variant || hint) && (
            <Tip content={<span>{m?.framework ? `${m.framework} · ` : ""}{m?.variant ?? ""}{hint ? ` ${hint}` : ""}{m?.definition ? ` (${m.definition})` : ""}</span>}>
              <Info className="size-3.5 cursor-help text-subtle" />
            </Tip>
          )}
        </div>
        {v === null || v === undefined ? (
          <div className="mt-2">
            <div className="font-mono text-lg text-subtle">unavailable</div>
            <div className="text-[11px] text-subtle">{m?.unavailable_reason ?? "not computed"}</div>
          </div>
        ) : (
          <div className="mt-1 font-mono text-2xl font-semibold">{pct(v, 1)}</div>
        )}
        {m?.framework && <div className="mt-1 text-[10px] text-brand-soft">{m.framework}</div>}
      </CardContent>
    </Card>
  );
}

function RagTab({ run }: { run: EvalRun }) {
  const s = run.summary;
  const m = s.metrics;
  const h = s.holdout?.metrics;
  const cats = Object.entries(s.by_category as Record<string, { n: number; passed: number }>).map(([k, v]) => ({ name: k.replace("_", " "), rate: v.passed / v.n, n: v.n }));
  return (
    <div>
      <RunMeta run={run} />
      <div className="mb-2 text-xs font-semibold uppercase tracking-wider text-subtle">Framework metrics (RAGAS)</div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Metric label="Context precision" m={m.context_precision} />
        <Metric label="Context recall" m={m.context_recall} />
        <Metric label="Faithfulness (LLM judge)" m={m.faithfulness} />
        <Metric label="Answer relevancy (LLM judge)" m={m.answer_relevancy} />
      </div>
      <div className="mb-2 mt-5 text-xs font-semibold uppercase tracking-wider text-subtle">Judge-free substitutes (labelled)</div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Metric label="Faithfulness (local NLI)" m={m.faithfulness_nli} />
        <Metric label="Answer relevancy (embedding)" m={m.answer_relevancy_embed} />
      </div>
      <div className="mb-2 mt-5 text-xs font-semibold uppercase tracking-wider text-subtle">Grounding pipeline</div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Metric label={`Retrieval hit rate @${m.retrieval_hit_rate?.k ?? 6}`} m={m.retrieval_hit_rate} />
        <Metric label="MRR" m={m.mrr} />
        <Metric label="Citation-location accuracy" m={m.citation_location_accuracy} />
        <Metric label="Answers with a correct citation" m={m.answer_with_correct_citation} />
        <Metric label="Supported-query answer coverage" m={m.supported_answer_coverage} />
        <Metric label="Unsupported-query refusal accuracy" m={m.unsupported_refusal_accuracy} />
        <Metric label="False refusal rate" m={m.false_refusal_rate} hint="(lower is better)" />
        <Metric label="Source recall @k" m={m.source_recall} />
      </div>

      <div className="mt-5 grid gap-4 lg:grid-cols-[1fr_1fr]">
        <Card>
          <CardHeader>
            <CardTitle>Pass rate by category</CardTitle>
            <CardDescription>Pass = answered (or correctly refused) with a retrieved and cited annotated location.</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="h-56">
              <ResponsiveContainer>
                <BarChart data={cats} layout="vertical" margin={{ left: 30 }}>
                  <CartesianGrid stroke="#1d2a44" strokeDasharray="3 3" horizontal={false} />
                  <XAxis type="number" domain={[0, 1]} tickFormatter={(v) => `${Math.round(v * 100)}%`} tick={{ fill: "#64708a", fontSize: 11 }} />
                  <YAxis type="category" dataKey="name" tick={{ fill: "#93a0bb", fontSize: 11 }} width={110} />
                  <Tooltip {...TT} formatter={(v, _n, p) => `${pct(Number(v))} of ${p.payload.n}`} />
                  <Bar dataKey="rate" fill="#818cf8" radius={[0, 6, 6, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </CardContent>
        </Card>
        {h && (
          <Card>
            <CardHeader>
              <CardTitle>Held-out set (written after the pipeline was frozen)</CardTitle>
              <CardDescription>{s.holdout.n_cases} cases ({s.holdout.n_unsupported} off-material). The less biased estimate.</CardDescription>
            </CardHeader>
            <CardContent className="grid grid-cols-2 gap-2 text-sm">
              {[
                ["Context precision", h.context_precision],
                ["Context recall", h.context_recall],
                ["Faithfulness (NLI)", h.faithfulness_nli],
                ["Citation-location accuracy", h.citation_location_accuracy],
                ["Answer coverage", h.supported_answer_coverage],
                ["Refusal accuracy", h.unsupported_refusal_accuracy],
                ["Retrieval hit rate", h.retrieval_hit_rate],
                ["Answer relevancy (embed)", h.answer_relevancy_embed],
              ].map(([k, v]: any) => (
                <div key={k} className="flex justify-between rounded-lg bg-surface-2/60 px-3 py-1.5">
                  <span className="text-muted">{k}</span>
                  <span className="font-mono">{v?.value === null || v?.value === undefined ? "—" : pct(v.value, 1)}</span>
                </div>
              ))}
            </CardContent>
          </Card>
        )}
      </div>
      {s.ingestion && <IngestionCard ing={s.ingestion} />}
      <Cases runId={run.id} kind="rag" />
    </div>
  );
}

function IngestionCard({ ing }: { ing: any }) {
  const rows: [string, string, string][] = [];
  Object.entries(ing.sources as Record<string, any>).forEach(([file, info]) => {
    if (info.page_coverage !== undefined) rows.push([file, "Pages with extracted units", pct(info.page_coverage, 1)]);
    if (info.slide_coverage !== undefined) rows.push([file, "Slides with extracted units", pct(info.slide_coverage, 1)]);
    if (info.video_span_coverage !== undefined) rows.push([file, "Narration segments covered by transcript units", pct(info.video_span_coverage, 1)]);
    if (info.asr_wer !== undefined) rows.push([file, `Speech-to-text word error rate vs narration script (${info.transcription_model}, ${info.asr_reference_words} words)`, pct(info.asr_wer, 1)]);
  });
  rows.push(["All sources", "Units with a page, slide or timestamp anchor", pct(ing.units_with_provenance, 1)]);
  return (
    <Card className="mt-4">
      <CardHeader>
        <CardTitle>Ingestion quality</CardTitle>
        <CardDescription>Measured against the demo pack&apos;s ground truth in the same run.</CardDescription>
      </CardHeader>
      <CardContent className="divide-y divide-line text-sm">
        {rows.map(([f, k, v]) => (
          <div key={f + k} className="flex items-center justify-between gap-3 py-1.5">
            <span className="min-w-0 truncate text-muted">
              <span className="font-mono text-xs text-subtle">{f}</span> · {k}
            </span>
            <span className="font-mono">{v}</span>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

function AssessTab({ run }: { run: EvalRun }) {
  const s = run.summary;
  const pool = s.pool;
  const rep = s.repetition;
  return (
    <div>
      <RunMeta run={run} />
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Metric label="Valid question rate (pool)" m={{ value: pool.valid_question_rate, definition: `${pool.verified}/${pool.total} generated questions passed verification` }} />
        <Metric label="Template answer keys pass plug-back" m={{ value: s.answer_keys.plug_back_pass_rate, definition: `${s.answer_keys.template_questions} computed questions re-checked independently` }} />
        <Metric label="Verifier: flawed drafts caught" m={{ value: s.verifier.flaw_detection_rate, definition: `${s.verifier.flawed} deliberately flawed drafts` }} />
        <Metric label="Verifier: sound drafts rejected" m={{ value: s.verifier.false_rejection_rate, definition: `${s.verifier.sound} sound drafts (lower is better)` }} />
        <Metric label="Source-concept tag agreement" m={{ value: s.source_tags.source_concept_agreement, definition: s.source_tags.definition }} />
        <Metric label="Numerical grading accuracy" m={{ value: s.numeric_grading.accuracy, definition: `${s.numeric_grading.n} labelled responses` }} />
        <Metric label="Short-answer grading accuracy" m={{ value: s.short_answer_grading.accuracy, definition: `${s.short_answer_grading.n} labelled answers; ${pct(s.short_answer_grading.flagged_for_review)} flagged for review` }} />
        <Metric label="Exact repeats over 6 assessments" m={{ value: rep.adaptive_exact_repeat_rate, definition: `random selector: ${pct(rep.random_exact_repeat_rate)}` }} />
      </div>
      <div className="mt-5 grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Verified pool composition</CardTitle>
            <CardDescription>
              By difficulty and type ({Object.entries(pool.by_origin).map(([k, v]: any) => `${k}: ${v.verified} verified / ${v.rejected} rejected`).join(" · ")})
            </CardDescription>
          </CardHeader>
          <CardContent className="grid grid-cols-2 gap-4">
            {[
              ["Difficulty", Object.entries(pool.by_difficulty).map(([k, v]) => ({ name: ["", "Easy", "Medium", "Hard"][Number(k)], v }))],
              ["Type", Object.entries(pool.by_type).map(([k, v]) => ({ name: k.replace("_", " "), v }))],
            ].map(([title, data]: any) => (
              <div key={title}>
                <div className="mb-1 text-xs text-subtle">{title}</div>
                <div className="h-40">
                  <ResponsiveContainer>
                    <BarChart data={data}>
                      <XAxis dataKey="name" tick={{ fill: "#93a0bb", fontSize: 10 }} />
                      <YAxis tick={{ fill: "#64708a", fontSize: 10 }} allowDecimals={false} width={28} />
                      <Tooltip {...TT} />
                      <Bar dataKey="v" fill="#22d3ee" radius={[5, 5, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </div>
            ))}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Question repetition</CardTitle>
            <CardDescription>{rep.note}</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="h-48">
              <ResponsiveContainer>
                <BarChart
                  data={[
                    { name: "exact repeats", adaptive: rep.adaptive_exact_repeat_rate, random: rep.random_exact_repeat_rate },
                    { name: "family repeats", adaptive: rep.adaptive_family_repeat_rate, random: rep.random_family_repeat_rate },
                  ]}
                >
                  <CartesianGrid stroke="#1d2a44" strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="name" tick={{ fill: "#93a0bb", fontSize: 11 }} />
                  <YAxis tickFormatter={(v) => `${Math.round(v * 100)}%`} tick={{ fill: "#64708a", fontSize: 11 }} />
                  <Tooltip {...TT} formatter={(v) => pct(Number(v), 1)} />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  <Bar dataKey="adaptive" name="Blindspot selector" fill="#818cf8" radius={[5, 5, 0, 0]} />
                  <Bar dataKey="random" name="Uniform random" fill="#64708a" radius={[5, 5, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </CardContent>
        </Card>
      </div>
      <Cases runId={run.id} kind="assessment" />
    </div>
  );
}

const PERS_METRICS: [string, string, boolean][] = [
  ["post_test_accuracy", "Held-out post-test accuracy", true],
  ["retention_accuracy", "Retention after a delay", true],
  ["misconceptions_resolved_rate", "Misconceptions resolved", true],
  ["true_known_end", "Concepts truly known at end", true],
  ["mastery_brier", "Mastery calibration (Brier, lower better)", false],
  ["weak_concept_identification_accuracy", "Weak-concept identification", true],
  ["gap_precision", "Misconception identification precision", true],
  ["gap_recall", "Misconception identification recall", true],
  ["exact_repeat_rate", "Exact question repeats", false],
  ["family_repeat_rate", "Question-family repeats", false],
];

function PersTab({ run }: { run: EvalRun }) {
  const s = run.summary;
  const profiles = Object.keys(s.by_profile).sort(); // JSONB does not preserve key order
  const chart = (key: string) =>
    profiles.map((p) => ({ name: p.replace(/_/g, " "), adaptive: s.by_profile[p].adaptive?.[key]?.mean ?? null, baseline: s.by_profile[p].baseline?.[key]?.mean ?? null }));
  return (
    <div>
      <RunMeta run={run} />
      <div className="mb-4 flex items-start gap-3 rounded-xl border border-warn/40 bg-warn/5 p-3 text-xs text-muted">
        <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warn" />
        Simulated learners with explicit, hand-set response and learning assumptions ({s.learners_per_profile} per profile, {s.posttest_items} held-out post-test items). These results show how the system behaves under those assumptions. They are not evidence of learning gains for real students.
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        {[
          ["post_test_accuracy", "Held-out post-test accuracy"],
          ["misconceptions_resolved_rate", "Share of initial misconceptions resolved"],
          ["mastery_brier", "Mastery calibration: Brier score (lower is better)"],
          ["exact_repeat_rate", "Exact question repeats (lower is better)"],
        ].map(([k, t]) => (
          <Card key={k}>
            <CardHeader>
              <CardTitle>{t}</CardTitle>
              <CardDescription>Adaptive (Blindspot Lab) vs generic random quiz, same interaction budget, mean over learners.</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="h-52">
                <ResponsiveContainer>
                  <BarChart data={chart(k)}>
                    <CartesianGrid stroke="#1d2a44" strokeDasharray="3 3" vertical={false} />
                    <XAxis dataKey="name" tick={{ fill: "#93a0bb", fontSize: 11 }} />
                    <YAxis tickFormatter={(v) => (k === "mastery_brier" ? v.toFixed(2) : `${Math.round(v * 100)}%`)} tick={{ fill: "#64708a", fontSize: 11 }} />
                    <Tooltip {...TT} formatter={(v) => (k === "mastery_brier" ? Number(v).toFixed(3) : pct(Number(v), 1))} />
                    <Legend wrapperStyle={{ fontSize: 11 }} />
                    <Bar dataKey="adaptive" name="Adaptive" fill="#818cf8" radius={[5, 5, 0, 0]} />
                    <Bar dataKey="baseline" name="Random-quiz baseline" fill="#64708a" radius={[5, 5, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
      <Card className="mt-4">
        <CardHeader>
          <CardTitle>All personalization metrics (mean ± sd)</CardTitle>
          <CardDescription>{Object.entries(s.profiles).map(([k, v]) => `${k}: ${v}`).join(" · ")}</CardDescription>
        </CardHeader>
        <CardContent className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-xs">
            <thead className="text-left text-subtle">
              <tr>
                <th className="pb-2 font-medium">Metric</th>
                {profiles.map((p) => (
                  <th key={p} className="pb-2 font-medium" colSpan={2}>
                    {p}
                  </th>
                ))}
              </tr>
              <tr className="text-[10px]">
                <th />
                {profiles.map((p) => (
                  <React.Fragment key={p}>
                    <th className="pb-1 font-normal text-brand-soft">adaptive</th>
                    <th className="pb-1 font-normal">baseline</th>
                  </React.Fragment>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {[...PERS_METRICS, ["questions_answered", "Scored questions answered", true], ["probes", "Probe interactions", true], ["blindspot_sessions", "Blindspot investigations", true], ["targeting_precision", "Investigations on a truly held misconception", true]].map(([k, label]) => (
                <tr key={k as string}>
                  <td className="py-1.5 text-muted">{label as string}</td>
                  {profiles.map((p) =>
                    (["adaptive", "baseline"] as const).map((arm) => {
                      const v = s.by_profile[p][arm]?.[k as string];
                      const isRate = !["questions_answered", "probes", "blindspot_sessions", "mastery_brier"].includes(k as string);
                      return (
                        <td key={p + arm} className="py-1.5 font-mono">
                          {v ? `${isRate ? pct(v.mean) : v.mean.toFixed(2)} ±${isRate ? pct(v.sd) : v.sd.toFixed(2)}` : "—"}
                        </td>
                      );
                    }),
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </CardContent>
      </Card>
      <Card className="mt-4">
        <CardHeader>
          <CardTitle>Simulation assumptions</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-1 text-xs text-muted sm:grid-cols-2">
          {Object.entries(s.assumptions).map(([k, v]) => (
            <div key={k} className="flex justify-between gap-2 border-b border-line py-1">
              <span>{k.replace(/_/g, " ")}</span>
              <span className="font-mono text-fg">{Array.isArray(v) ? v.join(", ") : String(v)}</span>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}

function Cases({ runId, kind }: { runId: string; kind: string }) {
  const [cat, setCat] = React.useState("");
  const [onlyFail, setOnlyFail] = React.useState(false);
  const [shown, setShown] = React.useState(20);
  React.useEffect(() => setShown(20), [cat, onlyFail]);
  const q = useQuery({
    queryKey: ["eval-results", runId, cat, onlyFail],
    queryFn: () => api<{ total: number; results: EvalResult[] }>(`/api/evaluation/runs/${runId}/results?limit=500${cat ? `&category=${cat}` : ""}${onlyFail ? "&passed=false" : ""}`),
  });
  const cats = Array.from(new Set((q.data?.results ?? []).map((r) => r.category ?? ""))).filter(Boolean);
  return (
    <Card className="mt-4">
      <CardHeader className="flex-row flex-wrap items-center justify-between gap-2">
        <div>
          <CardTitle>Case-level results ({q.data?.total ?? "…"})</CardTitle>
          <CardDescription>Inspect every test case: inputs, outputs, citations and per-case metrics.</CardDescription>
        </div>
        <div className="flex items-center gap-2 text-xs">
          <select value={cat} onChange={(e) => setCat(e.target.value)} className="rounded-lg border border-line-strong bg-surface-2 px-2 py-1.5" aria-label="Filter category">
            <option value="">All categories</option>
            {cats.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
          <label className="flex items-center gap-1.5 text-muted">
            <input type="checkbox" checked={onlyFail} onChange={(e) => setOnlyFail(e.target.checked)} /> failures only
          </label>
        </div>
      </CardHeader>
      <CardContent className="space-y-1.5">
        {q.isLoading && <LoadingState />}
        {q.data?.results.length === 0 && <p className="text-sm text-muted">No cases match this filter.</p>}
        {q.data?.results.slice(0, shown).map((r) => (
          <details key={r.id} className="group rounded-lg border border-line bg-surface-2/40 px-3 py-2" data-testid="eval-case">
            <summary className="flex cursor-pointer list-none items-center gap-2 text-sm">
              {r.passed === true ? <CheckCircle2 className="size-4 text-ok" /> : r.passed === false ? <XCircle className="size-4 text-bad" /> : <span className="size-4" />}
              <span className="font-mono text-xs text-subtle">{r.case_key}</span>
              <Badge variant="muted">{r.category}</Badge>
              <span className="min-w-0 flex-1 truncate text-muted">{String((r.output as any).question ?? (r.output as any).stem ?? (r.output as any).response ?? (r.output as any).profile ?? "")}</span>
              <ChevronDown className="size-4 text-subtle transition-transform group-open:rotate-180" />
            </summary>
            <CaseDetail r={r} kind={kind} />
          </details>
        ))}
        {q.data && q.data.results.length > shown && (
          <Button variant="ghost" size="sm" onClick={() => setShown((n) => n + 40)}>
            Show more ({q.data.results.length - shown} remaining)
          </Button>
        )}
      </CardContent>
    </Card>
  );
}

function CaseDetail({ r, kind }: { r: EvalResult; kind: string }) {
  const o = r.output as any;
  return (
    <div className="mt-3 grid gap-3 text-xs md:grid-cols-2">
      {kind === "rag" ? (
        <>
          <div className="space-y-2">
            <div className="font-semibold text-muted">Answer ({o.status}, {o.mode})</div>
            <pre className="max-h-60 overflow-auto whitespace-pre-wrap rounded-lg bg-bg/60 p-2 text-[11px] text-muted">{o.answer}</pre>
            {o.reference_answer && (
              <div>
                <span className="font-semibold text-muted">Reference: </span>
                {o.reference_answer}
              </div>
            )}
          </div>
          <div className="space-y-2">
            <div>
              <span className="font-semibold text-muted">Expected: </span>
              {(o.expected_sources ?? []).map((e: any) => `${e.file} ${e.page ? `p${e.page}` : e.slide ? `s${e.slide}` : `${e.start}-${e.end}s`}`).join("; ") || "refusal"}
            </div>
            <div>
              <span className="font-semibold text-muted">Cited: </span>
              {(o.citations ?? []).map((c: any) => c.label).join("; ") || "none"}
            </div>
            <div className="font-semibold text-muted">Retrieved (rerank logit)</div>
            <ul className="space-y-0.5 text-subtle">
              {(o.retrieved ?? []).map((h: any, i: number) => (
                <li key={i}>
                  {h.source} {h.page ? `p${h.page}` : h.slide ? `s${h.slide}` : `${h.start}s`} · {h.rerank_logit}
                </li>
              ))}
            </ul>
          </div>
        </>
      ) : (
        <pre className="max-h-60 overflow-auto whitespace-pre-wrap rounded-lg bg-bg/60 p-2 text-[11px] text-muted md:col-span-2">{JSON.stringify(o, null, 1)}</pre>
      )}
      <div className="md:col-span-2">
        <div className="mb-1 font-semibold text-muted">Metrics</div>
        <div className="flex flex-wrap gap-1.5">
          {Object.entries(r.metrics).map(([k, v]) => (
            <span key={k} className={cn("rounded-md border border-line px-1.5 py-0.5 font-mono text-[10px]")}>
              {k}: {typeof v === "number" ? (Math.abs(v) <= 1 ? v.toFixed(3) : v.toFixed(2)) : String(v)}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}

function RunsTab({ runs }: { runs: EvalRun[] }) {
  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle>Reproduce these results</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-sm text-muted">
          <pre className="overflow-x-auto rounded-lg bg-bg/70 p-3 font-mono text-xs text-fg">
            {"python evaluation/scripts/run_evaluation.py --kinds rag assessment personalization\npython evaluation/scripts/make_report.py"}
          </pre>
          <p>Runs are stored in the database (this page) and exported to evaluation/results/ with dataset versions, model identifiers, seeds and every case-level output.</p>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Run history</CardTitle>
        </CardHeader>
        <CardContent className="divide-y divide-line">
          {runs.map((r) => (
            <details key={r.id} className="py-2">
              <summary className="flex cursor-pointer list-none items-center gap-2 text-sm">
                <Badge variant={r.status === "succeeded" ? "ok" : r.status === "failed" ? "bad" : "warn"}>{r.status}</Badge>
                <span className="capitalize">{r.kind}</span>
                <span className="font-mono text-xs text-subtle">{r.id.slice(0, 8)}</span>
                <span className="ml-auto text-xs text-subtle">{timeAgo(r.created_at)}</span>
              </summary>
              <div className="mt-2 space-y-2 text-xs text-muted">
                {r.error && <p className="text-bad">{r.error}</p>}
                <div>Prompt version: {r.prompt_version ?? "n/a"} · seed: {r.seed ?? "n/a"} · dataset: {r.dataset_name ?? "n/a"} {r.dataset_version ?? ""}</div>
                <div>Models: {Object.entries(r.model_info).map(([k, v]) => `${k}=${v ?? "none"}`).join(", ")}</div>
                <ul className="list-disc space-y-0.5 pl-4">
                  {r.limitations.map((l) => (
                    <li key={l}>{l}</li>
                  ))}
                </ul>
              </div>
            </details>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}
