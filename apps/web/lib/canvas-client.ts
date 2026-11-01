/**
 * 画布传输。
 * 已有能力走 lib/api.ts：GET /canvas、POST /expert/select、POST /expert/rerun、POST /expert/timeline、POST /uploads。
 * R2 合并后：布局、自建节点、自建连线、替换参考图、单镜再生、结构化时间轴都请求真接口。
 * 真实项目的读取/写入失败必须显式报告；本地演示仅在显式 demo 模式启用。
 */

import { apiFetch, errorMessage } from "./api";
import {
  adaptLegacyCanvas,
  buildRerunBody,
  buildSelectBody,
  emptyOverlay,
  isLegacyCanvas,
  normalizeContractCanvas,
} from "./canvas-adapt";
import {
  CanvasMockStore,
  CanvasRequestError,
  readImageFile,
  type KeyValueStore,
} from "./canvas-mock";
import type {
  CanvasSnapshot,
  CreateEdgeWrite,
  CreateNodeWrite,
  LayoutWrite,
  NodeDataPatch,
  ReferenceWrite,
  RegenerateWrite,
  SelectWrite,
  TimelineWrite,
} from "./canvas-contract";
import { asShot, connectionRole, explainConnection, shotById, type CanvasEdge, type CanvasNode } from "./canvas-contract";

export type CanvasClient = {
  load(): Promise<CanvasSnapshot>;
  saveLayout(body: LayoutWrite): Promise<CanvasSnapshot>;
  stageLayout(body: LayoutWrite): void;
  createNode(body: CreateNodeWrite): Promise<CanvasSnapshot>;
  deleteNode(nodeId: string): Promise<CanvasSnapshot>;
  createEdge(body: CreateEdgeWrite): Promise<CanvasSnapshot>;
  deleteEdge(edgeId: string): Promise<CanvasSnapshot>;
  updateNodeData(nodeId: string, patch: NodeDataPatch): Promise<CanvasSnapshot>;
  stageNodeData(nodeId: string, patch: NodeDataPatch): CanvasSnapshot;
  flushNodeData(): Promise<CanvasSnapshot>;
  regenerate(shotId: string, body?: RegenerateWrite): Promise<CanvasSnapshot>;
  replaceReference(shotId: string, body: ReferenceWrite): Promise<CanvasSnapshot>;
  selectCandidate(body: SelectWrite): Promise<CanvasSnapshot>;
  saveTimeline(body: TimelineWrite): Promise<CanvasSnapshot>;
  uploadImage(file: File): Promise<{ upload_id: string; thumbnail_url: string }>;
  buildStoryboard(sentence: string): Promise<CanvasSnapshot>;
  generateNode(nodeId: string, body?: { prompt?: string; count?: number }): Promise<CanvasSnapshot>;
  startFilm(sentence: string): Promise<void>;
  releaseFilm(): Promise<void>;
};

const OVERLAY_PREFIX = "hilatv.canvas.overlay.v0.";

/** R2 新接口在老后端上还不存在：这两个状态回退到本地 overlay。 */
const MISSING_ROUTE = new Set([404, 405]);

function canvasPath(projectId: string, suffix: string): string {
  return `/v1/projects/${encodeURIComponent(projectId)}${suffix}`;
}

export function createCanvasClient(
  projectId: string, storage?: KeyValueStore, options: { demo?: boolean } = {},
): CanvasClient {
  const memory = storage ?? browserStorage();
  const store = new CanvasMockStore(memory, projectId);
  let last: CanvasSnapshot | null = null;
  const tabKey = "hilatv.canvas.draft-tab";
  let tabId = "local";
  if (typeof window !== "undefined") {
    tabId = window.sessionStorage.getItem(tabKey) || crypto.randomUUID();
    window.sessionStorage.setItem(tabKey, tabId);
  }
  const draftKey = `hilatv.canvas.node-drafts.v1.${projectId}.${tabId}`;
  let pending: Record<string, NodeDataPatch> = {};
  try {
    const saved: unknown = JSON.parse(memory.getItem(draftKey) || "{}");
    if (saved && typeof saved === "object" && !Array.isArray(saved)) {
      pending = Object.fromEntries(Object.entries(saved).filter(([, item]) => item && typeof item === "object" && ["shot", "brief", "ref_image", "image", "video", "script", "audio"].includes(item.kind)));
    }
  } catch { /* Corrupt backups are not server data. */ }
  let pendingLayout: LayoutWrite | null = null;
  const layoutKey = `${draftKey}.layout`;
  try {
    const saved = JSON.parse(memory.getItem(layoutKey) || "null");
    if (saved && typeof saved.layout_version === "number" && saved.positions && saved.viewport) pendingLayout = saved;
  } catch { /* Invalid local layout is not an acknowledged server revision. */ }
  let flushing: Promise<CanvasSnapshot> | null = null;

  function savePending() {
    if (Object.keys(pending).length) memory.setItem(draftKey, JSON.stringify(pending));
    else memory.removeItem(draftKey);
  }

  function withPending(doc: CanvasSnapshot): CanvasSnapshot {
    const nodes = doc.nodes.map((node) => {
      const patch = pending[node.id];
      if (!patch || patch.kind !== node.kind) return node;
      if (patch.kind === "shot") return { ...node, data: { ...node.data, ...(typeof patch.narration === "string" ? { narration: patch.narration } : {}), ...(typeof patch.prompt_suffix === "string" ? { prompt_suffix: patch.prompt_suffix } : {}) } };
      if (patch.kind === "brief") return { ...node, data: { ...node.data, text: patch.text } };
      if (patch.kind === "ref_image") return { ...node, data: { ...node.data, upload_id: patch.upload_id, thumbnail_url: patch.thumbnail_url } };
      return { ...node, data: { ...node.data, prompt: patch.prompt } };
    });
    return {
      ...doc,
      nodes: pendingLayout ? nodes.map((node) => pendingLayout!.positions[node.id] ? { ...node, position: pendingLayout!.positions[node.id] } : node) : nodes,
      viewport: pendingLayout?.viewport || doc.viewport,
      pending_edits: Object.keys(pending).length > 0 || pendingLayout !== null,
    };
  }

  function resetOverlay() {
    memory.removeItem(OVERLAY_PREFIX + projectId);
  }

  function contractWith(body: unknown): CanvasSnapshot | null {
    const normalized = normalizeContractCanvas(body);
    if (normalized) {
      if (last && normalized.layout_version < last.layout_version) return null;
      return withPending({ ...normalized, project_id: projectId, origin: "api" });
    }
    return null;
  }

  function remember(snapshot: CanvasSnapshot): CanvasSnapshot {
    last = snapshot;
    return snapshot;
  }

  async function loadFromApi(): Promise<CanvasSnapshot> {
    let response: Response;
    try {
      response = await apiFetch(canvasPath(projectId, "/canvas"));
    } catch {
      throw new CanvasRequestError(0, "连接中断，未能读取项目。请重试，原项目不会被替换。");
    }
    if (!response.ok) throw new CanvasRequestError(response.status, await errorMessage(response));
    let body: unknown;
    try {
      body = await response.json();
    } catch {
      throw new CanvasRequestError(502, "项目返回了无效数据，请重试");
    }
    const normalized = normalizeContractCanvas(body);
    if (normalized) return withPending({ ...normalized, project_id: projectId, origin: "api" });
    if (isLegacyCanvas(body)) return withPending(adaptLegacyCanvas(body, emptyOverlay()));
    throw new CanvasRequestError(502, "项目数据格式无法读取，原项目未被修改");
  }

  return {
    async load() {
      if (options.demo) return remember(markMock(store.load()));
      return remember(await loadFromApi());
    },

    stageLayout(body) {
      pendingLayout = body;
      memory.setItem(layoutKey, JSON.stringify(body));
    },

    async saveLayout(body) {
      const current = last ?? (await this.load());
      if (current.origin === "api") {
        this.stageLayout(body);
        const write = {
          layout_version: body.layout_version,
          positions: body.positions,
          viewport: body.viewport,
        };
        const response = await sendJson(canvasPath(projectId, "/canvas/layout"), "PUT", write);
        if (!response.ok) throw new CanvasRequestError(response.status, await errorMessage(response));
        const saved = (await response.json()) as { layout_version?: number };
        if (JSON.stringify(pendingLayout) === JSON.stringify(body)) {
          pendingLayout = null;
          memory.removeItem(layoutKey);
        }
        resetOverlay();
        const remote = await loadFromApi();
        if (remote) return remember(remote);
        return remember({
          ...current,
          layout_version: saved.layout_version ?? current.layout_version + 1,
          viewport: body.viewport,
          nodes: current.nodes.map((node) =>
            body.positions[node.id] ? { ...node, position: body.positions[node.id] } : node,
          ),
        });
      }
      return remember(markMock(store.saveLayout(body)));
    },

    async createNode(body) {
      const current = last ?? (await this.load());
      if (current.origin !== "api") return remember(markMock(store.createNode(body)));
      const response = await sendJson(canvasPath(projectId, "/canvas/nodes"), "POST", {
        kind: body.kind,
        position: body.position,
        data: body.data ?? {},
      });

      if (!response.ok) throw new CanvasRequestError(response.status, await errorMessage(response));
      const created = (await response.json()) as CanvasNode & { layout_version?: number };
      resetOverlay();
      const remote = await loadFromApi();
      if (remote) return remember(remote);
      return remember({
        ...current,
        nodes: [...current.nodes, created],
        layout_version: created.layout_version ?? current.layout_version + 1,
      });
    },

    async deleteNode(nodeId) {
      const current = last ?? (await this.load());
      if (current.origin !== "api") return remember(markMock(store.deleteNode(nodeId)));
      const response = await apiFetch(
        canvasPath(projectId, `/canvas/nodes/${encodeURIComponent(nodeId)}`),
        { method: "DELETE" },
      );

      if (!response.ok) throw new CanvasRequestError(response.status, await errorMessage(response));
      await response.json().catch(() => null);
      resetOverlay();
      const remote = await loadFromApi();
      if (remote) return remember(remote);
      const drop = (edge: CanvasEdge) => edge.source !== nodeId && edge.target !== nodeId;
      return remember({
        ...current,
        nodes: current.nodes.filter((node) => node.id !== nodeId),
        edges: current.edges.filter(drop),
      });
    },

    async createEdge(body) {
      const current = last ?? (await this.load());
      if (current.origin !== "api") return remember(markMock(store.createEdge(body)));
      const reason = explainConnection(current.nodes, current.edges, body.source, body.target);
      if (reason) throw new CanvasRequestError(422, reason);
      const source = current.nodes.find((node) => node.id === body.source);
      const target = current.nodes.find((node) => node.id === body.target);
      const role = source && target ? connectionRole(source.kind, target.kind) : null;
      if (!role) throw new CanvasRequestError(422, "只能把参考图或需求文本连到某一镜，或把某一镜连到成片");
      const response = await sendJson(canvasPath(projectId, "/canvas/edges"), "POST", {
        source: body.source,
        target: body.target,
        role: body.role ?? role,
        source_handle: body.source_handle ?? (role === "feeds_final" ? "out" : role),
        target_handle: body.target_handle ?? "in",
      });

      if (!response.ok) throw new CanvasRequestError(response.status, await errorMessage(response));
      const created = (await response.json()) as CanvasEdge & { layout_version?: number };
      resetOverlay();
      const remote = await loadFromApi();
      if (remote) return remember(remote);
      return remember({
        ...current,
        edges: [...current.edges, created],
        layout_version: created.layout_version ?? current.layout_version + 1,
      });
    },

    async deleteEdge(edgeId) {
      const current = last ?? (await this.load());
      if (current.origin !== "api") return remember(markMock(store.deleteEdge(edgeId)));
      const response = await apiFetch(
        canvasPath(projectId, `/canvas/edges/${encodeURIComponent(edgeId)}`),
        { method: "DELETE" },
      );

      if (!response.ok) throw new CanvasRequestError(response.status, await errorMessage(response));
      await response.json().catch(() => null);
      resetOverlay();
      const remote = await loadFromApi();
      if (remote) return remember(remote);
      return remember({ ...current, edges: current.edges.filter((edge) => edge.id !== edgeId) });
    },

    stageNodeData(nodeId, patch) {
      if (!last) throw new CanvasRequestError(409, "请先等待项目读取完成");
      if (last.origin !== "api") return remember(markMock(store.updateNodeData(nodeId, patch)));
      pending[nodeId] = { ...(pending[nodeId] || {}), ...patch } as NodeDataPatch;
      savePending();
      return remember(withPending(last));
    },

    flushNodeData() {
      if (flushing) return flushing;
      const run = (async () => {
        const current = last ?? (await this.load());
        if (current.origin !== "api") return current;
        if (pendingLayout) await this.saveLayout(pendingLayout);
        while (Object.keys(pending).length) {
          const [nodeId, patch] = Object.entries(pending)[0];
          const data = patch.kind === "brief" ? { text: patch.text }
            : patch.kind === "ref_image" ? { upload_id: patch.upload_id }
              : patch.kind === "shot" ? { narration: patch.narration, prompt_suffix: patch.prompt_suffix }
                : { prompt: patch.prompt };
          const response = await sendJson(canvasPath(projectId, `/canvas/nodes/${encodeURIComponent(nodeId)}`), "PATCH", { data });
          if (!response.ok) throw new CanvasRequestError(response.status, await errorMessage(response));
          await response.json();
          if (JSON.stringify(pending[nodeId]) === JSON.stringify(patch)) delete pending[nodeId];
          savePending();
        }
        resetOverlay();
        return remember(await loadFromApi());
      })();
      flushing = run;
      void run.then(() => { flushing = null; }, () => { flushing = null; });
      return run;
    },

    async updateNodeData(nodeId, patch) {
      this.stageNodeData(nodeId, patch);
      return this.flushNodeData();
    },

    async regenerate(shotId, body) {
      await this.flushNodeData();
      const current = last ?? (await this.load());
      const shot = shotById(current, shotId);
      const data = shot ? asShot(shot) : null;
      const selected = data?.candidates.find((item) => item.candidate_id === data.selected_candidate_id);
      const suffix = body?.prompt_suffix ?? data?.prompt_suffix ?? "";
      const narration = body?.narration ?? data?.narration ?? "";
      if (current.origin === "api") {
        const response = await sendJson(
          canvasPath(projectId, `/shots/${encodeURIComponent(shotId)}/regenerate`),
          "POST",
          { prompt_suffix: suffix, narration },
        );
        if (!MISSING_ROUTE.has(response.status)) {
          if (!response.ok) throw new CanvasRequestError(response.status, await errorMessage(response));
          const parsed = (await response.json()) as { canvas?: unknown };
          const remote = contractWith(parsed.canvas);
          if (remote) return remember(remote);
          const reloaded = await loadFromApi();
          if (reloaded) return remember(reloaded);
          throw new CanvasRequestError(502, "重做之后没有拿到画布");
        }
      }
      const payload = buildRerunBody(shotId, selected, suffix);
      if (current.origin === "api") {
        const response = await postJson(`/v1/projects/${encodeURIComponent(projectId)}/expert/rerun`, payload);
        if (!response.ok) throw new CanvasRequestError(response.status, await errorMessage(response));
        const parsed = (await response.json()) as { canvas?: unknown };
        if (parsed.canvas && isLegacyCanvas(parsed.canvas)) return remember(adaptLegacyCanvas(parsed.canvas, emptyOverlay()));
        const remote = contractWith(parsed.canvas);
        if (remote) return remember(remote);
        const reloaded = await loadFromApi();
        if (reloaded) return remember(reloaded);
        throw new CanvasRequestError(502, "重跑之后没有拿到画布");
      }
      return remember(markMock(store.regenerate(shotId, body)));
    },

    async replaceReference(shotId, body) {
      const current = last ?? (await this.load());
      if (current.origin !== "api") return remember(markMock(store.replaceReference(shotId, body)));
      const response = await sendJson(
        canvasPath(projectId, `/shots/${encodeURIComponent(shotId)}/reference`),
        "POST",
        { upload_id: body.upload_id },
      );
      if (!MISSING_ROUTE.has(response.status)) {
        if (!response.ok) throw new CanvasRequestError(response.status, await errorMessage(response));
        const parsed = (await response.json()) as { canvas?: unknown };
        const remote = contractWith(parsed.canvas);
        if (remote) return remember(remote);
        const reloaded = await loadFromApi();
        if (reloaded) return remember(reloaded);
      }
      if (MISSING_ROUTE.has(response.status)) {
        throw new CanvasRequestError(response.status, "当前服务不支持保存参考图，请更新服务后重试");
      }
      throw new CanvasRequestError(502, "替换参考图之后没有拿到画布");
    },

    async selectCandidate(body) {
      const current = last ?? (await this.load());
      const shot = shotById(current, body.shot_id);
      const data = shot ? asShot(shot) : null;
      const candidate = data?.candidates.find((item) => item.candidate_id === body.candidate_id);
      if (!candidate) throw new CanvasRequestError(404, "没有这条候选");
      const payload = buildSelectBody(body.shot_id, candidate);
      if (current.origin === "api") {
        const response = await postJson(`/v1/projects/${encodeURIComponent(projectId)}/expert/select`, payload);
        if (!response.ok) throw new CanvasRequestError(response.status, await errorMessage(response));
        const parsed = (await response.json()) as { canvas?: unknown };
        if (parsed.canvas && isLegacyCanvas(parsed.canvas)) return remember(adaptLegacyCanvas(parsed.canvas, emptyOverlay()));
        const remote = contractWith(parsed.canvas);
        if (remote) return remember(remote);
        throw new CanvasRequestError(502, "选用之后没有拿到画布");
      }
      return remember(markMock(store.selectCandidate(body)));
    },

    async saveTimeline(body) {
      const current = last ?? (await this.load());
      if ("ai_label" in body && body.ai_label === false) {
        throw new CanvasRequestError(422, "AI 生成标识不能关闭");
      }
      if (current.origin === "api") {
        const response = await sendJson(canvasPath(projectId, "/timeline"), "PUT", {
          clips: body.clips.map((clip) => ({
            shot_id: clip.shot_id,
            candidate_id: clip.candidate_id,
            in_s: clip.in_s,
            out_s: clip.out_s,
          })),
        });
        if (!MISSING_ROUTE.has(response.status)) {
          if (!response.ok) throw new CanvasRequestError(response.status, await errorMessage(response));
          const parsed = (await response.json()) as { canvas?: unknown; ai_label?: boolean };
          if (parsed.ai_label === false) throw new CanvasRequestError(422, "AI 生成标识不能关闭");
          const remote = contractWith(parsed.canvas);
          if (remote) return remember(remote);
          const reloaded = await loadFromApi();
          if (reloaded) return remember(reloaded);
          throw new CanvasRequestError(502, "保存时间轴之后没有拿到画布");
        }
        throw new CanvasRequestError(response.status, "当前服务不支持保存剪辑，请更新服务后重试");
      }
      return remember(markMock(store.saveTimeline(body)));
    },

    async buildStoryboard(sentence) {
      if (options.demo) throw new CanvasRequestError(422, "演示画布不会启动生成，请新建项目");
      const response = await sendJson(canvasPath(projectId, "/canvas/script"), "POST", { sentence });
      if (!response.ok) throw new CanvasRequestError(response.status, await errorMessage(response));
      const parsed = (await response.json()) as unknown;
      const remote = contractWith(parsed);
      if (remote) return remember(remote);
      const reloaded = await loadFromApi();
      if (reloaded) return remember(reloaded);
      throw new CanvasRequestError(502, "生成分镜之后没有拿到画布");
    },

    async generateNode(nodeId, body) {
      await this.flushNodeData();
      if (options.demo) throw new CanvasRequestError(422, "演示画布不会启动生成，请新建项目");
      const response = await sendJson(
        canvasPath(projectId, `/canvas/nodes/${encodeURIComponent(nodeId)}/generate`),
        "POST",
        { ...body },
      );
      if (!response.ok) throw new CanvasRequestError(response.status, await errorMessage(response));
      const parsed = (await response.json()) as { canvas?: unknown };
      const remote = contractWith(parsed.canvas);
      if (remote) return remember(remote);
      const reloaded = await loadFromApi();
      if (reloaded) return remember(reloaded);
      throw new CanvasRequestError(502, "生成之后没有拿到画布");
    },

    async startFilm(sentence) {
      await this.flushNodeData();
      if (options.demo) throw new CanvasRequestError(422, "演示画布不会启动生成，请新建项目");
      const response = await sendJson(`/v1/projects/${encodeURIComponent(projectId)}/film/start`, "POST", {
        sentence,
      });
      if (!response.ok) throw new CanvasRequestError(response.status, await errorMessage(response));
      await response.json().catch(() => null);
    },

    async releaseFilm() {
      if (options.demo) throw new CanvasRequestError(422, "演示画布不会启动生成，请新建项目");
      const response = await apiFetch(`/v1/projects/${encodeURIComponent(projectId)}/human-review/release`, {
        method: "POST",
      });
      if (!response.ok) throw new CanvasRequestError(response.status, await errorMessage(response));
      await response.json().catch(() => null);
    },

    async uploadImage(file) {
      if (options.demo) return readImageFile(file);
      const form = new FormData();
      form.append("file", file, file.name);
      const response = await apiFetch("/v1/uploads", { method: "POST", body: form });
      if (!response.ok) throw new CanvasRequestError(response.status, await errorMessage(response));
      const stored = (await response.json()) as { upload_id?: string };
      if (!stored.upload_id) throw new CanvasRequestError(502, "上传结果缺少素材标识，请重试");
      const local = await readImageFile(file);
      return { upload_id: stored.upload_id, thumbnail_url: local.thumbnail_url };
    },
  };

}

function markMock(snapshot: CanvasSnapshot): CanvasSnapshot {
  snapshot.origin = snapshot.origin ?? "mock";
  return snapshot;
}


async function postJson(path: string, body: unknown, method = "POST"): Promise<Response> {
  return sendJson(path, method, body);
}

async function sendJson(path: string, method: string, body: unknown): Promise<Response> {
  return apiFetch(path, {
    method,
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

function browserStorage(): KeyValueStore {
  if (typeof window === "undefined") {
    return { getItem: () => null, setItem: () => undefined, removeItem: () => undefined };
  }
  return window.localStorage;
}
