import * as React from "react";

import { cn } from "@/lib/utils";

function Textarea({ className, ...props }: React.ComponentProps<"textarea">) {
  return (
    <textarea
      className={cn(
        "flex min-h-32 w-full min-w-0 rounded-sm border border-border-strong bg-raised px-3 py-2 text-body text-text-1 placeholder:text-text-3 aria-invalid:border-danger disabled:cursor-not-allowed disabled:text-text-disabled",
        className,
      )}
      {...props}
    />
  );
}

export { Textarea };
