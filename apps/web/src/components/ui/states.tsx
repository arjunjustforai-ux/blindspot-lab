import { AlertTriangle, Inbox, Loader2, RotateCcw } from "lucide-react";
import * as React from "react";
import { Button } from "./button";

export function LoadingState({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-2 py-16 text-sm text-muted" role="status">
      <Loader2 className="size-4 animate-spin" /> {label}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded-2xl border border-bad/30 bg-bad/5 px-6 py-10 text-center" role="alert">
      <AlertTriangle className="size-6 text-bad" />
      <p className="max-w-md text-sm text-fg">{message}</p>
      {onRetry && (
        <Button variant="outline" size="sm" onClick={onRetry}>
          <RotateCcw /> Retry
        </Button>
      )}
    </div>
  );
}

export function EmptyState({ icon, title, children, action }: { icon?: React.ReactNode; title: string; children?: React.ReactNode; action?: React.ReactNode }) {
  return (
    <div className="relative flex flex-col items-center justify-center gap-3 overflow-hidden rounded-2xl border border-dashed border-line-strong px-6 py-12 text-center">
      <div className="bg-grid pointer-events-none absolute inset-0 opacity-60" />
      <div className="relative rounded-full border border-line-strong bg-surface-2 p-3 text-muted">{icon ?? <Inbox className="size-5" />}</div>
      <h3 className="relative text-sm font-semibold">{title}</h3>
      {children && <div className="relative max-w-md text-sm text-muted">{children}</div>}
      {action && <div className="relative">{action}</div>}
    </div>
  );
}
