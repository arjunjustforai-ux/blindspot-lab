"use client";

import { FileText, Film, Image as ImageIcon, Presentation, Sparkles } from "lucide-react";
import Link from "next/link";
import type { Citation } from "@/lib/types";
import { cn, fmtTs } from "@/lib/utils";
import { Tip } from "../ui/tooltip";

export function modalityIcon(sourceModality: string, unitModality?: string) {
  if (unitModality && /figure|chart|frame/.test(unitModality)) return ImageIcon;
  if (sourceModality === "video") return Film;
  if (sourceModality === "pptx") return Presentation;
  return FileText;
}

export function anchorText(c: Pick<Citation, "page" | "slide" | "start">) {
  if (c.page !== null && c.page !== undefined) return `Page ${c.page}`;
  if (c.slide !== null && c.slide !== undefined) return `Slide ${c.slide}`;
  return fmtTs(c.start);
}

export function CitationChip({ c, compact = false }: { c: Citation; compact?: boolean }) {
  const Icon = modalityIcon(c.source_modality, c.unit_modality);
  return (
    <Tip
      content={
        <div className="space-y-1">
          <div className="font-semibold">{c.label}</div>
          {c.heading && <div className="text-muted">{c.heading}</div>}
          <div className="text-muted">“{c.excerpt.slice(0, 260)}{c.excerpt.length > 260 ? "…" : ""}”</div>
          {c.is_generated && <div className="text-warn">Model-generated figure description</div>}
        </div>
      }
    >
      <Link
        href={c.link}
        data-testid="citation-chip"
        className={cn(
          "group inline-flex max-w-full items-center gap-1.5 rounded-lg border px-2 py-1 text-xs transition-colors",
          c.nearest_only ? "border-line-strong bg-surface-2 text-muted hover:text-fg" : "border-brand/35 bg-brand/10 text-brand-soft hover:border-brand/70 hover:bg-brand/20",
        )}
      >
        <span className="rounded bg-bg/40 px-1 font-mono text-[10px] text-fg/80">{c.id}</span>
        <Icon className="size-3.5 shrink-0" />
        <span className="truncate">{compact ? anchorText(c) : c.label}</span>
        {c.is_generated && <Sparkles className="size-3 text-warn" />}
      </Link>
    </Tip>
  );
}

export function CitationList({ citations, title = "Sources" }: { citations: Citation[]; title?: string }) {
  if (!citations.length) return null;
  return (
    <div className="space-y-1.5">
      <div className="text-[11px] font-semibold uppercase tracking-wider text-subtle">{title}</div>
      <div className="flex flex-wrap gap-1.5">
        {citations.map((c) => (
          <CitationChip key={`${c.id}-${c.unit_id}`} c={c} />
        ))}
      </div>
    </div>
  );
}
