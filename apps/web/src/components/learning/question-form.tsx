"use client";

import { Gauge, Send } from "lucide-react";
import * as React from "react";
import type { PublicQuestion } from "@/lib/types";
import { cn, difficultyLabel } from "@/lib/utils";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { Input, Textarea } from "../ui/input";

export interface AnswerPayload {
  response: Record<string, string>;
  reasoning: string | null;
  confidence: number | null;
}

export function QuestionMeta({ q }: { q: PublicQuestion }) {
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {q.concept_name && <Badge variant="muted">{q.concept_name}</Badge>}
      <Badge variant="default">{q.question_type === "mcq" ? "Multiple choice" : q.question_type === "numerical" ? "Numerical" : "Short answer"}</Badge>
      <Badge variant={q.difficulty === 3 ? "bad" : q.difficulty === 2 ? "warn" : "ok"}>{difficultyLabel(q.difficulty)}</Badge>
      <Badge variant="muted">{q.origin === "template" ? "Verified generated" : q.origin === "bank" ? "Verified bank" : q.origin}</Badge>
    </div>
  );
}

export function QuestionForm({
  q,
  onSubmit,
  pending,
  initial,
  askReasoning = true,
  submitLabel = "Submit answer",
}: {
  q: PublicQuestion;
  onSubmit: (p: AnswerPayload) => void;
  pending?: boolean;
  initial?: Partial<{ option_id: string; value: string; text: string; reasoning: string; confidence: number }>;
  askReasoning?: boolean;
  submitLabel?: string;
}) {
  const [option, setOption] = React.useState(initial?.option_id ?? "");
  const [value, setValue] = React.useState(initial?.value ?? "");
  const [text, setText] = React.useState(initial?.text ?? "");
  const [reasoning, setReasoning] = React.useState(initial?.reasoning ?? "");
  const [confidence, setConfidence] = React.useState<number | null>(initial?.confidence ?? null);

  React.useEffect(() => {
    setOption(initial?.option_id ?? "");
    setValue(initial?.value ?? "");
    setText(initial?.text ?? "");
    setReasoning(initial?.reasoning ?? "");
    setConfidence(initial?.confidence ?? null);
  }, [q.id, initial?.option_id, initial?.value, initial?.text, initial?.reasoning, initial?.confidence]);

  const ready = q.question_type === "mcq" ? !!option : q.question_type === "numerical" ? value.trim() !== "" : text.trim().split(/\s+/).length >= 3;

  return (
    <form
      className="space-y-4"
      onSubmit={(e) => {
        e.preventDefault();
        if (!ready || pending) return;
        const response: Record<string, string> =
          q.question_type === "mcq" ? { option_id: option } : q.question_type === "numerical" ? { value } : { text };
        onSubmit({ response, reasoning: reasoning.trim() || null, confidence });
      }}
    >
      <p className="text-[15px] leading-relaxed text-fg">{q.stem}</p>
      {q.assumptions && <p className="text-xs text-subtle">Assumptions: {q.assumptions}</p>}

      {q.question_type === "mcq" && (
        <fieldset className="space-y-2">
          <legend className="sr-only">Options</legend>
          {q.options.map((o) => (
            <label
              key={o.id}
              className={cn(
                "flex cursor-pointer items-start gap-3 rounded-xl border px-3.5 py-2.5 text-sm transition-colors",
                option === o.id ? "border-brand/70 bg-brand/10" : "border-line-strong bg-surface-2/50 hover:border-brand/40",
              )}
            >
              <input type="radio" name={`q-${q.id}`} value={o.id} checked={option === o.id} onChange={() => setOption(o.id)} className="mt-1 accent-[#6366f1]" />
              <span className="font-mono text-xs text-subtle">{o.id.toUpperCase()}</span>
              <span className="flex-1">{o.text}</span>
            </label>
          ))}
        </fieldset>
      )}

      {q.question_type === "numerical" && (
        <div className="flex max-w-sm items-center gap-2">
          <Input aria-label="Your numerical answer" inputMode="decimal" placeholder="Your answer" value={value} onChange={(e) => setValue(e.target.value)} />
          {q.answer_unit && <span className="whitespace-nowrap text-sm text-muted">{q.answer_unit}</span>}
        </div>
      )}

      {q.question_type === "short_answer" && (
        <Textarea aria-label="Your answer" rows={4} placeholder="Explain in your own words…" value={text} onChange={(e) => setText(e.target.value)} />
      )}

      {askReasoning && (
        <div className="grid gap-3 sm:grid-cols-[1fr_auto]">
          <div className="space-y-1">
            <label htmlFor={`r-${q.id}`} className="text-xs font-medium text-muted">
              How did you get there? <span className="text-subtle">(optional, helps diagnose your reasoning)</span>
            </label>
            <Textarea id={`r-${q.id}`} rows={2} value={reasoning} onChange={(e) => setReasoning(e.target.value)} placeholder="e.g. I compared the contribution per unit before and after…" />
          </div>
          <div className="space-y-1">
            <div className="flex items-center gap-1 text-xs font-medium text-muted">
              <Gauge className="size-3.5" /> Confidence
            </div>
            <div className="flex gap-1" role="radiogroup" aria-label="Confidence from 1 to 5">
              {[1, 2, 3, 4, 5].map((n) => (
                <button
                  type="button"
                  key={n}
                  role="radio"
                  aria-checked={confidence === n}
                  onClick={() => setConfidence(confidence === n ? null : n)}
                  className={cn(
                    "size-8 rounded-lg border text-xs font-semibold transition-colors",
                    confidence === n ? "border-accent bg-accent/15 text-accent" : "border-line-strong text-muted hover:border-accent/50",
                  )}
                >
                  {n}
                </button>
              ))}
            </div>
            <div className="text-[10px] text-subtle">1 = guessing · 5 = certain</div>
          </div>
        </div>
      )}

      <Button type="submit" disabled={!ready || pending}>
        <Send /> {pending ? "Grading…" : submitLabel}
      </Button>
    </form>
  );
}
