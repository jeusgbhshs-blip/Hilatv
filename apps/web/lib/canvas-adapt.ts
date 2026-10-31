/**
 * 把现有 GET /canvas 收成画布快照。
 * 质检只经 verdictLabel / shotVerdictFromLegacy。不把模型提示词放进卡片。
 */

import type { ExpertCandidate, ExpertCanvas, ExpertShot } from "./expert";
import {
  AI_LABEL_COPY,
  asShot,
  shotVerdictFromLegacy,
  type CanvasEdge,
  type CanvasNode,
  type CanvasOverlay,
  type CanvasPoint,
  type CanvasSnapshot,
  type ServerTimeline,
  type ShotCandidate,
  type TimelineClip,
} from "./canvas-contract";

export type { CanvasOverlay };

export function isContractCanvas(body: unknown): body is CanvasSnapshot {
  if (!body || typeof body !== "object") return false;
  const value = body as CanvasSnapshot;
  if (!Array.isArray(value.nodes) || typeof value.layout_version !== "number" || !value.viewport) return false;
  return value.nodes.every((node) => node && typeof node.kind === "string" && !!node.position);
}

export function isLegacyCanvas(body: unknown): body is ExpertCanvas {
  if (!body || typeof body !== "object") return false;
  if (isContractCanvas(body)) return false;
  const value = body as ExpertCanvas;
  return Array.isArray(value.nodes) && Array.isArray(value.shots);
}

export function adaptLegacyCanvas(canvas: ExpertCanvas, overlay?: CanvasOverlay | null): CanvasSnapshot {
  const shots = canvas.shots ?? [];
  const nodes: CanvasNode[] = [
    {
      id: "brief-1",
      kind: "brief",
      position: { x: 40, y: 24 },
      user_created: false,
      data: { text: canvas.sentence || "" },
    },
  ];
  shots.forEach((shot, index) => {
    nodes.push(shotNode(shot, index));
  });
  nodes.push({
    id: "final-1",
    kind: "final",
    position: { x: 980, y: 180 },
    user_created: false,
    data: { version_id: null, ai_label: true },
  });
  const edges: CanvasEdge[] = [];
  for (const shot of shots) {
    edges.push(link(`edge-brief-${shot.shot_id}`, "brief-1", shot.shot_id, "text", "text"));
    edges.push(link(`edge-${shot.shot_id}-final`, shot.shot_id, "final-1", "feeds_final", "out"));
  }
  const clips: TimelineClip[] = shots.map((shot) => {
    const data = asShot(nodes.find((node) => node.id === shot.shot_id)!);
    return {
      shot_id: shot.shot_id,
      candidate_id: data?.selected_candidate_id || data?.candidates[0]?.candidate_id || shot.shot_id,
      in_s: 0,
      out_s: data?.duration_s ?? 4,
    };
  });
  const server = serverTimeline(canvas);
  const snapshot: CanvasSnapshot = {
    project_id: canvas.project_id,
    nodes,
    edges,
    viewport: { x: 24, y: 16, zoom: 0.72 },
    layout_version: 1,
    sentence: canvas.sentence || "",
    budget: canvas.budget ?? { used: 0, limit: 0, remaining: 0 },
    timeline: {
      clips,
      ai_label: true,
      duration_s: clips.reduce((sum, clip) => sum + (clip.out_s - clip.in_s), 0),
    },
    origin: "api",
    server_timeline: server,
  };
  return applyOverlay(snapshot, overlay);
}

export function applyOverlay(snapshot: CanvasSnapshot, overlay?: CanvasOverlay | null): CanvasSnapshot {
  if (!overlay) return lockAi(snapshot);
  const nodes = snapshot.nodes.map((node) => {
    const position = overlay.positions[node.id];
    const reference = overlay.references?.[node.id] ?? overlay.references?.[asShot(node)?.shot_id ?? ""];
    let next = position ? { ...node, position: { ...position } } : node;
    const shot = asShot(next);
    if (shot && reference) {
      next = {
        ...next,
        data: {
          ...shot,
          reference_upload_id: reference.upload_id,
          reference_thumbnail_url: reference.thumbnail_url ?? null,
        },
      };
    }
    return next;
  });
  for (const extra of overlay.nodes) {
    if (!nodes.some((node) => node.id === extra.id)) nodes.push(extra);
  }
  const edges = snapshot.edges.slice();
  for (const extra of overlay.edges) {
    if (!edges.some((edge) => edge.id === extra.id)) edges.push(extra);
  }
  const clips = overlay.clips ?? snapshot.timeline.clips;
  return lockAi({
    ...snapshot,
    nodes,
    edges,
    viewport: overlay.viewport ?? snapshot.viewport,
    layout_version: overlay.layout_version || snapshot.layout_version,
    timeline: {
      clips,
      ai_label: true,
      duration_s: clips.reduce((sum, clip) => sum + Math.max(0, clip.out_s - clip.in_s), 0),
    },
  });
}

export function emptyOverlay(): CanvasOverlay {
  return { layout_version: 1, positions: {}, nodes: [], edges: [] };
}

export function buildSelectBody(shotId: string, candidate: ShotCandidate): {
  node: string;
  shot_id: string;
  candidate_id: string;
} {
  return {
    node: candidate.source_node || (candidate.kind === "keyframe" ? "n08_keyframe" : "n10_video"),
    shot_id: shotId,
    candidate_id: candidate.candidate_id,
  };
}

export function buildRerunBody(
  shotId: string,
  candidate: ShotCandidate | undefined,
  promptSuffix: string,
): { node: string; shot_id: string; prompt_suffix: string } {
  return {
    node: candidate?.source_node || (candidate?.kind === "keyframe" ? "n08_keyframe" : "n10_video"),
    shot_id: shotId,
    prompt_suffix: promptSuffix,
  };
}

/** 现有时间轴接口的正文。overlays 原样带回；缺「AI生成」时补上，不能删。 */
export function buildTimelineBody(server: ServerTimeline | undefined, clips: TimelineClip[]): ServerTimeline {
  const overlays = (server?.overlays ?? []).map((item) => ({ kind: item.kind, text: item.text }));
  if (!overlays.some((item) => item.kind === "ai_label" && item.text === AI_LABEL_COPY)) {
    overlays.push({ kind: "ai_label", text: AI_LABEL_COPY });
  }
  const posted =
    server?.clips?.length
      ? server.clips.map((clip) => ({
          clip_id: clip.clip_id,
          transition_out: clip.transition_out || "cut",
        }))
      : clips.map((clip) => ({ clip_id: clip.shot_id, transition_out: "cut" }));
  return { overlays, clips: posted };
}

function shotNode(shot: ExpertShot, index: number): CanvasNode {
  const candidates = [
    ...shot.keyframes.map((item) => toCandidate(item, "keyframe", "n08_keyframe")),
    ...shot.videos.map((item) => toCandidate(item, "video", "n10_video")),
  ];
  const selected = candidates.find((item) => item.candidate_id === selectedId(shot)) ?? candidates[0];
  const review = selected?.review;
  return {
    id: shot.shot_id,
    kind: "shot",
    position: { x: 520, y: 24 + index * 440 },
    user_created: false,
    data: {
      shot_id: shot.shot_id,
      index: shot.order || index + 1,
      thumbnail_url: selected?.thumbnail_url ?? null,
      duration_s: 4,
      verdict: review ? shotVerdictFromLegacy(review) : "unreviewed",
      review,
      regen_count: 0,
      candidates,
      selected_candidate_id: selected?.candidate_id ?? null,
      narration: shot.purpose || "",
      prompt_suffix: "",
    },
  };
}

function selectedId(shot: ExpertShot): string | undefined {
  return [...shot.keyframes, ...shot.videos].find((item) => item.selected)?.candidate_id;
}

function toCandidate(item: ExpertCandidate, kind: ShotCandidate["kind"], node: string): ShotCandidate {
  return {
    candidate_id: item.candidate_id,
    kind,
    thumbnail_url: item.media_url,
    model: item.model,
    verdict: shotVerdictFromLegacy(item.verdict),
    score: item.verdict.visual_reviewed ? item.verdict.total : null,
    source_node: node,
    review: item.verdict,
  };
}

function serverTimeline(canvas: ExpertCanvas): ServerTimeline {
  return {
    overlays: (canvas.timeline?.overlays ?? []).map((item) => ({
      kind: item.kind,
      text: item.text,
    })),
    clips: (canvas.timeline?.clips ?? []).map((item) => ({
      clip_id: item.clip_id,
      transition_out: item.transition_out,
    })),
  };
}

function link(
  id: string,
  source: string,
  target: string,
  role: CanvasEdge["role"],
  sourceHandle: string,
): CanvasEdge {
  return {
    id,
    source,
    target,
    source_handle: sourceHandle,
    target_handle: "in",
    role,
    user_created: false,
  };
}

function lockAi(snapshot: CanvasSnapshot): CanvasSnapshot {
  snapshot.timeline = { ...snapshot.timeline, ai_label: true };
  snapshot.nodes = snapshot.nodes.map((node) =>
    node.kind === "final" ? { ...node, data: { ...node.data, ai_label: true as const } } : node,
  );
  return snapshot;
}

export function overlayPositions(nodes: { id: string; position: CanvasPoint }[]): Record<string, CanvasPoint> {
  return Object.fromEntries(nodes.map((node) => [node.id, { x: Math.round(node.position.x), y: Math.round(node.position.y) }]));
}
