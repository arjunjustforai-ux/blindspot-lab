"use client";

import {
  ArrowRight,
  BookOpenCheck,
  Brain,
  CheckCircle2,
  FileText,
  Film,
  FlaskConical,
  HelpCircle,
  Lightbulb,
  Microscope,
  Presentation,
  Repeat,
  ScanSearch,
  Shuffle,
  Sparkles,
  TrendingUp,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import * as React from "react";
import { toast } from "sonner";
import { Logo } from "@/components/shell/logo";
import { Button } from "@/components/ui/button";
import { errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";

const LOOP = [
  { icon: BookOpenCheck, title: "Learn", text: "Lectures, textbooks and slides become one source-linked knowledge base." },
  { icon: HelpCircle, title: "Diagnose", text: "Answer a realistic problem and explain your reasoning." },
  { icon: Microscope, title: "Investigate", text: "A wrong answer opens competing hypotheses, not a verdict." },
  { icon: Shuffle, title: "Probe", text: "One discriminating follow-up question separates a slip from a misconception." },
  { icon: Lightbulb, title: "Explain", text: "A contrastive explanation cites the exact page, slide or timestamp." },
  { icon: Repeat, title: "Repair", text: "Targeted practice on the precise distinction you missed." },
  { icon: Shuffle, title: "Transfer", text: "A structurally different problem tests whether understanding moved." },
  { icon: TrendingUp, title: "Update & revisit", text: "Bayesian mastery updates, then a scheduled revisit later." },
];

export default function Landing() {
  const { user, demo } = useAuth();
  const router = useRouter();
  const [busy, setBusy] = React.useState(false);

  async function startDemo() {
    setBusy(true);
    try {
      if (!user) await demo();
      router.push("/app");
    } catch (e) {
      toast.error(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="relative overflow-hidden">
      <div className="glow-indigo pointer-events-none absolute inset-0" />
      <div className="bg-grid pointer-events-none absolute inset-x-0 top-0 h-[720px] opacity-70" />

      <header className="relative mx-auto flex max-w-6xl items-center justify-between px-5 py-5">
        <Logo />
        <div className="flex items-center gap-2">
          <Link href="/login" className="rounded-lg px-3 py-2 text-sm text-muted hover:text-fg">
            Sign in
          </Link>
          <Button size="sm" onClick={startDemo} disabled={busy}>
            {user ? "Open app" : "Try the live demo"}
          </Button>
        </div>
      </header>

      <section className="relative mx-auto grid max-w-6xl items-center gap-12 px-5 pb-20 pt-10 lg:grid-cols-[1.1fr_1fr] lg:pt-16">
        <div>
          <div className="mb-5 inline-flex items-center gap-2 rounded-full border border-line-strong bg-surface/70 px-3 py-1 text-xs text-muted">
            <Sparkles className="size-3.5 text-warn" /> Understand what you don&apos;t understand
          </div>
          <h1 className="text-4xl font-semibold leading-[1.08] tracking-tight sm:text-6xl">
            You don&apos;t know what you don&apos;t know.
            <br />
            <span className="text-gradient">Until now.</span>
          </h1>
          <p className="mt-6 max-w-xl text-lg leading-relaxed text-muted">
            Turn lectures, textbooks and slides into a learning experience that uncovers misconceptions and helps you prove real understanding.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <Button size="lg" onClick={startDemo} disabled={busy} data-testid="start-demo">
              Explore the demo course <ArrowRight />
            </Button>
            <Button size="lg" variant="outline" asChild>
              <Link href="/login?mode=register">Create an account</Link>
            </Button>
          </div>
          <p className="mt-4 text-xs text-subtle">
            Demo access creates a fresh, clearly labelled synthetic learner. The demo course is original material with fictional figures.
          </p>
        </div>

        <LoopPreview />
      </section>

      <section className="relative mx-auto max-w-6xl px-5 pb-20">
        <div className="mb-8 max-w-2xl">
          <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-brand-soft">The Blindspot loop</div>
          <h2 className="mt-2 text-3xl font-semibold tracking-tight">Right answers are not the goal. Understanding is.</h2>
          <p className="mt-3 text-muted">
            A learner can recall a formula and still apply it to the wrong quantity. Blindspot Lab separates correct reasoning from lucky answers, slips from misconceptions, and repair from repetition.
          </p>
        </div>
        <ol className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {LOOP.map((s, i) => (
            <li key={s.title} className="group relative rounded-2xl border border-line bg-surface/80 p-4 transition-colors hover:border-brand/40">
              <div className="mb-3 flex items-center justify-between">
                <s.icon className="size-5 text-brand-soft" />
                <span className="font-mono text-xs text-subtle">{String(i + 1).padStart(2, "0")}</span>
              </div>
              <div className="font-semibold">{s.title}</div>
              <p className="mt-1 text-sm text-muted">{s.text}</p>
            </li>
          ))}
        </ol>
      </section>

      <section className="relative mx-auto max-w-6xl px-5 pb-24">
        <div className="grid gap-4 md:grid-cols-3">
          <Feature
            icon={<div className="flex gap-1"><FileText className="size-5" /><Presentation className="size-5" /><Film className="size-5" /></div>}
            title="Every claim opens its source"
            text="Answers cite the exact PDF page, slide or lecture timestamp. Unsupported questions are declined, and outside knowledge only appears in a separately labelled mode."
          />
          <Feature
            icon={<CheckCircle2 className="size-5" />}
            title="Questions are verified before you see them"
            text="Computed answers pass independent plug-back checks, every question must be supported by your sources, and near-duplicates are blocked."
          />
          <Feature
            icon={<Brain className="size-5" />}
            title="A learner model you can inspect"
            text="Bayesian Knowledge Tracing per concept, with evidence weighting so repeated paraphrases can't inflate mastery, and every update is traceable."
          />
        </div>
        <div className="mt-6 flex flex-col items-start justify-between gap-4 rounded-2xl border border-line bg-surface/80 p-6 sm:flex-row sm:items-center">
          <div className="flex items-start gap-3">
            <FlaskConical className="mt-0.5 size-5 text-accent" />
            <div>
              <div className="font-semibold">Measured, not claimed</div>
              <p className="text-sm text-muted">The Evaluation Lab shows recorded benchmark runs (RAGAS context metrics, citation accuracy, refusal accuracy, verifier checks and simulated-learner comparisons) with their limitations.</p>
            </div>
          </div>
          <Button variant="outline" onClick={startDemo} disabled={busy}>
            <ScanSearch /> See it working
          </Button>
        </div>
      </section>

      <footer className="relative border-t border-line">
        <div className="mx-auto flex max-w-6xl flex-col gap-2 px-5 py-6 text-xs text-subtle sm:flex-row sm:justify-between">
          <span>Blindspot Lab · Multimodal AI Hackathon 2026 · Track D</span>
          <span>Misconception labels are evidence-backed hypotheses, not psychological diagnoses.</span>
        </div>
      </footer>
    </div>
  );
}

function Feature({ icon, title, text }: { icon: React.ReactNode; title: string; text: string }) {
  return (
    <div className="rounded-2xl border border-line bg-surface/80 p-5">
      <div className="mb-3 text-accent">{icon}</div>
      <div className="font-semibold">{title}</div>
      <p className="mt-1.5 text-sm leading-relaxed text-muted">{text}</p>
    </div>
  );
}

function LoopPreview() {
  return (
    <div className="relative">
      <div className="absolute -inset-4 rounded-[2rem] bg-gradient-to-br from-brand/20 via-transparent to-accent/10 blur-2xl" />
      <div className="relative space-y-3 rounded-3xl border border-line-strong bg-surface/90 p-5 shadow-2xl">
        <div className="flex items-center justify-between text-[11px] uppercase tracking-wider text-subtle">
          <span>Illustration of a Blindspot investigation</span>
          <span className="rounded-full border border-line-strong px-2 py-0.5 normal-case tracking-normal">walkthrough</span>
        </div>
        <div className="rounded-xl border border-line bg-surface-2 p-3 text-sm">
          Price ₹100 → ₹80, variable cost ₹60. What volume increase preserves total contribution?
          <div className="mt-2 flex items-center gap-2 text-xs">
            <span className="rounded-md bg-bad/15 px-2 py-0.5 font-mono text-bad">25%</span>
            <span className="text-muted">“compensates for the price reduction”</span>
          </div>
        </div>
        <div className="rounded-xl border border-warn/40 bg-warn/10 p-3 text-sm">
          <div className="font-semibold text-warn">Hypothesis · preserving revenue instead of contribution</div>
          <div className="mt-1 text-xs text-muted">Competing: arithmetic slip · misread target · missing prerequisite</div>
        </div>
        <div className="rounded-xl border border-brand/40 bg-brand/10 p-3 text-sm">
          <div className="font-semibold text-brand-soft">Probe</div>
          <div className="text-xs text-muted">Which quantity were you trying to keep the same: revenue, or contribution after variable costs?</div>
        </div>
        <div className="rounded-xl border border-ok/40 bg-ok/10 p-3 text-sm">
          <div className="font-semibold text-ok">Repair → transfer</div>
          <div className="text-xs text-muted">₹40 → ₹20 contribution per unit, so volume must double (+100%). Next: a price increase with a different structure.</div>
        </div>
      </div>
    </div>
  );
}
