"use client";

import {
  Background,
  Controls,
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
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { CanvasActionsProvider, type CanvasActions } from "@/components/canvas/canvas-context";
import { Inspector, type InspectorFocus } from "@/components/canvas/inspector";
import {
  BriefNode,
  FinalNode,
  PipelineNode,
  RefNode,
  ShotNode,
  type FlowData,
} from "@/components/canvas/nodes";
import { TimelineTrack } from "@/components/canvas/timeline-track";
import { Button } from "@/components/ui/button";
import { createCanvasClient, type CanvasClient } from "@/lib/canvas-client";
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
  final: FinalNode,
  pipeline: PipelineNode,
};

const FREE = new Set(["brief", "ref_image", "shot", "final"]);

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
  const [zoom, setZoom] = useState(1);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [choosingId, setChoosing] = useState<string | null>(null);
  const [busyShot, setBusyShot] = useState<string | null>(null);
  const [focus, setFocus] = useState<InspectorFocus | null>(null);

  const syncFlow = useCallback((next: CanvasSnapshot) => {
    const positions = new Map(nodesRef.current.map((node) => [node.id, node.position]));
    const selected = new Set(nodesRef.current.filter((node) => node.selected).map((node) => node.id));
    if (pendingSelect.current) {
      selected.clear();
      selected.add(pendingSelect.current);
      pendingSelect.current = null;
    }
    const flowNodes = next.nodes.map((node) => toFlowNode(node, positions.get(node.id), selected.has(node.id)));
    nodesRef.current = flowNodes;
    setNodes(flowNodes);
    setEdges(next.edges.map((edge) => toFlowEdge(edge, busyRef.current)));
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
          setNotice(message);
          if (error instanceof CanvasRequestError && error.status === 409 && clientRef.current) {
            const fresh = await clientRef.current.load();
            versionRef.current = fresh.layout_version;
            docRef.current = fresh;
            viewportRef.current = fresh.viewport;
            setDoc(fresh);
            syncFlow(fresh);
          }
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
    lastPersist.current = key;
    void enqueue(
      () =>
        client.saveLayout({
          layout_version: versionRef.current,
          positions,
          viewport,
        }),
      "remember",
    );
  }, [enqueue]);

  const scheduleLayout = useCallback(() => {
    window.clearTimeout(timerRef.current);
    timerRef.current = window.setTimeout(() => persistLayout(), 160);
  }, [persistLayout]);

  useEffect(() => {
    const client = createCanvasClient(projectId);
    clientRef.current = client;
    let cancel = false;
    void client.load().then((snapshot) => {
      if (cancel) return;
      versionRef.current = snapshot.layout_version;
      docRef.current = snapshot;
      viewportRef.current = snapshot.viewport;
      const flowNodes = snapshot.nodes.map((node) => toFlowNode(node));
      nodesRef.current = flowNodes;
      setDoc(snapshot);
      setNodes(flowNodes);
      setEdges(snapshot.edges.map((edge) => toFlowEdge(edge, null)));
      setZoom(snapshot.viewport.zoom);
      lastPersist.current = JSON.stringify({
        positions: Object.fromEntries(
          flowNodes.map((node) => [node.id, { x: Math.round(node.position.x), y: Math.round(node.position.y) }]),
        ),
        viewport: snapshot.viewport,
      });
      setReady(true);
    });
    return () => {
      cancel = true;
      window.clearTimeout(timerRef.current);
    };
  }, [projectId]);

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
      ).then(() => setNotice(""));
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
      }, "adopt");
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
      }, "adopt");
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

  const actions = useMemo<CanvasActions>(() => {
    return {
      doc: doc ?? emptyDoc(projectId),
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
  }, [choosingId, doc, enqueue, projectId, run]);

  function create(kind: "brief" | "ref_image") {
    const client = clientRef.current;
    if (!client) return;
    const position = nextPosition(nodesRef.current);
    const before = new Set((docRef.current?.nodes ?? []).map((node) => node.id));
    void enqueue(async () => {
      const next = await client.createNode({
        kind,
        position,
        data:
          kind === "brief"
            ? { text: "在这里写下要交给某一镜的话" }
            : { upload_id: "", thumbnail_url: null },
      });
      pendingSelect.current = next.nodes.find((node) => !before.has(node.id))?.id ?? null;
      return next;
    }, "adopt")
      .then(() => setNotice(""))
      .catch(() => undefined);
  }

  if (!doc || !ready) {
    return (
      <div className="hilatv-canvas-workspace" data-theme="dark" data-stage="canvas">
        <p className="p-6 text-small text-text-2">正在读取节点</p>
      </div>
    );
  }

  return (
    <div className="hilatv-canvas-workspace" data-theme="dark" data-stage="canvas">
      <header className="hilatv-canvas-toolbar">
        <div className="min-w-0">
          <h1 className="text-h2 font-medium">专家画布</h1>
          <p className="max-w-lg truncate text-caption text-text-2">{doc.sentence}</p>
        </div>
        <p className="tabular text-small text-text-2">
          重生次数 <span data-testid="regen-used">{doc.budget.used}</span> / {doc.budget.limit}
        </p>
        <p data-testid="viewport-zoom" className="tabular text-caption text-text-3">
          {Math.round(zoom * 100)}%
        </p>
        <p data-testid="layout-version" className="sr-only">
          {doc.layout_version}
        </p>
        <div className="ml-auto flex flex-wrap gap-2">
          <Button type="button" variant="secondary" onClick={() => create("brief")}>
            新建文本
          </Button>
          <Button type="button" variant="secondary" onClick={() => create("ref_image")}>
            新建参考图
          </Button>
        </div>
        <p className="w-full text-caption text-text-3">拖动画布平移，滚轮缩放，按住 Shift 框选。方向键移动选中的节点。</p>
        {notice ? (
          <p role="alert" data-testid="canvas-notice" className="w-full text-caption text-danger">
            {notice}
          </p>
        ) : null}
      </header>
      <div className="hilatv-canvas-body">
        <div className="hilatv-canvas-pane" data-testid="expert-flow">
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
              <Background color="var(--border)" gap={24} size={1} />
              <Controls showInteractive={false} aria-label="画布控制" />
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
