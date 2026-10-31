/**
 * 画布传输。
 * 已有能力走 lib/api.ts：GET /canvas、POST /expert/select、POST /expert/rerun、POST /expert/timeline、POST /uploads。
 * R2 合并后：布局、自建节点、自建连线、替换参考图、单镜再生、结构化时间轴都请求真接口。
 * 老后端还缺这些路径时返回 404/405，界面回退到本地 overlay，演示不会空白。
 */

import { apiFetch, errorMessage } from "./api";
import {
  adaptLegacyCanvas,
  applyOverlay,
  buildRerunBody,
  buildSelectBody,
  buildTimelineBody,
  emptyOverlay,
  isContractCanvas,
  isLegacyCanvas,
} from "./canvas-adapt";
import {
  CanvasMockStore,
  CanvasRequestError,
  readImageFile,
  type KeyValueStore,
} from "./canvas-mock";
import type {
  CanvasOverlay,
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
  createNode(body: CreateNodeWrite): Promise<CanvasSnapshot>;
  deleteNode(nodeId: string): Promise<CanvasSnapshot>;
  createEdge(body: CreateEdgeWrite): Promise<CanvasSnapshot>;
  deleteEdge(edgeId: string): Promise<CanvasSnapshot>;
  updateNodeData(nodeId: string, patch: NodeDataPatch): Promise<CanvasSnapshot>;
  regenerate(shotId: string, body?: RegenerateWrite): Promise<CanvasSnapshot>;
  replaceReference(shotId: string, body: ReferenceWrite): Promise<CanvasSnapshot>;
  selectCandidate(body: SelectWrite): Promise<CanvasSnapshot>;
  saveTimeline(body: TimelineWrite): Promise<CanvasSnapshot>;
  uploadImage(file: File): Promise<{ upload_id: string; thumbnail_url: string }>;
};

const OVERLAY_PREFIX = "hilatv.canvas.overlay.v0.";

/** R2 新接口在老后端上还不存在：这两个状态回退到本地 overlay。 */
const MISSING_ROUTE = new Set([404, 405]);

function canvasPath(projectId: string, suffix: string): string {
  return `/v1/projects/${encodeURIComponent(projectId)}${suffix}`;
}

export function createCanvasClient(projectId: string, storage?: KeyValueStore): CanvasClient {
  const memory = storage ?? browserStorage();
  const store = new CanvasMockStore(memory, projectId);
  let last: CanvasSnapshot | null = null;

  function overlay(): CanvasOverlay {
    const raw = memory.getItem(OVERLAY_PREFIX + projectId);
    if (!raw) return emptyOverlay();
    try {
      const parsed = JSON.parse(raw) as CanvasOverlay;
      if (!parsed || !parsed.positions) return emptyOverlay();
      return {
        layout_version: parsed.layout_version || 1,
        positions: parsed.positions,
        viewport: parsed.viewport,
        nodes: parsed.nodes ?? [],
        edges: parsed.edges ?? [],
        clips: parsed.clips,
        references: parsed.references,
      };
    } catch {
      return emptyOverlay();
    }
  }

  function writeOverlay(next: CanvasOverlay) {
    memory.setItem(OVERLAY_PREFIX + projectId, JSON.stringify(next));
  }

  /** 写进后端之后，本地 overlay 不能再用旧坐标和旧节点盖住服务端结果。 */
  function resetOverlay() {
    writeOverlay({ layout_version: 0, positions: {}, nodes: [], edges: [] });
  }

  /** api 来源以服务端 layout_version 为准；overlay 只提供本地补充。 */
  function apiOverlay(): CanvasOverlay {
    return { ...overlay(), layout_version: 0 };
  }

  function contractWith(body: unknown): CanvasSnapshot | null {
    if (body && isContractCanvas(body)) {
      return applyOverlay({ ...body, origin: "api", project_id: projectId }, apiOverlay());
    }
    return null;
  }

  function remember(snapshot: CanvasSnapshot): CanvasSnapshot {
    last = snapshot;
    return snapshot;
  }

  async function loadFromApi(): Promise<CanvasSnapshot | null> {
    try {
      const response = await apiFetch(`/v1/projects/${encodeURIComponent(projectId)}/canvas`);
      if (!response.ok) return null;
      const body: unknown = await response.json();
      if (isContractCanvas(body)) {
        return applyOverlay({ ...body, origin: "api", project_id: projectId }, apiOverlay());
      }
      if (isLegacyCanvas(body)) return adaptLegacyCanvas(body, overlay());
    } catch {
      return null;
    }
    return null;
  }

  return {
    async load() {
      const remote = await loadFromApi();
      if (remote) return remember(remote);
      const seeded = store.load();
      seeded.origin = "mock";
      return remember(seeded);
    },

    async saveLayout(body) {
      const current = last ?? (await this.load());
      if (current.origin === "api") {
        const write = {
          layout_version: body.layout_version,
          positions: body.positions,
          viewport: body.viewport,
        };
        let response = await sendJson(canvasPath(projectId, "/canvas/layout"), "PUT", write);
        if (response.status === 409) {
          const fresh = await loadFromApi();
          if (fresh) {
            response = await sendJson(canvasPath(projectId, "/canvas/layout"), "PUT", {
              ...write,
              layout_version: fresh.layout_version,
            });
          }
        }
        if (!response.ok) throw new CanvasRequestError(response.status, await errorMessage(response));
        const saved = (await response.json()) as { layout_version?: number };
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
      if (MISSING_ROUTE.has(response.status)) return remember(markMock(store.createNode(body)));
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
      if (MISSING_ROUTE.has(response.status)) return remember(markMock(store.deleteNode(nodeId)));
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
      if (MISSING_ROUTE.has(response.status)) return remember(markMock(store.createEdge(body)));
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
      if (MISSING_ROUTE.has(response.status)) return remember(markMock(store.deleteEdge(edgeId)));
      if (!response.ok) throw new CanvasRequestError(response.status, await errorMessage(response));
      await response.json().catch(() => null);
      resetOverlay();
      const remote = await loadFromApi();
      if (remote) return remember(remote);
      return remember({ ...current, edges: current.edges.filter((edge) => edge.id !== edgeId) });
    },

    async updateNodeData(nodeId, patch) {
      const current = last ?? (await this.load());
      if (current.origin === "api") {
        // R8 之前没有「修改镜头正文」的写接口；旁白和补充提示词先进本地，再生时随请求带走。
        if (patch.kind !== "shot") {
          const data = patch.kind === "brief" ? { text: patch.text } : { upload_id: patch.upload_id };
          const response = await sendJson(
            canvasPath(projectId, `/canvas/nodes/${encodeURIComponent(nodeId)}`),
            "PATCH",
            { data },
          );
          if (!MISSING_ROUTE.has(response.status) && response.ok) {
            resetOverlay();
            const remote = await loadFromApi();
            if (remote) return remember(remote);
          }
        }
      } else {
        return remember(markMock(store.updateNodeData(nodeId, patch)));
      }
      const nodes = current.nodes.map((node) => {
        if (node.id !== nodeId) return node;
        if (patch.kind === "brief" && node.kind === "brief") return { ...node, data: { text: patch.text } };
        if (patch.kind === "shot" && node.kind === "shot") {
          const data = asShot(node);
          if (!data) return node;
          return {
            ...node,
            data: {
              ...data,
              narration: patch.narration ?? data.narration,
              prompt_suffix: patch.prompt_suffix ?? data.prompt_suffix,
            },
          };
        }
        if (patch.kind === "ref_image" && node.kind === "ref_image") {
          return { ...node, data: { upload_id: patch.upload_id, thumbnail_url: patch.thumbnail_url ?? null } };
        }
        return node;
      });
      return remember({ ...current, nodes, sentence: patch.kind === "brief" && nodeId === "brief-1" ? patch.text : current.sentence });
    },

    async regenerate(shotId, body) {
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
        if (parsed.canvas && isLegacyCanvas(parsed.canvas)) return remember(adaptLegacyCanvas(parsed.canvas, overlay()));
        const remote = contractWith(parsed.canvas);
        if (remote) return remember(remote);
        const reloaded = await loadFromApi();
        if (reloaded) return remember(reloaded);
        throw new CanvasRequestError(502, "重跑之后没有拿到画布");
      }
      await postJson(`/v1/projects/${encodeURIComponent(projectId)}/expert/rerun`, payload).catch(() => null);
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
        const laid = overlay();
        laid.references = { ...laid.references, [shotId]: body };
        writeOverlay(laid);
        return remember(applyOverlay(current, laid));
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
        if (parsed.canvas && isLegacyCanvas(parsed.canvas)) return remember(adaptLegacyCanvas(parsed.canvas, overlay()));
        if (parsed.canvas && isContractCanvas(parsed.canvas)) {
          return remember(applyOverlay({ ...parsed.canvas, origin: "api" }, overlay()));
        }
        throw new CanvasRequestError(502, "选用之后没有拿到画布");
      }
      await postJson(`/v1/projects/${encodeURIComponent(projectId)}/expert/select`, payload).catch(() => null);
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
        // 老后端：沿用 expert/timeline 保住「AI生成」，入点出点先只记在本地。
        const posted = buildTimelineBody(current.server_timeline, body.clips);
        const legacy = await postJson(`/v1/projects/${encodeURIComponent(projectId)}/expert/timeline`, posted);
        if (!legacy.ok) throw new CanvasRequestError(legacy.status, await errorMessage(legacy));
        const laid = overlay();
        laid.clips = body.clips;
        writeOverlay(laid);
        return remember(applyOverlay(current, laid));
      }
      await postJson(`/v1/projects/${encodeURIComponent(projectId)}/expert/timeline`, buildTimelineBody(current.server_timeline, body.clips)).catch(() => null);
      return remember(markMock(store.saveTimeline(body)));
    },

    async uploadImage(file) {
      try {
        const form = new FormData();
        form.append("file", file, file.name);
        const response = await apiFetch("/v1/uploads", { method: "POST", body: form });
        if (response.ok) {
          const stored = (await response.json()) as { upload_id?: string };
          if (stored.upload_id) {
            const local = await readImageFile(file);
            return { upload_id: stored.upload_id, thumbnail_url: local.thumbnail_url };
          }
        }
      } catch {
        // 没有上传服务时仍留下本地缩略图，参考图替换本身是新接口。
      }
      return readImageFile(file);
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
