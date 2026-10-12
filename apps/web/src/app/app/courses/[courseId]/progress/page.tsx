"use client";

import { useQuery } from "@tanstack/react-query";
import { Activity, BrainCircuit, CalendarClock, ChevronDown, Microscope, Sigma } from "lucide-react";
import * as React from "react";
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { MasteryBadge, MasteryBar } from "@/components/learning/mastery";
import { RecommendationCard } from "@/components/learning/recommendations";
import { PageHeader } from "@/components/shell/page-header";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/states";
import { api, errorMessage } from "@/lib/api";
import { useCourseId } from "@/lib/hooks";
import type { Analytics } from "@/lib/types";
import { HYPOTHESIS_STYLE, cn, pct, timeAgo } from "@/lib/utils";

const PALETTE = ["#818cf8", "#22d3ee", "#34d399", "#fbbf24", "#f472b6", "#f87171", "#a78bfa", "#2dd4bf"];
const TT = { contentStyle: { background: "#16223a", border: "1px solid #2a3a5c", borderRadius: 8, fontSize: 12 }, labelStyle: { color: "#93a0bb" } };

export default function ProgressPage() {
  const courseId = useCourseId()!;
  const q = useQuery({ queryKey: ["analytics", courseId], queryFn: () => api<Analytics>(`/api/courses/${courseId}/analytics`) });
  if (q.isLoading) return <LoadingState />;
  if (q.isError) return <ErrorState message={errorMessage(q.error)} onRetry={() => q.refetch()} />;
  const a = q.data!;
  const names = Object.fromEntries(a.concepts.map((c) => [c.concept_id, c.name]));
  const active = a.hypotheses.filter((h) => ["suspected", "supported", "unresolved"].includes(h.status)).length;
  const repairing = a.hypotheses.filter((h) => h.status === "resolving").length;

  // Mastery trajectory: one row per observation, carrying forward each concept's latest estimate.
  const events = Object.entries(a.history)
    .flatMap(([cid, hs]) => hs.map((h) => ({ cid, ...h })))
    .sort((x, y) => x.t.localeCompare(y.t));
  const latest: Record<string, number> = {};
  const traj = events.map((e, i) => {
    latest[e.cid] = e.p_after;
    return { i: i + 1, t: e.t, ...Object.fromEntries(Object.entries(latest).map(([k, v]) => [names[k] ?? k, Math.round(v * 1000) / 1000])) };
  });

  return (
    <div className="mx-auto max-w-7xl">
      <PageHeader
        eyebrow="Mastery & progress"
        title="What the learner model believes, and why"
        description="Everything on this page is computed from your persisted, scored evidence. Mastery values are Bayesian Knowledge Tracing estimates, not validated measures of what you know."
      />
      {a.totals.attempts === 0 ? (
        <EmptyState icon={<Activity className="size-5" />} title="No scored evidence yet">
          Take the diagnostic check-in or a Blindspot investigation; this page fills in from your answers.
        </EmptyState>
      ) : (
        <div className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Kpi label="Concepts assessed" value={`${a.totals.assessed_concepts}/${a.totals.concepts}`} />
            <Kpi label="Scored answers" value={String(a.totals.attempts)} />
            <Kpi label="Accuracy" value={pct(a.totals.correct / Math.max(1, a.totals.attempts))} />
            <Kpi label="Open misconception hypotheses" value={String(active)} tone={active ? "warn" : undefined} hint={repairing ? `${repairing} repaired, revisit pending` : undefined} />
          </div>

          <div className="grid gap-4 lg:grid-cols-[1fr_1.2fr]">
            <Card>
              <CardHeader>
                <CardTitle>Mastery by concept</CardTitle>
                <CardDescription>Estimate, evidence quality and the next scheduled review.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                {a.topics.map((t) => (
                  <div key={t.topic_id} className="flex items-center justify-between rounded-lg bg-surface-2/60 px-3 py-1.5 text-xs">
                    <span className="font-semibold uppercase tracking-wider text-brand-soft">{t.name}</span>
                    <span className="font-mono text-muted">
                      {t.p_mastery === null ? "unassessed" : pct(t.p_mastery)} · {t.assessed_concepts}/{t.concepts} assessed
                    </span>
                  </div>
                ))}
                {a.concepts.map((m) => (
                  <div key={m.concept_id} className="space-y-1">
                    <div className="flex items-center justify-between gap-2 text-sm">
                      <span>{m.name}</span>
                      <MasteryBadge label={m.label} quality={m.evidence_quality} />
                    </div>
                    <MasteryBar m={m} />
                    <div className="flex gap-3 text-[10px] text-subtle">
                      <span>
                        {m.n_correct}/{m.n_observations} correct
                      </span>
                      <span>{m.distinct_questions} distinct questions</span>
                      {m.next_review_at && (
                        <span className={m.review_due ? "text-warn" : ""}>
                          <CalendarClock className="mr-0.5 inline size-3" />
                          review {m.review_due ? "due now" : new Date(m.next_review_at).toLocaleDateString()}
                        </span>
                      )}
                    </div>
                  </div>
                ))}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Mastery trajectory</CardTitle>
                <CardDescription>Each concept&apos;s estimate after every scored observation (x = observation number).</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="h-80" data-testid="trajectory-chart">
                  <ResponsiveContainer>
                    <LineChart data={traj} margin={{ left: -10, right: 10 }}>
                      <CartesianGrid stroke="#1d2a44" strokeDasharray="3 3" />
                      <XAxis dataKey="i" tick={{ fill: "#64708a", fontSize: 11 }} />
                      <YAxis domain={[0, 1]} tickFormatter={(v) => `${Math.round(v * 100)}%`} tick={{ fill: "#64708a", fontSize: 11 }} />
                      <Tooltip {...TT} formatter={(v) => pct(Number(v))} labelFormatter={(l) => `Observation ${l}`} />
                      <Legend wrapperStyle={{ fontSize: 11 }} />
                      {a.concepts
                        .filter((c) => c.n_observations > 0)
                        .map((c, i) => (
                          <Line key={c.concept_id} type="stepAfter" dataKey={c.name} stroke={PALETTE[i % PALETTE.length]} dot={false} strokeWidth={2} connectNulls />
                        ))}
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              </CardContent>
            </Card>
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle>Changes across sessions</CardTitle>
                <CardDescription>Mean estimated mastery of assessed concepts after each session.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="h-48">
                  <ResponsiveContainer>
                    <BarChart data={a.sessions.map((s, i) => ({ name: `${i + 1}`, v: s.mean_mastery_assessed, label: s.label, acc: s.observations ? s.correct / s.observations : 0 }))}>
                      <CartesianGrid stroke="#1d2a44" strokeDasharray="3 3" vertical={false} />
                      <XAxis dataKey="name" tick={{ fill: "#64708a", fontSize: 11 }} />
                      <YAxis domain={[0, 1]} tickFormatter={(v) => `${Math.round(v * 100)}%`} tick={{ fill: "#64708a", fontSize: 11 }} />
                      <Tooltip {...TT} formatter={(v) => pct(Number(v))} labelFormatter={(_l, p) => p?.[0]?.payload?.label ?? ""} />
                      <Bar dataKey="v" name="mean mastery" fill="#22d3ee" radius={[6, 6, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
                <div className="max-h-48 divide-y divide-line overflow-y-auto text-xs">
                  {a.sessions.map((s, i) => (
                    <div key={s.session_key} className="flex items-center gap-2 py-1.5">
                      <span className="w-5 font-mono text-subtle">{i + 1}</span>
                      <span className="flex-1">{s.label}</span>
                      <span className="text-muted">
                        {s.correct}/{s.observations} correct
                      </span>
                      <span className="w-20 text-right text-subtle">{timeAgo(s.at)}</span>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle>Question accuracy by concept</CardTitle>
                <CardDescription>All scored answers (assessments, investigations, knowledge checks).</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="h-64">
                  <ResponsiveContainer>
                    <BarChart data={a.accuracy.map((x) => ({ name: x.name.split(" ")[0], full: x.name, correct: x.correct, wrong: x.answered - x.correct }))} layout="vertical" margin={{ left: 10 }}>
                      <CartesianGrid stroke="#1d2a44" strokeDasharray="3 3" horizontal={false} />
                      <XAxis type="number" tick={{ fill: "#64708a", fontSize: 11 }} allowDecimals={false} />
                      <YAxis type="category" dataKey="name" tick={{ fill: "#93a0bb", fontSize: 11 }} width={90} />
                      <Tooltip {...TT} labelFormatter={(_l, p) => p?.[0]?.payload?.full ?? ""} />
                      <Bar dataKey="correct" stackId="a" fill="#34d399" />
                      <Bar dataKey="wrong" stackId="a" fill="#f87171" radius={[0, 6, 6, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </CardContent>
            </Card>
          </div>

          <div className="grid gap-4 lg:grid-cols-[1.3fr_1fr]">
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Microscope className="size-4 text-warn" /> Misconception hypotheses and their evidence
                </CardTitle>
                <CardDescription>Each update shows the likelihood ratio applied and the posterior before → after.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                {a.hypotheses.length === 0 && <p className="text-sm text-muted">No misconception evidence recorded.</p>}
                {a.hypotheses.map((h) => (
                  <details key={h.misconception_key} className="group rounded-xl border border-line bg-surface-2/50 p-3" data-testid="hypothesis-row">
                    <summary className="flex cursor-pointer list-none items-center gap-2">
                      <span className="flex-1 text-sm font-medium">{h.title}</span>
                      <span className={cn("rounded-full border px-2 py-0.5 text-[10px]", HYPOTHESIS_STYLE[h.status]?.cls)}>{HYPOTHESIS_STYLE[h.status]?.label}</span>
                      <span className="font-mono text-xs text-muted">{h.posterior.toFixed(2)}</span>
                      <ChevronDown className="size-4 text-subtle transition-transform group-open:rotate-180" />
                    </summary>
                    <ol className="mt-3 space-y-1.5 border-l border-line-strong pl-3">
                      {h.evidence?.map((e, i) => (
                        <li key={i} className="text-xs">
                          <div className="flex flex-wrap items-center gap-2">
                            <Badge variant="muted">{e.kind.replace("_", " ")}</Badge>
                            <span className="font-mono text-subtle">
                              LR {e.likelihood_ratio.toFixed(2)} · {e.posterior_before.toFixed(2)} → {e.posterior_after.toFixed(2)}
                            </span>
                            <span className="text-subtle">{timeAgo(e.at)}</span>
                          </div>
                          <p className="mt-0.5 text-muted">{e.summary}</p>
                        </li>
                      ))}
                    </ol>
                  </details>
                ))}
              </CardContent>
            </Card>
            <div className="space-y-4">
              <Card>
                <CardHeader>
                  <CardTitle>Retention and revisits</CardTitle>
                  <CardDescription>{a.retention.definition}</CardDescription>
                </CardHeader>
                <CardContent className="space-y-2 text-sm">
                  <div className="flex justify-between">
                    <span className="text-muted">Revisit accuracy</span>
                    <span className="font-mono">{a.retention.revisit_attempts ? `${pct(a.retention.revisit_accuracy)} (${a.retention.revisit_correct}/${a.retention.revisit_attempts})` : "no revisits yet"}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted">Reviews due</span>
                    <span>{a.retention.due_reviews.length ? a.retention.due_reviews.join(", ") : "none"}</span>
                  </div>
                </CardContent>
              </Card>
              <Card>
                <CardHeader>
                  <CardTitle>Suggested next</CardTitle>
                </CardHeader>
                <CardContent className="space-y-2">
                  {a.recommendations.map((r, i) => (
                    <RecommendationCard key={r.title} courseId={courseId} r={r} primary={i === 0} />
                  ))}
                </CardContent>
              </Card>
            </div>
          </div>
        </div>
      )}

      <Card className="mt-4">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <BrainCircuit className="size-4 text-brand-soft" /> How mastery is estimated
          </CardTitle>
          <CardDescription>{a.method.model}</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-6 text-sm md:grid-cols-2">
          <div className="space-y-3">
            <div className="rounded-xl border border-line bg-surface-2/60 p-3 font-mono text-xs leading-6 text-muted">
              <div className="mb-1 flex items-center gap-1 text-fg">
                <Sigma className="size-3.5" /> Update after an answer
              </div>
              P(L|correct) = P(L)(1−S)ʷ / [P(L)(1−S)ʷ + (1−P(L))Gʷ]
              <br />
              P(L|wrong) = P(L)Sʷ / [P(L)Sʷ + (1−P(L))(1−G)ʷ]
              <br />
              P(L′) = P(L|obs) + (1 − P(L|obs))·T·w
              <div className="mt-1 font-sans text-[11px] text-subtle">With w = 1 this is standard BKT; w &lt; 1 tempers weak evidence.</div>
            </div>
            <ul className="space-y-1 text-xs text-muted">
              <li>
                Initial P(L₀) = <b className="text-fg">{a.method.parameters.p_init}</b>, learning T = <b className="text-fg">{a.method.parameters.p_transit}</b>
              </li>
              <li>Guess G by type: {Object.entries(a.method.parameters.guess_by_type).map(([k, v]) => `${k} ${v}`).join(", ")}</li>
              <li>Slip S by difficulty: {Object.entries(a.method.parameters.slip_by_difficulty).map(([k, v]) => `level ${k}: ${v}`).join(", ")}</li>
            </ul>
          </div>
          <div className="space-y-3">
            <div className="text-xs font-semibold uppercase tracking-wider text-subtle">Evidence weight w (likelihoods raised to w)</div>
            <ul className="space-y-1 text-xs text-muted">
              {Object.entries(a.method.evidence_weighting).map(([k, v]) => (
                <li key={k}>
                  <b className="text-fg">{k.replace(/_/g, " ")}</b>: {v}
                </li>
              ))}
            </ul>
            <ul className="list-disc space-y-1 pl-4 text-xs text-subtle">
              {a.method.caveats.map((c) => (
                <li key={c}>{c}</li>
              ))}
            </ul>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function Kpi({ label, value, tone, hint }: { label: string; value: string; tone?: "warn"; hint?: string }) {
  return (
    <Card>
      <CardContent className="p-4">
        <div className="text-[11px] uppercase tracking-wider text-subtle">{label}</div>
        <div className={cn("mt-1 font-mono text-2xl font-semibold", tone === "warn" ? "text-warn" : "text-fg")}>{value}</div>
        {hint && <div className="mt-0.5 text-[11px] text-accent">{hint}</div>}
      </CardContent>
    </Card>
  );
}
