/** Fold WebSocket events and the project snapshot into the progress page. */

export const PHASES = ["理解需求", "选方案", "看分镜", "生成中", "成片"] as const;

export type Phase = (typeof PHASES)[number];

export type ShotSummary = {
  shot_id?: string;
  order: number;
  purpose?: string;
};

export type ProgressEvent = {
  type?: string;
  node?: string | null;
  phase?: string | null;
  message?: string | null;
  status?: string | null;
  shot_id?: string | null;
  shot_index?: number | null;
  error?: string | null;
  ts?: number | null;
};

export type ShotView = {
  key: string;
  order: number;
  purpose: string;
  stage: string;
};

export type AttachmentView = {
  kind: string;
  uri: string;
  filename: string;
  upload_id?: string;
};

export type ProjectSnapshot = {
  status?: string;
  phase?: string | null;
  message?: string | null;
  error?: string | null;
  elapsed_s?: number | null;
  sentence?: string;
  shots?: ShotSummary[];
  events?: ProgressEvent[];
  attachments?: AttachmentView[];
  storyboard?: unknown;
  concept_degraded?: boolean;
  concept_ok?: boolean | null;
  concept_text_source?: string | null;
  quality_pass?: boolean;
  delivery_status?: string;
  media_provenance?: string;
  preview_available?: boolean;
  preview_path?: string | null;
  download_path?: string | null;
  media_hash?: string | null;
  delivery_reasons?: string[];
  revision_notice?: string | null;
};

export function eventKey(event: ProgressEvent): string {
  return [
    event.ts ?? "",
    event.shot_index ?? "",
    event.node ?? "",
    event.status ?? "",
    event.message ?? "",
  ].join("|");
}

export function mergeEvents(current: ProgressEvent[], incoming: ProgressEvent[]): ProgressEvent[] {
  const map = new Map<string, ProgressEvent>();
  for (const event of [...current, ...incoming]) {
    if (!event || event.type === "error") continue;
    map.set(eventKey(event), event);
  }
  return [...map.values()].sort((left, right) => (left.ts ?? 0) - (right.ts ?? 0));
}

export function readShots(value: unknown): ShotSummary[] {
  if (!Array.isArray(value)) return [];
  const shots: ShotSummary[] = [];
  for (const item of value) {
    if (!item || typeof item !== "object") continue;
    const record = item as Record<string, unknown>;
    const order = Number(record.order);
    if (!Number.isFinite(order) || order <= 0) continue;
    shots.push({
      shot_id: typeof record.shot_id === "string" ? record.shot_id : undefined,
      order,
      purpose: typeof record.purpose === "string" ? record.purpose : "",
    });
  }
  return shots;
}

export function readEvents(value: unknown): ProgressEvent[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is ProgressEvent => Boolean(item) && typeof item === "object");
}

export function readAttachments(value: unknown): AttachmentView[] {
  if (!Array.isArray(value)) return [];
  const found: AttachmentView[] = [];
  for (const item of value) {
    if (!item || typeof item !== "object") continue;
    const record = item as Record<string, unknown>;
    const kind = typeof record.kind === "string" ? record.kind : "";
    const uri = typeof record.uri === "string" ? record.uri : "";
    const filename = typeof record.filename === "string" ? record.filename : "";
    const uploadId = typeof record.upload_id === "string" ? record.upload_id : "";
    if (!uri && !filename && !uploadId) continue;
    found.push({ kind, uri, filename, upload_id: uploadId });
  }
  return found;
}

export function shotViews(shots: ShotSummary[], events: ProgressEvent[]): ShotView[] {
  const byOrder = new Map<number, ShotView>();
  for (const shot of shots) {
    const order = Number(shot.order);
    if (!Number.isFinite(order) || order <= 0) continue;
    byOrder.set(order, {
      key: shot.shot_id || String(order),
      order,
      purpose: shot.purpose || "",
      stage: "即将开始",
    });
  }
  for (const event of events) {
    const order = Number(event.shot_index);
    if (!Number.isFinite(order) || order <= 0) continue;
    const message = (event.message || "").trim();
    if (!message) continue;
    const existing = byOrder.get(order);
    byOrder.set(order, {
      key: event.shot_id || existing?.key || String(order),
      order,
      purpose: existing?.purpose || "",
      stage: message,
    });
  }
  return [...byOrder.values()].sort((left, right) => left.order - right.order);
}

export function latestPhase(events: ProgressEvent[], fallback = "理解需求"): string {
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const phase = events[index]?.phase;
    if (phase) return phase;
  }
  return fallback;
}

export function latestMessage(events: ProgressEvent[], fallback: string): string {
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const message = events[index]?.message;
    if (message) return message;
  }
  return fallback;
}

export function projectStatus(snapshotStatus: string | undefined, events: ProgressEvent[]): string {
  if (snapshotStatus && ["draft", "paused", "needs_human_review", "failed", "completed"].includes(snapshotStatus)) return snapshotStatus;
  let status = snapshotStatus || "running";
  for (const event of events) {
    if (event.status) status = event.status;
  }
  return status;
}

function safeFilename(name: string): string {
  const trimmed = name.trim();
  if (!trimmed || trimmed.includes("/") || trimmed.includes("\\") || trimmed.includes("..")) return "";
  return trimmed;
}

export function attachmentLabel(item: AttachmentView): string {
  const filename = safeFilename(item.filename);
  if (item.kind === "url" && /^https?:\/\//i.test(item.uri)) return item.uri;
  if (item.kind === "url") return filename || "链接";
  return filename || (item.kind === "pdf" ? "PDF" : "图片");
}
