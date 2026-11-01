import { cn } from "@/lib/utils";

/** DESIGN.md §9.1 Progress: 4px track, blue fill. `value` is 0..1. */
function Progress({ value, className, label, valueText }: { value: number; className?: string; label?: string; valueText?: string }) {
  const clamped = Math.max(0, Math.min(1, Number.isFinite(value) ? value : 0));
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(clamped * 100)}
      aria-valuetext={valueText}
      className={cn("h-1 w-full overflow-hidden rounded-full bg-hover", className)}
    >
      <div
        className="h-full origin-left rounded-full bg-blue transition-transform duration-320 ease-out"
        style={{ transform: `scaleX(${clamped})` }}
      />
    </div>
  );
}

export { Progress };
