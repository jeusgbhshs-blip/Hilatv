/** Choose one exported film from aspect, language, and duration. */

export const ASPECT_RATIOS = ["16:9", "9:16", "1:1", "4:3", "3:4", "3:2", "2:3", "4:5", "21:9"] as const;
export type MediaMetadata = { width: number | null; height: number | null; duration_s: number | null };
export type ProjectMediaSettings = {
  generation_settings?: { aspect_ratio?: string | null; duration_s?: number | null };
  resolved_generation_settings?: { aspect_ratio?: string | null; duration_s?: number | null; language?: string | null };
  width?: number | null; height?: number | null; duration_s?: number | null;
};

function positiveNumber(value: unknown): value is number { return typeof value === "number" && Number.isFinite(value) && value > 0; }

/** Only server-probed or decoded values count as actual media dimensions. */
export function mediaMetadata(value?: Partial<MediaMetadata> | null): MediaMetadata {
  const dimensions = positiveNumber(value?.width) && positiveNumber(value?.height);
  return { width: dimensions ? value!.width! : null, height: dimensions ? value!.height! : null, duration_s: positiveNumber(value?.duration_s) ? value.duration_s : null };
}

export function mediaOrientation(value: MediaMetadata): "portrait" | "landscape" | "square" | "unknown" {
  if (value.width === null || value.height === null) return "unknown";
  return value.width === value.height ? "square" : value.height > value.width ? "portrait" : "landscape";
}

export function generationTargetSummary(value: ProjectMediaSettings | null): string {
  const ratio = value?.generation_settings?.aspect_ratio || value?.resolved_generation_settings?.aspect_ratio;
  const duration = value?.generation_settings?.duration_s ?? value?.resolved_generation_settings?.duration_s;
  return `主画幅 · ${ratio || "自动"}；目标时长 · ${positiveNumber(duration) ? `${duration} 秒` : "自动"}`;
}

export function defaultExportAspect(value: ProjectMediaSettings | null): typeof ASPECT_RATIOS[number] {
  const configured = value?.generation_settings?.aspect_ratio || value?.resolved_generation_settings?.aspect_ratio;
  if (ASPECT_RATIOS.includes(configured as typeof ASPECT_RATIOS[number])) return configured as typeof ASPECT_RATIOS[number];
  const actual = mediaMetadata(value);
  return ASPECT_RATIOS.find((ratio) => {
    const [width, height] = ratio.split(":").map(Number);
    return actual.width !== null && actual.height !== null && Math.abs(actual.width / actual.height - width / height) < 0.01;
  }) || "16:9";
}

export function currentExportLanguage(value: ProjectMediaSettings | null, selectedLanguage?: string): string {
  return value?.resolved_generation_settings?.language || selectedLanguage || "zh";
}

/** Export one chosen frame in the existing language, never speculative variants. */
export function deliveryRequest(aspect: string, language: string): { aspect_ratios: string[]; languages: string[] } {
  if (!ASPECT_RATIOS.includes(aspect as typeof ASPECT_RATIOS[number])) throw new Error("请选择可用的导出画幅");
  if (!/^[a-zA-Z]{2,3}(?:-[a-zA-Z0-9]{2,8})*$/.test(language)) throw new Error("当前语种尚未确认，请重新读取项目");
  return { aspect_ratios: [aspect], languages: [language] };
}

export type FilmVersion = {
  version_id: string;
  aspect_ratio: string;
  language: string;
  duration_s: number;
  width: number;
  height: number;
  download_path: string;
  share_path?: string | null;
  preview_path?: string | null;
  preview_available?: boolean;
  media_hash?: string | null;
  delivery_status?: string;
  quality_pass?: boolean;
  media_provenance?: string;
  qa_status?: string;
  subject_box_source?: string;
};

export type VersionChoice = {
  aspect: string;
  language: string;
  duration: number | null;
};

const ASPECT_LABELS: Record<string, string> = {
  "16:9": "16:9 横屏",
  "9:16": "9:16 竖屏",
  "1:1": "1:1 方形",
  "4:3": "4:3 横屏",
  "3:4": "3:4 竖屏",
  "3:2": "3:2 横屏",
  "2:3": "2:3 竖屏",
  "4:5": "4:5 竖屏",
  "21:9": "21:9 宽屏",
};

const LANGUAGE_LABELS: Record<string, string> = {
  zh: "中文",
  en: "English",
};

export function readVersions(body: unknown): FilmVersion[] {
  const list = Array.isArray(body)
    ? body
    : body && typeof body === "object" && Array.isArray((body as { versions?: unknown }).versions)
      ? (body as { versions: unknown[] }).versions
      : [];
  const versions: FilmVersion[] = [];
  for (const item of list) {
    if (!item || typeof item !== "object") continue;
    const record = item as Record<string, unknown>;
    const versionId = record.version_id;
    const aspect = record.aspect_ratio;
    const language = record.language;
    const duration = Number(record.duration_s);
    const width = Number(record.width);
    const height = Number(record.height);
    const download = record.download_path;
    if (typeof versionId !== "string" || !versionId) continue;
    if (typeof aspect !== "string" || !aspect) continue;
    if (typeof language !== "string" || !language) continue;
    if (!Number.isFinite(duration) || duration <= 0) continue;
    if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) continue;
    if (typeof download !== "string" || (!download.startsWith("/") || download.startsWith("//"))) continue;
    versions.push({
      version_id: versionId,
      aspect_ratio: aspect,
      language,
      duration_s: duration,
      width,
      height,
      download_path: download,
      share_path: typeof record.share_path === "string" ? record.share_path : null,
      preview_path: typeof record.preview_path === "string" && record.preview_path.startsWith("/") && !record.preview_path.startsWith("//") ? record.preview_path : null,
      preview_available: record.preview_available === true,
      media_hash: typeof record.media_hash === "string" ? record.media_hash : null,
      delivery_status: typeof record.delivery_status === "string" ? record.delivery_status : undefined,
      quality_pass: record.quality_pass === true,
      media_provenance: typeof record.media_provenance === "string" ? record.media_provenance : undefined,
      qa_status: typeof record.qa_status === "string" ? record.qa_status : undefined,
      subject_box_source:
        typeof record.subject_box_source === "string" ? record.subject_box_source : undefined,
    });
  }
  return versions;
}

export function aspectLabel(aspect: string): string {
  return ASPECT_LABELS[aspect] ?? aspect;
}

export function languageLabel(language: string): string {
  const primary = language.toLowerCase().split("-")[0] ?? language;
  return LANGUAGE_LABELS[primary] ?? language;
}

export function durationLabel(seconds: number): string {
  const rounded = Math.round(seconds * 10) / 10;
  return Number.isInteger(rounded) ? `${rounded.toFixed(0)} 秒` : `${rounded} 秒`;
}

export function downloadName(version: FilmVersion | null): string {
  if (!version) return "master.mp4";
  const aspect = version.aspect_ratio.replace(":", "x");
  const seconds = Math.round(version.duration_s * 10) / 10;
  return `hilatv-${aspect}-${version.language}-${seconds}s.mp4`;
}

export function defaultChoice(versions: FilmVersion[]): VersionChoice {
  const aspects = uniqueAspects(versions);
  const aspect = aspects.includes("16:9") ? "16:9" : (aspects[0] ?? "");
  const languages = uniqueLanguages(versions, aspect);
  const language = languages.includes("zh") ? "zh" : (languages[0] ?? "");
  const durations = uniqueDurations(versions, aspect, language);
  return { aspect, language, duration: durations.at(-1) ?? null };
}

export function reconcile(versions: FilmVersion[], choice: VersionChoice): VersionChoice {
  const aspects = uniqueAspects(versions);
  const aspect = aspects.includes(choice.aspect) ? choice.aspect : (aspects[0] ?? "");
  const languages = uniqueLanguages(versions, aspect);
  const language = languages.includes(choice.language) ? choice.language : (languages[0] ?? "");
  const durations = uniqueDurations(versions, aspect, language);
  const duration =
    choice.duration !== null && durations.some((item) => sameDuration(item, choice.duration ?? 0))
      ? durations.find((item) => sameDuration(item, choice.duration ?? 0)) ?? null
      : (durations.at(-1) ?? null);
  return { aspect, language, duration };
}

export function pickVersion(versions: FilmVersion[], choice: VersionChoice): FilmVersion | null {
  const settled = reconcile(versions, choice);
  return (
    versions.find(
      (item) =>
        item.aspect_ratio === settled.aspect &&
        item.language === settled.language &&
        settled.duration !== null &&
        sameDuration(item.duration_s, settled.duration),
    ) ?? null
  );
}

export function uniqueAspects(versions: FilmVersion[]): string[] {
  return unique(versions.map((item) => item.aspect_ratio));
}

export function uniqueLanguages(versions: FilmVersion[], aspect: string): string[] {
  return unique(versions.filter((item) => item.aspect_ratio === aspect).map((item) => item.language));
}

export function uniqueDurations(versions: FilmVersion[], aspect: string, language: string): number[] {
  const found = versions
    .filter((item) => item.aspect_ratio === aspect && item.language === language)
    .map((item) => item.duration_s);
  return [...new Set(found.map((item) => Math.round(item * 1000) / 1000))].sort((left, right) => left - right);
}

function unique(values: string[]): string[] {
  return [...new Set(values)];
}

function sameDuration(left: number, right: number): boolean {
  return Math.abs(left - right) < 0.05;
}
