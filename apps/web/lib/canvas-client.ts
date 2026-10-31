/**
 * 画布传输层。R2 合并前，开发期和测试都走 mock，不发起网络请求。
 */

import {
  CanvasMockStore,
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

export function createCanvasClient(projectId: string, storage?: KeyValueStore): CanvasClient {
  const store = new CanvasMockStore(storage ?? browserStorage(), projectId);
  return {
    load: async () => store.load(),
    saveLayout: async (body) => store.saveLayout(body),
    createNode: async (body) => store.createNode(body),
    deleteNode: async (nodeId) => store.deleteNode(nodeId),
    createEdge: async (body) => store.createEdge(body),
    deleteEdge: async (edgeId) => store.deleteEdge(edgeId),
    updateNodeData: async (nodeId, patch) => store.updateNodeData(nodeId, patch),
    regenerate: async (shotId, body) => {
      await pause(240);
      return store.regenerate(shotId, body);
    },
    replaceReference: async (shotId, body) => store.replaceReference(shotId, body),
    selectCandidate: async (body) => store.selectCandidate(body),
    saveTimeline: async (body) => store.saveTimeline(body),
    uploadImage: (file) => readImageFile(file),
  };
}

function browserStorage(): KeyValueStore {
  if (typeof window === "undefined") {
    return {
      getItem: () => null,
      setItem: () => undefined,
      removeItem: () => undefined,
    };
  }
  return window.localStorage;
}

function pause(ms: number): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}
