"use client";

import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";
import { useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { useCanvasActions } from "@/components/canvas/canvas-context";
import { FrameView } from "@/components/canvas/frame-view";
import {
  AI_LABEL_COPY,
  EMPTY_FRAME_COPY,
  asBrief,
  asFinal,
  asRef,
  asShot,
  shotVerdictLabel,
  upstreamFor,
  type CanvasNode,
  type ShotCandidate,
  type ShotVerdict,
} from "@/lib/canvas-contract";
import { cn } from "@/lib/utils";

export type FlowData = {
  kind: string;
  userCreated: boolean;
  [key: string]: unknown;
};

const actionClass =
  "nodrag nopan nowheel flex min-h-11 items-center justify-center rounded-sm px-2 text-center text-caption text-text-1 hover:bg-hover";

function Shell({
  id,
  title,
  x,
  y,
  selected,
  dot,
  testId,
  trailing,
  children,
}: {
  id: string;
  title: string;
  x: number;
  y: number;
  selected: boolean;
  dot: string;
  testId?: string;
  trailing?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <article
      data-testid={testId ?? `node-${id}`}
      data-x={Math.round(x)}
      data-y={Math.round(y)}
      className={cn(
        "w-60 rounded-md border-2 bg-surface text-left",
        selected ? "border-blue" : "border-border",
      )}
    >
      <header className="flex items-center justify-between gap-2 border-b border-border px-3 py-2">
        <h2 className="text-h3 font-medium text-text-1">{title}</h2>
        <span className="flex items-center gap-2">
          {trailing}
          <span aria-hidden="true" className={cn("size-2 shrink-0 rounded-full", dot)} />
        </span>
      </header>
      <div className="grid gap-2 p-3">{children}</div>
    </article>
  );
}

function verdictDot(verdict: ShotVerdict): string {
  if (verdict === "pass") return "bg-success";
  if (verdict === "hard_fail") return "bg-danger";
  return "bg-warning";
}

function verdictTone(verdict: ShotVerdict): "success" | "danger" | "warning" {
  if (verdict === "pass") return "success";
  if (verdict === "hard_fail") return "danger";
  return "warning";
}

export function BriefNode({ id, selected, positionAbsoluteX, positionAbsoluteY }: NodeProps<Node<FlowData, "brief">>) {
  const { doc, changeBrief } = useCanvasActions();
  const node = doc.nodes.find((item) => item.id === id);
  const data = node ? asBrief(node) : null;
  const [text, setText] = useState(data?.text ?? "");
  useEffect(() => {
    setText(data?.text ?? "");
  }, [data?.text]);
  if (!node || !data) return null;
  return (
    <Shell
      id={id}
      title="需求文本"
      x={positionAbsoluteX}
      y={positionAbsoluteY}
      selected={selected}
      dot={text.trim() ? "bg-success" : "bg-text-3"}
    >
      <Handle type="source" position={Position.Right} id="text" data-testid={`handle-${id}-source`} />
      <textarea
        aria-label="需求文本"
        value={text}
        rows={4}
        onChange={(event) => setText(event.target.value)}
        onBlur={() => changeBrief(id, text)}
        className="nodrag nopan nowheel w-full resize-none rounded-sm border border-border-strong bg-raised px-3 py-2 text-small text-text-1"
      />
    </Shell>
  );
}

export function RefNode({ id, selected, positionAbsoluteX, positionAbsoluteY }: NodeProps<Node<FlowData, "ref_image">>) {
  const { doc, uploadRefNode } = useCanvasActions();
  const node = doc.nodes.find((item) => item.id === id);
  const data = node ? asRef(node) : null;
  if (!node || !data) return null;
  return (
    <Shell
      id={id}
      title="参考图"
      x={positionAbsoluteX}
      y={positionAbsoluteY}
      selected={selected}
      dot={data.thumbnail_url ? "bg-success" : "bg-text-3"}
    >
      <Handle type="source" position={Position.Right} id="reference" data-testid={`handle-${id}-source`} />
      <FrameView url={data.thumbnail_url} alt={id === "ref-product" ? "产品参考图" : "参考图"} />
      <label className={cn(actionClass, "border border-border-strong bg-surface")}>
        <input
          type="file"
          accept="image/png,image/jpeg,image/webp,image/gif"
          className="sr-only"
          aria-label="上传参考图"
          data-testid={`upload-ref-${id}`}
          onChange={(event) => {
            const file = event.target.files?.[0];
            event.target.value = "";
            if (file) uploadRefNode(id, file);
          }}
        />
        上传参考图
      </label>
    </Shell>
  );
}

export function ShotNode({ id, selected, positionAbsoluteX, positionAbsoluteY }: NodeProps<Node<FlowData, "shot">>) {
  const actions = useCanvasActions();
  const node = actions.doc.nodes.find((item) => item.id === id);
  const data = node ? asShot(node) : null;
  const [deriveOpen, setDeriveOpen] = useState(false);
  const [generatorOpen, setGeneratorOpen] = useState(false);
  const [narration, setNarration] = useState(data?.narration ?? "");
  const [prompt, setPrompt] = useState(data?.prompt_suffix ?? "");
  useEffect(() => {
    setNarration(data?.narration ?? "");
    setPrompt(data?.prompt_suffix ?? "");
  }, [data?.narration, data?.prompt_suffix]);
  if (!node || !data) return null;
  const upstream = upstreamFor(actions.doc, id);
  const choosing = actions.choosingId === id;
  return (
    <Shell
      id={id}
      title={`第 ${data.index} 镜`}
      x={positionAbsoluteX}
      y={positionAbsoluteY}
      selected={selected}
      dot={verdictDot(data.verdict)}
      trailing={
        <span className="relative">
          <button
            type="button"
            aria-label="从这一镜派生节点"
            aria-expanded={deriveOpen}
            className="nodrag nopan flex size-6 items-center justify-center rounded-sm text-caption text-text-2 hover:bg-hover hover:text-text-1"
            onClick={() => setDeriveOpen((open) => !open)}
          >
            ＋
          </button>
          {deriveOpen ? (
            <span className="nodrag nopan absolute right-0 top-7 z-20 flex w-24 flex-col rounded-sm border border-border bg-surface p-1">
              <button
                type="button"
                className="rounded-sm px-2 py-1 text-left text-caption text-text-1 hover:bg-hover"
                onClick={() => {
                  actions.derive(id, "brief");
                  setDeriveOpen(false);
                }}
              >
                文本节点
              </button>
              <button
                type="button"
                className="rounded-sm px-2 py-1 text-left text-caption text-text-1 hover:bg-hover"
                onClick={() => {
                  actions.derive(id, "ref_image");
                  setDeriveOpen(false);
                }}
              >
                图片节点
              </button>
            </span>
          ) : null}
        </span>
      }
    >
      <Handle type="target" position={Position.Left} id="in" data-testid={`handle-${id}-target`} />
      <Handle type="source" position={Position.Right} id="out" data-testid={`handle-${id}-source`} />
      <FrameView
        url={data.thumbnail_url}
        alt={`第 ${data.index} 镜画面`}
        testId={`frame-${id}`}
      />
      {data.candidates.length > 0 ? (
        <div data-testid={`candidates-${id}`} className="grid grid-cols-3 gap-1">
          {data.candidates.slice(0, 6).map((item) => (
            <span key={item.candidate_id} className="aspect-video overflow-hidden rounded-xs bg-stage">
              {item.thumbnail_url ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={item.thumbnail_url}
                  alt={`候选 ${item.candidate_id}`}
                  className="size-full object-cover"
                />
              ) : (
                <span className="flex size-full items-center justify-center text-caption text-text-3">
                  {item.kind === "video" ? "视频" : "图"}
                </span>
              )}
            </span>
          ))}
        </div>
      ) : null}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Badge tone={verdictTone(data.verdict)}>{shotVerdictLabel(data.verdict, data.review)}</Badge>
        <span className="tabular text-caption text-text-2">{data.duration_s.toFixed(1)} 秒</span>
      </div>
      <p className="tabular text-caption text-text-3">重生 {data.regen_count} 次</p>
      {upstream.refs.length > 0 ? (
        <div className="flex items-center gap-2">
          {upstream.refs.map((ref) =>
            ref.thumbnailUrl ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                key={ref.nodeId}
                src={ref.thumbnailUrl}
                alt="已接入的参考图"
                data-testid="upstream-ref"
                className="size-10 rounded-sm bg-stage object-contain"
              />
            ) : (
              <span key={ref.nodeId} data-testid="upstream-ref" className="text-caption text-text-3">
                {EMPTY_FRAME_COPY}
              </span>
            ),
          )}
          <span className="text-caption text-text-2">已接入参考图</span>
        </div>
      ) : null}
      {data.reference_thumbnail_url ? (
        <div className="flex items-center gap-2">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={data.reference_thumbnail_url}
            alt="本镜替换的参考图"
            className="size-10 rounded-sm bg-stage object-contain"
          />
          <span className="text-caption text-text-2">已替换参考图</span>
        </div>
      ) : null}
      <div className="grid grid-cols-2 gap-1">
        <button type="button" className={actionClass} onClick={() => actions.regenerate(data.shot_id)}>
          再生这一镜
        </button>
        <button type="button" className={actionClass} onClick={() => actions.editWords(data.shot_id)}>
          改这一镜的话
        </button>
        <button
          type="button"
          className={actionClass}
          aria-expanded={choosing}
          onClick={() => actions.setChoosing(choosing ? null : id)}
        >
          选用另一张
        </button>
        <label className={cn(actionClass, "cursor-pointer")}>
          <input
            type="file"
            accept="image/png,image/jpeg,image/webp,image/gif"
            className="sr-only"
            aria-label="上传替换参考图"
            data-testid={`upload-${id}`}
            onChange={(event) => {
              const file = event.target.files?.[0];
              event.target.value = "";
              if (file) actions.uploadReference(data.shot_id, file);
            }}
          />
          上传替换参考图
        </label>
      </div>
      <button
        type="button"
        className={cn(actionClass, "border border-border")}
        aria-expanded={generatorOpen}
        onClick={() => setGeneratorOpen((open) => !open)}
      >
        生成器 {generatorOpen ? "收起" : "展开"}
      </button>
      {generatorOpen ? (
        <div className="grid gap-1" data-testid={`generator-${id}`}>
          <label className="text-caption text-text-3" htmlFor={`narration-${id}`}>
            这一镜的话
          </label>
          <textarea
            id={`narration-${id}`}
            value={narration}
            onChange={(event) => setNarration(event.target.value)}
            className="nodrag nowheel min-h-16 rounded-sm border border-border bg-raised px-2 py-1 text-caption text-text-1"
          />
          <label className="text-caption text-text-3" htmlFor={`prompt-${id}`}>
            补充提示词
          </label>
          <textarea
            id={`prompt-${id}`}
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
            className="nodrag nowheel min-h-16 rounded-sm border border-border bg-raised px-2 py-1 text-caption text-text-1"
          />
          <button
            type="button"
            className={cn(actionClass, "border border-blue text-text-1 hover:bg-blue-soft")}
            onClick={() => actions.regenerate(data.shot_id, { narration, prompt_suffix: prompt })}
          >
            生成这一镜
          </button>
        </div>
      ) : null}
      <button type="button" className={actionClass} onClick={() => actions.showPrompt(data.shot_id)}>
        查看提示词
      </button>
      {choosing ? (
        <ul role="listbox" aria-label="候选" className="nodrag nopan nowheel grid gap-1">
          {data.candidates.map((candidate) => (
            <li key={candidate.candidate_id}>
              <CandidateOption
                candidate={candidate}
                selected={candidate.candidate_id === data.selected_candidate_id}
                onPick={() => actions.choose(data.shot_id, candidate.candidate_id)}
              />
            </li>
          ))}
        </ul>
      ) : null}
    </Shell>
  );
}

function CandidateOption({
  candidate,
  selected,
  onPick,
}: {
  candidate: ShotCandidate;
  selected: boolean;
  onPick: () => void;
}) {
  return (
    <button
      type="button"
      role="option"
      aria-selected={selected}
      data-testid={`pick-${candidate.candidate_id}`}
      className={cn(actionClass, "justify-between gap-2 border border-border", selected && "border-blue")}
      onClick={onPick}
    >
      <span>{candidate.kind === "keyframe" ? "关键帧" : "视频"}</span>
      <span>{shotVerdictLabel(candidate.verdict, candidate.review)}</span>
      {candidate.thumbnail_url ? null : <span>{EMPTY_FRAME_COPY}</span>}
    </button>
  );
}

export function FinalNode({ id, selected, positionAbsoluteX, positionAbsoluteY }: NodeProps<Node<FlowData, "final">>) {
  const { doc } = useCanvasActions();
  const node = doc.nodes.find((item) => item.id === id);
  const data = node ? asFinal(node) : null;
  if (!node || !data) return null;
  const frames = doc.timeline.clips
    .map((clip) => {
      const shot = doc.nodes.find((item) => asShot(item)?.shot_id === clip.shot_id);
      return shot ? asShot(shot)?.thumbnail_url : null;
    })
    .filter((url): url is string => Boolean(url));
  return (
    <Shell
      id={id}
      title="成片"
      x={positionAbsoluteX}
      y={positionAbsoluteY}
      selected={selected}
      dot="bg-success"
    >
      <Handle type="target" position={Position.Left} id="in" data-testid={`handle-${id}-target`} />
      <FrameView url={frames[0]} alt="成片画面" />
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone="neutral">{AI_LABEL_COPY}</Badge>
        <span className="text-caption text-text-3">标识不能关闭</span>
      </div>
      <p className="tabular text-caption text-text-2">
        {doc.timeline.duration_s.toFixed(1)} 秒
        {data.version_id ? ` · ${data.version_id}` : ""}
      </p>
    </Shell>
  );
}

export function PipelineNode({ id, selected, positionAbsoluteX, positionAbsoluteY }: NodeProps<Node<FlowData, "pipeline">>) {
  const { doc } = useCanvasActions();
  const node = doc.nodes.find((item) => item.id === id);
  if (!node) return null;
  return (
    <Shell
      id={id}
      title={pipelineTitle(node)}
      x={positionAbsoluteX}
      y={positionAbsoluteY}
      selected={selected}
      dot="bg-text-3"
    >
      <p className="text-caption text-text-2">工序节点</p>
    </Shell>
  );
}

function pipelineTitle(node: CanvasNode): string {
  const known: Record<string, string> = {
    n01_brief: "需求理解",
    n08_keyframe: "关键帧",
    n10_video: "视频",
    n15_compose: "合成",
  };
  return known[node.kind] ?? "工序";
}
