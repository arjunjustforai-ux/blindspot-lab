"use client";

import { ChevronLeft, ChevronRight, ZoomIn, ZoomOut } from "lucide-react";
import * as React from "react";
import { Document, Page, pdfjs } from "react-pdf";
import "react-pdf/dist/Page/AnnotationLayer.css";
import "react-pdf/dist/Page/TextLayer.css";
import { Button } from "../ui/button";

pdfjs.GlobalWorkerOptions.workerSrc = new URL("pdfjs-dist/build/pdf.worker.min.mjs", import.meta.url).toString();

function norm(s: string) {
  return s.toLowerCase().replace(/[^a-z0-9₹%]+/g, " ").trim();
}

export default function PdfViewer({ url, page, onPage, highlight }: { url: string; page: number; onPage: (p: number) => void; highlight?: string | null }) {
  const [numPages, setNumPages] = React.useState<number>();
  const [scale, setScale] = React.useState(1.15);
  const [error, setError] = React.useState<string | null>(null);
  const target = React.useMemo(() => (highlight ? norm(highlight) : ""), [highlight]);

  const textRenderer = React.useCallback(
    ({ str }: { str: string }) => {
      const n = norm(str);
      if (target && n.length > 3 && target.includes(n)) return `<mark>${escapeHtml(str)}</mark>`;
      return escapeHtml(str);
    },
    [target],
  );

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-1">
          <Button variant="outline" size="icon" aria-label="Previous page" disabled={page <= 1} onClick={() => onPage(page - 1)}>
            <ChevronLeft />
          </Button>
          <span className="px-2 font-mono text-xs text-muted">
            Page {page} / {numPages ?? "…"}
          </span>
          <Button variant="outline" size="icon" aria-label="Next page" disabled={!!numPages && page >= numPages} onClick={() => onPage(page + 1)}>
            <ChevronRight />
          </Button>
        </div>
        <div className="flex items-center gap-1">
          <Button variant="ghost" size="icon" aria-label="Zoom out" onClick={() => setScale((s) => Math.max(0.6, s - 0.15))}>
            <ZoomOut />
          </Button>
          <Button variant="ghost" size="icon" aria-label="Zoom in" onClick={() => setScale((s) => Math.min(2.2, s + 0.15))}>
            <ZoomIn />
          </Button>
        </div>
      </div>
      <div className="overflow-auto rounded-xl border border-line bg-surface-3 p-3" data-testid="pdf-viewer">
        {error ? (
          <p className="p-6 text-sm text-bad">{error}</p>
        ) : (
          <Document file={url} onLoadSuccess={(d) => setNumPages(d.numPages)} onLoadError={(e) => setError(`Could not load PDF: ${e.message}`)} loading={<p className="p-6 text-sm text-muted">Loading PDF…</p>}>
            <Page pageNumber={page} scale={scale} className="mx-auto w-fit shadow-2xl" customTextRenderer={textRenderer} />
          </Document>
        )}
      </div>
    </div>
  );
}

function escapeHtml(s: string) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}
