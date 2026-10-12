import { cva, type VariantProps } from "class-variance-authority";
import * as React from "react";
import { cn } from "@/lib/utils";

const badgeVariants = cva("inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium leading-4", {
  variants: {
    variant: {
      default: "border-brand/40 bg-brand/15 text-brand-soft",
      accent: "border-accent/40 bg-accent/10 text-accent",
      ok: "border-ok/40 bg-ok/10 text-ok",
      warn: "border-warn/40 bg-warn/10 text-warn",
      bad: "border-bad/40 bg-bad/10 text-bad",
      muted: "border-line-strong bg-surface-3 text-muted",
    },
  },
  defaultVariants: { variant: "default" },
});

export function Badge({ className, variant, ...props }: React.HTMLAttributes<HTMLSpanElement> & VariantProps<typeof badgeVariants>) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />;
}
