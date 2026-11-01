"use client";

import {
  Background,
  BackgroundVariant,

  MiniMap,
  ReactFlow,
  SelectionMode,
  applyEdgeChanges,
  applyNodeChanges,
  useReactFlow,
  type Connection,
  type Edge,
  type Node,
  type NodeChange,
  type OnBeforeDelete,
  type OnConnectEnd,
} from "@xyflow/react";
import Image from "next/image";
import Link from "next/link";
import { Clapperboard, Image as ImageIcon, Sparkles, TextCursorInput } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { CanvasAddMenu, CanvasToolRail, CANVAS_TOOLBOX_EVENT } from "@/components/canvas/add-menu";
import { CanvasActionsProvider, type CanvasActions } from "@/components/canvas/canvas-context";
import { Inspector, type InspectorFocus } from "@/components/canvas/inspector";
import {
  BriefNode,
  ContentNode,
  FinalNode,
  PipelineNode,
  RefNode,
  ScriptNode,
  ShotNode,
  type FlowData,
} from "@/components/canvas/nodes";
import { TimelineTrack } from "@/components/canvas/timeline-track";
import { SharePanel } from "@/components/share/share-panel";
import { createCanvasClient, type CanvasClient } from "@/lib/canvas-client";
import {
  addGroup,
  loadGroups,
  removeGroup,
  type ToolboxGroup,
} from "@/lib/canvas-toolbox";
import {
  AI_LABEL_COPY,
  ROLE_COPY,
  asShot,
  explainConnection,
  type CanvasNode,
  type CanvasPoint,
  type CanvasSnapshot,
  type CanvasViewport,
  type EdgeRole,
  type RegenerateWrite,
} from "@/lib/canvas-contract";
import { CanvasRequestError } from "@/lib/canvas-mock";

import "@xyflow/react/dist/style.css";
import "@/components/canvas/canvas.css";

const nodeTypes = {
  brief: BriefNode,
  ref_image: RefNode,
  shot: ShotNode,
  image: ContentNode,
  video: ContentNode,
  audio: ContentNode,
  script: ScriptNode,
  final: FinalNode,
  pipeline: PipelineNode,
};

const FREE = new Set(["brief", "ref_image", "shot", "final", "image", "video", "script", "audio"]);

/** 管线工序是内部节点，LibTV 式画布只铺内容节点。 */
function visibleFlow(snapshot: CanvasSnapshot): { nodes: CanvasNode[]; edges: CanvasSnapshot["edges"] } {
  const content = snapshot.nodes.filter((node) =>
    ["brief", "ref_image", "shot", "image", "video", "script", "audio"].includes(node.kind),
  );
  const nodes = snapshot.nodes.filter((node) => FREE.has(node.kind) && (node.kind !== "final" || content.length > 0));
  const ids = new Set(nodes.map((node) => node.id));
  return { nodes, edges: snapshot.edges.filter((edge) => ids.has(edge.source) && ids.has(edge.target)) };
}

const ariaLabelConfig = {
  "node.a11yDescription.default":
    "回车或空格选中。方向键移动节点，按住 Shift 移动更快。Delete 删除你新建的节点，Esc 取消。",
  "node.a11yDescription.keyboardDisabled":
    "回车或空格选中。方向键移动节点。Delete 删除你新建的节点，Esc 取消。",
  "node.a11yDescription.ariaLiveMessage": ({
    direction,
    x,
    y,
  }: {
    direction: string;
    x: number;
    y: number;
  }) => {
    const name = { left: "左", right: "右", up: "上", down: "下" }[direction] ?? direction;
    return `节点已向${name}移动。位置 ${x}，${y}`;
  },
  "edge.a11yDescription.default": "回车或空格选中连线。Delete 删除，Esc 取消。",
  "controls.ariaLabel": "画布控制",
  "controls.zoomIn.ariaLabel": "放大",
  "controls.zoomOut.ariaLabel": "缩小",
  "controls.fitView.ariaLabel": "适配画面",
  "controls.interactive.ariaLabel": "切换交互",
  "minimap.ariaLabel": "小地图",
  "handle.ariaLabel": "连线手柄",
};

export function CanvasStage({ projectId }: { projectId: string }) {
  const clientRef = useRef<CanvasClient | null>(null);
  const docRef = useRef<CanvasSnapshot | null>(null);
  const nodesRef = useRef<Node<FlowData>[]>([]);
  const viewportRef = useRef<CanvasViewport>({ x: 0, y: 0, zoom: 1 });
  const versionRef = useRef(1);
  const busyRef = useRef<string | null>(null);
  const queueRef = useRef<Promise<void>>(Promise.resolve());
  const timerRef = useRef<number>(0);
  const pendingSelect = useRef<string | null>(null);
  const lastPersist = useRef("");
  const [doc, setDoc] = useState<CanvasSnapshot | null>(null);
  const [nodes, setNodes] = useState<Node<FlowData>[]>([]);
  const [edges, setEdges] = useState<Edge[]>([]);
  const [ready, setReady] = useState(false);
  const [notice, setNotice] = useState("");
  const [noticeTone, setNoticeTone] = useState<"neutral" | "danger">("neutral");
  const [loadError, setLoadError] = useState("");
  const [loadAttempt, setLoadAttempt] = useState(0);
  const [zoom, setZoom] = useState(1);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [choosingId, setChoosing] = useState<string | null>(null);
  const [busyShot, setBusyShot] = useState<string | null>(null);
  const [focus, setFocus] = useState<InspectorFocus | null>(null);
  const [scriptOpen, setScriptOpen] = useState(false);
  const [toolboxOpen, setToolboxOpen] = useState(false);
  const [groups, setGroups] = useState<ToolboxGroup[]>([]);
  const [groupName, setGroupName] = useState("");
  const [filmRunning, setFilmRunning] = useState(false);
  const [agentOpen, setAgentOpen] = useState(false);
  const [agentText, setAgentText] = useState("");
  const pollRef = useRef<number>(0);
  const [scriptText, setScriptText] = useState("");
  const [scriptBusy, setScriptBusy] = useState(false);

  const syncFlow = useCallback((next: CanvasSnapshot) => {
    const positions = new Map(nodesRef.current.map((node) => [node.id, node.position]));
    const selected = new Set(nodesRef.current.filter((node) => node.selected).map((node) => node.id));
    if (pendingSelect.current) {
      selected.clear();
      selected.add(pendingSelect.current);
      pendingSelect.current = null;
    }
    const visible = visibleFlow(next);
    const flowNodes = visible.nodes.map((node) => toFlowNode(node, positions.get(node.id), selected.has(node.id)));
    nodesRef.current = flowNodes;
    setNodes(flowNodes);
    setEdges(visible.edges.map((edge) => toFlowEdge(edge, busyRef.current)));
    setSelectedIds(flowNodes.filter((node) => node.selected).map((node) => node.id));
  }, []);

  const enqueue = useCallback(
    (task: () => Promise<CanvasSnapshot>, mode: "adopt" | "remember") => {
      const run = queueRef.current.then(async () => {
        try {
          const next = await task();
          versionRef.current = next.layout_version;
          docRef.current = next;
          setDoc(next);
          setZoom(next.viewport.zoom);
          if (mode === "adopt") syncFlow(next);
          return next;
        } catch (error) {
          const message = error instanceof CanvasRequestError ? error.message : "没有保存成功";
          setNoticeTone("danger");
          setNotice(message);
          // Preserve local positions on conflict; do not adopt a different revision silently.
          throw error;
        }
      });
      queueRef.current = run.then(
        () => undefined,
        () => undefined,
      );
      return run;
    },
    [syncFlow],
  );

  const persistLayout = useCallback(() => {
    const client = clientRef.current;
    const current = docRef.current;
    if (!client || !current || nodesRef.current.length === 0) return;
    const positions = Object.fromEntries(
      nodesRef.current.map((node) => [node.id, { x: Math.round(node.position.x), y: Math.round(node.position.y) }]),
    );
    const viewport = {
      x: viewportRef.current.x,
      y: viewportRef.current.y,
      zoom: viewportRef.current.zoom,
    };
    const key = JSON.stringify({ positions, viewport });
    if (key === lastPersist.current) return;
    void enqueue(
      () =>
        client.saveLayout({
          layout_version: versionRef.current,
          positions,
          viewport,
        }),
      "remember",
    ).then(() => { lastPersist.current = key; }).catch(() => undefined);
  }, [enqueue]);

  const scheduleLayout = useCallback(() => {
    window.clearTimeout(timerRef.current);
    timerRef.current = window.setTimeout(() => persistLayout(), 160);
  }, [persistLayout]);

  useEffect(() => {
    const client = createCanvasClient(projectId, undefined, { demo: projectId === "demo-canvas" });
    setLoadError("");
    setReady(false);
    clientRef.current = client;
    let cancel = false;
    void client.load().then((snapshot) => {
      if (cancel) return;
      versionRef.current = snapshot.layout_version;
      docRef.current = snapshot;
      viewportRef.current = snapshot.viewport;
      const visible = visibleFlow(snapshot);
      const flowNodes = visible.nodes.map((node) => toFlowNode(node));
      nodesRef.current = flowNodes;
      setDoc(snapshot);
      setNodes(flowNodes);
      setEdges(visible.edges.map((edge) => toFlowEdge(edge, null)));
      setZoom(snapshot.viewport.zoom);
      lastPersist.current = JSON.stringify({
        positions: Object.fromEntries(
          flowNodes.map((node) => [node.id, { x: Math.round(node.position.x), y: Math.round(node.position.y) }]),
        ),
        viewport: snapshot.viewport,
      });
      setReady(true);
    }).catch((error: unknown) => {
      if (!cancel) setLoadError(error instanceof Error ? error.message : "读取失败，请重试");
    });
    return () => {
      cancel = true;
      window.clearTimeout(timerRef.current);
      window.clearInterval(pollRef.current);
    };
  }, [projectId, loadAttempt]);

  useEffect(() => {
    setGroups(loadGroups());
    function onToolbox() {
      setToolboxOpen((open) => !open);
    }
    window.addEventListener(CANVAS_TOOLBOX_EVENT, onToolbox);
    return () => window.removeEventListener(CANVAS_TOOLBOX_EVENT, onToolbox);
  }, []);

  const onNodesChange = useCallback(
    (changes: NodeChange<Node<FlowData>>[]) => {
      setNodes((current) => {
        const next = applyNodeChanges(changes, current);
        nodesRef.current = next;
        return next;
      });
      if (changes.some((change) => change.type === "position" && change.dragging === false)) {
        scheduleLayout();
      }
    },
    [scheduleLayout],
  );

  const onSelectionChange = useCallback(({ nodes: picked }: { nodes: Node<FlowData>[] }) => {
    const ids = picked.map((node) => node.id);
    setSelectedIds((current) => (sameList(current, ids) ? current : ids));
  }, []);

  const onMove = useCallback((_event: unknown, viewport: CanvasViewport) => {
    viewportRef.current = viewport;
    setZoom((current) => (Math.abs(current - viewport.zoom) < 0.001 ? current : viewport.zoom));
  }, []);

  const onMoveEnd = useCallback(
    (_event: unknown, viewport: CanvasViewport) => {
      viewportRef.current = viewport;
      setZoom((current) => (Math.abs(current - viewport.zoom) < 0.001 ? current : viewport.zoom));
      scheduleLayout();
    },
    [scheduleLayout],
  );

  const onConnect = useCallback(
    (connection: Connection) => {
      if (!connection.source || !connection.target || !clientRef.current) return;
      const client = clientRef.current;
      void enqueue(
        () =>
          client.createEdge({
            source: connection.source!,
            target: connection.target!,
            source_handle: connection.sourceHandle,
            target_handle: connection.targetHandle,
          }),
        "adopt",
      ).then(() => setNotice("")).catch(() => undefined);
    },
    [enqueue],
  );

  const onConnectEnd = useCallback<OnConnectEnd>((_event, state) => {
    if (state.isValid !== false || !docRef.current) return;
    const source = state.fromNode?.id;
    const target = state.toNode?.id;
    if (!source || !target) {
      setNotice("松手时要对准另一个节点的连接点");
      return;
    }
    setNotice(
      explainConnection(docRef.current.nodes, docRef.current.edges, source, target) ?? "这条线不能连",
    );
  }, []);

  const isValidConnection = useCallback((connection: Edge | Connection) => {
    if (!connection.source || !connection.target || !docRef.current) return false;
    return (
      explainConnection(docRef.current.nodes, docRef.current.edges, connection.source, connection.target) ===
      null
    );
  }, []);

  const onBeforeDelete = useCallback<OnBeforeDelete<Node<FlowData>, Edge>>(async ({ nodes: doomed, edges: doomedEdges }) => {
    const allowed = doomed.filter((node) => node.data.userCreated === true);
    if (allowed.length !== doomed.length) setNotice("只能删除你新建的文本或参考图");
    return { nodes: allowed, edges: doomedEdges };
  }, []);

  const onNodesDelete = useCallback(
    (deleted: Node<FlowData>[]) => {
      const client = clientRef.current;
      if (!client || deleted.length === 0) return;
      void enqueue(async () => {
        let latest = docRef.current;
        for (const node of deleted) latest = await client.deleteNode(node.id);
        return latest ?? docRef.current!;
      }, "adopt").catch(() => undefined);
    },
    [enqueue],
  );

  const onEdgesDelete = useCallback(
    (deleted: Edge[]) => {
      const client = clientRef.current;
      if (!client || deleted.length === 0) return;
      void enqueue(async () => {
        let latest = docRef.current;
        for (const edge of deleted) latest = await client.deleteEdge(edge.id);
        return latest ?? docRef.current!;
      }, "adopt").catch(() => undefined);
    },
    [enqueue],
  );

  const run = useCallback(
    (task: (client: CanvasClient) => Promise<CanvasSnapshot>) => {
      const client = clientRef.current;
      if (!client) return;
      void enqueue(() => task(client), "adopt").catch(() => undefined);
    },
    [enqueue],
  );

  const beginPolling = useCallback(
    (client: CanvasClient) => {
      window.clearInterval(pollRef.current);
      pollRef.current = window.setInterval(async () => {
        try {
          const next = await client.load();
          versionRef.current = next.layout_version;
          docRef.current = next;
          setDoc(next);
          syncFlow(next);
          const status = next.status ?? "";
          if (status && status !== "running") {
            window.clearInterval(pollRef.current);
            setFilmRunning(false);
            setNotice(
              status === "completed"
                ? "成片出来了"
                : status === "needs_human_review"
                  ? "画面需要你确认后再放行"
                  : "已停止",
            );
          }
        } catch {
          // 网络抖一下不影响出片
        }
      }, 6000);
    },
    [syncFlow],
  );

  const actions = useMemo<CanvasActions>(() => {
    return {
      doc: doc ?? emptyDoc(projectId),
      startFilm: async (sentence: string) => {
        const client = clientRef.current;
        if (!client) return;
        await client.startFilm(sentence);
        setAgentOpen(false);
        setFilmRunning(true);
        setNoticeTone("neutral");
        setNotice("AI 开始出片，约 1–2 分钟");
        beginPolling(client);
      },
      releaseFilm: async () => {
        const client = clientRef.current;
        if (!client) return;
        await client.releaseFilm();
        setFilmRunning(true);
        setNoticeTone("neutral");
        setNotice("已放行，正在合成成片");
        beginPolling(client);
      },
      saveGroup: (name: string) => {
        const current = docRef.current;
        if (!current) return;
        const picked = new Set(selectedIds);
        const nodes = current.nodes.filter((node) => picked.has(node.id));
        if (nodes.length < 2) return;
        const minX = Math.min(...nodes.map((node) => node.position.x));
        const minY = Math.min(...nodes.map((node) => node.position.y));
        const index = new Map(nodes.map((node, position) => [node.id, position]));
        const edges = current.edges
          .filter((edge) => index.has(edge.source) && index.has(edge.target))
          .map((edge) => ({
            from: index.get(edge.source) as number,
            to: index.get(edge.target) as number,
            role: edge.role,
            fromHandle: edge.source_handle ?? undefined,
            toHandle: edge.target_handle ?? undefined,
          }));
        const group: ToolboxGroup = {
          id: crypto.randomUUID(),
          name: name.trim() || `组合 ${groups.length + 1}`,
          saved_at: Date.now(),
          edges,
          nodes: nodes.map((node) => ({
            kind: node.kind,
            prompt:
              typeof (node.data as { prompt?: unknown }).prompt === "string"
                ? (node.data as { prompt: string }).prompt
                : undefined,
            text:
              typeof (node.data as { text?: unknown }).text === "string"
                ? (node.data as { text: string }).text
                : undefined,
            dx: Math.round(node.position.x - minX),
            dy: Math.round(node.position.y - minY),
          })),
        };
        setGroups(addGroup(group));
        setGroupName("");
        setNoticeTone("neutral");
        setNotice(`已存入工具箱：${group.name}`);
      },
      applyGroup: (group: ToolboxGroup) => {
        const client = clientRef.current;
        if (!client) return;
        const base = nextPosition(nodesRef.current);
        void enqueue(async () => {
          const created: string[] = [];
          const seen = new Set((docRef.current?.nodes ?? []).map((node) => node.id));
          let latest: CanvasSnapshot | null = null;
          for (const node of group.nodes) {
            latest = await client.createNode({
              kind: node.kind as "brief" | "ref_image" | "image" | "video" | "script" | "audio",
              position: { x: base.x + node.dx, y: base.y + node.dy },
              data:
                node.kind === "brief"
                  ? { text: node.text ?? "写一句话" }
                  : node.kind === "ref_image"
                    ? { upload_id: "", thumbnail_url: null }
                    : { prompt: node.prompt ?? "" },
            });
            const fresh = latest.nodes.find((item) => !seen.has(item.id));
            if (fresh) {
              created.push(fresh.id);
              seen.add(fresh.id);
            }
          }
          for (const edge of group.edges) {
            const source = created[edge.from];
            const target = created[edge.to];
            if (!source || !target) continue;
            latest = await client.createEdge({
              source,
              target,
              role: edge.role as EdgeRole,
              source_handle: edge.fromHandle,
              target_handle: edge.toHandle,
            });
          }
          return latest ?? docRef.current!;
        }, "adopt")
          .then(() => {
            setToolboxOpen(false);
            setNoticeTone("neutral");
        setNotice(`已套用组合：${group.name}`);
          })
          .catch(() => undefined);
      },
      deleteGroup: (id: string) => {
        setGroups(removeGroup(id));
      },
      generateNode: async (nodeId: string, body?: { prompt?: string; count?: number }) => {
        const client = clientRef.current;
        if (!client) return;
        await enqueue(() => client.generateNode(nodeId, body), "adopt").catch(() => undefined);
      },
      storyboard: async (sentence: string) => {
        const client = clientRef.current;
        if (!client) return;
        setScriptBusy(true);
        try {
          await enqueue(() => client.buildStoryboard(sentence), "adopt");
          setScriptOpen(false);
          setScriptText("");
        } finally {
          setScriptBusy(false);
        }
      },
      choosingId,
      setChoosing,
      regenerate: (shotId: string, copy?: RegenerateWrite) => {
        const client = clientRef.current;
        if (!client) return;
        busyRef.current = shotId;
        setBusyShot(shotId);
        if (docRef.current) setEdges(docRef.current.edges.map((edge) => toFlowEdge(edge, shotId)));
        void enqueue(async () => {
          try {
            return await client.regenerate(shotId, copy);
          } finally {
            busyRef.current = null;
            setBusyShot(null);
          }
        }, "adopt").catch(() => undefined);
      },
      editWords: (shotId: string) => {
        setSelectedIds([shotId]);
        setFocus({ shotId, field: "narration", nonce: Date.now() });
      },
      choose: (shotId, candidateId) => {
        setChoosing(null);
        run((client) => client.selectCandidate({ shot_id: shotId, candidate_id: candidateId }));
      },
      uploadReference: (shotId, file) => {
        run(async (client) => {
          const uploaded = await client.uploadImage(file);
          return client.replaceReference(shotId, uploaded);
        });
      },
      showPrompt: (shotId) => {
        setSelectedIds([shotId]);
        setFocus({ shotId, field: "prompt", nonce: Date.now() });
      },
      changeBrief: (nodeId, text) => {
        run((client) => client.updateNodeData(nodeId, { kind: "brief", text }));
      },
      derive: (nodeId, kind) => {
        const client = clientRef.current;
        const source = nodesRef.current.find((node) => node.id === nodeId);
        if (!client || !source) return;
        const before = new Set((docRef.current?.nodes ?? []).map((node) => node.id));
        const position = { x: Math.max(0, source.position.x - 300), y: source.position.y + 40 };
        void enqueue(async () => {
          let next = await client.createNode({
            kind,
            position,
            data:
              kind === "brief"
                ? { text: "写一句话交给这一镜" }
                : { upload_id: "", thumbnail_url: null },
          });
          const created = next.nodes.find((node) => !before.has(node.id));
          if (created) {
            next = await client.createEdge({
              source: created.id,
              target: nodeId,
              role: kind === "brief" ? "text" : "reference",
            });
            pendingSelect.current = created.id;
          }
          return next;
        }, "adopt").catch(() => undefined);
      },
      uploadRefNode: (nodeId, file) => {
        run(async (client) => {
          const uploaded = await client.uploadImage(file);
          return client.updateNodeData(nodeId, {
            kind: "ref_image",
            upload_id: uploaded.upload_id,
            thumbnail_url: uploaded.thumbnail_url,
          });
        });
      },
    };
  }, [beginPolling, choosingId, doc, enqueue, groups.length, projectId, run, selectedIds]);

  function create(
    kind: "brief" | "ref_image" | "image" | "video" | "script" | "audio",
    at?: CanvasPoint,
  ) {
    const client = clientRef.current;
    if (!client) return;
    const position = at ?? nextPosition(nodesRef.current);
    const before = new Set((docRef.current?.nodes ?? []).map((node) => node.id));
    void enqueue(async () => {
      const next = await client.createNode({
        kind,
        position,
        data:
          kind === "brief"
            ? { text: "在这里写下要交给某一镜的话" }
            : kind === "ref_image"
              ? { upload_id: "", thumbnail_url: null }
              : { prompt: "" },
      });
      pendingSelect.current = next.nodes.find((node) => !before.has(node.id))?.id ?? null;
      return next;
    }, "adopt")
      .then(() => setNotice(""))
      .catch(() => undefined);
  }

  if (!doc || !ready) {
    return (
      <div className="hilatv-canvas-workspace" data-theme="dark" data-stage="canvas" data-standalone="true">
        {loadError ? (
          <div className="grid gap-4 p-6">
            <h1 className="text-h2 font-medium">未能打开项目</h1>
            <p role="alert" className="text-small text-danger">{loadError}</p>
            <div className="flex gap-4">
              <button type="button" className="hilatv-canvas-back" onClick={() => setLoadAttempt((n) => n + 1)}>重新读取</button>
              <Link href="/projects" className="hilatv-canvas-back">返回项目</Link>
              <Link href="/projects/demo-canvas/expert" className="hilatv-canvas-back">打开演示画布</Link>
            </div>
          </div>
        ) : <p role="status" className="p-6 text-small text-text-2">正在读取节点</p>}
      </div>
    );
  }

  const isEmpty = !doc.nodes.some((node) =>
    ["brief", "ref_image", "shot", "image", "video", "script", "audio"].includes(node.kind),
  );

  return (
    <div className="hilatv-canvas-workspace" data-theme="dark" data-stage="canvas" data-standalone="true">
      <header className="hilatv-canvas-topbar">
        <Link href="/" className="hilatv-canvas-brand" aria-label="HiLatv 首页">
          {/* 公司标志原样使用：不改色、不拉伸、不加效果 */}
          <Image src="/brand/mark.svg" alt="" width={20} height={20} aria-hidden="true" />
          <span className="text-small font-medium text-text-1">HiLatv</span>
          <span className="hilatv-canvas-brand-sep" aria-hidden="true" />
          <span className="max-w-sm truncate text-small text-text-2">{doc.sentence || "未命名项目"}</span>
        </Link>
        {doc.origin === "mock" ? <p title="修改仅保存在此浏览器" className="shrink-0 whitespace-nowrap text-caption text-warning">本地演示<span className="sr-only"> · 修改仅保存在此浏览器</span></p> : null}
        {filmRunning ? <p className="hilatv-canvas-running">AI 正在出片…</p> : null}
        {doc.status === "needs_human_review" ? (
          <button type="button" className="hilatv-canvas-release" onClick={() => void actions.releaseFilm()}>
            人工放行，继续出片
          </button>
        ) : null}
        <div className="ml-auto flex items-center gap-3">
          <p className="tabular text-caption text-text-2">
            重生次数 <span data-testid="regen-used">{doc.budget.used}</span> / {doc.budget.limit}
          </p>
          <SharePanel projectId={projectId} />
          <Link href={`/projects/${projectId}`} className="hilatv-canvas-back">
            返回项目
          </Link>
        </div>
        <p data-testid="viewport-zoom" className="tabular text-caption text-text-3">
          {Math.round(zoom * 100)}%
        </p>
        <p data-testid="layout-version" className="sr-only">
          {doc.layout_version}
        </p>
        {notice ? (
          <p role={noticeTone === "danger" ? "alert" : "status"} data-tone={noticeTone} data-testid="canvas-notice" className="hilatv-canvas-notice px-3 py-2 text-caption">
            {notice}
          </p>
        ) : null}
      </header>
      <div className="hilatv-canvas-body">
        <div className="hilatv-canvas-pane" data-testid="expert-flow">
          <CanvasToolRail />
          {isEmpty ? (
            <div className="hilatv-canvas-empty" data-testid="canvas-empty">
              <p className="hilatv-canvas-empty-hint">双击画布，自由生成节点</p>
              {agentOpen ? (
                <div className="hilatv-canvas-empty-compose" role="dialog" aria-label="一句话出整条片">
                  <label className="text-caption text-text-3" htmlFor="canvas-agent">
                    或者让 AI 一句话跑完整条片（会先生成分镜，再逐镜出画面）
                  </label>
                  <textarea
                    id="canvas-agent"
                    value={agentText}
                    onChange={(event) => setAgentText(event.target.value)}
                    placeholder="例如：给高压球阀做一条 15 秒产品宣传片，面向采购，风格稳重"
                    className="min-h-24 rounded-sm border border-border bg-raised px-2 py-2 text-small text-text-1"
                  />
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      className="inline-flex min-h-10 items-center rounded-full border border-blue px-4 text-small text-text-1 hover:bg-blue-soft disabled:cursor-not-allowed disabled:text-text-disabled"
                      disabled={!agentText.trim()}
                      onClick={() => void actions.startFilm(agentText)}
                    >
                      开始出片
                    </button>
                    <button
                      type="button"
                      className="inline-flex min-h-10 items-center rounded-full px-3 text-small text-text-2 hover:bg-hover hover:text-text-1"
                      onClick={() => setAgentOpen(false)}
                    >
                      取消
                    </button>
                  </div>
                </div>
              ) : (
                <button
                  type="button"
                  className="hilatv-canvas-empty-agent"
                  onClick={() => setAgentOpen(true)}
                >
                  ✦ 一句话出整条片（AI 自动搭工作流）
                </button>
              )}
              <div className="hilatv-canvas-empty-actions">
                <button type="button" className="hilatv-canvas-empty-card" onClick={() => create("brief")}>
                  <TextCursorInput aria-hidden="true" className="size-5" strokeWidth={1.5} />
                  <span>文本节点</span>
                  <span className="text-caption text-text-3">写一句话</span>
                </button>
                <button type="button" className="hilatv-canvas-empty-card" onClick={() => create("image")}>
                  <ImageIcon aria-hidden="true" className="size-5" strokeWidth={1.5} />
                  <span>图片节点</span>
                  <span className="text-caption text-text-3">写提示词直接出图</span>
                </button>
                <button
                  type="button"
                  className="hilatv-canvas-empty-card"
                  onClick={() => setScriptOpen(true)}
                >
                  <Sparkles aria-hidden="true" className="size-5" strokeWidth={1.5} />
                  <span>脚本分镜</span>
                  <span className="text-caption text-text-3">一句话出分镜</span>
                </button>
                <button type="button" className="hilatv-canvas-empty-card" onClick={() => create("video")}>
                  <Clapperboard aria-hidden="true" className="size-5" strokeWidth={1.5} />
                  <span>视频节点</span>
                  <span className="text-caption text-text-3">从图片或提示词出视频</span>
                </button>
              </div>
              {scriptOpen ? (
                <div className="hilatv-canvas-empty-compose" role="dialog" aria-label="一句话生成分镜">
                  <label className="text-caption text-text-3" htmlFor="canvas-script">
                    写一句话，先生成分镜脚本（不跑成片）
                  </label>
                  <textarea
                    id="canvas-script"
                    value={scriptText}
                    onChange={(event) => setScriptText(event.target.value)}
                    placeholder="例如：给高压球阀做一条 15 秒产品宣传片，面向采购，风格稳重"
                    className="min-h-24 rounded-sm border border-border bg-raised px-2 py-2 text-small text-text-1"
                  />
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      className="inline-flex min-h-10 items-center rounded-full border border-blue px-4 text-small text-text-1 hover:bg-blue-soft disabled:cursor-not-allowed disabled:text-text-disabled"
                      disabled={scriptBusy || !scriptText.trim()}
                      onClick={() => void actions.storyboard(scriptText)}
                    >
                      {scriptBusy ? "正在生成分镜" : "生成分镜"}
                    </button>
                    <button
                      type="button"
                      className="inline-flex min-h-10 items-center rounded-full px-3 text-small text-text-2 hover:bg-hover hover:text-text-1"
                      onClick={() => setScriptOpen(false)}
                    >
                      取消
                    </button>
                  </div>
                </div>
              ) : null}
            </div>
          ) : null}
          <CanvasActionsProvider value={actions}>
            <ReactFlow
              className="hilatv-canvas"
              colorMode="dark"
              nodes={nodes}
              edges={edges}
              nodeTypes={nodeTypes}
              onNodesChange={onNodesChange}
              onEdgesChange={(changes) => {
                setEdges((current) => applyEdgeChanges(changes, current));
              }}
              onConnect={onConnect}
              onConnectEnd={onConnectEnd}
              isValidConnection={isValidConnection}
              onMove={onMove}
              onMoveEnd={onMoveEnd}
              onSelectionChange={onSelectionChange}
              onBeforeDelete={onBeforeDelete}
              onNodesDelete={onNodesDelete}
              onEdgesDelete={onEdgesDelete}
              defaultViewport={doc.viewport}
              fitView={false}
              minZoom={0.25}
              maxZoom={1.75}
              panOnDrag
              zoomOnScroll
              zoomOnPinch
              panOnScroll={false}
              selectionOnDrag={false}
              selectionKeyCode="Shift"
              selectionMode={SelectionMode.Partial}
              multiSelectionKeyCode={["Meta", "Control"]}
              deleteKeyCode={["Backspace", "Delete"]}
              nodesDraggable
              nodesConnectable
              elementsSelectable
              nodesFocusable
              edgesFocusable
              connectionRadius={48}
              connectionLineStyle={{ stroke: "var(--blue)", strokeWidth: 1.5 }}
              proOptions={{ hideAttribution: false }}
              ariaLabelConfig={ariaLabelConfig}
            >
              <CanvasHotkeys />
              <CanvasAddMenu onCreate={create} />
              <CanvasZoomPill />
              <AutoFitView ready={ready} />
              <Background variant={BackgroundVariant.Dots} color="var(--border-strong)" gap={22} size={1.5} />

              <MiniMap
                pannable
                zoomable
                ariaLabel="小地图"
                bgColor="var(--surface)"
                maskColor="var(--overlay)"
                nodeStrokeWidth={0}
                nodeColor={(node) => (node.selected ? "var(--blue)" : "var(--border-strong)")}
              />
            </ReactFlow>
          </CanvasActionsProvider>
        </div>
        {selectedIds.length > 0 ? (
        <div className="hilatv-canvas-inspector-float">
        <Inspector
          doc={doc}
          selectedIds={selectedIds}
          busy={busyShot !== null}
          focus={focus}
          onRegenerate={(shotId, narration, promptSuffix) =>
            actions.regenerate(shotId, { narration, prompt_suffix: promptSuffix })
          }
          onChoose={actions.choose}
          onUpload={actions.uploadReference}
          onNarration={(shotId, narration) => {
            const node = doc.nodes.find((item) => asShot(item)?.shot_id === shotId);
            if (!node) return;
            run((client) => client.updateNodeData(node.id, { kind: "shot", narration }));
          }}
          onPrompt={(shotId, suffix) => {
            const node = doc.nodes.find((item) => asShot(item)?.shot_id === shotId);
            if (!node) return;
            run((client) => client.updateNodeData(node.id, { kind: "shot", prompt_suffix: suffix }));
          }}
          onBrief={(nodeId, text) => actions.changeBrief(nodeId, text)}
        />
        </div>
        ) : null}
      </div>
      {selectedIds.length >= 2 ? (
        <div className="hilatv-canvas-groupbar" role="group" aria-label="打组">
          <span className="text-caption text-text-2">已选 {selectedIds.length} 个节点</span>
          <input
            value={groupName}
            onChange={(event) => setGroupName(event.target.value)}
            placeholder="组合名字（可留空）"
            aria-label="组合名字"
            className="hilatv-canvas-groupbar-input"
          />
          <button
            type="button"
            className="hilatv-canvas-groupbar-save"
            onClick={() => actions.saveGroup(groupName)}
          >
            打组存入工具箱
          </button>
        </div>
      ) : null}
      {toolboxOpen ? (
        <div className="hilatv-canvas-toolbox" role="dialog" aria-label="工具箱">
          <p className="px-2 pb-1 text-caption text-text-3">工具箱 · 本机保存的组合</p>
          {groups.length === 0 ? (
            <p className="px-2 py-1 text-caption text-text-3">框选两个以上节点，点「打组存入工具箱」。</p>
          ) : (
            groups.map((group) => (
              <div key={group.id} className="flex items-center gap-2 px-2 py-1">
                <span className="min-w-0 flex-1 truncate text-small text-text-1">{group.name}</span>
                <span className="text-caption text-text-3">{group.nodes.length} 节点</span>
                <button
                  type="button"
                  className="rounded-sm px-2 py-1 text-caption text-text-1 hover:bg-hover"
                  onClick={() => actions.applyGroup(group)}
                >
                  套用
                </button>
                <button
                  type="button"
                  className="rounded-sm px-2 py-1 text-caption text-text-3 hover:bg-hover hover:text-danger"
                  onClick={() => actions.deleteGroup(group.id)}
                >
                  删除
                </button>
              </div>
            ))
          )}
          <button
            type="button"
            className="mt-1 w-full rounded-sm px-2 py-1 text-left text-caption text-text-3 hover:bg-hover"
            onClick={() => setToolboxOpen(false)}
          >
            关闭
          </button>
        </div>
      ) : null}
      <TimelineTrack
        doc={doc}
        busy={busyShot !== null}
        onCommit={(clips) => {
          run((client) => client.saveTimeline({ clips }));
        }}
      />
      <p className="sr-only">{AI_LABEL_COPY}</p>
    </div>
  );
}

function AutoFitView({ ready }: { ready: boolean }) {
  const { fitView } = useReactFlow();
  const done = useRef(false);
  useEffect(() => {
    if (!ready || done.current) return;
    done.current = true;
    const timer = window.setTimeout(() => void fitView({ padding: 0.2, duration: 0, maxZoom: 1 }), 240);
    return () => window.clearTimeout(timer);
  }, [fitView, ready]);
  return null;
}

function CanvasZoomPill() {
  const { zoomIn, zoomOut, fitView, getZoom } = useReactFlow();
  const [value, setValue] = useState(Math.round(getZoom() * 100));
  useEffect(() => {
    const timer = window.setInterval(() => setValue(Math.round(getZoom() * 100)), 400);
    return () => window.clearInterval(timer);
  }, [getZoom]);
  return (
    <div className="hilatv-canvas-zoompill" aria-label="画布控制">
      <button type="button" aria-label="缩小" onClick={() => void zoomOut()}>
        −
      </button>
      <button type="button" aria-label="适配画面" onClick={() => void fitView({ padding: 0.2 })}>
        {value}%
      </button>
      <button type="button" aria-label="放大" onClick={() => void zoomIn()}>
        ＋
      </button>
    </div>
  );
}

function CanvasHotkeys() {
  const { zoomIn, zoomOut } = useReactFlow();
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      const target = event.target;
      if (target instanceof HTMLElement) {
        const tag = target.tagName;
        if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || target.isContentEditable) return;
      }
      if (event.key === "+" || event.key === "=") {
        event.preventDefault();
        void zoomIn();
      } else if (event.key === "-" || event.key === "_") {
        event.preventDefault();
        void zoomOut();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [zoomIn, zoomOut]);
  return null;
}

function toFlowNode(node: CanvasNode, position?: CanvasPoint, selected?: boolean): Node<FlowData> {
  return {
    id: node.id,
    type: FREE.has(node.kind) ? node.kind : "pipeline",
    position: position ?? { x: node.position.x, y: node.position.y },
    data: { kind: node.kind, userCreated: node.user_created },
    selected: Boolean(selected),
    ariaLabel: labelFor(node),
  };
}

function toFlowEdge(edge: CanvasSnapshot["edges"][number], busyShotId: string | null): Edge {
  const running = busyShotId !== null && edge.target === busyShotId;
  return {
    id: edge.id,
    source: edge.source,
    target: edge.target,
    sourceHandle: edge.source_handle ?? undefined,
    targetHandle: edge.target_handle ?? undefined,
    label: ROLE_COPY[edge.role as EdgeRole] ?? "",
    animated: running,
    className: running ? "hilatv-edge-running" : undefined,
    style: { strokeWidth: 1.5 },
    labelStyle: { fill: "var(--text-2)", fontSize: 12 },
    labelBgStyle: { fill: "var(--surface)", fillOpacity: 1 },
    labelBgPadding: [4, 2],
    labelBgBorderRadius: 4,
  };
}

function labelFor(node: CanvasNode): string {
  if (node.kind === "brief") return "需求文本";
  if (node.kind === "ref_image") return "参考图";
  if (node.kind === "image") return "图片";
  if (node.kind === "video") return "视频";
  if (node.kind === "final") return "成片";
  const shot = asShot(node);
  if (shot) return `第 ${shot.index} 镜`;
  return "工序";
}

function nextPosition(flowNodes: Node<FlowData>[]): CanvasPoint {
  const bottom = flowNodes.reduce((max, node) => Math.max(max, node.position.y), 0);
  return { x: 40, y: Math.round(bottom + 280) };
}

function sameList(left: string[], right: string[]): boolean {
  return left.length === right.length && left.every((item, index) => item === right[index]);
}

function emptyDoc(projectId: string): CanvasSnapshot {
  return {
    project_id: projectId,
    nodes: [],
    edges: [],
    viewport: { x: 0, y: 0, zoom: 1 },
    layout_version: 1,
    sentence: "",
    budget: { used: 0, limit: 0, remaining: 0 },
    timeline: { clips: [], ai_label: true, duration_s: 0 },
  };
}
