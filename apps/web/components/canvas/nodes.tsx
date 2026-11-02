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
  type ImageData,
  shotVerdictLabel,
  upstreamFor,
  type CanvasNode,
  type ShotCandidate,
  type ShotVerdict,
} from "@/lib/canvas-contract";
import { apiFetch } from "@/lib/api";
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
                  {item.kind === "video" ? "视频" : item.kind === "audio" ? "音频" : "图"}
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
          <button
            type="button"
            className={cn(actionClass, "border border-border-strong")}
            onClick={() => actions.dubShot(data.shot_id, narration)}
          >
            生成配音
          </button>
          {data.voiceover_url ? <VoiceoverPlayer url={data.voiceover_url} /> : null}
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

function VoiceoverPlayer({ url }: { url: string }) {
  const [src, setSrc] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let revoked: string | null = null;
    let cancelled = false;
    setFailed(false);
    void apiFetch(url)
      .then(async (response) => {
        if (!response.ok) throw new Error("配音读不到");
        const blob = await response.blob();
        if (cancelled) return;
        revoked = URL.createObjectURL(blob);
        setSrc(revoked);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
      if (revoked) URL.revokeObjectURL(revoked);
    };
  }, [url]);
  if (failed) return <span className="text-caption text-text-3">配音暂时听不了</span>;
  if (!src) return <span className="text-caption text-text-3">正在准备配音…</span>;
  return (
    <audio controls src={src} preload="metadata" data-testid="voiceover-player" className="col-span-2 h-9 w-full" />
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

const PRO_FEATURES = [
  {
    label: "多机位九宫格",
    note: "同一主体的九个机位",
    prompt: "九宫格多机位：正面、侧面、背面、俯拍、仰拍、特写、全景、过肩、低角度，风格统一，人物一致",
  },
  {
    label: "剧情推演四宫格",
    note: "起承转合一格一张",
    prompt: "四宫格剧情推演：起、承、转、合各一格，人物、服装和场景保持一致",
  },
  {
    label: "25 宫格连贯分镜",
    note: "一格一个镜头",
    prompt: "25 宫格连贯分镜：一格一个镜头，动作连贯，人物一致，镜头之间不跳戏",
  },
  {
    label: "角色三视图",
    note: "正面 / 侧面 / 背面",
    prompt: "角色三视图：正面、侧面、背面，纯色背景，比例一致，服装细节一致",
  },
  {
    label: "画面推演（3 秒后）",
    note: "顺着当前画面往后推",
    prompt: "按当前画面推演 3 秒后的画面，动作自然延续，光线和构图不变",
  },
  {
    label: "画面推演（5 秒前）",
    note: "补出前因",
    prompt: "按当前画面推演 5 秒前的画面，补出合理的起因，光线和构图不变",
  },
  {
    label: "电影级光影校正",
    note: "主光 / 轮廓光 / 冷暖",
    prompt: "电影级光影：明确主光方向、加轮廓光、冷暖对比，保持原有构图和主体",
  },
] as const;

export function ContentNode({ id, selected, positionAbsoluteX, positionAbsoluteY }: NodeProps<Node<FlowData, "image" | "video">>) {
  const actions = useCanvasActions();
  const node = actions.doc.nodes.find((item) => item.id === id);
  const data =
    node && (node.kind === "image" || node.kind === "video" || node.kind === "audio")
      ? (node.data as ImageData)
      : null;
  const [prompt, setPrompt] = useState(data?.prompt ?? "");
  const [busy, setBusy] = useState(false);
  const [proOpen, setProOpen] = useState(false);
  useEffect(() => {
    setPrompt(data?.prompt ?? "");
  }, [data?.prompt]);
  if (!node || !data) return null;
  const isVideo = node.kind === "video";
  const isAudio = node.kind === "audio";
  const candidates = data.candidates ?? [];
  const chosen = candidates.find((item) => item.candidate_id === data.selected_candidate_id) ?? candidates[0];
  return (
    <Shell
      id={id}
      title={isAudio ? "音频" : isVideo ? "视频" : "图片"}
      x={positionAbsoluteX}
      y={positionAbsoluteY}
      selected={selected}
      dot={chosen ? "bg-success" : "bg-warning"}
    >
      <Handle type="target" position={Position.Left} id="in" data-testid={`handle-${id}-target`} />
      <Handle type="source" position={Position.Right} id="out" data-testid={`handle-${id}-source`} />
      <FrameView
        url={chosen?.thumbnail_url ?? null}
        alt={isVideo ? "视频画面" : "图片"}
        testId={`frame-${id}`}
      />
      {candidates.length > 0 ? (
        <div data-testid={`candidates-${id}`} className="grid grid-cols-3 gap-1">
          {candidates.slice(-6).map((item) => (
            <span key={item.candidate_id} className="flex aspect-video items-center justify-center rounded-xs bg-stage text-caption text-text-3">
              {item.kind === "video" ? "视频" : item.kind === "audio" ? "音频" : "图"}
            </span>
          ))}
        </div>
      ) : null}
      <textarea
        aria-label={isVideo ? "视频提示词" : "图片提示词"}
        value={prompt}
        onChange={(event) => setPrompt(event.target.value)}
        placeholder={
          isAudio
            ? "想要的音乐，例如：轻快的电子背景乐，节奏稳"
            : isVideo
              ? "想要的镜头运动，例如：镜头缓慢推进"
              : "想要的画面，例如：香水瓶特写，夜色，丝绒质感"
        }
        className="nodrag nowheel min-h-16 rounded-sm border border-border bg-raised px-2 py-1 text-caption text-text-1"
      />
      <div className="relative">
        <button
          type="button"
          className={cn(actionClass, "border border-border text-text-2")}
          aria-expanded={proOpen}
          onClick={() => setProOpen((open) => !open)}
        >
          ✦ 专业功能（/）
        </button>
        {proOpen ? (
          <div className="nodrag nopan absolute bottom-8 left-0 z-20 flex w-56 flex-col rounded-sm border border-border bg-surface p-1">
            {PRO_FEATURES.map((item) => (
              <button
                key={item.label}
                type="button"
                className="rounded-sm px-2 py-1 text-left text-caption text-text-1 hover:bg-hover"
                onClick={() => {
                  const base = prompt.trim();
                  setPrompt(base ? `${base}；${item.prompt}` : item.prompt);
                  setProOpen(false);
                }}
              >
                {item.label}
                <span className="ml-1 text-text-3">{item.note}</span>
              </button>
            ))}
          </div>
        ) : null}
      </div>
      <button
        type="button"
        className={cn(actionClass, "border border-blue text-text-1 hover:bg-blue-soft")}
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          try {
            await actions.generateNode(id, { prompt, count: isVideo || isAudio ? 1 : 2 });
          } finally {
            setBusy(false);
          }
        }}
      >
        {busy ? "正在生成" : isAudio ? "生成音乐" : isVideo ? "生成视频" : "生成图片"}
      </button>
    </Shell>
  );
}

export function ScriptNode({ id, selected, positionAbsoluteX, positionAbsoluteY }: NodeProps<Node<FlowData, "script">>) {
  const actions = useCanvasActions();
  const node = actions.doc.nodes.find((item) => item.id === id);
  const data = node && node.kind === "script" ? (node.data as ImageData) : null;
  const [prompt, setPrompt] = useState(data?.prompt ?? "");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    setPrompt(data?.prompt ?? "");
  }, [data?.prompt]);
  if (!node || !data) return null;
  return (
    <Shell id={id} title="脚本" x={positionAbsoluteX} y={positionAbsoluteY} selected={selected} dot="bg-warning">
      <Handle type="target" position={Position.Left} id="in" data-testid={`handle-${id}-target`} />
      <textarea
        aria-label="脚本提示"
        value={prompt}
        onChange={(event) => setPrompt(event.target.value)}
        placeholder="写一句话，生成分镜脚本"
        className="nodrag nowheel min-h-20 rounded-sm border border-border bg-raised px-2 py-1 text-caption text-text-1"
      />
      <button
        type="button"
        className={cn(actionClass, "border border-blue text-text-1 hover:bg-blue-soft")}
        disabled={busy || !prompt.trim()}
        onClick={async () => {
          setBusy(true);
          try {
            await actions.storyboard(prompt);
          } finally {
            setBusy(false);
          }
        }}
      >
        {busy ? "正在生成分镜" : "生成分镜"}
      </button>
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
