import {
  Building2,
  Factory,
  Globe,
  GraduationCap,
  type LucideIcon,
  ShoppingCart,
  Store,
} from "lucide-react";

import { cn } from "@/lib/utils";

const ICONS: Record<string, LucideIcon> = {
  manufacturing: Factory,
  foreign_trade: Globe,
  ecommerce: ShoppingCart,
  local_life: Store,
  education: GraduationCap,
  public_sector: Building2,
};

/** DESIGN.md §9.2 IndustryShortcut: a line icon and a name. Selected = blue outline, not blue fill. */
export function IndustryShortcut({
  id,
  label,
  pressed,
  onClick,
  hint,
  icon,
  variant = "compact",
}: {
  id: string;
  label: string;
  pressed: boolean;
  onClick: () => void;
  hint?: string;
  icon?: LucideIcon;
  variant?: "compact" | "tile";
}) {
  const Icon = icon ?? ICONS[id] ?? Factory;
  return (
    <button
      type="button"
      aria-pressed={pressed}
      data-entry={id}
      onClick={onClick}
      className={cn(
        "min-h-11 border bg-surface text-left text-small",
        variant === "tile"
          ? "tile-lift flex h-full w-full min-w-0 flex-col items-center justify-center gap-2 rounded-lg border-2 px-2 py-4 text-center"
          : "flex items-center gap-2.5 rounded-md px-3 py-2.5 transition-colors duration-fast md:flex-col md:items-start md:gap-2 md:py-3",
        pressed
          ? variant === "tile"
            ? "border-blue text-text-1"
            : "border-blue bg-blue-soft text-text-1 ring-1 ring-blue"
          : "border-border text-text-2 hover:border-border-strong hover:text-text-1",
      )}
    >
      <Icon aria-hidden="true" className="size-6 shrink-0" strokeWidth={1.5} />
      <span className="w-full font-medium text-text-1">{label}</span>
      {hint ? <span className="w-full text-caption text-text-3">{hint}</span> : null}
    </button>
  );
}
