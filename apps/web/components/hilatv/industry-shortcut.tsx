import { Building2, Factory, Globe, GraduationCap, type LucideIcon, ShoppingCart, Store } from "lucide-react";

import { cn } from "@/lib/utils";

const ICONS: Record<string, LucideIcon> = {
  manufacturing: Factory,
  foreign_trade: Globe,
  ecommerce: ShoppingCart,
  local_life: Store,
  education: GraduationCap,
  public_sector: Building2,
};

/** DESIGN.md §9.2 IndustryShortcut: a small card with a line icon. Selected = blue outline, not blue fill. */
export function IndustryShortcut({
  id,
  label,
  pressed,
  onClick,
}: {
  id: string;
  label: string;
  pressed: boolean;
  onClick: () => void;
}) {
  const Icon = ICONS[id] ?? Factory;
  return (
    <button
      type="button"
      aria-pressed={pressed}
      onClick={onClick}
      className={cn(
        "flex min-h-11 items-center gap-2.5 rounded-md border bg-surface px-3 py-2.5 text-left text-small transition-colors duration-120 md:flex-col md:items-start md:gap-2 md:py-3",
        pressed
          ? "border-blue bg-blue-soft text-text-1 ring-1 ring-blue"
          : "border-border text-text-1 hover:border-border-strong",
      )}
    >
      <Icon aria-hidden="true" className="size-5.5 shrink-0 text-text-2" strokeWidth={1.5} />
      <span className="font-medium">{label}</span>
    </button>
  );
}
