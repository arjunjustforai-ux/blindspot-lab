"use client";

import * as React from "react";
import { MobileTopbar, Sidebar } from "@/components/shell/sidebar";
import { LoadingState } from "@/components/ui/states";
import { useRequireAuth } from "@/lib/auth";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const { user, ready } = useRequireAuth();
  const [open, setOpen] = React.useState(false);
  if (!ready || !user) return <LoadingState label="Checking your session…" />;
  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[260px_1fr]">
      <div className="hidden border-r border-line bg-surface/60 lg:block">
        <aside className="sticky top-0 h-screen">
          <Sidebar />
        </aside>
      </div>
      <MobileTopbar onMenu={() => setOpen(true)} />
      {open && (
        <div className="fixed inset-0 z-40 lg:hidden" role="dialog" aria-modal>
          <div className="absolute inset-0 bg-black/60" onClick={() => setOpen(false)} />
          <div className="absolute inset-y-0 left-0 w-72 border-r border-line bg-surface">
            <Sidebar onNavigate={() => setOpen(false)} />
          </div>
        </div>
      )}
      <main className="min-w-0 px-4 py-6 sm:px-8 lg:py-8">{children}</main>
    </div>
  );
}
