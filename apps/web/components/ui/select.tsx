import * as React from "react";

import { cn } from "@/lib/utils";

/** Native select in DESIGN.md input skin. Native keeps keyboard and phone pickers. */
function Select({ className, ...props }: React.ComponentProps<"select">) {
  return (
    <select
      className={cn(
        "h-11 w-full min-w-0 rounded-sm border border-border-strong bg-raised px-3 text-body text-text-1 disabled:cursor-not-allowed disabled:text-text-disabled md:h-9",
        className,
      )}
      {...props}
    />
  );
}

export { Select };
