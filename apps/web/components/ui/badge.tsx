import { cva, type VariantProps } from "class-variance-authority";
import * as React from "react";

import { cn } from "@/lib/utils";

/** DESIGN.md §9.1 Chip / Tag: soft background, solid text, never a solid colour block. */
const badgeVariants = cva(
  "inline-flex min-h-5.5 max-w-full items-center gap-1 rounded-full px-2.5 text-caption",
  {
    variants: {
      tone: {
        neutral: "bg-hover text-text-2",
        blue: "bg-blue-soft text-blue-text",
        success: "bg-success-soft text-success",
        warning: "bg-warning-soft text-warning",
        danger: "bg-danger-soft text-danger",
      },
    },
    defaultVariants: { tone: "neutral" },
  },
);

function Badge({
  className,
  tone,
  ...props
}: React.ComponentProps<"span"> & VariantProps<typeof badgeVariants>) {
  return <span className={cn(badgeVariants({ tone }), className)} {...props} />;
}

export { Badge, badgeVariants };
