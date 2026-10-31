/**
 * 画布传输。
 * 已有能力走 lib/api.ts：GET /canvas、POST /expert/select、POST /expert/rerun、POST /expert/timeline、POST /uploads。
 * 契约里的新写接口只落在本地 mock，不请求尚未合并的路径。
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

  function remember(snapshot: CanvasSnapshot): CanvasSnapshot {
    last = snapshot;
    return snapshot;
  }

  async function loadFromApi(): Promise<CanvasSnapshot | null> {
    try {
      const response = await apiFetch(`/v1/projects/${encodeURIComponent(projectId)}/canvas`);
      if (!response.ok) return null;
      const body: unknown = await response.json();
      const laid = overlay();
      if (isContractCanvas(body)) {
        return applyOverlay({ ...body, origin: "api", project_id: projectId }, laid);
      }
      if (isLegacyCanvas(body)) return adaptLegacyCanvas(body, laid);
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
        const laid = overlay();
        laid.positions = { ...laid.positions, ...body.positions };
        laid.viewport = body.viewport;
        laid.layout_version = body.layout_version + 1;
        writeOverlay(laid);
        return remember(
          applyOverlay(
            { ...current, nodes: current.nodes.map((node) => ({ ...node })) },
            laid,
          ),
        );
      }
      return remember(markMock(store.saveLayout(body)));
    },

    async createNode(body) {
      const current = last ?? (await this.load());
      if (current.origin !== "api") return remember(markMock(store.createNode(body)));
      if (body.kind !== "brief" && body.kind !== "ref_image") {
        throw new CanvasRequestError(422, "这里只能新建需求文本或参考图");
      }
      const id = nextLocalId(current.nodes, body.kind === "brief" ? "brief" : "ref");
      const node: CanvasNode =
        body.kind === "brief"
          ? {
              id,
              kind: "brief",
              position: body.position,
              user_created: true,
              data: { text: body.data && "text" in body.data ? body.data.text : "在这里写下要交给某一镜的话" },
            }
          : {
              id,
              kind: "ref_image",
              position: body.position,
              user_created: true,
              data: {
                upload_id: body.data && "upload_id" in body.data ? body.data.upload_id : "",
                thumbnail_url: body.data && "thumbnail_url" in body.data ? (body.data.thumbnail_url ?? null) : null,
              },
            };
      const laid = overlay();
      laid.nodes = [...laid.nodes, node];
      laid.layout_version += 1;
      writeOverlay(laid);
      return remember(applyOverlay(current, laid));
    },

    async deleteNode(nodeId) {
      const current = last ?? (await this.load());
      if (current.origin !== "api") return remember(markMock(store.deleteNode(nodeId)));
      const laid = overlay();
      const target = laid.nodes.find((node) => node.id === nodeId);
      if (!target?.user_created) throw new CanvasRequestError(422, "只能删除你新建的文本或参考图");
      laid.nodes = laid.nodes.filter((node) => node.id !== nodeId);
      laid.edges = laid.edges.filter((edge) => edge.source !== nodeId && edge.target !== nodeId);
      laid.layout_version += 1;
      writeOverlay(laid);
      return remember(applyOverlay({ ...current, nodes: current.nodes.filter((node) => node.id !== nodeId), edges: current.edges.filter((edge) => edge.source !== nodeId && edge.target !== nodeId) }, laid));
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
      const added: CanvasEdge = {
        id: `edge-${body.source}-${body.target}`,
        source: body.source,
        target: body.target,
        source_handle: body.source_handle ?? (role === "feeds_final" ? "out" : role),
        target_handle: body.target_handle ?? "in",
        role,
        user_created: true,
      };
      const laid = overlay();
      laid.edges = [...laid.edges, added];
      laid.layout_version += 1;
      writeOverlay(laid);
      return remember(applyOverlay(current, laid));
    },

    async deleteEdge(edgeId) {
      const current = last ?? (await this.load());
      if (current.origin !== "api") return remember(markMock(store.deleteEdge(edgeId)));
      const laid = overlay();
      laid.edges = laid.edges.filter((edge) => edge.id !== edgeId);
      laid.layout_version += 1;
      writeOverlay(laid);
      return remember(
        applyOverlay(
          { ...current, edges: current.edges.filter((edge) => edge.id !== edgeId) },
          laid,
        ),
      );
    },

    async updateNodeData(nodeId, patch) {
      const current = last ?? (await this.load());
      if (current.origin !== "api") return remember(markMock(store.updateNodeData(nodeId, patch)));
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
      const payload = buildRerunBody(shotId, selected, body?.prompt_suffix ?? data?.prompt_suffix ?? "");
      if (current.origin === "api") {
        const response = await postJson(`/v1/projects/${encodeURIComponent(projectId)}/expert/rerun`, payload);
        if (!response.ok) throw new CanvasRequestError(response.status, await errorMessage(response));
        const parsed = (await response.json()) as { canvas?: unknown };
        if (parsed.canvas && isLegacyCanvas(parsed.canvas)) return remember(adaptLegacyCanvas(parsed.canvas, overlay()));
        if (parsed.canvas && isContractCanvas(parsed.canvas)) {
          return remember(applyOverlay({ ...parsed.canvas, origin: "api" }, overlay()));
        }
        const remote = await loadFromApi();
        if (remote) return remember(remote);
        throw new CanvasRequestError(502, "重跑之后没有拿到画布");
      }
      await postJson(`/v1/projects/${encodeURIComponent(projectId)}/expert/rerun`, payload).catch(() => null);
      return remember(markMock(store.regenerate(shotId, body)));
    },

    async replaceReference(shotId, body) {
      const current = last ?? (await this.load());
      if (current.origin !== "api") return remember(markMock(store.replaceReference(shotId, body)));
      const laid = overlay();
      laid.references = { ...laid.references, [shotId]: body };
      laid.layout_version += 1;
      writeOverlay(laid);
      return remember(applyOverlay(current, laid));
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
      const posted = buildTimelineBody(current.server_timeline, body.clips);
      if (current.origin === "api") {
        const response = await postJson(`/v1/projects/${encodeURIComponent(projectId)}/expert/timeline`, posted);
        if (!response.ok) throw new CanvasRequestError(response.status, await errorMessage(response));
        const laid = overlay();
        laid.clips = body.clips;
        laid.layout_version += 1;
        writeOverlay(laid);
        const parsed = (await response.json()) as { canvas?: unknown; ai_label?: boolean };
        if (parsed.ai_label === false) throw new CanvasRequestError(422, "AI 生成标识不能关闭");
        if (parsed.canvas && isLegacyCanvas(parsed.canvas)) return remember(adaptLegacyCanvas(parsed.canvas, laid));
        return remember(applyOverlay(current, laid));
      }
      await postJson(`/v1/projects/${encodeURIComponent(projectId)}/expert/timeline`, posted).catch(() => null);
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

function nextLocalId(nodes: { id: string }[], prefix: string): string {
  let n = nodes.length + 1;
  let id = `${prefix}-${n}`;
  while (nodes.some((node) => node.id === id)) {
    n += 1;
    id = `${prefix}-${n}`;
  }
  return id;
}

async function postJson(path: string, body: unknown): Promise<Response> {
  return apiFetch(path, {
    method: "POST",
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
