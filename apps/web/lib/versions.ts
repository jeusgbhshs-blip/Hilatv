/** Choose one exported film from aspect, language, and duration. */

export type FilmVersion = {
  version_id: string;
  aspect_ratio: string;
  language: string;
  duration_s: number;
  width: number;
  height: number;
  download_path: string;
  share_path?: string | null;
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
    if (!Number.isFinite(width) || !Number.isFinite(height)) continue;
    if (typeof download !== "string" || !download.startsWith("/")) continue;
    versions.push({
      version_id: versionId,
      aspect_ratio: aspect,
      language,
      duration_s: duration,
      width,
      height,
      download_path: download,
      share_path: typeof record.share_path === "string" ? record.share_path : null,
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
