"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Background, Controls, Handle, MarkerType, Position, ReactFlow, type Edge, type Node, type NodeProps } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { Check, GitBranch, Link2, ListChecks, Plus, X } from "lucide-react";
import * as React from "react";
import { toast } from "sonner";
import { CitationChip } from "@/components/learning/citations";
import { MasteryBadge, MasteryBar } from "@/components/learning/mastery";
import { PageHeader } from "@/components/shell/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/states";
import { api, errorMessage } from "@/lib/api";
import { useCourse, useCourseId } from "@/lib/hooks";
import type { Citation, GraphEdge, GraphNode, MasteryView, Unit } from "@/lib/types";
import { cn, difficultyLabel, masteryColor, pct } from "@/lib/utils";

interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
  coverage: { units: number; tagged_units: number };
  knowledge_status: string;
}

interface ConceptDetail {
  id: string;
  name: string;
  kind: string;
  description: string | null;
  origin: string;
  review_status: string;
  aliases: string[];
  parent: { id: string; name: string } | null;
  children: { id: string; name: string; kind: string }[];
  mastery: MasteryView;
  prerequisites: (GraphEdge & { name: string })[];
  unlocks: (GraphEdge & { name: string })[];
  sources: (Unit & { relevance: number; primary: boolean; method: string })[];
  questions: { id: string; stem: string; question_type: string; difficulty: number; origin: string; template_key: string | null; purpose: string; sources: number }[];
  misconceptions: { key: string; title: string; active: boolean; reason: string }[];
}

type ConceptNodeData = { node: GraphNode; subs: GraphNode[]; selected: boolean };

function ConceptNode({ data }: NodeProps<Node<ConceptNodeData>>) {
  const n = data.node;
  const color = masteryColor(n.label);
  return (
    <div className={cn("w-[230px] rounded-2xl border bg-surface px-3.5 py-3 shadow-xl transition-shadow", data.selected ? "border-brand shadow-[0_0_0_2px_rgb(99_102_241/0.5)]" : "border-line-strong")}>
      <Handle type="target" position={Position.Left} className="!size-2 !border-0 !bg-line-strong" />
      <div className="flex items-start justify-between gap-2">
        <div className="text-[13px] font-semibold leading-tight text-fg">{n.name}</div>
        <span className="mt-0.5 size-2.5 shrink-0 rounded-full" style={{ background: color }} />
      </div>
      <div className="mt-2">
        <MasteryBar m={n} />
      </div>
      <div className="mt-2 flex gap-2 text-[10px] text-subtle">
        <span>{n.units} units</span>
        <span>{n.questions} verified Qs</span>
      </div>
      {data.subs.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {data.subs.slice(0, 4).map((s) => (
            <span key={s.concept_id} className="rounded bg-surface-3 px-1.5 py-0.5 text-[9px] text-muted">
              {s.name}
            </span>
          ))}
        </div>
      )}
      <Handle type="source" position={Position.Right} className="!size-2 !border-0 !bg-brand" />
    </div>
  );
}
const nodeTypes = { concept: ConceptNode };

function layout(nodes: GraphNode[], edges: GraphEdge[]) {
  const concepts = nodes.filter((n) => n.kind === "concept");
  const ids = new Set(concepts.map((c) => c.concept_id));
  const pre: Record<string, string[]> = {};
  edges.filter((e) => e.review_status !== "rejected" && ids.has(e.concept_id) && ids.has(e.prerequisite_id)).forEach((e) => (pre[e.concept_id] ??= []).push(e.prerequisite_id));
  const depth: Record<string, number> = {};
  const d = (id: string, seen = new Set<string>()): number => {
    if (depth[id] !== undefined) return depth[id];
    if (seen.has(id)) return 0;
    seen.add(id);
    depth[id] = Math.max(0, ...(pre[id] ?? []).map((p) => d(p, seen) + 1));
    return depth[id];
  };
  concepts.forEach((c) => d(c.concept_id));
  const cols: Record<number, GraphNode[]> = {};
  concepts.sort((a, b) => a.order_index - b.order_index).forEach((c) => (cols[depth[c.concept_id]] ??= []).push(c));
  const pos: Record<string, { x: number; y: number }> = {};
  Object.entries(cols).forEach(([col, list]) => list.forEach((c, i) => (pos[c.concept_id] = { x: Number(col) * 300, y: i * 175 + (Number(col) % 2) * 60 })));
  return pos;
}

export default function KnowledgePage() {
  const courseId = useCourseId()!;
  const course = useCourse(courseId);
  const g = useQuery({ queryKey: ["graph", courseId], queryFn: () => api<GraphData>(`/api/courses/${courseId}/graph`) });
  const [sel, setSel] = React.useState<string | null>(null);
  const canManage = course.data?.role === "owner" || course.data?.role === "instructor";

  const flow = React.useMemo(() => {
    if (!g.data) return { nodes: [] as Node<ConceptNodeData>[], edges: [] as Edge[] };
    const pos = layout(g.data.nodes, g.data.edges);
    const nodes: Node<ConceptNodeData>[] = g.data.nodes
      .filter((n) => n.kind === "concept")
      .map((n) => ({
        id: n.concept_id,
        type: "concept",
        position: pos[n.concept_id] ?? { x: 0, y: 0 },
        data: { node: n, subs: g.data!.nodes.filter((s) => s.parent_id === n.concept_id), selected: sel === n.concept_id },
      }));
    const edges: Edge[] = g.data.edges
      .filter((e) => e.review_status !== "rejected")
      .map((e) => ({
        id: e.id,
        source: e.prerequisite_id,
        target: e.concept_id,
        animated: e.origin === "instructor",
        markerEnd: { type: MarkerType.ArrowClosed, color: "#818cf8" },
        style: { stroke: e.origin === "catalog" ? "#818cf8" : e.origin === "instructor" ? "#34d399" : "#64708a", strokeWidth: 1.6, strokeDasharray: e.review_status === "proposed" && e.origin !== "catalog" ? "5 4" : undefined },
      }));
    return { nodes, edges };
  }, [g.data, sel]);

  if (g.isLoading) return <LoadingState />;
  if (g.isError) return <ErrorState message={errorMessage(g.error)} onRetry={() => g.refetch()} />;
  const data = g.data!;
  const topics = data.nodes.filter((n) => n.kind === "topic");

  return (
    <div className="mx-auto max-w-[1500px]">
      <PageHeader
        eyebrow="Knowledge Explorer"
        title="Concepts and prerequisites"
        description={`Built automatically from your sources: ${topics.length} topics, ${data.nodes.filter((n) => n.kind === "concept").length} concepts, ${data.nodes.filter((n) => n.kind === "subconcept").length} sub-concepts. ${data.coverage.tagged_units}/${data.coverage.units} content units tagged. Arrows point from a prerequisite to the concept that builds on it.`}
      />
      {flow.nodes.length === 0 ? (
        <EmptyState title="No concepts yet">Upload sources in the Course Studio; the knowledge model is built after ingestion.</EmptyState>
      ) : (
        <div className="grid gap-4 xl:grid-cols-[1fr_420px]">
          <Card className="overflow-hidden">
            <div className="h-[640px]" data-testid="concept-graph">
              <ReactFlow
                nodes={flow.nodes}
                edges={flow.edges}
                nodeTypes={nodeTypes}
                fitView
                fitViewOptions={{ padding: 0.2 }}
                proOptions={{ hideAttribution: true }}
                nodesDraggable
                onNodeClick={(_, n) => setSel(n.id)}
                colorMode="dark"
              >
                <Background color="#1d2a44" gap={22} />
                <Controls showInteractive={false} />
              </ReactFlow>
            </div>
            <div className="flex flex-wrap items-center gap-4 border-t border-line px-4 py-3 text-[11px] text-muted">
              {["unassessed", "emerging", "developing", "proficient", "mastered"].map((l) => (
                <span key={l} className="flex items-center gap-1.5 capitalize">
                  <span className="size-2.5 rounded-full" style={{ background: masteryColor(l) }} /> {l}
                </span>
              ))}
              <span className="flex items-center gap-1.5"><span className="h-0.5 w-5 bg-[#818cf8]" /> catalogue edge</span>
              <span className="flex items-center gap-1.5"><span className="h-0.5 w-5 bg-[#34d399]" /> instructor edge</span>
              <span className="flex items-center gap-1.5"><span className="h-0.5 w-5 border-t border-dashed border-[#64708a]" /> proposed (heuristic)</span>
            </div>
          </Card>
          <div className="space-y-4">
            {sel ? (
              <ConceptDrawer id={sel} courseId={courseId} concepts={data.nodes.filter((n) => n.kind === "concept")} canManage={canManage} onClose={() => setSel(null)} />
            ) : (
              <Card>
                <CardHeader>
                  <CardTitle>Topics</CardTitle>
                  <CardDescription>Select a concept in the map to see its explanation, sources, prerequisites, questions and your mastery.</CardDescription>
                </CardHeader>
                <CardContent className="space-y-3">
                  {topics.map((t) => (
                    <div key={t.concept_id}>
                      <div className="text-xs font-semibold uppercase tracking-wider text-brand-soft">{t.name}</div>
                      <div className="mt-1 flex flex-wrap gap-1.5">
                        {data.nodes
                          .filter((n) => n.parent_id === t.concept_id)
                          .map((c) => (
                            <button key={c.concept_id} onClick={() => setSel(c.concept_id)} className="rounded-lg border border-line-strong px-2 py-1 text-xs hover:border-brand/50">
                              {c.name}
                            </button>
                          ))}
                      </div>
                    </div>
                  ))}
                </CardContent>
              </Card>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function ConceptDrawer({ id, courseId, concepts, canManage, onClose }: { id: string; courseId: string; concepts: GraphNode[]; canManage: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["concept", id], queryFn: () => api<ConceptDetail>(`/api/concepts/${id}`) });
  const [addPre, setAddPre] = React.useState("");
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["concept", id] });
    qc.invalidateQueries({ queryKey: ["graph", courseId] });
  };
  const add = useMutation({
    mutationFn: () => api(`/api/courses/${courseId}/prerequisites`, { method: "POST", body: { concept_id: id, prerequisite_id: addPre } }),
    onSuccess: () => {
      setAddPre("");
      toast.success("Prerequisite added");
      refresh();
    },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const review = useMutation({
    mutationFn: (p: { edge: string; status: string }) => api(`/api/prerequisites/${p.edge}`, { method: "PATCH", body: { review_status: p.status } }),
    onSuccess: refresh,
    onError: (e) => toast.error(errorMessage(e)),
  });
  if (q.isLoading) return <LoadingState />;
  if (q.isError) return <ErrorState message={errorMessage(q.error)} />;
  const c = q.data!;
  return (
    <Card data-testid="concept-drawer">
      <CardHeader>
        <div className="flex items-start justify-between gap-2">
          <div>
            {c.parent && <div className="text-[11px] uppercase tracking-wider text-subtle">{c.parent.name}</div>}
            <CardTitle className="text-base">{c.name}</CardTitle>
          </div>
          <button onClick={onClose} aria-label="Close" className="rounded p-1 text-subtle hover:bg-surface-3">
            <X className="size-4" />
          </button>
        </div>
        <div className="flex flex-wrap gap-1.5">
          <Badge variant="muted">origin: {c.origin}</Badge>
          <Badge variant={c.review_status === "approved" ? "ok" : "muted"}>{c.review_status}</Badge>
        </div>
      </CardHeader>
      <CardContent className="max-h-[70vh] space-y-5 overflow-y-auto">
        {c.description && <p className="text-sm leading-relaxed text-muted">{c.description}</p>}
        <div className="space-y-1.5 rounded-xl border border-line bg-surface-2/60 p-3">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium">Your mastery estimate</span>
            <MasteryBadge label={c.mastery.label} quality={c.mastery.evidence_quality} />
          </div>
          <MasteryBar m={c.mastery} />
          <div className="text-[11px] text-subtle">
            {c.mastery.n_observations ? `${c.mastery.n_correct}/${c.mastery.n_observations} correct · ${c.mastery.distinct_questions} distinct questions · effective evidence ${c.mastery.effective_evidence.toFixed(1)}` : "Unassessed: no scored evidence yet."}
          </div>
        </div>
        {c.children.length > 0 && (
          <Section title="Sub-concepts" icon={<ListChecks className="size-3.5" />}>
            <div className="flex flex-wrap gap-1.5">
              {c.children.map((ch) => (
                <span key={ch.id} className="rounded-md bg-surface-3 px-2 py-0.5 text-xs text-muted">
                  {ch.name}
                </span>
              ))}
            </div>
          </Section>
        )}
        <Section title="Prerequisites" icon={<GitBranch className="size-3.5" />}>
          {c.prerequisites.length === 0 && <p className="text-xs text-muted">None. This is a starting point.</p>}
          {c.prerequisites.map((e) => (
            <div key={e.id} className={cn("rounded-lg border border-line p-2 text-xs", e.review_status === "rejected" && "opacity-50")}>
              <div className="flex items-center justify-between gap-2">
                <span className="font-medium">{e.name}</span>
                <span className="text-subtle">
                  {e.origin} · {pct(e.confidence)} · {e.review_status}
                </span>
              </div>
              {e.rationale && <p className="mt-0.5 text-subtle">{e.rationale}</p>}
              {canManage && (
                <div className="mt-1.5 flex gap-1">
                  <Button size="sm" variant="ghost" onClick={() => review.mutate({ edge: e.id, status: "approved" })}>
                    <Check /> Approve
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => review.mutate({ edge: e.id, status: "rejected" })}>
                    <X /> Reject
                  </Button>
                </div>
              )}
            </div>
          ))}
          {canManage && (
            <div className="flex gap-2 pt-1">
              <select value={addPre} onChange={(e) => setAddPre(e.target.value)} aria-label="Add prerequisite" className="flex-1 rounded-lg border border-line-strong bg-surface-2 px-2 text-xs">
                <option value="">Add a prerequisite…</option>
                {concepts
                  .filter((x) => x.concept_id !== id)
                  .map((x) => (
                    <option key={x.concept_id} value={x.concept_id}>
                      {x.name}
                    </option>
                  ))}
              </select>
              <Button size="sm" variant="outline" disabled={!addPre || add.isPending} onClick={() => add.mutate()}>
                <Plus /> Add
              </Button>
            </div>
          )}
          {c.unlocks.length > 0 && <p className="text-xs text-subtle">Unlocks: {c.unlocks.map((u) => u.name).join(", ")}</p>}
        </Section>
        <Section title="Source material" icon={<Link2 className="size-3.5" />}>
          {c.sources.map((u) => {
            const cite: Citation = {
              id: u.primary ? "★" : "·",
              unit_id: u.id,
              source_id: u.source_id,
              course_id: courseId,
              filename: u.filename,
              source_modality: u.filename.endsWith(".pdf") ? "pdf" : u.filename.endsWith(".pptx") ? "pptx" : "video",
              unit_modality: u.modality,
              page: u.page,
              slide: u.slide,
              start: u.start,
              end: u.end,
              label: `${u.filename} — ${u.anchor}`,
              heading: u.heading,
              excerpt: u.content,
              is_generated: u.is_generated,
              has_image: !!u.image_url,
              support: u.relevance,
              link: `/app/courses/${courseId}/sources/${u.source_id}?${u.page ? `page=${u.page}&` : ""}${u.slide ? `slide=${u.slide}&` : ""}${u.start !== null && !u.page && !u.slide ? `t=${u.start}&` : ""}unit=${u.id}`,
            };
            return (
              <div key={u.id} className="space-y-1 rounded-lg border border-line bg-surface-2/40 p-2">
                <CitationChip c={cite} />
                <p className="line-clamp-2 text-[11px] text-muted">{u.content}</p>
              </div>
            );
          })}
        </Section>
        <Section title={`Verified questions (${c.questions.length})`} icon={<ListChecks className="size-3.5" />}>
          {c.questions.slice(0, 8).map((qq) => (
            <div key={qq.id} className="rounded-lg border border-line p-2 text-xs">
              <div className="mb-1 flex flex-wrap gap-1">
                <Badge variant="muted">{qq.question_type}</Badge>
                <Badge variant="muted">{difficultyLabel(qq.difficulty)}</Badge>
                <Badge variant="muted">{qq.origin}</Badge>
                {qq.purpose === "heldout" && <Badge variant="warn">held-out (evaluation only)</Badge>}
              </div>
              <p className="line-clamp-2 text-muted">{qq.stem}</p>
            </div>
          ))}
        </Section>
        {c.misconceptions.length > 0 && (
          <Section title="Misconceptions mapped to this concept">
            {c.misconceptions.map((m) => (
              <div key={m.key} className="text-xs">
                <span className={m.active ? "text-warn" : "text-subtle"}>{m.title}</span> <span className="text-subtle">· {m.active ? "active" : "inactive"}</span>
              </div>
            ))}
          </Section>
        )}
      </CardContent>
    </Card>
  );
}

function Section({ title, icon, children }: { title: string; icon?: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-subtle">
        {icon} {title}
      </div>
      {children}
    </div>
  );
}
