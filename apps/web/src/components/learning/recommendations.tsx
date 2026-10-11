"use client";

import { ArrowRight, BookOpenCheck, ClipboardCheck, Repeat, ScanSearch, Target, Trophy } from "lucide-react";
import Link from "next/link";
import type { Recommendation } from "@/lib/types";
import { cn } from "@/lib/utils";

const ICON = {
  diagnostic_assessment: ClipboardCheck,
  blindspot_session: ScanSearch,
  practice: Target,
  review: Repeat,
  assessment: BookOpenCheck,
  mock_exam: Trophy,
};

export function recHref(courseId: string, r: Recommendation): string {
  if (r.type === "blindspot_session") return `/app/courses/${courseId}/lab?misconception=${r.misconception_key ?? ""}`;
  if (r.type === "diagnostic_assessment") return `/app/courses/${courseId}/assess?kind=diagnostic`;
  const kind = r.type === "review" ? "review" : r.type === "mock_exam" ? "mock_exam" : "practice";
  const q = new URLSearchParams({ kind });
  if (r.concept_ids.length && r.type !== "mock_exam") q.set("concepts", r.concept_ids.join(","));
  if (r.difficulty) q.set("difficulty", String(r.difficulty));
  return `/app/courses/${courseId}/assess?${q.toString()}`;
}

export function RecommendationCard({ courseId, r, primary = false }: { courseId: string; r: Recommendation; primary?: boolean }) {
  const Icon = ICON[r.type] ?? Target;
  return (
    <Link
      href={recHref(courseId, r)}
      className={cn(
        "group flex items-start gap-3 rounded-xl border p-3.5 transition-colors",
        r.type === "blindspot_session" ? "border-warn/40 bg-warn/5 hover:bg-warn/10" : primary ? "border-brand/40 bg-brand/10 hover:bg-brand/15" : "border-line bg-surface-2/60 hover:border-brand/40",
      )}
    >
      <div className={cn("rounded-lg p-2", r.type === "blindspot_session" ? "bg-warn/15 text-warn" : "bg-brand/15 text-brand-soft")}>
        <Icon className="size-4" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 text-sm font-semibold">
          {r.title}
          <ArrowRight className="size-3.5 opacity-0 transition-opacity group-hover:opacity-100" />
        </div>
        <p className="mt-0.5 text-xs leading-relaxed text-muted">{r.rationale}</p>
      </div>
    </Link>
  );
}
