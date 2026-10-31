/**
 * R2 ↔ R3 画布接口契约 v0（交付研发部，2026-10-31）。
 * 契约里的类型只放在这个文件。开发期读写走 `canvas-client.ts` 的 mock。
 * 和契约正文不一致的地方记在 `CANVAS_CONTRACT_NOTES`。
 */

import { verdictLabel, type Verdict } from "./expert";

export type { Verdict };

export const CANVAS_STORAGE_PREFIX = "hilatv.canvas.v0.";

/** 与 workers/qa/settings.py 的 PROJECT_RETRIES 对齐。mock 不读环境变量。 */
export const MOCK_RETRY_LIMIT = 12;

export const EMPTY_FRAME_COPY = "尚无画面";

export const AI_LABEL_COPY = "AI生成";

export const CANVAS_CONTRACT_NOTES = [
  "开发期和测试的画布读写都走 lib/canvas-client.ts 的 mock，不请求 /v1，因此不读 .env，也不打开 HILATV_LIVE。",
  "契约没有「修改节点正文」的写接口。需求文本、旁白、补充提示词先写进 mock 文档；再生这一镜时把当前旁白和补充提示词放进 regenerate 的 body。",
  "节点增加 user_created。只有用户新建的需求文本和参考图可以删除。示例节点为 false。",
  "候选增加可空 score，给检查器显示评分。未评审时 score 为 null，界面写「—」，不会显示成通过。",
  "GET 额外返回 sentence、budget、timeline，供顶栏、检查器和时间轴使用。契约原文的 GET 只有 nodes、edges、viewport、layout_version。",
  "mock 里每次写操作都让 layout_version 加 1。契约原文只要求布局接口返回新版本。",
  "mock 里 shot_id 与节点 id 相同。",
  "再生之后自动选中新候选。新候选 verdict 一律是 unreviewed，卡片因此显示未评审。",
  "选用候选时，时间轴里该镜的 candidate_id 跟着改成这一条。",
  "参考图节点可以先空着（upload_id 为空、thumbnail_url 为 null），上传后再补。",
  "镜头上的「上传替换参考图」写入 shot.data.reference_upload_id 和 reference_thumbnail_url。再生时和连进来的参考图一起读。",
  "成片节点和时间轴的 ai_label 固定为 true。写入里若出现 ai_label: false，返回 422，存储也不会改成 false。",
  "mock 不模拟 404。任意项目编号都会铺同一套示例，并按项目分开放在 localStorage。",
  "保存布局时，节点坐标四舍五入到整数像素。刷新后从 localStorage 读回位置和视口。",
  "左键拖空白处平移，滚轮缩放，按住 Shift 拖动框选。选中节点后用方向键移动，按住 Shift 移动更快。",
  "导出不生成视频文件，只在导出结果里保留「AI生成」，并且没有关闭开关。",
  "minZoom 0.25、maxZoom 1.75。原来的 0.8–1.4 看不出整张画布。",
  "检查器宽度 372px 写在画布自己的样式里，没有改 globals.css，也没有用任意值 Tailwind 类。",
  "质检文案只走 expert.ts 的 verdictLabel，不另写一套通过规则。",
  "项目已在后端时：读取走 GET /canvas，选用走 POST /expert/select，再生走 POST /expert/rerun（带 shot_id 和 prompt_suffix），时间轴保存走 POST /expert/timeline，上传走 POST /uploads。这些都经 lib/api.ts。",
  "上述现有接口失败或项目不存在时，演示画布回退到本地 mock，避免没有后端项目时页面空白。回退不会改写已成功的后端结果。",
  "现有 expert/timeline 只接收 overlays 和带 clip_id 的 clips，不写入点出点。入点出点和顺序先记在本地；提交时原样带回 overlays，因此「AI生成」不会被拿掉。",
  "布局、自建节点、自建连线、替换参考图、单镜再生、结构化时间轴走 R2 新接口。后端返回 404/405（R2 未合并）时回退到本地 overlay，演示不空白。",
  "布局保存遇到 409（版本冲突）会重新读画布，用服务端版本重试一次；写成功后清空本地 overlay，避免旧坐标盖住服务端结果。",
  "旧的 live 专家画布端到端测试在这条里跳过，界面演示改到 canvas-demo.spec.ts。",
] as const;

export type CanvasPoint = { x: number; y: number };

export type CanvasViewport = { x: number; y: number; zoom: number };

export type ShotVerdict = "unreviewed" | "pass" | "hard_fail";

export type CandidateKind = "keyframe" | "video" | "image";

export type EdgeRole = "reference" | "text" | "feeds_final" | "pipeline";

export type FreeNodeKind = "brief" | "ref_image" | "shot" | "final";

/** 含现有管线节点名。mock 只铺四类自由节点。 */
export type CanvasNodeKind = FreeNodeKind | (string & {});

export type ShotCandidate = {
  candidate_id: string;
  kind: CandidateKind;
  thumbnail_url?: string | null;
  model: string;
  verdict: ShotVerdict;
  /** 假设：契约候选没有分数字段。null 表示没有评分。 */
  score?: number | null;
  /** 现有 expert/select、expert/rerun 需要的节点名，例如 n08_keyframe。 */
  source_node?: string;
  /** 现有质检对象。有它时文案只走 verdictLabel。 */
  review?: Verdict;
};

export type ShotData = {
  shot_id: string;
  index: number;
  thumbnail_url?: string | null;
  duration_s: number;
  verdict: ShotVerdict;
  regen_count: number;
  candidates: ShotCandidate[];
  selected_candidate_id?: string | null;
  narration: string;
  prompt_suffix?: string;
  /** 假设：这一镜上传替换的参考图，不属于连线那边的参考图节点。 */
  reference_upload_id?: string | null;
  reference_thumbnail_url?: string | null;
  /** 假设：最近一次再生读到的上游，用来证明连线进了这一镜。 */
  reference_upload_ids?: string[];
  text_inputs?: string[];
  /** 选中候选的质检对象，文案走 verdictLabel。 */
  review?: Verdict;
};

export type RefImageData = {
  upload_id: string;
  thumbnail_url?: string | null;
};

export type BriefData = {
  text: string;
};

export type FinalData = {
  version_id?: string | null;
  ai_label: true;
};

export type PipelineData = {
  label?: string;
};

export type ContentCandidate = {
  candidate_id: string;
  kind: CandidateKind;
  uri?: string;
  thumbnail_url?: string | null;
  model: string;
  verdict: ShotVerdict;
  duration_s?: number | null;
};

/** 图片/视频节点：节点上写提示词，直接生成候选。 */
export type ImageData = {
  prompt: string;
  candidates: ContentCandidate[];
  selected_candidate_id?: string | null;
  thumbnail_url?: string | null;
};

export type VideoData = ImageData;

export type CanvasNodeData =
  | BriefData
  | RefImageData
  | ShotData
  | FinalData
  | PipelineData
  | ImageData;

export type CanvasNode = {
  id: string;
  kind: CanvasNodeKind;
  position: CanvasPoint;
  /** 假设：契约节点没有这个字段。 */
  user_created: boolean;
  data: CanvasNodeData;
};

export type CanvasEdge = {
  id: string;
  source: string;
  target: string;
  source_handle?: string | null;
  target_handle?: string | null;
  role: EdgeRole;
  user_created: boolean;
};

export type TimelineClip = {
  shot_id: string;
  candidate_id: string;
  in_s: number;
  out_s: number;
};

export type CanvasTimeline = {
  clips: TimelineClip[];
  ai_label: true;
  duration_s: number;
};

export type CanvasBudget = {
  used: number;
  limit: number;
  remaining: number;
};

export type ServerTimeline = {
  overlays: { kind: string; text: string }[];
  clips: { clip_id: string; transition_out: string }[];
};

export type CanvasSnapshot = {
  project_id: string;
  nodes: CanvasNode[];
  edges: CanvasEdge[];
  viewport: CanvasViewport;
  layout_version: number;
  /** 假设：契约 GET 没有这三项，界面需要。 */
  sentence: string;
  budget: CanvasBudget;
  timeline: CanvasTimeline;
  /** api：来自现有 GET /canvas。mock：后端没有这个项目时的演示底稿。 */
  origin?: "api" | "mock";
  /** 现有 POST /expert/timeline 的正文。入点出点不在这里。 */
  server_timeline?: ServerTimeline;
};

/** 现有接口之外的布局和自建节点。只存在浏览器本地。 */
export type CanvasOverlay = {
  layout_version: number;
  positions: Record<string, CanvasPoint>;
  viewport?: CanvasViewport;
  nodes: CanvasNode[];
  edges: CanvasEdge[];
  clips?: TimelineClip[];
  references?: Record<string, { upload_id: string; thumbnail_url?: string | null }>;
};

export type LayoutWrite = {
  layout_version: number;
  positions: Record<string, CanvasPoint>;
  viewport: CanvasViewport;
};

export type CreateNodeWrite = {
  kind: "brief" | "ref_image" | "image" | "video" | "script";
  position: CanvasPoint;
  data?: BriefData | RefImageData | { prompt?: string };
};

export type CreateEdgeWrite = {
  source: string;
  target: string;
  source_handle?: string | null;
  target_handle?: string | null;
  role?: EdgeRole;
};

export type RegenerateWrite = {
  narration?: string;
  prompt_suffix?: string;
};

export type ReferenceWrite = {
  upload_id: string;
  thumbnail_url?: string | null;
};

export type SelectWrite = {
  shot_id: string;
  candidate_id: string;
};

export type TimelineWrite = {
  clips: TimelineClip[];
  /** 契约规定不可写。出现且不为 true 时拒绝。 */
  ai_label?: boolean;
};

export type BriefPatch = { kind: "brief"; text: string };
export type ShotCopyPatch = { kind: "shot"; narration?: string; prompt_suffix?: string };
export type RefPatch = { kind: "ref_image"; upload_id: string; thumbnail_url?: string | null };
export type ContentPromptPatch = { kind: "prompt"; prompt: string };
export type NodeDataPatch = BriefPatch | ShotCopyPatch | RefPatch | ContentPromptPatch;

export const VERDICT_COPY: Record<ShotVerdict, "未评审" | "通过" | "硬伤"> = {
  unreviewed: "未评审",
  pass: "通过",
  hard_fail: "硬伤",
};

export const ROLE_COPY: Record<EdgeRole, string> = {
  reference: "参考图",
  text: "文本",
  feeds_final: "成片",
  pipeline: "工序",
};

const ROLE_BY_PAIR: Record<string, EdgeRole> = {
  "brief>shot": "text",
  "ref_image>shot": "reference",
  "shot>final": "feeds_final",
};

/** 没有完整质检对象时，先收成现有 Verdict，再交给 verdictLabel。 */
export function verdictAsLegacy(verdict: ShotVerdict): Verdict {
  if (verdict === "pass") {
    return {
      visual_reviewed: true,
      qa_passed: true,
      hard_fail: [],
      total: null,
      notes: "",
      blocked: false,
    };
  }
  if (verdict === "hard_fail") {
    return {
      visual_reviewed: true,
      qa_passed: false,
      hard_fail: ["sensitive"],
      total: null,
      notes: "",
      blocked: true,
    };
  }
  return {
    visual_reviewed: false,
    qa_passed: false,
    hard_fail: ["not_reviewed"],
    total: null,
    notes: "",
    blocked: false,
  };
}

export function shotVerdictLabel(verdict: ShotVerdict, review?: Verdict | null): string {
  return verdictLabel(review ?? verdictAsLegacy(verdict));
}

/** 先走 verdictLabel，未评审不会因为 qa_passed 变成通过。 */
export function shotVerdictFromLegacy(verdict: Verdict): ShotVerdict {
  const label = verdictLabel(verdict);
  if (label === "质检通过") return "pass";
  if (label === "未评审") return "unreviewed";
  return "hard_fail";
}

export function isShotData(data: CanvasNodeData): data is ShotData {
  return "shot_id" in data && "candidates" in data;
}

export function asShot(node: CanvasNode): ShotData | null {
  if (node.kind !== "shot" || !isShotData(node.data)) return null;
  return node.data;
}

export function asBrief(node: CanvasNode): BriefData | null {
  if (node.kind !== "brief" || !("text" in node.data)) return null;
  return node.data as BriefData;
}

export function asRef(node: CanvasNode): RefImageData | null {
  if (node.kind !== "ref_image" || !("upload_id" in node.data)) return null;
  return node.data as RefImageData;
}

export function asFinal(node: CanvasNode): FinalData | null {
  if (node.kind !== "final") return null;
  return node.data as FinalData;
}

export function connectionRole(sourceKind: string, targetKind: string): EdgeRole | null {
  return ROLE_BY_PAIR[`${sourceKind}>${targetKind}`] ?? null;
}

export function explainConnection(
  nodes: Pick<CanvasNode, "id" | "kind">[],
  edges: Pick<CanvasEdge, "source" | "target">[],
  source: string,
  target: string,
): string | null {
  if (source === target) return "不能把节点连到自己";
  const from = nodes.find((node) => node.id === source);
  const to = nodes.find((node) => node.id === target);
  if (!from || !to) return "连线的节点不存在";
  if (!connectionRole(from.kind, to.kind)) {
    return "只能把参考图或需求文本连到某一镜，或把某一镜连到成片";
  }
  if (edges.some((edge) => edge.source === source && edge.target === target)) {
    return "这两个节点已经连过";
  }
  if (reaches(edges, target, source)) return "这条线会绕回上游，不能连";
  return null;
}

export function clampNumber(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

export function roundTenth(value: number): number {
  return Math.round(value * 10) / 10;
}

export function trimClip(
  clip: TimelineClip,
  edge: "in" | "out",
  next: number,
  duration: number,
): TimelineClip {
  const minGap = 0.1;
  if (edge === "in") {
    const in_s = roundTenth(clampNumber(next, 0, Math.max(0, clip.out_s - minGap)));
    return { ...clip, in_s };
  }
  const out_s = roundTenth(clampNumber(next, clip.in_s + minGap, duration));
  return { ...clip, out_s };
}

export function reorderClips(clips: TimelineClip[], from: number, to: number): TimelineClip[] {
  if (from === to || from < 0 || to < 0 || from >= clips.length || to >= clips.length) {
    return clips.slice();
  }
  const next = clips.slice();
  const [item] = next.splice(from, 1);
  next.splice(to, 0, item);
  return next;
}

export function timelineDuration(clips: TimelineClip[]): number {
  const total = clips.reduce((sum, clip) => sum + Math.max(0, clip.out_s - clip.in_s), 0);
  return roundTenth(total);
}

export type UpstreamRef = { nodeId: string; uploadId: string; thumbnailUrl: string | null };
export type UpstreamText = { nodeId: string; text: string };

export function upstreamFor(
  doc: Pick<CanvasSnapshot, "nodes" | "edges">,
  nodeId: string,
): { refs: UpstreamRef[]; texts: UpstreamText[] } {
  const refs: UpstreamRef[] = [];
  const texts: UpstreamText[] = [];
  for (const edge of doc.edges) {
    if (edge.target !== nodeId) continue;
    const source = doc.nodes.find((node) => node.id === edge.source);
    if (!source) continue;
    if (edge.role === "reference") {
      const data = asRef(source);
      if (!data) continue;
      refs.push({
        nodeId: source.id,
        uploadId: data.upload_id,
        thumbnailUrl: data.thumbnail_url ?? null,
      });
    }
    if (edge.role === "text") {
      const data = asBrief(source);
      if (!data) continue;
      texts.push({ nodeId: source.id, text: data.text });
    }
  }
  return { refs, texts };
}

export function shotById(doc: Pick<CanvasSnapshot, "nodes">, shotId: string): CanvasNode | undefined {
  return doc.nodes.find((node) => node.kind === "shot" && asShot(node)?.shot_id === shotId);
}

function reaches(
  edges: Pick<CanvasEdge, "source" | "target">[],
  start: string,
  goal: string,
): boolean {
  const next = new Map<string, string[]>();
  for (const edge of edges) {
    const list = next.get(edge.source) ?? [];
    list.push(edge.target);
    next.set(edge.source, list);
  }
  const seen = new Set<string>();
  const stack = [start];
  while (stack.length > 0) {
    const current = stack.pop();
    if (!current || seen.has(current)) continue;
    if (current === goal) return true;
    seen.add(current);
    for (const id of next.get(current) ?? []) stack.push(id);
  }
  return false;
}
