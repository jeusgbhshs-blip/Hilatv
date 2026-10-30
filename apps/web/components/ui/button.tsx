import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { LoaderCircle } from "lucide-react";
import * as React from "react";

import { cn } from "@/lib/utils";

/**
 * DESIGN.md §9.1 Button. One primary (blue) button per screen.
 * `default` and `outline` are kept as aliases of `primary` and `secondary`
 * so older call sites keep working.
 */
const buttonVariants = cva(
  "inline-flex select-none items-center justify-center gap-2 whitespace-nowrap rounded-sm text-small font-medium transition-colors duration-120 ease-out disabled:pointer-events-none disabled:text-text-disabled aria-disabled:pointer-events-none aria-disabled:text-text-disabled",
  {
    variants: {
      variant: {
        primary:
          "bg-blue text-primary-foreground hover:bg-blue-hover active:bg-blue-press disabled:bg-hover aria-disabled:bg-hover",
        default:
          "bg-blue text-primary-foreground hover:bg-blue-hover active:bg-blue-press disabled:bg-hover aria-disabled:bg-hover",
        secondary:
          "border border-border-strong bg-surface text-text-1 hover:bg-hover active:bg-hover disabled:bg-surface",
        outline:
          "border border-border-strong bg-surface text-text-1 hover:bg-hover active:bg-hover disabled:bg-surface",
        ghost: "text-text-1 hover:bg-hover active:bg-hover",
        danger: "text-danger hover:bg-danger-soft active:bg-danger-soft",
      },
      size: {
        default: "h-11 px-4 md:h-9",
        sm: "h-11 px-3 md:h-7.5",
        lg: "h-11 px-5",
        icon: "size-11 md:size-8",
      },
    },
    defaultVariants: {
      variant: "primary",
      size: "default",
    },
  },
);

function Button({
  className,
  variant,
  size,
  asChild = false,
  loading = false,
  children,
  ...props
}: React.ComponentProps<"button"> &
  VariantProps<typeof buttonVariants> & {
    asChild?: boolean;
    loading?: boolean;
  }) {
  const Comp = asChild ? Slot : "button";
  if (asChild) {
    return (
      <Comp className={cn(buttonVariants({ variant, size, className }))} {...props}>
        {children}
      </Comp>
    );
  }
  return (
    <Comp
      className={cn(buttonVariants({ variant, size, className }))}
      aria-busy={loading || undefined}
      {...props}
    >
      {loading ? <LoaderCircle aria-hidden="true" className="size-3.5 animate-spin" /> : null}
      {children}
    </Comp>
  );
}

export { Button, buttonVariants };
