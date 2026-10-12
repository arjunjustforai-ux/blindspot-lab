import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function pct(x: number | null | undefined, digits = 0): string {
  if (x === null || x === undefined || Number.isNaN(x)) return "—";
  return `${(x * 100).toFixed(digits)}%`;
}

export function fmtTs(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "—";
  const s = Math.floor(seconds);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  const mm = String(m).padStart(2, "0");
  const ss = String(sec).padStart(2, "0");
  return h ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}

export function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

export function timeAgo(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = (Date.now() - new Date(iso).getTime()) / 1000;
  if (d < 60) return "just now";
  if (d < 3600) return `${Math.floor(d / 60)} min ago`;
  if (d < 86400) return `${Math.floor(d / 3600)} h ago`;
  return `${Math.floor(d / 86400)} d ago`;
}

export const MASTERY_COLORS: Record<string, string> = {
  unassessed: "#64708a",
  emerging: "#f87171",
  developing: "#fbbf24",
  proficient: "#22d3ee",
  mastered: "#34d399",
};

export function masteryColor(label: string | undefined): string {
  return MASTERY_COLORS[label ?? "unassessed"] ?? MASTERY_COLORS.unassessed;
}

export const HYPOTHESIS_STYLE: Record<string, { label: string; cls: string }> = {
  suspected: { label: "Suspected", cls: "border-warn/40 bg-warn/10 text-warn" },
  supported: { label: "Supported by evidence", cls: "border-warn/60 bg-warn/15 text-warn" },
  unresolved: { label: "Unresolved", cls: "border-line-strong bg-surface-3 text-muted" },
  rejected: { label: "Rejected", cls: "border-line bg-surface-2 text-subtle" },
  resolving: { label: "Repaired · revisit pending", cls: "border-accent/40 bg-accent/10 text-accent" },
  resolved: { label: "Resolved", cls: "border-ok/40 bg-ok/10 text-ok" },
};

export const CATEGORY_STYLE: Record<string, string> = {
  correct_supported: "text-ok",
  correct_questionable_reasoning: "text-warn",
  calculation_error: "text-accent",
  likely_misconception: "text-warn",
  missing_prerequisite: "text-bad",
  incomplete_or_ambiguous: "text-muted",
  insufficient_evidence: "text-muted",
};

export function difficultyLabel(d: number): string {
  return ["", "Easy", "Medium", "Hard"][d] ?? `Level ${d}`;
}
