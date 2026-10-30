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

