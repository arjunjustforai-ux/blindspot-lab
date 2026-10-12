"use client";

import Link from "next/link";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Citation } from "@/lib/types";
import { Tip } from "./ui/tooltip";

/** Renders model/source text as Markdown WITHOUT raw HTML; [S1]-style markers become citation links. */
export function Markdown({ text, citations = [] }: { text: string; citations?: Citation[] }) {
  const byId = Object.fromEntries(citations.map((c) => [c.id, c]));
  const prepared = text.replace(/\[(S\d+)\]/g, (_m, id: string) => `[${id}](#cite-${id})`);
  return (
    <div className="prose-lab text-[14px]">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        skipHtml
        components={{
          a: ({ href, children }) => {
            const id = href?.startsWith("#cite-") ? href.slice(6) : null;
            const c = id ? byId[id] : null;
            if (c) {
              return (
                <Tip content={<span><b>{c.label}</b><br />{c.excerpt.slice(0, 220)}</span>}>
                  <Link href={c.link} className="mx-0.5 inline-flex -translate-y-px items-center rounded-md border border-brand/40 bg-brand/15 px-1.5 text-[11px] font-semibold text-brand-soft no-underline hover:bg-brand/30">
                    {id}
                  </Link>
                </Tip>
              );
            }
            if (id) return <span className="text-[11px] text-subtle">[{id}]</span>;
            return (
              <a href={href} target="_blank" rel="noopener noreferrer nofollow" className="text-accent underline">
                {children}
              </a>
            );
          },
          img: () => null,
        }}
      >
        {prepared}
      </ReactMarkdown>
    </div>
  );
}
