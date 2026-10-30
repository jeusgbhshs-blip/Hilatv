import { cn } from "@/lib/utils";

/**
 * Company mark from public/brand/mark.svg, inlined so the curve and bars take
 * currentColor (Ink on light, Paper on dark). The dot stays Source Blue.
 */
export function BrandMark({ className, title }: { className?: string; title?: string }) {
  return (
    <svg
      viewBox="-40.66 -20.45 445.26 445.26"
      className={cn("shrink-0", className)}
      role={title ? "img" : undefined}
      aria-label={title}
      aria-hidden={title ? undefined : true}
      focusable="false"
    >
      <path
        d="M58.00 292.00 C56.00 334.00 104.00 338.00 132.00 300.00 C168.00 252.00 188.00 140.00 232.00 98.00 C256.00 74.00 292.00 70.00 306.00 96.00"
        fill="none"
        stroke="currentColor"
        strokeWidth="28"
        strokeLinecap="round"
      />
      <rect x="166" y="286" width="28" height="44" rx="14" fill="currentColor" />
      <rect x="224" y="214" width="28" height="116" rx="14" fill="currentColor" />
      <rect x="286" y="214" width="28" height="116" rx="14" fill="currentColor" />
      <circle cx="300" cy="162" r="20" className="fill-blue" />
    </svg>
  );
}
