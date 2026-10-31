/**
 * 画布 mock。形状对齐 canvas-contract.ts。不访问网络，不读环境变量。
 */

import { finalFrame, productFrame, shotFrame } from "./canvas-frames";
import {
  AI_LABEL_COPY,
  asBrief,
  asFinal,
  asRef,
  asShot,
  CANVAS_STORAGE_PREFIX,
  connectionRole,
  explainConnection,
  MOCK_RETRY_LIMIT,
  roundTenth,
  shotById,
  timelineDuration,
  upstreamFor,
  type CanvasEdge,
  type CanvasNode,
  type CanvasSnapshot,
  type CreateEdgeWrite,
  type CreateNodeWrite,
  type LayoutWrite,
  type NodeDataPatch,
  type ReferenceWrite,
  type RegenerateWrite,
  type SelectWrite,
  type ShotCandidate,
  type ShotData,
  type TimelineClip,
  type TimelineWrite,
} from "./canvas-contract";

export class CanvasRequestError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "CanvasRequestError";
    this.status = status;
  }
}

export type KeyValueStore = {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
};

export function canvasStorageKey(projectId: string): string {
  return `${CANVAS_STORAGE_PREFIX}${projectId}`;
}

export function seedCanvas(projectId: string): CanvasSnapshot {
  const sentence = "给新款手持云台做一条 15 秒产品短片，突出稳和轻。";
  const shot1 = "shot-1";
  const shot2 = "shot-2";
  const selected1 = "shot1-a";
  const selected2 = "shot2-a";
  const nodes: CanvasNode[] = [
    {
      id: "brief-1",
      kind: "brief",
      position: { x: 40, y: 24 },
      user_created: false,
      data: { text: sentence },
    },
    {
      id: "ref-product",
      kind: "ref_image",
      position: { x: 40, y: 280 },
      user_created: false,
      data: { upload_id: "up-product", thumbnail_url: productFrame() },
    },
    {
      id: shot1,
      kind: "shot",
      position: { x: 520, y: 24 },
      user_created: false,
      data: {
        shot_id: shot1,
        index: 1,
        thumbnail_url: shotFrame(1),
        duration_s: 4,
        verdict: "pass",
        regen_count: 0,
        selected_candidate_id: selected1,
        narration: "云台托住设备，画面几乎不动。",
        prompt_suffix: "",
        candidates: [
          {
            candidate_id: selected1,
            kind: "keyframe",
            thumbnail_url: shotFrame(1),
            model: "试用画面",
            verdict: "pass",
            score: 8.6,
          },
          {
            candidate_id: "shot1-b",
            kind: "keyframe",
            thumbnail_url: shotFrame(3),
            model: "试用画面",
            verdict: "hard_fail",
            score: 2.1,
          },
        ],
      },
    },
    {
      id: shot2,
      kind: "shot",
      position: { x: 520, y: 460 },
      user_created: false,
      data: {
        shot_id: shot2,
        index: 2,
        thumbnail_url: shotFrame(2),
        duration_s: 6,
        verdict: "unreviewed",
        regen_count: 1,
        selected_candidate_id: selected2,
        narration: "单手提起，重量放在掌心。",
        prompt_suffix: "手持，背景干净",
        candidates: [
          {
            candidate_id: selected2,
            kind: "keyframe",
            thumbnail_url: shotFrame(2),
            model: "试用画面",
            verdict: "unreviewed",
            score: null,
          },
          {
            candidate_id: "shot2-b",
            kind: "keyframe",
            thumbnail_url: shotFrame(1),
            model: "试用画面",
            verdict: "pass",
            score: 8.2,
          },
          {
            candidate_id: "shot2-c",
            kind: "video",
            thumbnail_url: null,
            model: "试用视频",
            verdict: "unreviewed",
            score: null,
          },
        ],
      },
    },
    {
      id: "final-1",
      kind: "final",
      position: { x: 980, y: 200 },
      user_created: false,
      data: { version_id: "v1", ai_label: true },
    },
  ];
  const edges: CanvasEdge[] = [
    edge("edge-brief-shot-1", "brief-1", shot1, "text", "text", "in", false),
    edge("edge-brief-shot-2", "brief-1", shot2, "text", "text", "in", false),
    edge("edge-ref-shot-1", "ref-product", shot1, "reference", "reference", "in", false),
    edge("edge-shot-1-final", shot1, "final-1", "feeds_final", "out", "in", false),
    edge("edge-shot-2-final", shot2, "final-1", "feeds_final", "out", "in", false),
  ];
  const clips: TimelineClip[] = [
    { shot_id: shot1, candidate_id: selected1, in_s: 0, out_s: 4 },
    { shot_id: shot2, candidate_id: selected2, in_s: 0, out_s: 6 },
  ];
  return lockLabels({
    project_id: projectId,
    nodes,
    edges,
    viewport: { x: 24, y: 16, zoom: 0.62 },
    layout_version: 1,
    sentence,
    budget: { used: 1, limit: MOCK_RETRY_LIMIT, remaining: MOCK_RETRY_LIMIT - 1 },
    timeline: { clips, ai_label: true, duration_s: timelineDuration(clips) },
  });
}

export class CanvasMockStore {
  private readonly key: string;

  constructor(
    private readonly storage: KeyValueStore,
    private readonly projectId: string,
  ) {
    if (!projectId.trim()) throw new CanvasRequestError(422, "缺少项目编号");
    this.key = canvasStorageKey(projectId);
  }

  load(): CanvasSnapshot {
    return structuredClone(this.read());
  }

  saveLayout(body: LayoutWrite): CanvasSnapshot {
    return this.commit((doc) => {
      if (body.layout_version !== doc.layout_version) {
        throw new CanvasRequestError(409, "画布已被其他修改更新，请刷新后再保存");
      }
      for (const [id, position] of Object.entries(body.positions)) {
        const node = doc.nodes.find((item) => item.id === id);
        if (!node || !position) continue;
        node.position = { x: Math.round(position.x), y: Math.round(position.y) };
      }
      doc.viewport = {
        x: body.viewport.x,
        y: body.viewport.y,
        zoom: body.viewport.zoom,
      };
      doc.layout_version += 1;
    });
  }

  createNode(body: CreateNodeWrite): CanvasSnapshot {
    return this.commit((doc) => {
      if (body.kind !== "brief" && body.kind !== "ref_image") {
        throw new CanvasRequestError(422, "这里只能新建需求文本或参考图");
      }
      const id = nextId(doc, body.kind === "brief" ? "brief" : "ref");
      const data =
        body.kind === "brief"
          ? { text: body.data && "text" in body.data ? body.data.text : "在这里写下要交给某一镜的话" }
          : {
              upload_id: body.data && "upload_id" in body.data ? body.data.upload_id : "",
              thumbnail_url:
                body.data && "thumbnail_url" in body.data ? (body.data.thumbnail_url ?? null) : null,
            };
      doc.nodes.push({
        id,
        kind: body.kind,
        position: { x: Math.round(body.position.x), y: Math.round(body.position.y) },
        user_created: true,
        data,
      });
      doc.layout_version += 1;
    });
  }

  deleteNode(nodeId: string): CanvasSnapshot {
    return this.commit((doc) => {
      const node = doc.nodes.find((item) => item.id === nodeId);
      if (!node) throw new CanvasRequestError(404, "没有这个节点");
      if (!node.user_created || (node.kind !== "brief" && node.kind !== "ref_image")) {
        throw new CanvasRequestError(422, "只能删除你新建的文本或参考图");
      }
      doc.nodes = doc.nodes.filter((item) => item.id !== nodeId);
      doc.edges = doc.edges.filter((item) => item.source !== nodeId && item.target !== nodeId);
      doc.layout_version += 1;
    });
  }

  createEdge(body: CreateEdgeWrite): CanvasSnapshot {
    return this.commit((doc) => {
      const reason = explainConnection(doc.nodes, doc.edges, body.source, body.target);
      if (reason) throw new CanvasRequestError(422, reason);
      const source = doc.nodes.find((node) => node.id === body.source);
      const target = doc.nodes.find((node) => node.id === body.target);
      if (!source || !target) throw new CanvasRequestError(422, "连线的节点不存在");
      const role = connectionRole(source.kind, target.kind);
      if (!role) throw new CanvasRequestError(422, "只能把参考图或需求文本连到某一镜，或把某一镜连到成片");
      if (body.role && body.role !== role) {
        throw new CanvasRequestError(422, "这条线的类型和两端节点对不上");
      }
      doc.edges.push(
        edge(
          `edge-${body.source}-${body.target}`,
          body.source,
          body.target,
          role,
          body.source_handle ?? (role === "feeds_final" ? "out" : role),
          body.target_handle ?? "in",
          true,
        ),
      );
      doc.layout_version += 1;
    });
  }

  deleteEdge(edgeId: string): CanvasSnapshot {
    return this.commit((doc) => {
      if (!doc.edges.some((item) => item.id === edgeId)) {
        throw new CanvasRequestError(404, "没有这条线");
      }
      doc.edges = doc.edges.filter((item) => item.id !== edgeId);
      doc.layout_version += 1;
    });
  }

  updateNodeData(nodeId: string, patch: NodeDataPatch): CanvasSnapshot {
    return this.commit((doc) => {
      const node = doc.nodes.find((item) => item.id === nodeId);
      if (!node) throw new CanvasRequestError(404, "没有这个节点");
      if (patch.kind === "brief") {
        const data = asBrief(node);
        if (!data || node.kind !== "brief") throw new CanvasRequestError(422, "这不是需求文本");
        data.text = patch.text;
        if (node.id === "brief-1") doc.sentence = patch.text;
      } else if (patch.kind === "shot") {
        const data = asShot(node);
        if (!data) throw new CanvasRequestError(422, "这不是镜头");
        if (patch.narration !== undefined) data.narration = patch.narration;
        if (patch.prompt_suffix !== undefined) data.prompt_suffix = patch.prompt_suffix;
      } else {
        const data = asRef(node);
        if (!data) throw new CanvasRequestError(422, "这不是参考图");
        data.upload_id = patch.upload_id;
        data.thumbnail_url = patch.thumbnail_url ?? null;
      }
      doc.layout_version += 1;
    });
  }

  regenerate(shotId: string, body: RegenerateWrite = {}): CanvasSnapshot {
    return this.commit((doc) => {
      if (doc.budget.used >= doc.budget.limit) {
        throw new CanvasRequestError(409, "重生次数已用完");
      }
      const node = shotById(doc, shotId);
      const data = node ? asShot(node) : null;
      if (!node || !data) throw new CanvasRequestError(404, "没有这一镜");
      if (body.narration !== undefined) data.narration = body.narration;
      if (body.prompt_suffix !== undefined) data.prompt_suffix = body.prompt_suffix;
      const upstream = upstreamFor(doc, node.id);
      const uploadIds = upstream.refs.map((item) => item.uploadId).filter((id) => id.length > 0);
      if (data.reference_upload_id) uploadIds.unshift(data.reference_upload_id);
      data.reference_upload_ids = uploadIds;
      data.text_inputs = upstream.texts.map((item) => item.text);
      data.regen_count += 1;
      const candidate: ShotCandidate = {
        candidate_id: `${data.shot_id}-r${data.regen_count}`,
        kind: "video",
        thumbnail_url: null,
        model: "试用视频",
        verdict: "unreviewed",
        score: null,
      };
      data.candidates = [...data.candidates, candidate];
      data.selected_candidate_id = candidate.candidate_id;
      data.thumbnail_url = null;
      data.verdict = "unreviewed";
      for (const clip of doc.timeline.clips) {
        if (clip.shot_id === data.shot_id) clip.candidate_id = candidate.candidate_id;
      }
      doc.budget.used += 1;
      doc.budget.remaining = Math.max(0, doc.budget.limit - doc.budget.used);
      doc.layout_version += 1;
    });
  }

  replaceReference(shotId: string, body: ReferenceWrite): CanvasSnapshot {
    return this.commit((doc) => {
      if (!body.upload_id.trim()) throw new CanvasRequestError(422, "缺少参考图");
      const data = shotData(doc, shotId);
      data.reference_upload_id = body.upload_id;
      data.reference_thumbnail_url = body.thumbnail_url ?? null;
      doc.layout_version += 1;
    });
  }

  selectCandidate(body: SelectWrite): CanvasSnapshot {
    return this.commit((doc) => {
      const data = shotData(doc, body.shot_id);
      const candidate = data.candidates.find((item) => item.candidate_id === body.candidate_id);
      if (!candidate) throw new CanvasRequestError(404, "没有这条候选");
      data.selected_candidate_id = candidate.candidate_id;
      data.thumbnail_url = candidate.thumbnail_url ?? null;
      data.verdict = candidate.verdict;
      for (const clip of doc.timeline.clips) {
        if (clip.shot_id === data.shot_id) clip.candidate_id = candidate.candidate_id;
      }
      doc.layout_version += 1;
    });
  }

  saveTimeline(body: TimelineWrite): CanvasSnapshot {
    return this.commit((doc) => {
      if ("ai_label" in body && body.ai_label !== true) {
        throw new CanvasRequestError(422, "AI 生成标识不能关闭");
      }
      if (!Array.isArray(body.clips) || body.clips.length === 0) {
        throw new CanvasRequestError(422, "时间轴至少留一段");
      }
      const clips = body.clips.map((clip) => checkClip(doc, clip));
      doc.timeline = {
        clips,
        ai_label: true,
        duration_s: timelineDuration(clips),
      };
      doc.layout_version += 1;
    });
  }

  private commit(mutator: (doc: CanvasSnapshot) => void): CanvasSnapshot {
    const doc = structuredClone(this.read());
    mutator(doc);
    const locked = lockLabels(doc);
    this.storage.setItem(this.key, JSON.stringify(locked));
    return structuredClone(locked);
  }

  private read(): CanvasSnapshot {
    const raw = this.storage.getItem(this.key);
    if (!raw) return seedCanvas(this.projectId);
    try {
      return normalize(JSON.parse(raw) as unknown, this.projectId);
    } catch (error) {
      if (error instanceof CanvasRequestError) throw error;
      return seedCanvas(this.projectId);
    }
  }
}

export async function readImageFile(file: File): Promise<{ upload_id: string; thumbnail_url: string }> {
  if (!file.type.startsWith("image/")) throw new CanvasRequestError(415, "只接收图片");
  const thumbnail_url = await readAsDataUrl(file);
  const id = typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : String(Date.now());
  return { upload_id: `up-${id}`, thumbnail_url };
}

function readAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.addEventListener("load", () => {
      if (typeof reader.result === "string") resolve(reader.result);
      else reject(new CanvasRequestError(422, "没有读到这张图"));
    });
    reader.addEventListener("error", () => reject(new CanvasRequestError(422, "没有读到这张图")));
    reader.readAsDataURL(file);
  });
}

function edge(
  id: string,
  source: string,
  target: string,
  role: CanvasEdge["role"],
  sourceHandle: string,
  targetHandle: string,
  userCreated: boolean,
): CanvasEdge {
  return {
    id,
    source,
    target,
    source_handle: sourceHandle,
    target_handle: targetHandle,
    role,
    user_created: userCreated,
  };
}

function nextId(doc: CanvasSnapshot, prefix: string): string {
  let n = doc.nodes.length + 1;
  let id = `${prefix}-${n}`;
  while (doc.nodes.some((node) => node.id === id)) {
    n += 1;
    id = `${prefix}-${n}`;
  }
  return id;
}

function shotData(doc: CanvasSnapshot, shotId: string): ShotData {
  const node = shotById(doc, shotId);
  const data = node ? asShot(node) : null;
  if (!data) throw new CanvasRequestError(404, "没有这一镜");
  return data;
}

function checkClip(doc: CanvasSnapshot, clip: TimelineClip): TimelineClip {
  const data = shotData(doc, clip.shot_id);
  if (!data.candidates.some((item) => item.candidate_id === clip.candidate_id)) {
    throw new CanvasRequestError(422, "这一段用的候选不属于该镜头");
  }
  if (!(clip.in_s >= 0) || !(clip.out_s > clip.in_s) || clip.out_s - clip.in_s < 0.1) {
    throw new CanvasRequestError(422, "入点不能晚于出点");
  }
  if (clip.out_s > data.duration_s + 0.001) {
    throw new CanvasRequestError(422, "入点出点必须落在这一镜的时长里");
  }
  return {
    shot_id: clip.shot_id,
    candidate_id: clip.candidate_id,
    in_s: roundTenth(clip.in_s),
    out_s: roundTenth(clip.out_s),
  };
}

function lockLabels(doc: CanvasSnapshot): CanvasSnapshot {
  doc.timeline = { ...doc.timeline, ai_label: true };
  for (const node of doc.nodes) {
    if (node.kind !== "final") continue;
    const data = asFinal(node);
    node.data = { version_id: data?.version_id ?? null, ai_label: true };
  }
  if (!doc.timeline.clips) doc.timeline.clips = [];
  doc.timeline.duration_s = timelineDuration(doc.timeline.clips);
  return doc;
}

function normalize(raw: unknown, projectId: string): CanvasSnapshot {
  if (!raw || typeof raw !== "object") return seedCanvas(projectId);
  const doc = raw as Partial<CanvasSnapshot>;
  if (!Array.isArray(doc.nodes) || !Array.isArray(doc.edges) || !doc.timeline || !doc.viewport) {
    return seedCanvas(projectId);
  }
  doc.project_id = projectId;
  if (typeof doc.layout_version !== "number") doc.layout_version = 1;
  if (!doc.budget) doc.budget = { used: 0, limit: MOCK_RETRY_LIMIT, remaining: MOCK_RETRY_LIMIT };
  doc.sentence = doc.sentence ?? "";
  return lockLabels(doc as CanvasSnapshot);
}

export const AI_LABEL = AI_LABEL_COPY;
