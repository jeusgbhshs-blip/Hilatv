import * as React from "react";

import { cn } from "@/lib/utils";

/** DESIGN.md §9.1 Card. Selected cards get a 2px blue ring. */
function Card({
  className,
  selected = false,
  ...props
}: React.ComponentProps<"div"> & { selected?: boolean }) {
  return (
    <div
      data-selected={selected || undefined}
      className={cn(
        "rounded-md border border-border bg-surface text-text-1",
        selected && "border-blue ring-1 ring-blue",
        className,
      )}
      {...props}
    />
  );
}

export { Card };
