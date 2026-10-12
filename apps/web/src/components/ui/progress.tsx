"use client";
import * as ProgressPrimitive from "@radix-ui/react-progress";
import * as React from "react";
import { cn } from "@/lib/utils";

export function Progress({ value, className, indicatorClassName, ...props }: React.ComponentProps<typeof ProgressPrimitive.Root> & { indicatorClassName?: string }) {
  return (
    <ProgressPrimitive.Root className={cn("relative h-2 w-full overflow-hidden rounded-full bg-surface-3", className)} value={value} {...props}>
      <ProgressPrimitive.Indicator
        className={cn("h-full rounded-full bg-gradient-to-r from-brand to-accent transition-all duration-500", indicatorClassName)}
        style={{ width: `${Math.max(0, Math.min(100, value ?? 0))}%` }}
      />
    </ProgressPrimitive.Root>
  );
}
