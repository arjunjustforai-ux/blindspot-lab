"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, ChevronLeft, ChevronRight, Film, Sparkles } from "lucide-react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import * as React from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { api, errorMessage, mediaUrl } from "@/lib/api";
import type { Source, Unit } from "@/lib/types";
import { cn, fmtTs } from "@/lib/utils";

const PdfViewer = dynamic(() => import("@/components/viewer/pdf-viewer"), { ssr: false, loading: () => <LoadingState label="Loading PDF viewer…" /> });

interface ViewInfo {
  source: Source;
  file_url: string;
  slide_previews: Record<string, string>;
}

function ViewerInner() {
  const { courseId, sourceId } = useParams<{ courseId: string; sourceId: string }>();
  const sp = useSearchParams();
  const router = useRouter();
  const unitParam = sp.get("unit");
  const view = useQuery({ queryKey: ["view", sourceId], queryFn: () => api<ViewInfo>(`/api/sources/${sourceId}/view`) });
  const units = useQuery({ queryKey: ["units", sourceId], queryFn: () => api<{ units: Unit[] }>(`/api/sources/${sourceId}/units`) });
  const [page, setPage] = React.useState(Number(sp.get("page")) || 1);
  const [slide, setSlide] = React.useState(Number(sp.get("slide")) || 1);
  const t = sp.get("t") ? Number(sp.get("t")) : null;

  if (view.isLoading || units.isLoading) return <LoadingState />;
  if (view.isError) return <ErrorState message={errorMessage(view.error)} onRetry={() => view.refetch()} />;
  const v = view.data!;
  const all = units.data?.units ?? [];
  const cited = all.find((u) => u.id === unitParam) ?? null;
  const src = v.source;

  const setAnchor = (key: "page" | "slide", n: number) => {
    if (key === "page") setPage(n);
    else setSlide(n);
    const q = new URLSearchParams(sp.toString());
    q.set(key, String(n));
    q.delete("unit");
    router.replace(`?${q.toString()}`, { scroll: false });
  };

  const here = src.modality === "pdf" ? all.filter((u) => u.page === page) : src.modality === "pptx" ? all.filter((u) => u.slide === slide) : all;

  return (
    <div className="mx-auto max-w-7xl">
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Button variant="ghost" size="sm" onClick={() => router.back()}>
          <ArrowLeft /> Back
        </Button>
        <h1 className="truncate text-lg font-semibold">{src.filename}</h1>
        <Badge variant="muted">{src.modality}</Badge>
        {cited && <Badge variant="warn">Cited location: {cited.anchor}</Badge>}
      </div>

      <div className="grid gap-4 xl:grid-cols-[1.5fr_1fr]">
        <div>
          {src.modality === "pdf" && <PdfViewer url={mediaUrl(v.file_url)!} page={page} onPage={(p) => setAnchor("page", p)} highlight={cited && cited.page === page ? cited.content : null} />}
          {src.modality === "pptx" && <SlideViewer previews={v.slide_previews} count={src.slide_count ?? 1} slide={slide} onSlide={(n) => setAnchor("slide", n)} />}
          {src.modality === "video" && <VideoViewer url={mediaUrl(v.file_url)!} start={t} units={all} citedUnitId={unitParam} />}
        </div>

        <Card className="h-fit">
          <CardHeader>
            <CardTitle>{src.modality === "video" ? "Indexed segments" : `Extracted from ${src.modality === "pdf" ? `page ${page}` : `slide ${slide}`}`}</CardTitle>
          </CardHeader>
          <CardContent className="max-h-[75vh] space-y-2 overflow-y-auto">
            {src.modality !== "video" && here.length === 0 && <p className="text-sm text-muted">No content units on this {src.modality === "pdf" ? "page" : "slide"}.</p>}
            {(src.modality === "video" ? all.filter((u) => u.modality === "video_frame") : here).map((u) => (
              <UnitCard key={u.id} u={u} active={u.id === unitParam} />
            ))}
          </CardContent>
        </Card>
      </div>
      <p className="mt-4 text-xs text-subtle">
        Course {courseId.slice(0, 8)} · media links are signed and expire; access is re-checked against your course membership.
      </p>
    </div>
  );
}

function UnitCard({ u, active }: { u: Unit; active: boolean }) {
  const ref = React.useRef<HTMLDivElement>(null);
  React.useEffect(() => {
    if (active) ref.current?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [active]);
  return (
    <div ref={ref} className={cn("rounded-lg border p-3 text-sm", active ? "border-warn/60 bg-warn/10" : "border-line bg-surface-2/60")} data-testid={active ? "cited-unit" : undefined}>
      <div className="mb-1 flex flex-wrap items-center gap-1.5">
        <Badge variant="accent">{u.anchor}</Badge>
        <Badge variant="muted">{u.modality.replace("_", " ")}</Badge>
        {u.is_generated && (
          <Badge variant="warn">
            <Sparkles className="size-3" /> model interpretation
          </Badge>
        )}
        {active && <Badge variant="warn">cited</Badge>}
      </div>
      {u.heading && <div className="text-xs font-medium text-subtle">{u.heading}</div>}
      {u.image_url && (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={mediaUrl(u.image_url)} alt={`Figure, ${u.anchor}`} className="my-2 max-h-56 w-full rounded-md border border-line bg-white object-contain" />
      )}
      <p className="whitespace-pre-line text-xs leading-relaxed text-muted">{u.content}</p>
      {typeof u.extraction_meta?.ocr_mean_confidence === "number" && (
        <div className="mt-1 text-[10px] text-subtle">OCR mean confidence {(u.extraction_meta.ocr_mean_confidence as number).toFixed(0)}</div>
      )}
    </div>
  );
}

function SlideViewer({ previews, count, slide, onSlide }: { previews: Record<string, string>; count: number; slide: number; onSlide: (n: number) => void }) {
  const url = previews[String(slide)];
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-1">
        <Button variant="outline" size="icon" aria-label="Previous slide" disabled={slide <= 1} onClick={() => onSlide(slide - 1)}>
          <ChevronLeft />
        </Button>
        <span className="px-2 font-mono text-xs text-muted">
          Slide {slide} / {count}
        </span>
        <Button variant="outline" size="icon" aria-label="Next slide" disabled={slide >= count} onClick={() => onSlide(slide + 1)}>
          <ChevronRight />
        </Button>
      </div>
      <div className="overflow-hidden rounded-xl border border-line bg-white" data-testid="slide-viewer">
        {url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={mediaUrl(url)} alt={`Slide ${slide}`} className="w-full" />
        ) : (
          <p className="bg-surface p-8 text-sm text-muted">No rendered preview available for this slide; its extracted text is shown alongside.</p>
        )}
      </div>
      <div className="flex gap-2 overflow-x-auto pb-1">
        {Array.from({ length: count }, (_, i) => i + 1).map((n) => (
          <button key={n} onClick={() => onSlide(n)} className={cn("shrink-0 overflow-hidden rounded-md border-2", n === slide ? "border-brand" : "border-transparent opacity-70 hover:opacity-100")} aria-label={`Go to slide ${n}`}>
            {previews[String(n)] ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={mediaUrl(previews[String(n)])} alt="" className="h-14 w-24 bg-white object-cover" />
            ) : (
              <span className="flex h-14 w-24 items-center justify-center bg-surface-3 text-xs">{n}</span>
            )}
          </button>
        ))}
      </div>
    </div>
  );
}

function VideoViewer({ url, start, units, citedUnitId }: { url: string; start: number | null; units: Unit[]; citedUnitId: string | null }) {
  const ref = React.useRef<HTMLVideoElement>(null);
  const [time, setTime] = React.useState(start ?? 0);
  const segs = units
    .filter((u) => u.modality === "transcript")
    .flatMap((u) => (u.segments ?? []).map((s) => ({ ...s, unit: u.id })));
  const seek = (s: number) => {
    if (ref.current) {
      ref.current.currentTime = s;
      ref.current.play().catch(() => undefined);
    }
  };
  return (
    <div className="space-y-3">
      <video
        ref={ref}
        src={start !== null ? `${url}#t=${start}` : url}
        controls
        preload="metadata"
        className="w-full rounded-xl border border-line bg-black"
        data-testid="video-player"
        onLoadedMetadata={() => {
          if (start !== null && ref.current) ref.current.currentTime = start;
        }}
        onTimeUpdate={(e) => setTime(e.currentTarget.currentTime)}
      />
      {start !== null && (
        <p className="flex items-center gap-2 text-xs text-warn">
          <Film className="size-3.5" /> Opened at the cited timestamp {fmtTs(start)} (a Whisper segment boundary).
        </p>
      )}
      <Card>
        <CardHeader>
          <CardTitle>Transcript (Whisper segments)</CardTitle>
        </CardHeader>
        <CardContent className="max-h-80 space-y-1 overflow-y-auto">
          {segs.map((s) => {
            const active = time >= s.start && time < s.end;
            // The segment the citation points at: inside the cited unit, starting at the cited timestamp.
            const cited = s.unit === citedUnitId && start !== null && Math.abs(s.start - start) < 0.5;
            return (
              <button
                key={`${s.unit}-${s.start}`}
                onClick={() => seek(s.start)}
                data-testid={cited ? "cited-unit" : undefined}
                className={cn("flex w-full gap-3 rounded-md px-2 py-1 text-left text-sm", active ? "bg-brand/15 text-fg" : "text-muted hover:bg-surface-3", cited && "ring-1 ring-warn/60")}
              >
                <span className="w-12 shrink-0 font-mono text-xs text-brand-soft">{fmtTs(s.start)}</span>
                <span className="flex-1">{s.text}</span>
                {s.confidence !== null && <span className="text-[10px] text-subtle">{Math.round(s.confidence * 100)}%</span>}
              </button>
            );
          })}
        </CardContent>
      </Card>
    </div>
  );
}

export default function SourceViewerPage() {
  return (
    <React.Suspense fallback={<LoadingState />}>
      <ViewerInner />
    </React.Suspense>
  );
}
