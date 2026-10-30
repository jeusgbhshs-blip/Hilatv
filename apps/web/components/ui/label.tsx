import * as React from "react";

import { cn } from "@/lib/utils";

function Label({ className, ...props }: React.ComponentProps<"label">) {
  return <label className={cn("text-small font-medium text-text-1", className)} {...props} />;
}

export { Label };
