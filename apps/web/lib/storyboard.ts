/** Cards for the storyboard pause. Placeholder frames never become images. */

export type StoryboardCard = {
  shot_id: string;
  order: number;
  duration_s: number;
  purpose: string;
  voiceover: string;
  preview_status: string;
  visual_reviewed: boolean;
  preview_note: string;
  frame_url: string | null;
};

export type CardMedia = {
  showImage: boolean;
  reviewed: boolean;
  note: string;
};

export function readCards(value: unknown): StoryboardCard[] {
  if (!Array.isArray(value)) return [];
  const cards: StoryboardCard[] = [];
  for (const item of value) {
    if (!item || typeof item !== "object") continue;
    const record = item as Record<string, unknown>;
    const shotId = typeof record.shot_id === "string" ? record.shot_id : "";
    const order = Number(record.order);
    if (!shotId || !Number.isFinite(order)) continue;
    const ready = record.preview_status === "ready" && typeof record.frame_url === "string";
    const reviewed = ready && record.visual_reviewed === true;
    cards.push({
      shot_id: shotId,
      order,
      duration_s: Number(record.duration_s) || 0,
      purpose: typeof record.purpose === "string" ? record.purpose : "",
      voiceover: typeof record.voiceover === "string" ? record.voiceover : "",
      preview_status: ready ? "ready" : "unavailable",
      visual_reviewed: reviewed,
      preview_note: reviewed ? "" : ready ? "未评审" : "未测",
      frame_url: ready ? String(record.frame_url) : null,
    });
  }
  return cards.sort((left, right) => left.order - right.order);
}

export function cardMedia(card: StoryboardCard): CardMedia {
  const showImage = card.preview_status === "ready" && Boolean(card.frame_url);
  const reviewed = showImage && card.visual_reviewed === true;
  return {
    showImage,
    reviewed,
    note: reviewed ? "已看过画面" : showImage ? "未评审" : "这一镜还没有可看的画面",
  };
}
