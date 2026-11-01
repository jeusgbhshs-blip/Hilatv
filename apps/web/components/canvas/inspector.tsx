"use client";

import { useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { FrameView } from "@/components/canvas/frame-view";
import {
  AI_LABEL_COPY,
  asBrief,
  asFinal,
  asRef,
  asShot,
  shotVerdictLabel,
  upstreamFor,
  type CanvasNode,
  type CanvasSnapshot,
  type ShotData,
} from "@/lib/canvas-contract";

export type InspectorFocus = {
  shotId: string;
  field: "narration" | "prompt";
  nonce: number;
};

export function Inspector({
  doc,
  selectedIds,
  busy,
  focus,
  onRegenerate,
  onChoose,
  onUpload,
  onNarration,
  onPrompt,
  onBrief,
}: {
  doc: CanvasSnapshot;
  selectedIds: string[];
  busy: boolean;
  focus: InspectorFocus | null;
  onRegenerate: (shotId: string, narration: string, promptSuffix: string) => void;
  onChoose: (shotId: string, candidateId: string) => void;
  onUpload: (shotId: string, file: File) => void;
  onNarration: (shotId: string, narration: string) => void;
  onPrompt: (shotId: string, suffix: string) => void;
  onBrief: (nodeId: string, text: string) => void;
}) {
  const selected = selectedIds
    .map((id) => doc.nodes.find((node) => node.id === id))
    .filter((node): node is CanvasNode => Boolean(node));
  return (
    <aside data-testid="inspector" aria-label="检查器" className="hilatv-inspector">
      <h2 className="text-h3 font-medium">检查器</h2>
      {selected.length === 0 ? (
        <p className="mt-3 text-small text-text-2">选中一个节点，查看候选、评分和连线。</p>
      ) : null}
      {selected.length > 1 ? (
        <p className="mt-3 text-small text-text-2">已框选 {selected.length} 个节点。</p>
      ) : null}
      {selected.length === 1 ? (
        <NodeInspector
          doc={doc}
          node={selected[0]}
          busy={busy}
          focus={focus}
          onRegenerate={onRegenerate}
          onChoose={onChoose}
          onUpload={onUpload}
          onNarration={onNarration}
          onPrompt={onPrompt}
          onBrief={onBrief}
        />
      ) : null}
    </aside>
  );
}

function NodeInspector({
  doc,
  node,
  busy,
  focus,
  onRegenerate,
  onChoose,
  onUpload,
  onNarration,
  onPrompt,
  onBrief,
}: {
  doc: CanvasSnapshot;
  node: CanvasNode;
  busy: boolean;
  focus: InspectorFocus | null;
  onRegenerate: (shotId: string, narration: string, promptSuffix: string) => void;
  onChoose: (shotId: string, candidateId: string) => void;
  onUpload: (shotId: string, file: File) => void;
  onNarration: (shotId: string, narration: string) => void;
  onPrompt: (shotId: string, suffix: string) => void;
  onBrief: (nodeId: string, text: string) => void;
}) {
  const shot = asShot(node);
  const brief = asBrief(node);
  const ref = asRef(node);
  const finalData = asFinal(node);
  if (shot) {
    return (
      <ShotInspector
        doc={doc}
        nodeId={node.id}
        shot={shot}
        busy={busy}
        focus={focus}
        onRegenerate={onRegenerate}
        onChoose={onChoose}
        onUpload={onUpload}
        onNarration={onNarration}
        onPrompt={onPrompt}
      />
    );
  }
  if (brief) {
    return (
      <label className="mt-4 grid gap-2 text-small">
        需求文本
        <textarea
          aria-label="检查器里的需求文本"
          defaultValue={brief.text}
          key={brief.text}
          rows={5}
          onBlur={(event) => onBrief(node.id, event.target.value)}
          className="w-full rounded-sm border border-border-strong bg-raised px-3 py-2 text-small"
        />
      </label>
    );
  }
  if (ref) {
    return (
      <div className="mt-4 grid gap-3">
        <FrameView url={ref.thumbnail_url} alt="参考图" />
        <p className="break-all font-mono text-caption text-text-3">
          {ref.upload_id ? ref.upload_id : "还没有上传"}
        </p>
      </div>
    );
  }
  if (finalData) {
    return (
      <div className="mt-4 grid gap-2">
        <p className="text-small">成片 {finalData.version_id ?? ""}</p>
        <p className="text-small">
          {AI_LABEL_COPY}
          <span className="text-text-3"> · 标识不能关闭</span>
        </p>
      </div>
    );
  }
  return <p className="mt-3 text-small text-text-2">工序节点</p>;
}

function ShotInspector({
  doc,
  nodeId,
  shot,
  busy,
  focus,
  onRegenerate,
  onChoose,
  onUpload,
  onNarration,
  onPrompt,
}: {
  doc: CanvasSnapshot;
  nodeId: string;
  shot: ShotData;
  busy: boolean;
  focus: InspectorFocus | null;
  onRegenerate: (shotId: string, narration: string, promptSuffix: string) => void;
  onChoose: (shotId: string, candidateId: string) => void;
  onUpload: (shotId: string, file: File) => void;
  onNarration: (shotId: string, narration: string) => void;
  onPrompt: (shotId: string, suffix: string) => void;
}) {
  const [narration, setNarration] = useState(shot.narration);
  const [suffix, setSuffix] = useState(shot.prompt_suffix ?? "");
  useEffect(() => {
    setNarration(shot.narration);
    setSuffix(shot.prompt_suffix ?? "");
  }, [shot.shot_id, shot.narration, shot.prompt_suffix]);
  useEffect(() => {
    if (!focus || focus.shotId !== shot.shot_id) return;
    const id = focus.field === "narration" ? "narration-input" : "prompt-input";
    document.getElementById(id)?.focus();
  }, [focus, shot.shot_id]);
  const selected = shot.candidates.find((item) => item.candidate_id === shot.selected_candidate_id) ?? shot.candidates[0];
  const upstream = upstreamFor(doc, nodeId);
  return (
    <div className="mt-4 grid gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-small">{shotVerdictLabel(shot.verdict, shot.review)}</span>
        <span className="tabular text-caption text-text-2">重生 {shot.regen_count} 次</span>
        <span className="tabular text-caption text-text-2">{shot.duration_s.toFixed(1)} 秒</span>
      </div>
      <Button
        type="button"
        disabled={busy}
        loading={busy}
        onClick={() => onRegenerate(shot.shot_id, narration, suffix)}
      >
        {busy ? "正在再生" : "再生这一镜"}
      </Button>
      {selected ? (
        <div className="grid gap-1">
          <p className="font-mono text-caption text-text-2">{selected.model}</p>
          <p className="tabular text-small">
            评分 {selected.score == null || selected.verdict === "unreviewed" ? "—" : selected.score.toFixed(1)}
          </p>
        </div>
      ) : null}
      <div className="grid gap-2">
        <h3 className="text-h3 font-medium">候选</h3>
        <ul className="grid gap-2">
          {shot.candidates.map((candidate) => {
            const current = candidate.candidate_id === shot.selected_candidate_id;
            return (
              <li key={candidate.candidate_id} data-testid={`inspector-${candidate.candidate_id}`}>
                <button
                  type="button"
                  aria-pressed={current}
                  onClick={() => onChoose(shot.shot_id, candidate.candidate_id)}
                  className="flex w-full items-center justify-between gap-2 rounded-sm border border-border px-2 py-2 text-left text-caption hover:bg-hover"
                >
                  <span>{candidate.kind === "keyframe" ? "关键帧" : "视频"}</span>
                  <span className="font-mono text-text-3">{candidate.model}</span>
                  <span>{shotVerdictLabel(candidate.verdict, candidate.review)}</span>
                  <span className="tabular">
                    {candidate.score == null || candidate.verdict === "unreviewed" ? "—" : candidate.score.toFixed(1)}
                  </span>
                  {current ? <Badge tone="blue">当前</Badge> : null}
                </button>
              </li>
            );
          })}
        </ul>
      </div>
      <label className="grid gap-2 text-small">
        这一镜的话
        <textarea
          id="narration-input"
          data-testid="narration-input"
          aria-label="这一镜的话"
          value={narration}
          rows={3}
          onChange={(event) => { setNarration(event.target.value); onNarration(shot.shot_id, event.target.value); }}
                    className="w-full rounded-sm border border-border-strong bg-raised px-3 py-2 text-small"
        />
      </label>
      <label className="grid gap-2 text-small">
        补充提示词
        <textarea
          id="prompt-input"
          data-testid="prompt-input"
          aria-label="补充提示词"
          value={suffix}
          rows={2}
          placeholder="没有补充提示词"
          onChange={(event) => { setSuffix(event.target.value); onPrompt(shot.shot_id, event.target.value); }}
                    className="w-full rounded-sm border border-border-strong bg-raised px-3 py-2 font-mono text-small"
        />
      </label>
      {suffix.trim() === "" ? <p className="text-caption text-text-3">没有补充提示词</p> : null}
      <div className="grid gap-2">
        <h3 className="text-h3 font-medium">连线带进来的内容</h3>
        {upstream.refs.length === 0 && upstream.texts.length === 0 ? (
          <p className="text-caption text-text-3">还没有连进来的参考图或文本</p>
        ) : null}
        {upstream.refs.map((ref) => (
          <p key={ref.nodeId} data-testid="inspector-upstream-ref" className="text-caption text-text-2">
            参考图 {ref.uploadId || "未上传"}
          </p>
        ))}
        {upstream.texts.map((item) => (
          <p key={item.nodeId} className="text-caption text-text-2">
            文本 {item.text}
          </p>
        ))}
      </div>
      <label className="text-small">
        上传替换参考图
        <input
          type="file"
          accept="image/png,image/jpeg,image/webp,image/gif"
          aria-label="检查器里上传替换参考图"
          className="mt-2 block w-full text-caption"
          onChange={(event) => {
            const file = event.target.files?.[0];
            event.target.value = "";
            if (file) onUpload(shot.shot_id, file);
          }}
        />
      </label>
    </div>
  );
}
