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

import { Badge } from "@/components/ui/badge";
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
      className={`w-60 rounded-md border bg-surface px-3 py-2 text-left ${
        data.active ? "border-blue ring-1 ring-blue" : "border-border"
      }`}
    >
      <p className="text-small font-medium text-text-1">{data.label}</p>
      <p className="text-caption text-text-2">{data.detail}</p>
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
    void ensureSession()
      .then(setToken)
      .catch(() => setToken(""));
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
    setTimelineText(
      JSON.stringify({ clips: body.timeline.clips, overlays: body.timeline.overlays }, null, 2),
    );
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
      const detail = node.completed ? (count > 0 ? `${count} 个候选` : "已完成") : "未跑";
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
        <h1 className="text-h1 font-medium">项目不存在</h1>
        <Button asChild className="mt-6">
          <Link href="/">返回输入</Link>
        </Button>
      </div>
    );
  }

  if (!canvas) {
    return <p className="text-small text-text-2">正在读取节点</p>;
  }

  const node = canvas.nodes.find((item) => item.id === active) ?? canvas.nodes[0];
  const showingMedia = active === "n08_keyframe" || active === "n10_video";

  return (
    <div className="mx-auto grid w-full min-w-0 max-w-360 gap-4 overflow-x-hidden">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          <p className="text-small text-text-2">专家模式</p>
          <h1 className="mt-1 text-h1 font-medium tracking-wide">节点画布</h1>
          {canvas.sentence ? (
            <p className="mt-2 break-words text-small text-text-2">{canvas.sentence}</p>
          ) : null}
        </div>
        <p className="tabular text-small text-text-2">
          重生次数 <span data-testid="regen-used">{canvas.budget.used}</span> / {canvas.budget.limit}
        </p>
      </div>

      <div className="flex min-w-0 flex-col gap-4 lg:flex-row lg:items-start">
        <div
          data-theme="dark"
          data-stage="canvas"
          className="h-120 w-full min-w-0 overflow-hidden rounded-lg border border-border bg-stage lg:h-180 lg:w-80 lg:shrink-0"
        >
          <ReactFlow
            className="h-full w-full"
            colorMode="dark"
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

        <section className="min-w-0 flex-1 rounded-lg border border-border bg-surface p-4 md:p-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-h2 font-medium">{node?.label}</h2>
              <p className="text-small text-text-2">
                {showingMedia
                  ? `${candidateCount(active, canvas.shots)} 个${active === "n08_keyframe" ? "关键帧" : "视频"}候选`
                  : node?.completed
                    ? "已完成"
                    : "未跑"}
              </p>
            </div>
            <Button type="button" onClick={() => void rerun()} disabled={busy} loading={busy}>
              {busy ? "正在重跑" : "重跑此节点"}
            </Button>
          </div>

          <p className="mt-3 text-small" data-testid="master-reason">
            {canvas.master.blocked ? "内容安全硬伤不能进入成片" : canvas.master.reason}
          </p>
          {error ? (
            <p role="alert" className="mt-3 break-words text-caption text-danger">
              {error}
            </p>
          ) : null}

          {showingMedia ? (
            <label className="mt-4 grid gap-2 text-small">
              补充提示词
              <textarea
                value={suffix}
                onChange={(event) => setSuffix(event.target.value)}
                maxLength={500}
                rows={2}
                className="w-full rounded-sm border border-border-strong bg-raised px-3 py-2 font-mono text-small"
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
                    <h3 className="text-h3 font-medium">
                      第 {shot.order} 镜{shot.purpose ? ` · ${shot.purpose}` : ""}
                    </h3>
                    <ul className="mt-2 grid gap-3">
                      {rows.map((candidate) => (
                        <li
                          key={candidate.candidate_id}
                          data-testid="candidate"
                          className="min-w-0 rounded-md border border-border bg-surface p-3"
                        >
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <p className="text-small font-medium">{verdictLabel(candidate.verdict)}</p>
                            {candidate.selected ? <Badge tone="blue">已选用</Badge> : null}
                          </div>
                          <p className="mt-1 break-all font-mono text-caption text-text-3">
                            {candidate.model}
                            {candidate.seed != null ? ` · seed ${candidate.seed}` : ""}
                          </p>
                          {candidate.media_url ? (
                            candidate.frame === "video" || active === "n10_video" ? (
                              <video
                                data-theme="dark"
                                className="mt-2 max-h-40 w-full rounded-sm bg-stage object-contain"
                                src={token ? withSession(apiUrl(candidate.media_url), token) : undefined}
                                controls
                                playsInline
                              />
                            ) : (
                              // eslint-disable-next-line @next/next/no-img-element
                              <img
                                data-theme="dark"
                                className="mt-2 max-h-40 w-full rounded-sm bg-stage object-contain"
                                src={token ? withSession(apiUrl(candidate.media_url), token) : undefined}
                                alt=""
                              />
                            )
                          ) : candidate.media_note ? (
                            <p className="mt-2 text-caption text-text-3">{candidate.media_note}</p>
                          ) : null}
                          <p className="mt-2 break-words font-mono text-caption">{candidate.prompt}</p>
                          {candidate.verdict.hard_fail.length > 0 ? (
                            <p className="mt-2 break-words text-caption text-text-2">
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
              <p className="text-small">
                {canvas.timeline.ai_label ? "成片保留「AI生成」标识" : "时间轴缺少「AI生成」标识"}
              </p>
              <label className="grid gap-2 text-small">
                时间轴 JSON
                <textarea
                  aria-label="时间轴 JSON"
                  value={timelineText}
                  onChange={(event) => setTimelineText(event.target.value)}
                  rows={8}
                  className="w-full break-all rounded-sm border border-border-strong bg-raised px-3 py-2 font-mono text-caption"
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
