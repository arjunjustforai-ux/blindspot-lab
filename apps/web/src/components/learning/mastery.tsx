import type { MasteryView } from "@/lib/types";
import { cn, masteryColor, pct } from "@/lib/utils";
import { Badge } from "../ui/badge";
import { Tip } from "../ui/tooltip";

const LABEL: Record<string, string> = {
  unassessed: "Unassessed",
  emerging: "Emerging",
  developing: "Developing",
  proficient: "Proficient",
  mastered: "Mastered (est.)",
};

export function MasteryBar({ m, showLabel = true }: { m: Pick<MasteryView, "p_mastery" | "label" | "evidence_quality" | "n_observations">; showLabel?: boolean }) {
  const color = masteryColor(m.label);
  return (
    <Tip
      content={
        m.p_mastery === null
          ? "No scored evidence yet: the model only has its prior."
          : `BKT estimate ${pct(m.p_mastery)} from ${m.n_observations} scored observation(s); evidence quality ${m.evidence_quality}. An estimate, not a measurement.`
      }
    >
      <div className="flex w-full items-center gap-2">
        <div className="relative h-2 flex-1 overflow-hidden rounded-full bg-surface-3">
          {m.p_mastery === null ? (
            <div className="absolute inset-0 bg-[repeating-linear-gradient(45deg,transparent,transparent_4px,rgb(100_112_138/0.35)_4px,rgb(100_112_138/0.35)_8px)]" />
          ) : (
            <div className="h-full rounded-full transition-all duration-700" style={{ width: `${m.p_mastery * 100}%`, background: color }} />
          )}
        </div>
        {showLabel && (
          <span className="w-12 text-right font-mono text-xs tabular-nums" style={{ color }}>
            {m.p_mastery === null ? "—" : pct(m.p_mastery)}
          </span>
        )}
      </div>
    </Tip>
  );
}

export function MasteryBadge({ label, quality }: { label: string; quality?: string }) {
  const variant = label === "mastered" || label === "proficient" ? "ok" : label === "developing" ? "warn" : label === "emerging" ? "bad" : "muted";
  return (
    <span className="inline-flex items-center gap-1">
      <Badge variant={variant}>{LABEL[label] ?? label}</Badge>
      {quality && label !== "unassessed" && <span className={cn("text-[10px] text-subtle")}>{quality} evidence</span>}
    </span>
  );
}
