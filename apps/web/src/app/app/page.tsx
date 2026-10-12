"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowRight, BookMarked, Layers, Plus, RotateCcw, Sparkles, Target } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import * as React from "react";
import { Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { toast } from "sonner";
import { MasteryBadge, MasteryBar } from "@/components/learning/mastery";
import { RecommendationCard } from "@/components/learning/recommendations";
import { PageHeader } from "@/components/shell/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Input, Textarea } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/states";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { Analytics, Course } from "@/lib/types";
import { HYPOTHESIS_STYLE, cn, pct, timeAgo } from "@/lib/utils";

export default function Dashboard() {
  const { user } = useAuth();
  const qc = useQueryClient();
  const dash = useQuery({ queryKey: ["dashboard"], queryFn: () => api<{ courses: Course[] }>("/api/dashboard") });
  const courses = dash.data?.courses ?? [];
  const [focus, setFocus] = React.useState<string | undefined>();
  const course = courses.find((c) => c.id === focus) ?? courses[0];
  const analytics = useQuery({
    queryKey: ["analytics", course?.id],
    queryFn: () => api<Analytics>(`/api/courses/${course!.id}/analytics`),
    enabled: !!course && course.concepts > 0,
  });
  const reset = useMutation({
    mutationFn: () => api("/api/demo/reset", { method: "POST" }),
    onSuccess: () => {
      qc.invalidateQueries();
      toast.success("Demo progress reset: you are a brand-new learner again.");
    },
    onError: (e) => toast.error(errorMessage(e)),
  });

  if (dash.isLoading) return <LoadingState />;
  if (dash.isError) return <ErrorState message={errorMessage(dash.error)} onRetry={() => dash.refetch()} />;

  const a = analytics.data;
  const attention = a?.concepts.filter((c) => c.p_mastery !== null && c.p_mastery < 0.6).sort((x, y) => (x.p_mastery ?? 0) - (y.p_mastery ?? 0)) ?? [];
  const gaps = a?.hypotheses.filter((h) => ["suspected", "supported", "unresolved", "resolving"].includes(h.status)) ?? [];

  return (
    <div className="mx-auto max-w-7xl">
      <PageHeader
        eyebrow="Learning dashboard"
        title={<>Welcome{user?.is_demo ? "" : " back"}, {user?.display_name}</>}
        description="Your courses, what needs attention, and the next most useful activity, all computed from your scored evidence."
        actions={<NewCourseDialog />}
      />

      {user?.is_demo && (
        <div className="mb-6 flex flex-col gap-3 rounded-2xl border border-accent/30 bg-accent/5 p-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-start gap-3 text-sm">
            <Sparkles className="mt-0.5 size-4 shrink-0 text-accent" />
            <span className="text-muted">
              You are using a <b className="text-fg">synthetic demo learner</b>. Everything you do here runs through the real grading, retrieval and learner-model code; the demo course itself is original synthetic material.
            </span>
          </div>
          <Button variant="outline" size="sm" onClick={() => reset.mutate()} disabled={reset.isPending}>
            <RotateCcw /> Reset my demo progress
          </Button>
        </div>
      )}

      {courses.length === 0 ? (
        <EmptyState title="No courses yet" action={<NewCourseDialog />}>
          Create a course and upload a PDF, slide deck or lecture video to get started.
        </EmptyState>
      ) : (
        <div className="space-y-6">
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {courses.map((c) => (
              <button
                key={c.id}
                onClick={() => setFocus(c.id)}
                className={cn("rounded-2xl border bg-surface p-5 text-left transition-colors", course?.id === c.id ? "border-brand/60 shadow-[0_0_0_1px_rgb(99_102_241/0.3)]" : "border-line hover:border-line-strong")}
              >
                <div className="mb-2 flex flex-wrap gap-1.5">
                  {c.is_demo && <Badge variant="accent">Demo course</Badge>}
                  <Badge variant="muted">{c.role}</Badge>
                  <Badge variant={c.knowledge_status === "ready" ? "ok" : c.knowledge_status === "failed" ? "bad" : "warn"}>knowledge {c.knowledge_status}</Badge>
                </div>
                <div className="line-clamp-2 font-semibold">{c.title}</div>
                <div className="mt-3 grid grid-cols-3 gap-2 text-center">
                  <Stat label="sources" value={c.sources} />
                  <Stat label="concepts" value={c.concepts} />
                  <Stat label="verified Qs" value={c.verified_questions} />
                </div>
                <div className="mt-3 text-xs text-muted">
                  {c.mastery.assessed ? (
                    <>Mean estimated mastery {pct(c.mastery.mean)} across {c.mastery.assessed} assessed concept(s)</>
                  ) : (
                    <>No scored evidence yet</>
                  )}
                </div>
              </button>
            ))}
          </div>

          {course && (
            <div className="grid gap-4 lg:grid-cols-[1.35fr_1fr]">
              <Card>
                <CardHeader className="flex-row items-center justify-between">
                  <div>
                    <CardTitle>Recommended next</CardTitle>
                    <CardDescription>Chosen by the adaptive decision engine from mastery, misconception evidence and prerequisites.</CardDescription>
                  </div>
                  <Link href={`/app/courses/${course.id}/progress`} className="text-xs text-brand-soft hover:underline">
                    Why? →
                  </Link>
                </CardHeader>
                <CardContent className="space-y-2">
                  {course.concepts === 0 ? (
                    <EmptyState title="Upload materials first" action={<Button asChild size="sm"><Link href={`/app/courses/${course.id}/studio`}>Open Course Studio</Link></Button>}>
                      Concepts and questions are built from your uploaded sources.
                    </EmptyState>
                  ) : (
                    (course.recommendations ?? []).map((r, i) => <RecommendationCard key={r.title} courseId={course.id} r={r} primary={i === 0} />)
                  )}
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle>Knowledge gaps under investigation</CardTitle>
                  <CardDescription>Misconception hypotheses with their current status. Hypotheses, not verdicts.</CardDescription>
                </CardHeader>
                <CardContent className="space-y-2">
                  {analytics.isLoading && <LoadingState />}
                  {gaps.length === 0 && !analytics.isLoading && (
                    <p className="rounded-xl border border-dashed border-line-strong p-4 text-sm text-muted">No misconception hypotheses yet. They appear when an answer matches a known misconception pattern.</p>
                  )}
                  {gaps.map((h) => (
                    <Link key={h.misconception_key} href={`/app/courses/${course.id}/lab?misconception=${h.misconception_key}`} className="block rounded-xl border border-line bg-surface-2/60 p-3 hover:border-warn/40">
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-sm font-medium">{h.title}</span>
                        <span className={cn("rounded-full border px-2 py-0.5 text-[10px]", HYPOTHESIS_STYLE[h.status]?.cls)}>{HYPOTHESIS_STYLE[h.status]?.label}</span>
                      </div>
                      <div className="mt-1 text-xs text-muted">
                        model posterior {h.posterior.toFixed(2)} · {h.evidence_count} piece(s) of evidence
                      </div>
                    </Link>
                  ))}
                </CardContent>
              </Card>

              <Card>
                <CardHeader className="flex-row items-center justify-between">
                  <div>
                    <CardTitle>Concept mastery</CardTitle>
                    <CardDescription>Bayesian Knowledge Tracing estimates; striped = no evidence yet.</CardDescription>
                  </div>
                  <Layers className="size-4 text-subtle" />
                </CardHeader>
                <CardContent className="space-y-3">
                  {a?.concepts.map((m) => (
                    <div key={m.concept_id} className="space-y-1">
                      <div className="flex items-center justify-between gap-2 text-sm">
                        <span className="truncate">{m.name}</span>
                        <MasteryBadge label={m.label} quality={m.evidence_quality} />
                      </div>
                      <MasteryBar m={m} />
                    </div>
                  ))}
                  {!a && !analytics.isLoading && <p className="text-sm text-muted">No concepts yet.</p>}
                </CardContent>
              </Card>

              <div className="grid gap-4">
                <Card>
                  <CardHeader>
                    <CardTitle className="flex items-center gap-2">
                      <AlertTriangle className="size-4 text-warn" /> Topics needing attention
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-1.5 text-sm">
                    {attention.length ? (
                      attention.slice(0, 4).map((m) => (
                        <div key={m.concept_id} className="flex items-center justify-between">
                          <span>{m.name}</span>
                          <span className="font-mono text-xs text-warn">{pct(m.p_mastery)}</span>
                        </div>
                      ))
                    ) : (
                      <p className="text-muted">{a?.totals.attempts ? "Nothing below 60% estimated mastery." : "Take the diagnostic to find out."}</p>
                    )}
                  </CardContent>
                </Card>
                <Card>
                  <CardHeader>
                    <CardTitle className="flex items-center gap-2">
                      <Target className="size-4 text-accent" /> Progress across sessions
                    </CardTitle>
                    <CardDescription>Mean estimated mastery of assessed concepts after each session.</CardDescription>
                  </CardHeader>
                  <CardContent>
                    {a && a.sessions.length > 1 ? (
                      <div className="h-32">
                        <ResponsiveContainer>
                          <AreaChart data={a.sessions.map((s, i) => ({ i: i + 1, v: s.mean_mastery_assessed, label: s.label }))}>
                            <defs>
                              <linearGradient id="dashg" x1="0" x2="0" y1="0" y2="1">
                                <stop offset="0" stopColor="#22d3ee" stopOpacity={0.4} />
                                <stop offset="1" stopColor="#22d3ee" stopOpacity={0} />
                              </linearGradient>
                            </defs>
                            <XAxis dataKey="i" tick={{ fill: "#64708a", fontSize: 10 }} axisLine={false} tickLine={false} />
                            <YAxis domain={[0, 1]} tickFormatter={(v) => `${Math.round(v * 100)}%`} tick={{ fill: "#64708a", fontSize: 10 }} axisLine={false} tickLine={false} width={34} />
                            <Tooltip contentStyle={{ background: "#16223a", border: "1px solid #2a3a5c", borderRadius: 8, fontSize: 12 }} formatter={(v) => pct(Number(v))} labelFormatter={(_l, p) => p?.[0]?.payload?.label ?? ""} />
                            <Area dataKey="v" stroke="#22d3ee" fill="url(#dashg)" strokeWidth={2} />
                          </AreaChart>
                        </ResponsiveContainer>
                      </div>
                    ) : (
                      <p className="text-sm text-muted">Appears after two or more scored sessions.</p>
                    )}
                  </CardContent>
                </Card>
              </div>

              <Card className="lg:col-span-2">
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <BookMarked className="size-4 text-brand-soft" /> Recent activity
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  {a?.recent.length ? (
                    <ul className="divide-y divide-line">
                      {a.recent.slice(0, 6).map((r) => (
                        <li key={r.at + r.question} className="flex items-center gap-3 py-2 text-sm">
                          <span className={cn("size-2 shrink-0 rounded-full", r.is_correct ? "bg-ok" : r.is_correct === false ? "bg-bad" : "bg-subtle")} />
                          <span className="min-w-0 flex-1 truncate">{r.question}</span>
                          <Badge variant="muted">{r.context}</Badge>
                          <span className="w-20 text-right text-xs text-subtle">{timeAgo(r.at)}</span>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="text-sm text-muted">
                      No scored answers yet.{" "}
                      <Link className="text-brand-soft hover:underline" href={`/app/courses/${course.id}/assess?kind=diagnostic`}>
                        Start the diagnostic <ArrowRight className="inline size-3" />
                      </Link>
                    </p>
                  )}
                </CardContent>
              </Card>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border border-line bg-surface-2/60 py-1.5">
      <div className="font-mono text-base font-semibold">{value}</div>
      <div className="text-[10px] uppercase tracking-wider text-subtle">{label}</div>
    </div>
  );
}

function NewCourseDialog() {
  const [open, setOpen] = React.useState(false);
  const [title, setTitle] = React.useState("");
  const [desc, setDesc] = React.useState("");
  const qc = useQueryClient();
  const router = useRouter();
  const create = useMutation({
    mutationFn: () => api<Course>("/api/courses", { method: "POST", body: { title, description: desc || null } }),
    onSuccess: (c) => {
      qc.invalidateQueries({ queryKey: ["courses"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      setOpen(false);
      router.push(`/app/courses/${c.id}/studio`);
    },
    onError: (e) => toast.error(errorMessage(e)),
  });
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button>
          <Plus /> New course
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogTitle>Create a course</DialogTitle>
        <DialogDescription>You will be the owner and can upload PDFs, slide decks and lecture videos.</DialogDescription>
        <form
          className="mt-4 space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            if (title.trim().length >= 2) create.mutate();
          }}
        >
          <div className="space-y-1.5">
            <Label htmlFor="ct">Title</Label>
            <Input id="ct" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Pricing Strategy, Week 3" />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="cd">Description (optional)</Label>
            <Textarea id="cd" value={desc} onChange={(e) => setDesc(e.target.value)} />
          </div>
          <Button type="submit" disabled={title.trim().length < 2 || create.isPending}>
            Create course
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
