import * as React from "react";

import { cn } from "@/lib/utils";

function Badge({ className, ...props }: React.ComponentProps<"span">) {
  return (
    <span
      className={cn(
        "inline-flex max-w-full items-center rounded-full border border-border bg-muted px-2.5 py-1 text-xs text-foreground",
        className,
      )}
      {...props}
    />
  );
}

export { Badge };
