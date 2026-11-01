export const ASPECT_RATIOS = ["16:9", "9:16", "1:1", "4:3", "3:4", "3:2", "2:3", "4:5", "21:9"] as const;
export type AspectRatio = typeof ASPECT_RATIOS[number];
export type GenerationSettings = { aspect_ratio: AspectRatio | null; duration_s: number | null };

/** Null means infer from the sentence and project; it is not a fixed default. */
export function generationSettings(value?: unknown): GenerationSettings {
  const raw = value && typeof value === "object" ? value as Record<string, unknown> : {};
  return {
    aspect_ratio: ASPECT_RATIOS.includes(raw.aspect_ratio as AspectRatio) ? raw.aspect_ratio as AspectRatio : null,
    duration_s: typeof raw.duration_s === "number" && Number.isInteger(raw.duration_s) && raw.duration_s >= 5 && raw.duration_s <= 180 ? raw.duration_s : null,
  };
}

export function settingsKey(value?: unknown): string { return JSON.stringify(generationSettings(value)); }
export function conceptInputKey(sentence: string, settings?: unknown): string { return JSON.stringify([sentence.trim(), generationSettings(settings)]); }
export function settingsSummary(value?: unknown): string {
  const settings = generationSettings(value);
  return `比例 · ${settings.aspect_ratio || "自动"}；时长 · ${settings.duration_s === null ? "自动" : `${settings.duration_s} 秒`}`;
}
