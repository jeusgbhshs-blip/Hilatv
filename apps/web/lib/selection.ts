/** Pick one of three concept cards, or leave the choice to the system. */

export type DirectionCard = {
  direction_id: string;
  title: string;
  idea: string;
  mood?: string;
  duration_s?: number;
  aspect_ratio?: string;
  cover_preview?: string;
  estimated_effect?: string;
};

export type CardChoice = {
  id: string;
  auto: boolean;
  label: string;
};

export function chooseCard(cards: DirectionCard[], selection: string | null): CardChoice {
  if (!selection || selection === "你帮我选" || !cards.some((card) => card.direction_id === selection)) {
    return { id: "你帮我选", auto: true, label: "你帮我选" };
  }
  const found = cards.find((card) => card.direction_id === selection);
  return {
    id: selection,
    auto: false,
    label: found?.title || selection,
  };
}

const ENTERPRISE_KEY = "hilatv.enterpriseId";

export function rememberEnterprise(id: string): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(ENTERPRISE_KEY, id);
}

export function rememberedEnterprise(): string {
  if (typeof window === "undefined") return "";
  const existing = window.localStorage.getItem(ENTERPRISE_KEY);
  if (existing) return existing;
  const created = crypto.randomUUID();
  window.localStorage.setItem(ENTERPRISE_KEY, created);
  return created;
}
