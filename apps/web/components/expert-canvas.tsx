"use client";

import {
  Background,
  Controls,
  ReactFlow,
  type Node,
  type NodeMouseHandler,
  type NodeProps,
} from "@xyflow/react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { apiFetch, apiUrl, ensureSession, errorMessage, withSession } from "@/lib/api";
import {
  candidateCount,
  candidatesFor,
  verdictLabel,
  type ExpertCanvas,
  type ExpertCandidate,
} from "@/lib/expert";

import "@xyflow/react/dist/style.css";

type NodeData = {
  label: string;
  detail: string;
  nodeId: string;
  active: boolean;
};

function ExpertNode({ data }: NodeProps<Node<NodeData>>) {
  return (
    <div
      data-testid={`node-${data.nodeId}`}
      className={`w-[200px] rounded-lg border px-3 py-2 text-left shadow-sm ${
        data.active ? "border-primary bg-accent" : "border-border bg-card"
      }`}
    >
      <p className="text-sm font-medium">{data.label}</p>
      <p className="text-xs text-muted-foreground">{data.detail}</p>
    </div>
  );
}

const nodeTypes = { expert: ExpertNode };

export function ExpertCanvas({ projectId }: { projectId: string }) {
  const [canvas, setCanvas] = useState<ExpertCanvas | null>(null);
  const [active, setActive] = useState("n08_keyframe");
  const [missing, setMissing] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [suffix, setSuffix] = useState("");
  const [timelineText, setTimelineText] = useState("");
  const [token, setToken] = useState("");

  useEffect(() => {
    void ensureSession().then(setToken).catch(() => setToken(""));
  }, []);

  const load = useCallback(async () => {
    const response = await apiFetch(`/v1/projects/${encodeURIComponent(projectId)}/canvas`);
    if (response.status === 404) {
      setMissing(true);
      return;
    }
    if (!response.ok) {
      setError(await errorMessage(response));
      return;
    }
    const body = (await response.json()) as ExpertCanvas;
    setCanvas(body);
    setTimelineText(JSON.stringify({ clips: body.timeline.clips, overlays: body.timeline.overlays }, null, 2));
  }, [projectId]);

  useEffect(() => {
    void load();
  }, [load]);

  const onNodeClick = useCallback<NodeMouseHandler>((_, node) => {
    setActive(node.id);
    setError("");
  }, []);

  const nodes: Node<NodeData>[] = useMemo(() => {
    if (!canvas) return [];
    return canvas.nodes.map((node, index) => {
      const count = candidateCount(node.id, canvas.shots);
      const detail = node.completed
        ? count > 0
          ? `${count} 个候选`
          : "已完成"
        : "未跑";
      return {
        id: node.id,
        type: "expert",
        position: { x: 16, y: index * 84 },
        data: { label: node.label, detail, nodeId: node.id, active: node.id === active },
        draggable: false,
        connectable: false,
      };
    });
  }, [canvas, active]);

  const edges = useMemo(
    () =>
      (canvas?.edges ?? []).map((edge) => ({
        id: `${edge.source}-${edge.target}`,
        source: edge.source,
        target: edge.target,
      })),
    [canvas],
  );

  async function rerun() {
    setBusy(true);
    setError("");
    try {
      const response = await apiFetch(`/v1/projects/${encodeURIComponent(projectId)}/expert/rerun`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ node: active, prompt_suffix: suffix }),
      });
      if (!response.ok) {
        setError(await errorMessage(response));
        return;
      }
      const body = (await response.json()) as { canvas?: ExpertCanvas };
      if (body.canvas) {
        setCanvas(body.canvas);
        setTimelineText(
          JSON.stringify(
            { clips: body.canvas.timeline.clips, overlays: body.canvas.timeline.overlays },
            null,
            2,
          ),
        );
      } else {
        await load();
      }
    } finally {
      setBusy(false);
    }
  }

  async function choose(candidate: ExpertCandidate) {
    setBusy(true);
    setError("");
    try {
      const response = await apiFetch(`/v1/projects/${encodeURIComponent(projectId)}/expert/select`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          node: active,
          shot_id: candidate.shot_id,
          candidate_id: candidate.candidate_id,
        }),
      });
      if (!response.ok) {
        setError(await errorMessage(response));
        return;
      }
      const body = (await response.json()) as { canvas?: ExpertCanvas };
      if (body.canvas) setCanvas(body.canvas);
    } finally {
      setBusy(false);
    }
  }

  async function saveTimeline() {
    setBusy(true);
    setError("");
    try {
      let parsed: unknown;
      try {
        parsed = JSON.parse(timelineText);
      } catch {
        setError("时间轴不是合法 JSON");
        return;
      }
      const response = await apiFetch(`/v1/projects/${encodeURIComponent(projectId)}/expert/timeline`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(parsed),
      });
      if (!response.ok) {
        setError(await errorMessage(response));
        return;
      }
      const body = (await response.json()) as { canvas?: ExpertCanvas };
      if (body.canvas) setCanvas(body.canvas);
    } finally {
      setBusy(false);
    }
  }

  if (missing) {
    return (
      <div>
        <h1 className="text-3xl font-semibold">项目不存在</h1>
        <Button asChild className="mt-6">
          <Link href="/">返回输入</Link>
        </Button>
      </div>
    );
  }

  if (!canvas) {
    return <p className="text-sm text-muted-foreground">正在读取节点</p>;
  }

  const node = canvas.nodes.find((item) => item.id === active) ?? canvas.nodes[0];
  const showingMedia = active === "n08_keyframe" || active === "n10_video";

  return (
    <div className="grid min-w-0 gap-4 overflow-x-hidden">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm text-muted-foreground">专家模式</p>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight sm:text-3xl">节点画布</h1>
          {canvas.sentence ? (
            <p className="mt-2 break-words text-sm text-muted-foreground">{canvas.sentence}</p>
          ) : null}
        </div>
        <p className="text-sm text-muted-foreground">
          重生次数 <span data-testid="regen-used">{canvas.budget.used}</span> / {canvas.budget.limit}
        </p>
      </div>

      <div className="grid min-w-0 gap-4 lg:grid-cols-[minmax(0,280px)_minmax(0,1fr)]">
        <div className="h-[70dvh] w-full min-w-0 overflow-hidden rounded-lg border border-border bg-card">
          <ReactFlow
            className="h-full w-full"
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            onNodeClick={onNodeClick}
            fitView={false}
            defaultViewport={{ x: 0, y: 0, zoom: 1 }}
            minZoom={0.8}
            maxZoom={1.4}
            nodesDraggable={false}
            nodesConnectable={false}
            elementsSelectable
            proOptions={{ hideAttribution: false }}
          >
            <Background />
            <Controls showInteractive={false} />
          </ReactFlow>
        </div>

        <section className="min-w-0 rounded-lg border border-border bg-card p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-lg font-medium">{node?.label}</h2>
              <p className="text-sm text-muted-foreground">
                {showingMedia
                  ? `${candidateCount(active, canvas.shots)} 个${active === "n08_keyframe" ? "关键帧" : "视频"}候选`
                  : node?.completed
                    ? "已完成"
                    : "未跑"}
              </p>
            </div>
            <Button type="button" onClick={() => void rerun()} disabled={busy}>
              {busy ? "正在重跑" : "重跑此节点"}
            </Button>
          </div>

          <p className="mt-3 text-sm" data-testid="master-reason">
            {canvas.master.blocked ? "内容安全硬伤不能进入成片" : canvas.master.reason}
          </p>
          {error ? (
            <p role="alert" className="mt-3 break-words text-sm text-destructive">
              {error}
            </p>
          ) : null}

          {showingMedia ? (
            <label className="mt-4 grid gap-2 text-sm">
              补充提示词
              <textarea
                value={suffix}
                onChange={(event) => setSuffix(event.target.value)}
                maxLength={500}
                rows={2}
                className="w-full rounded-md border border-input bg-background px-3 py-2"
                aria-label="补充提示词"
              />
            </label>
          ) : null}

          {showingMedia ? (
            <div className="mt-4 grid gap-4">
              {canvas.shots.map((shot) => {
                const rows = candidatesFor(active, shot);
                if (rows.length === 0) return null;
                return (
                  <div key={shot.shot_id} className="min-w-0">
                    <h3 className="text-sm font-medium">
                      第 {shot.order} 镜{shot.purpose ? ` · ${shot.purpose}` : ""}
                    </h3>
                    <ul className="mt-2 grid gap-3">
                      {rows.map((candidate) => (
                        <li
                          key={candidate.candidate_id}
                          data-testid="candidate"
                          className="min-w-0 rounded-md border border-border p-3"
                        >
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <p className="text-sm font-medium">{verdictLabel(candidate.verdict)}</p>
                            {candidate.selected ? (
                              <span className="rounded-full bg-accent px-2 py-0.5 text-xs">已选用</span>
                            ) : null}
                          </div>
                          <p className="mt-1 break-all text-xs text-muted-foreground">
                            {candidate.model}
                            {candidate.seed != null ? ` · seed ${candidate.seed}` : ""}
                          </p>
                          {candidate.media_url ? (
                            candidate.frame === "video" || active === "n10_video" ? (
                              <video
                                className="mt-2 max-h-40 w-full rounded bg-black"
                                src={token ? withSession(apiUrl(candidate.media_url), token) : undefined}
                                controls
                                playsInline
                              />
                            ) : (
                              // eslint-disable-next-line @next/next/no-img-element
                              <img
                                className="mt-2 max-h-40 w-full rounded object-contain"
                                src={token ? withSession(apiUrl(candidate.media_url), token) : undefined}
                                alt=""
                              />
                            )
                          ) : candidate.media_note ? (
                            <p className="mt-2 text-xs text-muted-foreground">{candidate.media_note}</p>
                          ) : null}
                          <p className="mt-2 break-words text-sm leading-6">{candidate.prompt}</p>
                          {candidate.verdict.hard_fail.length > 0 ? (
                            <p className="mt-2 break-words text-xs text-muted-foreground">
                              {candidate.verdict.hard_fail.join("、")}
                            </p>
                          ) : null}
                          <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            className="mt-3"
                            disabled={busy || candidate.verdict.blocked}
                            onClick={() => void choose(candidate)}
                          >
                            选用这条
                          </Button>
                        </li>
                      ))}
                    </ul>
                  </div>
                );
              })}
            </div>
          ) : null}

          {active === "n15_compose" && canvas.timeline.present ? (
            <div className="mt-4 grid gap-2">
              <p className="text-sm">
                {canvas.timeline.ai_label ? "成片保留「AI生成」标识" : "时间轴缺少「AI生成」标识"}
              </p>
              <label className="grid gap-2 text-sm">
                时间轴 JSON
                <textarea
                  aria-label="时间轴 JSON"
                  value={timelineText}
                  onChange={(event) => setTimelineText(event.target.value)}
                  rows={8}
                  className="w-full break-all rounded-md border border-input bg-background px-3 py-2 font-mono text-xs"
                />
              </label>
              <Button type="button" variant="outline" onClick={() => void saveTimeline()} disabled={busy}>
                保存时间轴
              </Button>
            </div>
          ) : null}
        </section>
      </div>
    </div>
  );
}
