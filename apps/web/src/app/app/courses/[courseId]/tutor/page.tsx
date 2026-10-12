"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BadgeCheck, Ban, Brain, Globe, MessageSquarePlus, Quote, Send, Trash2 } from "lucide-react";
import Link from "next/link";
import * as React from "react";
import { toast } from "sonner";
import { FeedbackPanel } from "@/components/learning/feedback";
import { CitationChip, CitationList } from "@/components/learning/citations";
import { QuestionForm, QuestionMeta } from "@/components/learning/question-form";
import { Markdown } from "@/components/markdown";
import { PageHeader } from "@/components/shell/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Textarea } from "@/components/ui/input";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/states";
import { Switch } from "@/components/ui/switch";
import { Tip } from "@/components/ui/tooltip";
import { api, errorMessage } from "@/lib/api";
import { useCourse, useCourseId } from "@/lib/hooks";
import type { Assessment, Conversation, Feedback, LearnerContext, TutorMessage } from "@/lib/types";
import { cn, HYPOTHESIS_STYLE, masteryColor, pct, timeAgo } from "@/lib/utils";

const STARTERS = [
  "Why can a price cut need more extra volume than people expect?",
  "What is break-even ROAS and why isn't a ROAS above 1 enough?",
  "In the lecture, what happens to contribution per pod after the price cut?",
  "Which channels lose money even though their ROAS is above 1?",
];

export default function TutorPage() {
  const courseId = useCourseId()!;
  const course = useCourse(courseId);
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ["convs", courseId], queryFn: () => api<{ id: string; title: string; created_at: string }[]>(`/api/courses/${courseId}/conversations`) });
  const [active, setActive] = React.useState<string | null>(null);
  React.useEffect(() => {
    if (!active && list.data?.length) setActive(list.data[0].id);
  }, [list.data, active]);
  const create = useMutation({
    mutationFn: () => api<{ id: string }>(`/api/courses/${courseId}/conversations`, { method: "POST", body: {} }),
    onSuccess: (c) => {
      qc.invalidateQueries({ queryKey: ["convs", courseId] });
      setActive(c.id);
    },
  });
  const remove = useMutation({
    mutationFn: (id: string) => api(`/api/conversations/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      setActive(null);
      qc.invalidateQueries({ queryKey: ["convs", courseId] });
    },
  });

  return (
    <div className="mx-auto max-w-7xl">
      <PageHeader
        eyebrow="Grounded AI Tutor"
        title="Ask your course materials"
        description="Every answer is built only from retrieved course sources and links to the exact page, slide or timestamp. If the materials don't cover a question, the tutor says so."
        actions={
          <Button onClick={() => create.mutate()} disabled={create.isPending} data-testid="new-conversation">
            <MessageSquarePlus /> New conversation
          </Button>
        }
      />
      <div className="grid gap-4 lg:grid-cols-[250px_1fr]">
        <Card className="h-fit">
          <CardContent className="space-y-1 p-2">
            {list.isLoading && <LoadingState />}
            {list.data?.length === 0 && <p className="p-3 text-xs text-muted">No conversations yet.</p>}
            {list.data?.map((c) => (
              <div key={c.id} className={cn("group flex items-center gap-1 rounded-lg", active === c.id ? "bg-surface-3" : "hover:bg-surface-2")}>
                <button onClick={() => setActive(c.id)} className="min-w-0 flex-1 px-3 py-2 text-left">
                  <div className="truncate text-sm">{c.title}</div>
                  <div className="text-[10px] text-subtle">{timeAgo(c.created_at)}</div>
                </button>
                <button aria-label="Delete conversation" onClick={() => remove.mutate(c.id)} className="mr-1 rounded p-1 text-subtle opacity-0 hover:text-bad group-hover:opacity-100">
                  <Trash2 className="size-3.5" />
                </button>
              </div>
            ))}
          </CardContent>
        </Card>
        {active ? (
          <Chat key={active} conversationId={active} isDemo={!!course.data?.is_demo} />
        ) : (
          <EmptyState
            icon={<Brain className="size-5" />}
            title="Start a conversation"
            action={
              <Button onClick={() => create.mutate()} disabled={create.isPending}>
                <MessageSquarePlus /> New conversation
              </Button>
            }
          >
            Questions are answered from your uploaded materials only, with citations you can open.
          </EmptyState>
        )}
      </div>
    </div>
  );
}

function Chat({ conversationId, isDemo }: { conversationId: string; isDemo: boolean }) {
  const qc = useQueryClient();
  const conv = useQuery({ queryKey: ["conv", conversationId], queryFn: () => api<Conversation>(`/api/conversations/${conversationId}`) });
  const [text, setText] = React.useState("");
  const [external, setExternal] = React.useState(false);
  const end = React.useRef<HTMLDivElement>(null);
  const send = useMutation({
    mutationFn: (content: string) => api(`/api/conversations/${conversationId}/messages`, { method: "POST", body: { content, allow_external: external } }),
    onSuccess: () => {
      setText("");
      qc.invalidateQueries({ queryKey: ["conv", conversationId] });
      qc.invalidateQueries({ queryKey: ["convs"] });
    },
    onError: (e) => toast.error(errorMessage(e)),
  });
  React.useEffect(() => end.current?.scrollIntoView({ behavior: "smooth" }), [conv.data?.messages.length, send.isPending]);

  if (conv.isLoading) return <LoadingState />;
  if (conv.isError) return <ErrorState message={errorMessage(conv.error)} onRetry={() => conv.refetch()} />;
  const c = conv.data!;
  const extAvailable = c.mode.external_mode_available;

  return (
    <Card className="flex min-h-[70vh] flex-col">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-5 py-3 text-xs text-muted">
        <span className="flex items-center gap-2">
          <Quote className="size-3.5 text-brand-soft" />
          {c.mode.generation === "llm"
            ? `Generative mode (${c.mode.model}): answers must cite sources; uncited answers are withheld.`
            : "Local extractive mode: answers quote your sources verbatim, so they never go beyond them."}
        </span>
        <Tip content={extAvailable ? "Adds a separately labelled section with general knowledge that is NOT verified against your sources." : "Needs a configured generative model. This deployment runs in local extractive mode."}>
          <label className={cn("flex items-center gap-2", !extAvailable && "opacity-50")}>
            <Globe className="size-3.5" /> Outside knowledge
            <Switch checked={external} onCheckedChange={setExternal} disabled={!extAvailable} aria-label="Allow outside knowledge" />
          </label>
        </Tip>
      </div>
      <div className="flex-1 space-y-5 overflow-y-auto px-5 py-5">
        {c.messages.length === 0 && (
          <div className="space-y-3">
            <p className="text-sm text-muted">Try asking:</p>
            <div className="grid gap-2 sm:grid-cols-2">
              {(isDemo ? STARTERS : ["Summarise the key ideas of the first chapter", "What does the lecture say about the main example?"]).map((s) => (
                <button key={s} onClick={() => send.mutate(s)} className="rounded-xl border border-line bg-surface-2/60 p-3 text-left text-sm hover:border-brand/50">
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}
        {c.messages.map((m) => (m.role === "user" ? <UserBubble key={m.id} m={m} /> : <AssistantBubble key={m.id} m={m} conversationId={conversationId} courseId={c.course_id} />))}
        {send.isPending && <div className="animate-pulse text-sm text-muted">Retrieving sources and checking support…</div>}
        <div ref={end} />
      </div>
      <form
        className="flex items-end gap-2 border-t border-line p-4"
        onSubmit={(e) => {
          e.preventDefault();
          if (text.trim().length >= 2) send.mutate(text.trim());
        }}
      >
        <Textarea
          aria-label="Ask a question"
          data-testid="tutor-input"
          rows={2}
          value={text}
          placeholder="Ask about your course materials…"
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              if (text.trim().length >= 2) send.mutate(text.trim());
            }
          }}
        />
        <Button type="submit" disabled={send.isPending || text.trim().length < 2} data-testid="tutor-send">
          <Send /> Ask
        </Button>
      </form>
    </Card>
  );
}

function UserBubble({ m }: { m: TutorMessage }) {
  return (
    <div className="flex justify-end">
      <div className="max-w-[80%] rounded-2xl rounded-br-md bg-brand/20 px-4 py-2.5 text-sm">{m.content}</div>
    </div>
  );
}

function AssistantBubble({ m, conversationId, courseId }: { m: TutorMessage; conversationId: string; courseId: string }) {
  const cites = m.citations.filter((c) => !c.nearest_only);
  const nearest = m.citations.filter((c) => c.nearest_only);
  const [check, setCheck] = React.useState<Assessment | null>(null);
  const [fb, setFb] = React.useState<Feedback | null>(null);
  const qc = useQueryClient();
  const start = useMutation({
    mutationFn: () => api<Assessment>(`/api/conversations/${conversationId}/knowledge-check`, { method: "POST", body: { message_id: m.id } }),
    onSuccess: setCheck,
    onError: (e) => toast.error(errorMessage(e)),
  });
  const answer = useMutation({
    mutationFn: (p: { response: Record<string, string>; reasoning: string | null; confidence: number | null }) =>
      api<{ feedback: Feedback }>(`/api/assessments/${check!.id}/answers`, { method: "POST", body: { question_id: check!.items[0].question.id, ...p } }),
    onSuccess: (r) => {
      setFb(r.feedback);
      qc.invalidateQueries({ queryKey: ["analytics"] });
    },
    onError: (e) => toast.error(errorMessage(e)),
  });

  return (
    <div className="flex gap-3" data-testid="assistant-message">
      <div className={cn("mt-1 flex size-8 shrink-0 items-center justify-center rounded-full", m.grounding_status === "grounded" ? "bg-ok/15 text-ok" : "bg-surface-3 text-muted")}>
        {m.grounding_status === "grounded" ? <BadgeCheck className="size-4" /> : <Ban className="size-4" />}
      </div>
      <div className="min-w-0 flex-1 space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          {m.grounding_status === "grounded" ? (
            <Badge variant="ok">Grounded in {cites.length} source location{cites.length === 1 ? "" : "s"}</Badge>
          ) : m.grounding_status === "refused" ? (
            <Badge variant="muted" data-testid="refusal-badge">Not covered by the course materials</Badge>
          ) : (
            <Badge variant="bad">Error</Badge>
          )}
          {m.answer_mode && <Badge variant="muted">{m.answer_mode === "extractive" ? "verbatim quotes" : "generated with citations"}</Badge>}
        </div>
        <div className="rounded-2xl rounded-tl-md border border-line bg-surface-2/60 px-4 py-3">
          <Markdown text={m.content} citations={cites} />
        </div>
        {cites.length > 0 && <CitationList citations={cites} />}
        {nearest.length > 0 && (
          <div className="space-y-1">
            <div className="text-[11px] text-subtle">Closest material found (shown for transparency, not as an answer):</div>
            <div className="flex flex-wrap gap-1.5">
              {nearest.map((c) => (
                <CitationChip key={c.unit_id} c={c} compact />
              ))}
            </div>
          </div>
        )}
        {m.external_content && (
          <div className="rounded-xl border border-warn/40 bg-warn/5 p-3">
            <div className="mb-1 flex items-center gap-1.5 text-xs font-semibold text-warn">
              <Globe className="size-3.5" /> Outside the course materials: general knowledge, not verified against your sources
            </div>
            <Markdown text={m.external_content} />
          </div>
        )}
        {m.learner_context?.concepts?.length ? (
          <LearnerContextStrip ctx={m.learner_context} courseId={courseId} />
        ) : null}
        {m.grounding_status === "grounded" && m.concept_ids.length > 0 && !check && (
          <Button variant="outline" size="sm" onClick={() => start.mutate()} disabled={start.isPending} data-testid="knowledge-check">
            <Brain /> Check my understanding
          </Button>
        )}
        {check && (
          <div className="space-y-3 rounded-xl border border-brand/30 bg-brand/5 p-4">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold uppercase tracking-wider text-brand-soft">Knowledge check (scored, updates mastery)</span>
              <QuestionMeta q={check.items[0].question} />
            </div>
            {fb ? <FeedbackPanel f={fb} compact /> : <QuestionForm q={check.items[0].question} onSubmit={(p) => answer.mutate(p)} pending={answer.isPending} askReasoning={false} />}
          </div>
        )}
      </div>
    </div>
  );
}

function LearnerContextStrip({ ctx, courseId }: { ctx: LearnerContext; courseId: string }) {
  const s = ctx.suggestion;
  return (
    <div className="space-y-2 rounded-xl border border-line bg-surface/70 p-3 text-xs" data-testid="learner-context">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-semibold uppercase tracking-wider text-subtle">Your learner model</span>
        {ctx.concepts?.map((c) => (
          <span key={c.concept_id} className="inline-flex items-center gap-1.5 rounded-full border border-line-strong px-2 py-0.5">
            <span className="size-2 rounded-full" style={{ background: masteryColor(c.label) }} />
            {c.name}: {c.p_mastery === null ? "unassessed" : pct(c.p_mastery)}
          </span>
        ))}
      </div>
      {ctx.hypotheses?.map((h) => (
        <div key={h.misconception_key} className="flex flex-wrap items-center gap-2 text-muted">
          <span className={cn("rounded-full border px-2 py-0.5 text-[10px]", HYPOTHESIS_STYLE[h.status]?.cls)}>{HYPOTHESIS_STYLE[h.status]?.label ?? h.status}</span>
          {h.title} (posterior {pct(h.posterior)})
        </div>
      ))}
      {s && (
        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line pt-2">
          <span className="text-muted">{s.text}</span>
          {s.type === "blindspot_session" && (
            <Button size="sm" variant="warn" asChild>
              <Link href={`/app/courses/${courseId}/lab?misconception=${s.misconception_key ?? ""}`}>Investigate</Link>
            </Button>
          )}
          {s.type === "practice" && (
            <Button size="sm" variant="outline" asChild>
              <Link href={`/app/courses/${courseId}/assess?kind=practice&concepts=${s.concept_id ?? ""}`}>Practise prerequisite</Link>
            </Button>
          )}
        </div>
      )}
    </div>
  );
}
