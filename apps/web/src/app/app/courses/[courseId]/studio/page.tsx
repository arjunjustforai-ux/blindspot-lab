"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Eye, FileText, Film, Loader2, Lock, Presentation, RefreshCw, ShieldCheck, Sparkles, Trash2, UploadCloud, XCircle } from "lucide-react";
import Link from "next/link";
import * as React from "react";
import { toast } from "sonner";
import { PageHeader } from "@/components/shell/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/states";
import { API_URL, api, errorMessage, getToken, mediaUrl } from "@/lib/api";
import { useCourse, useCourseId } from "@/lib/hooks";
import type { GraphNode, Job, Source, Unit } from "@/lib/types";
import { cn, fmtBytes, fmtTs } from "@/lib/utils";

const STAGES = ["uploaded", "extracting", "indexing", "ready"] as const;
const ACCEPT = ".pdf,.pptx,.mp4,.m4v,.mov,.webm";
const LIMITS: Record<string, number> = { pdf: 60, pptx: 60, video: 400 };

function modalityOf(name: string): "pdf" | "pptx" | "video" | null {
  const ext = name.toLowerCase().split(".").pop();
  if (ext === "pdf") return "pdf";
  if (ext === "pptx") return "pptx";
  if (["mp4", "m4v", "mov", "webm"].includes(ext ?? "")) return "video";
  return null;
}

function upload(courseId: string, file: File, onProgress: (f: number) => void): Promise<Source> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_URL}/api/courses/${courseId}/sources`);
    const t = getToken();
    if (t) xhr.setRequestHeader("Authorization", `Bearer ${t}`);
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
    xhr.onload = () => {
      const body = xhr.responseText ? JSON.parse(xhr.responseText) : null;
      if (xhr.status >= 200 && xhr.status < 300) resolve(body);
      else reject(new Error(body?.error?.message ?? `Upload failed (${xhr.status})`));
    };
    xhr.onerror = () => reject(new Error("Network error during upload"));
    const fd = new FormData();
    fd.append("file", file);
    xhr.send(fd);
  });
}

export default function StudioPage() {
  const courseId = useCourseId()!;
  const qc = useQueryClient();
  const course = useCourse(courseId);
  const canManage = course.data?.role === "owner" || course.data?.role === "instructor";
  const sources = useQuery({
    queryKey: ["sources", courseId],
    queryFn: () => api<Source[]>(`/api/courses/${courseId}/sources`),
    refetchInterval: (q) => ((q.state.data ?? []).some((s) => s.status !== "ready" && s.status !== "failed") ? 2000 : false),
  });
  const jobs = useQuery({
    queryKey: ["jobs", courseId],
    queryFn: () => api<Job[]>(`/api/courses/${courseId}/jobs`),
    refetchInterval: (q) => ((q.state.data ?? []).some((j) => j.status === "queued" || j.status === "running") ? 2000 : false),
  });
  const graph = useQuery({ queryKey: ["graph", courseId], queryFn: () => api<{ nodes: GraphNode[]; coverage: { units: number; tagged_units: number } }>(`/api/courses/${courseId}/graph`) });
  const ready = useQuery({ queryKey: ["ready"], queryFn: () => api<{ checks: { ai_mode: { generation: string; external_processing: boolean; transcription: string; embeddings: string } } }>("/api/ready") });

  const [uploads, setUploads] = React.useState<{ name: string; progress: number; error?: string }[]>([]);
  const [drag, setDrag] = React.useState(false);
  const [selected, setSelected] = React.useState<string | null>(null);

  const anyActive = (jobs.data ?? []).some((j) => j.status === "queued" || j.status === "running");
  const wasActive = React.useRef(false);
  React.useEffect(() => {
    if (wasActive.current && !anyActive) {
      qc.invalidateQueries({ queryKey: ["graph", courseId] });
      qc.invalidateQueries({ queryKey: ["course", courseId] });
      qc.invalidateQueries({ queryKey: ["sources", courseId] });
    }
    wasActive.current = anyActive;
  }, [anyActive, qc, courseId]);

  async function handleFiles(files: FileList | File[]) {
    for (const file of Array.from(files)) {
      const m = modalityOf(file.name);
      if (!m) {
        toast.error(`${file.name}: unsupported type. Use PDF, PPTX or MP4/MOV/WEBM.`);
        continue;
      }
      if (file.size > LIMITS[m] * 1024 * 1024) {
        toast.error(`${file.name}: larger than the ${LIMITS[m]} MB limit for ${m} files.`);
        continue;
      }
      setUploads((u) => [...u, { name: file.name, progress: 0 }]);
      try {
        await upload(courseId, file, (f) => setUploads((u) => u.map((x) => (x.name === file.name ? { ...x, progress: f } : x))));
        setUploads((u) => u.filter((x) => x.name !== file.name));
        toast.success(`${file.name} uploaded. Processing started.`);
        qc.invalidateQueries({ queryKey: ["sources", courseId] });
        qc.invalidateQueries({ queryKey: ["jobs", courseId] });
      } catch (e) {
        setUploads((u) => u.map((x) => (x.name === file.name ? { ...x, error: errorMessage(e) } : x)));
      }
    }
  }

  const del = useMutation({
    mutationFn: (id: string) => api(`/api/sources/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      toast.success("Source removed; the knowledge model is being rebuilt.");
      qc.invalidateQueries({ queryKey: ["sources", courseId] });
      qc.invalidateQueries({ queryKey: ["jobs", courseId] });
    },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const reindex = useMutation({
    mutationFn: (id: string) => api(`/api/sources/${id}/reindex`, { method: "POST" }),
    onSuccess: () => {
      toast.success("Re-indexing queued.");
      qc.invalidateQueries({ queryKey: ["sources", courseId] });
      qc.invalidateQueries({ queryKey: ["jobs", courseId] });
    },
    onError: (e) => toast.error(errorMessage(e)),
  });

  const mode = ready.data?.checks.ai_mode;
  const topics = (graph.data?.nodes ?? []).filter((n) => n.kind === "topic");
  const rebuild = (jobs.data ?? []).find((j) => j.kind === "rebuild_knowledge" && (j.status === "queued" || j.status === "running"));

  return (
    <div className="mx-auto max-w-7xl">
      <PageHeader
        eyebrow="Course Studio"
        title={course.data?.title ?? "Course"}
        description="Upload lecture videos, textbooks and slide decks. Each file is extracted with its page, slide or timestamp preserved, indexed, and organised into concepts automatically."
      />

      <div className="grid gap-4 lg:grid-cols-[1.4fr_1fr]">
        <Card>
          <CardContent className="p-5">
            {canManage ? (
              <label
                onDragOver={(e) => {
                  e.preventDefault();
                  setDrag(true);
                }}
                onDragLeave={() => setDrag(false)}
                onDrop={(e) => {
                  e.preventDefault();
                  setDrag(false);
                  handleFiles(e.dataTransfer.files);
                }}
                className={cn(
                  "relative flex cursor-pointer flex-col items-center justify-center gap-3 overflow-hidden rounded-2xl border-2 border-dashed px-6 py-10 text-center transition-colors",
                  drag ? "border-brand bg-brand/10" : "border-line-strong hover:border-brand/50",
                )}
              >
                <div className="bg-grid pointer-events-none absolute inset-0 opacity-50" />
                <UploadCloud className="relative size-8 text-brand-soft" />
                <div className="relative">
                  <div className="font-semibold">Drop course files here or click to browse</div>
                  <div className="mt-1 text-xs text-muted">PDF and PPTX up to 60 MB · lecture video (MP4, MOV, WEBM) up to 400 MB / 90 min</div>
                </div>
                <div className="relative flex gap-2 text-subtle">
                  <FileText className="size-4" /> <Presentation className="size-4" /> <Film className="size-4" />
                </div>
                <input type="file" multiple accept={ACCEPT} className="sr-only" data-testid="file-input" onChange={(e) => e.target.files && handleFiles(e.target.files)} />
              </label>
            ) : (
              <div className="flex items-start gap-3 rounded-xl border border-line bg-surface-2/60 p-4 text-sm text-muted">
                <Lock className="mt-0.5 size-4 shrink-0" />
                You are enrolled as a student, so course materials are read-only here. Create your own course from the dashboard to upload files.
              </div>
            )}
            {uploads.length > 0 && (
              <div className="mt-4 space-y-2">
                {uploads.map((u) => (
                  <div key={u.name} className="rounded-lg border border-line bg-surface-2 p-3 text-sm">
                    <div className="mb-1.5 flex justify-between">
                      <span className="truncate">{u.name}</span>
                      <span className="font-mono text-xs text-muted">{u.error ? "failed" : `${Math.round(u.progress * 100)}% sent`}</span>
                    </div>
                    {u.error ? <p className="text-xs text-bad">{u.error}</p> : <Progress value={u.progress * 100} />}
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <ShieldCheck className="size-4 text-ok" /> Processing &amp; privacy
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-xs text-muted">
            {mode ? (
              <>
                <div className="flex justify-between"><span>Answer generation</span><Badge variant="muted">{mode.generation}</Badge></div>
                <div className="flex justify-between"><span>Speech-to-text</span><Badge variant="muted">{mode.transcription}</Badge></div>
                <div className="flex justify-between"><span>Embeddings</span><Badge variant="muted">{mode.embeddings}</Badge></div>
                <p className="pt-1">
                  {mode.external_processing
                    ? "Uploaded content is sent to the configured external AI provider for processing."
                    : "All processing runs on this server with local models; no course content is sent to an external AI provider."}
                </p>
              </>
            ) : (
              <LoadingState />
            )}
            <p>Uploaded material is treated as untrusted content: instructions inside documents never change the tutor&apos;s rules. You can delete any source at any time.</p>
          </CardContent>
        </Card>
      </div>

      <Card className="mt-4">
        <CardHeader className="flex-row items-center justify-between">
          <div>
            <CardTitle>Sources</CardTitle>
            <CardDescription>Uploaded → Extracting → Indexing → Ready (live status from the ingestion worker)</CardDescription>
          </div>
          {rebuild && (
            <Badge variant="warn">
              <Loader2 className="size-3 animate-spin" /> rebuilding knowledge model: {rebuild.stage}
            </Badge>
          )}
        </CardHeader>
        <CardContent>
          {sources.isLoading && <LoadingState />}
          {sources.isError && <ErrorState message={errorMessage(sources.error)} onRetry={() => sources.refetch()} />}
          {sources.data?.length === 0 && <EmptyState title="No sources yet">Upload a PDF, slide deck or lecture video to build this course&apos;s knowledge base.</EmptyState>}
          <div className="space-y-3">
            {sources.data?.map((s) => {
              const job = jobs.data?.find((j) => j.source_file_id === s.id);
              const counts = (s.metadata?.unit_counts ?? {}) as Record<string, number>;
              const Icon = s.modality === "pdf" ? FileText : s.modality === "pptx" ? Presentation : Film;
              return (
                <div key={s.id} className="rounded-xl border border-line bg-surface-2/50 p-4" data-testid="source-row">
                  <div className="flex flex-col gap-3 md:flex-row md:items-center">
                    <div className="flex min-w-0 flex-1 items-center gap-3">
                      <div className="rounded-lg bg-surface-3 p-2"><Icon className="size-5 text-brand-soft" /></div>
                      <div className="min-w-0">
                        <div className="truncate font-medium">{s.filename}</div>
                        <div className="text-xs text-subtle">
                          {fmtBytes(s.size_bytes)}
                          {s.page_count ? ` · ${s.page_count} pages` : ""}
                          {s.slide_count ? ` · ${s.slide_count} slides` : ""}
                          {s.duration_seconds ? ` · ${fmtTs(s.duration_seconds)}` : ""}
                        </div>
                      </div>
                    </div>
                    <StatusPipeline status={s.status} />
                    <div className="flex gap-1.5">
                      <Button variant="outline" size="sm" asChild disabled={s.status !== "ready"}>
                        <Link href={`/app/courses/${courseId}/sources/${s.id}`}><Eye /> View</Link>
                      </Button>
                      <Button variant="ghost" size="sm" onClick={() => setSelected(selected === s.id ? null : s.id)} disabled={s.status !== "ready"}>
                        Units
                      </Button>
                      {canManage && (
                        <>
                          <Button variant="ghost" size="icon" aria-label="Re-index" onClick={() => reindex.mutate(s.id)} disabled={s.status !== "ready" && s.status !== "failed"}>
                            <RefreshCw />
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon"
                            aria-label="Delete source"
                            onClick={() => window.confirm(`Delete ${s.filename} and all content extracted from it?`) && del.mutate(s.id)}
                          >
                            <Trash2 className="text-bad" />
                          </Button>
                        </>
                      )}
                    </div>
                  </div>
                  <div className="mt-3 flex flex-wrap items-center gap-1.5 text-xs">
                    {s.status === "failed" ? (
                      <span className="text-bad">{s.error ?? "Processing failed"}</span>
                    ) : s.status !== "ready" ? (
                      <div className="flex w-full items-center gap-3">
                        <span className="text-muted">{job?.stage ?? s.status_detail}</span>
                        <Progress value={(job?.progress ?? 0) * 100} className="max-w-xs" />
                      </div>
                    ) : (
                      Object.entries(counts).map(([k, v]) => (
                        <Badge key={k} variant={/figure|chart|frame|table/.test(k) ? "accent" : "muted"}>
                          {v} {k.replace("_", " ")}
                        </Badge>
                      ))
                    )}
                  </div>
                  {selected === s.id && <UnitBrowser sourceId={s.id} />}
                </div>
              );
            })}
          </div>
        </CardContent>
      </Card>

      <Card className="mt-4">
        <CardHeader className="flex-row items-center justify-between">
          <div>
            <CardTitle>Extracted topics and concepts</CardTitle>
            <CardDescription>
              {graph.data ? `${graph.data.coverage.tagged_units} of ${graph.data.coverage.units} content units are tagged to at least one concept.` : "Built automatically after ingestion."}
            </CardDescription>
          </div>
          <Button variant="outline" size="sm" asChild>
            <Link href={`/app/courses/${courseId}/knowledge`}>Open Knowledge Explorer</Link>
          </Button>
        </CardHeader>
        <CardContent>
          {topics.length === 0 ? (
            <p className="text-sm text-muted">No topics yet.</p>
          ) : (
            <div className="grid gap-3 md:grid-cols-3">
              {topics.map((t) => (
                <div key={t.concept_id} className="rounded-xl border border-line bg-surface-2/50 p-4">
                  <div className="text-xs font-semibold uppercase tracking-wider text-brand-soft">{t.name}</div>
                  <ul className="mt-2 space-y-1.5">
                    {graph.data!.nodes
                      .filter((n) => n.parent_id === t.concept_id)
                      .map((c) => (
                        <li key={c.concept_id} className="text-sm">
                          <div className="flex items-center justify-between gap-2">
                            <span>{c.name}</span>
                            <span className="font-mono text-[11px] text-subtle">{c.units} units</span>
                          </div>
                          <div className="mt-0.5 flex flex-wrap gap-1">
                            {graph.data!.nodes
                              .filter((x) => x.parent_id === c.concept_id)
                              .map((sc) => (
                                <span key={sc.concept_id} className="rounded-md bg-surface-3 px-1.5 py-0.5 text-[10px] text-muted">
                                  {sc.name}
                                </span>
                              ))}
                          </div>
                        </li>
                      ))}
                  </ul>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function StatusPipeline({ status }: { status: Source["status"] }) {
  if (status === "failed")
    return (
      <Badge variant="bad">
        <XCircle className="size-3" /> Failed
      </Badge>
    );
  const idx = STAGES.indexOf(status as (typeof STAGES)[number]);
  return (
    <ol className="flex items-center gap-1 text-[11px]" aria-label={`Status: ${status}`}>
      {STAGES.map((st, i) => (
        <li key={st} className="flex items-center gap-1">
          <span
            className={cn(
              "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 capitalize",
              i < idx ? "border-ok/40 text-ok" : i === idx ? (st === "ready" ? "border-ok/50 bg-ok/10 text-ok" : "border-brand/50 bg-brand/15 text-brand-soft") : "border-line text-subtle",
            )}
          >
            {i === idx && st !== "ready" && <Loader2 className="size-3 animate-spin" />}
            {st === "ready" && i === idx && <CheckCircle2 className="size-3" />}
            {st}
          </span>
          {i < STAGES.length - 1 && <span className="h-px w-2 bg-line-strong" />}
        </li>
      ))}
    </ol>
  );
}

function UnitBrowser({ sourceId }: { sourceId: string }) {
  const q = useQuery({ queryKey: ["units", sourceId], queryFn: () => api<{ units: Unit[] }>(`/api/sources/${sourceId}/units`) });
  const [filter, setFilter] = React.useState<string>("all");
  if (q.isLoading) return <LoadingState />;
  if (q.isError) return <ErrorState message={errorMessage(q.error)} />;
  const units = q.data!.units;
  const kinds = Array.from(new Set(units.map((u) => u.modality)));
  const shown = filter === "all" ? units : units.filter((u) => u.modality === filter);
  return (
    <div className="mt-4 space-y-3 border-t border-line pt-4">
      <div className="flex flex-wrap gap-1.5">
        {["all", ...kinds].map((k) => (
          <button key={k} onClick={() => setFilter(k)} className={cn("rounded-full border px-2.5 py-0.5 text-xs", filter === k ? "border-brand bg-brand/15 text-brand-soft" : "border-line-strong text-muted")}>
            {k.replace("_", " ")} {k === "all" ? units.length : units.filter((u) => u.modality === k).length}
          </button>
        ))}
      </div>
      <div className="max-h-[480px] space-y-2 overflow-y-auto pr-1">
        {shown.map((u) => (
          <div key={u.id} className="rounded-lg border border-line bg-surface p-3 text-sm">
            <div className="mb-1.5 flex flex-wrap items-center gap-1.5">
              <Badge variant="accent">{u.anchor}</Badge>
              <Badge variant="muted">{u.modality.replace("_", " ")}</Badge>
              {u.is_generated && (
                <Badge variant="warn">
                  <Sparkles className="size-3" /> model-generated
                </Badge>
              )}
              {u.heading && <span className="truncate text-xs text-subtle">{u.heading}</span>}
            </div>
            <div className="flex gap-3">
              {u.image_url && (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={mediaUrl(u.image_url)} alt={`Figure at ${u.anchor}`} className="h-20 w-32 shrink-0 rounded-md border border-line object-contain bg-white/90" />
              )}
              <p className="line-clamp-4 whitespace-pre-line text-xs text-muted">{u.content}</p>
            </div>
            {u.concepts && u.concepts.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1">
                {u.concepts.map((c) => (
                  <span key={c.concept_id} className={cn("rounded-md px-1.5 py-0.5 text-[10px]", c.primary ? "bg-brand/20 text-brand-soft" : "bg-surface-3 text-muted")}>
                    {c.name}
                  </span>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
