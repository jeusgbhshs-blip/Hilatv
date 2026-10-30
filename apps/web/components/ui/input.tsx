import * as React from "react";

import { cn } from "@/lib/utils";

function Input({ className, type, ...props }: React.ComponentProps<"input">) {
  return (
    <input
      type={type}
      className={cn(
        "flex h-11 w-full min-w-0 rounded-sm border border-border-strong bg-raised px-3 text-body text-text-1 placeholder:text-text-3 aria-invalid:border-danger disabled:cursor-not-allowed disabled:text-text-disabled md:h-9",
        "file:mr-3 file:border-0 file:bg-transparent file:text-small file:text-text-1",
        className,
      )}
      {...props}
    />
  );
}

export { Input };
