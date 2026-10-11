"use client";

import {
  BarChart3,
  BookOpenCheck,
  Brain,
  FlaskConical,
  GaugeCircle,
  LayoutDashboard,
  LogOut,
  MessagesSquare,
  Network,
  ScanSearch,
  UploadCloud,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import * as React from "react";
import { Badge } from "@/components/ui/badge";
import { useAuth } from "@/lib/auth";
import { lastCourse, rememberCourse, useCourseId, useCourses } from "@/lib/hooks";
import { cn } from "@/lib/utils";
import { Logo } from "./logo";

const COURSE_NAV = [
  { href: "studio", label: "Course Studio", icon: UploadCloud },
  { href: "knowledge", label: "Knowledge Explorer", icon: Network },
  { href: "tutor", label: "Grounded Tutor", icon: MessagesSquare },
  { href: "lab", label: "Blindspot Lab", icon: ScanSearch, highlight: true },
  { href: "assess", label: "Adaptive Assessment", icon: BookOpenCheck },
  { href: "progress", label: "Mastery & Progress", icon: BarChart3 },
];

export function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  const router = useRouter();
  const { user, logout } = useAuth();
  const courses = useCourses(!!user);
  const routeCourse = useCourseId();
  const [selected, setSelected] = React.useState<string | undefined>(routeCourse);

  React.useEffect(() => {
    if (routeCourse) {
      setSelected(routeCourse);
      rememberCourse(routeCourse);
    } else if (!selected && courses.data?.length) {
      const last = lastCourse();
      setSelected(courses.data.find((c) => c.id === last)?.id ?? courses.data[0].id);
    }
  }, [routeCourse, courses.data, selected]);

  const course = courses.data?.find((c) => c.id === selected);
  const link = (href: string) => (selected ? `/app/courses/${selected}/${href}` : "/app");

  return (
    <nav className="flex h-full flex-col gap-6 p-4" aria-label="Main">
      <Link href="/app" onClick={onNavigate} className="px-2 pt-1">
        <Logo />
      </Link>

      <div className="space-y-1">
        <NavItem href="/app" active={pathname === "/app"} icon={LayoutDashboard} label="Learning Dashboard" onClick={onNavigate} />
      </div>

      <div className="space-y-2">
        <label htmlFor="course-switch" className="px-2 text-[11px] font-semibold uppercase tracking-wider text-subtle">
          Course
        </label>
        <select
          id="course-switch"
          value={selected ?? ""}
          onChange={(e) => {
            setSelected(e.target.value);
            rememberCourse(e.target.value);
            const section = pathname.split("/")[4];
            router.push(`/app/courses/${e.target.value}/${section ?? "knowledge"}`);
            onNavigate?.();
          }}
          className="w-full rounded-lg border border-line-strong bg-surface-2 px-2.5 py-2 text-xs text-fg focus:outline-none focus:ring-2 focus:ring-brand/60"
        >
          {!courses.data?.length && <option value="">No courses yet</option>}
          {courses.data?.map((c) => (
            <option key={c.id} value={c.id}>
              {c.is_demo ? "★ " : ""}
              {c.title}
            </option>
          ))}
        </select>
        {course && (
          <div className="flex flex-wrap gap-1 px-1">
            {course.is_demo && <Badge variant="accent">Demo course</Badge>}
            <Badge variant="muted">{course.role}</Badge>
          </div>
        )}
        <div className="space-y-1 pt-1">
          {COURSE_NAV.map((n) => (
            <NavItem
              key={n.href}
              href={link(n.href)}
              active={pathname.includes(`/${n.href}`)}
              icon={n.icon}
              label={n.label}
              highlight={n.highlight}
              disabled={!selected}
              onClick={onNavigate}
            />
          ))}
        </div>
      </div>

      <div className="space-y-1">
        <div className="px-2 text-[11px] font-semibold uppercase tracking-wider text-subtle">Evidence</div>
        <NavItem href="/app/evaluation" active={pathname.startsWith("/app/evaluation")} icon={FlaskConical} label="Evaluation Lab" onClick={onNavigate} />
      </div>

      <div className="mt-auto space-y-3">
        <div className="rounded-xl border border-line bg-surface-2/60 p-3">
          <div className="flex items-center gap-2">
            <div className="flex size-8 items-center justify-center rounded-full bg-gradient-to-br from-brand to-accent text-xs font-bold text-white">
              {user?.display_name?.[0] ?? "?"}
            </div>
            <div className="min-w-0">
              <div className="truncate text-xs font-medium">{user?.display_name}</div>
              <div className="truncate text-[11px] text-subtle">{user?.is_demo ? "Synthetic demo learner" : user?.email}</div>
            </div>
          </div>
        </div>
        <button
          onClick={() => {
            logout();
            router.push("/");
          }}
          className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-xs text-muted hover:bg-surface-3 hover:text-fg"
        >
          <LogOut className="size-3.5" /> Sign out
        </button>
      </div>
    </nav>
  );
}

function NavItem({
  href,
  active,
  icon: Icon,
  label,
  highlight,
  disabled,
  onClick,
}: {
  href: string;
  active: boolean;
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  highlight?: boolean;
  disabled?: boolean;
  onClick?: () => void;
}) {
  return (
    <Link
      href={disabled ? "#" : href}
      onClick={onClick}
      aria-current={active ? "page" : undefined}
      aria-disabled={disabled}
      className={cn(
        "group flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-[13px] transition-colors",
        active ? "bg-surface-3 text-fg shadow-[inset_2px_0_0_0_var(--color-brand)]" : "text-muted hover:bg-surface-2 hover:text-fg",
        disabled && "pointer-events-none opacity-40",
      )}
    >
      <Icon className={cn("size-4", highlight ? "text-warn" : active ? "text-brand-soft" : "text-subtle group-hover:text-muted")} />
      <span className="flex-1">{label}</span>
      {highlight && <Brain className="size-3.5 text-warn/70" />}
    </Link>
  );
}

export function MobileTopbar({ onMenu }: { onMenu: () => void }) {
  return (
    <div className="sticky top-0 z-30 flex items-center justify-between border-b border-line bg-bg/90 px-4 py-3 backdrop-blur lg:hidden">
      <Logo />
      <button onClick={onMenu} className="rounded-lg border border-line-strong p-2 text-muted" aria-label="Open navigation">
        <GaugeCircle className="size-4" />
      </button>
    </div>
  );
}
