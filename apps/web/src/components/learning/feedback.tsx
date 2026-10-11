"use client";

import { AlertTriangle, CheckCircle2, CircleHelp, Flag, TrendingDown, TrendingUp, XCircle } from "lucide-react";
import type { Feedback } from "@/lib/types";
import { CATEGORY_STYLE, cn, HYPOTHESIS_STYLE, pct } from "@/lib/utils";
import { Badge } from "../ui/badge";
import { CitationList } from "./citations";

export function FeedbackPanel({ f, compact = false }: { f: Feedback; compact?: boolean }) {
  const ok = f.is_correct;
  return (
    <div className={cn("space-y-4 rounded-xl border p-4", ok ? "border-ok/30 bg-ok/5" : ok === false ? "border-bad/30 bg-bad/5" : "border-line-strong bg-surface-2")} data-testid="feedback">
      <div className="flex flex-wrap items-center gap-2">
        {ok ? <CheckCircle2 className="size-5 text-ok" /> : ok === false ? <XCircle className="size-5 text-bad" /> : <CircleHelp className="size-5 text-muted" />}
        <span className="font-semibold">{ok ? "Correct" : ok === false ? "Not correct" : "Could not grade reliably"}</span>
        {f.score !== null && f.score !== undefined && f.score !== 0 && f.score !== 1 && <Badge variant="muted">rubric score {pct(f.score)}</Badge>}
        {f.needs_review && (
          <Badge variant="warn">
            <Flag className="size-3" /> flagged for review: not used as mastery evidence
          </Badge>
        )}
        <span className={cn("ml-auto text-xs font-medium", CATEGORY_STYLE[f.classification.category])}>{f.classification.label}</span>
      </div>

      <div className="grid gap-3 text-sm md:grid-cols-2">
        <div>
          <div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-subtle">Verified answer</div>
          {f.correct_answer.text && <p>{f.correct_answer.option_id?.toUpperCase()}. {f.correct_answer.text}</p>}
          {f.correct_answer.value !== undefined && (
            <p className="font-mono">
              {f.correct_answer.value} {f.correct_answer.unit}
            </p>
          )}
          {f.correct_answer.key_points && (
            <ul className="list-disc space-y-0.5 pl-4 text-muted">
              {f.correct_answer.key_points.map((k) => (
                <li key={k}>{k}</li>
              ))}
            </ul>
          )}
        </div>
        <div>
          <div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-subtle">Why</div>
          {f.worked_steps.length > 0 ? (
            <ol className="list-decimal space-y-0.5 pl-4 text-muted">
              {f.worked_steps.map((s) => (
                <li key={s}>{s}</li>
              ))}
            </ol>
          ) : (
            <p className="text-muted">{f.explanation}</p>
          )}
        </div>
      </div>

      {!compact && <p className="text-xs text-muted">{f.classification.summary}</p>}

      {f.misconception_alert && (
        <div className="flex gap-3 rounded-lg border border-warn/40 bg-warn/10 p-3 text-sm">
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warn" />
          <div className="space-y-1">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-semibold text-warn">Possible blindspot: {f.misconception_alert.title}</span>
              <span className={cn("rounded-full border px-2 py-0.5 text-[10px]", HYPOTHESIS_STYLE[f.misconception_alert.status]?.cls)}>
                {HYPOTHESIS_STYLE[f.misconception_alert.status]?.label ?? f.misconception_alert.status} · p={f.misconception_alert.posterior.toFixed(2)}
              </span>
            </div>
            <p className="text-xs text-muted">{f.misconception_alert.message}</p>
          </div>
        </div>
      )}

      {f.mastery && f.mastery.after !== null && f.mastery.before !== null && (
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
          {f.mastery.after >= f.mastery.before ? <TrendingUp className="size-4 text-ok" /> : <TrendingDown className="size-4 text-bad" />}
          <span>
            Mastery estimate for <b className="text-fg">{f.mastery.name}</b>: {pct(f.mastery.before)} → <b className="text-fg">{pct(f.mastery.after)}</b>
          </span>
          <span className="text-subtle">· evidence weight {f.mastery.weight} ({f.mastery.weight_reasons.join("; ")})</span>
        </div>
      )}

      <CitationList citations={f.citations} title="Source evidence" />
    </div>
  );
}
