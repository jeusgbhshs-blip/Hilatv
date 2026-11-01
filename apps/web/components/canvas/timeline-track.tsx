"use client";

import { useEffect, useState, type PointerEvent as ReactPointerEvent } from "react";

import Link from "next/link";

import { Button } from "@/components/ui/button";
import {
  AI_LABEL_COPY,
  asShot,
  reorderClips,
  shotById,
  trimClip,
  type CanvasSnapshot,
  type TimelineClip,
} from "@/lib/canvas-contract";

const PIXELS_PER_SECOND = 56;

export function TimelineTrack({
  doc,
  busy,
  onCommit,
}: {
  doc: CanvasSnapshot;
  busy: boolean;
  onCommit: (clips: TimelineClip[]) => void;
}) {
  const [clips, setClips] = useState(doc.timeline.clips);
  useEffect(() => {
    setClips(doc.timeline.clips);
  }, [doc.timeline]);
  const order = clips.map((clip) => clip.shot_id).join(",");
  return (
    <section className="hilatv-timeline" aria-label="成片时间轴">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-h3 font-medium">时间轴</h2>
          <p className="text-caption text-text-3">拖片段改顺序，拖两端改入点出点。</p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <p className="text-small">
            <span data-testid="ai-label">{AI_LABEL_COPY}</span>
            <span className="text-text-3"> · 标识不能关闭</span>
          </p>
          {!busy && doc.origin === "api" && doc.status === "completed" ? (
            <Button asChild variant="secondary">
              <Link href={`/projects/${encodeURIComponent(doc.project_id)}/film`}>查看成片与导出</Link>
            </Button>
          ) : (
            <Button type="button" variant="secondary" disabled aria-describedby="timeline-export-note">
              导出
            </Button>
          )}
        </div>
      </div>
      <div
        className="hilatv-track"
        data-testid="timeline-order"
        data-order={order}
        role="list"
      >
        {clips.map((clip, index) => (
          <Clip
            key={clip.shot_id}
            clip={clip}
            index={index}
            doc={doc}
            onPreview={(next) => setClips(next)}
            onCommit={onCommit}
            clips={clips}
          />
        ))}
      </div>
      <p id="timeline-export-note" className="mt-3 text-caption text-text-3">
        {doc.origin === "mock"
          ? "演示画布不生成文件。新建项目后可以制作和导出成片。"
          : "时间轴修改会保存到项目；请在成片页核对最新渲染版本后导出。"}
      </p>
    </section>
  );
}

function Clip({
  clip,
  index,
  doc,
  clips,
  onPreview,
  onCommit,
}: {
  clip: TimelineClip;
  index: number;
  doc: CanvasSnapshot;
  clips: TimelineClip[];
  onPreview: (clips: TimelineClip[]) => void;
  onCommit: (clips: TimelineClip[]) => void;
}) {
  const shot = shotById(doc, clip.shot_id);
  const data = shot ? asShot(shot) : null;
  const duration = data?.duration_s ?? clip.out_s;
  const width = Math.max(96, (clip.out_s - clip.in_s) * PIXELS_PER_SECOND);
  function replace(next: TimelineClip): TimelineClip[] {
    return clips.map((item) => (item.shot_id === clip.shot_id ? next : item));
  }
  function commitTrim(edge: "in" | "out", nextValue: number) {
    onCommit(replace(trimClip(clip, edge, nextValue, duration)));
  }
  return (
    <div
      role="listitem"
      className="hilatv-clip"
      style={{ width }}
      data-testid={`clip-${clip.shot_id}`}
    >
      <div
        role="slider"
        tabIndex={0}
        aria-label="入点"
        aria-valuemin={0}
        aria-valuemax={duration}
        aria-valuenow={clip.in_s}
        aria-valuetext={`${clip.in_s.toFixed(1)} 秒`}
        data-testid={`clip-in-${clip.shot_id}`}
        className="hilatv-trim"
        onPointerDown={(event) =>
          trackPointer(event, clip.in_s, (value) => onPreview(replace(trimClip(clip, "in", value, duration))), (value) =>
            commitTrim("in", value),
          )
        }
        onKeyDown={(event) => {
          if (event.key === "ArrowLeft") commitTrim("in", clip.in_s - 0.1);
          if (event.key === "ArrowRight") commitTrim("in", clip.in_s + 0.1);
          if (event.key.startsWith("Arrow")) event.preventDefault();
        }}
      />
      <div
        role="button"
        tabIndex={0}
        data-testid={`clip-move-${clip.shot_id}`}
        aria-label={`第 ${data?.index ?? index + 1} 镜，拖动调整顺序`}
        aria-keyshortcuts="Alt+ArrowLeft Alt+ArrowRight"
        className="hilatv-clip-body"
        onPointerDown={(event) => dragReorder(event, index, clips, onPreview, onCommit)}
        onKeyDown={(event) => {
          if (!event.altKey) return;
          if (event.key === "ArrowLeft" && index > 0) onCommit(reorderClips(clips, index, index - 1));
          if (event.key === "ArrowRight" && index < clips.length - 1) {
            onCommit(reorderClips(clips, index, index + 1));
          }
          if (event.key.startsWith("Arrow")) event.preventDefault();
        }}
      >
        <span className="text-caption text-text-1">第 {data?.index ?? index + 1} 镜</span>
        <span data-testid={`clip-range-${clip.shot_id}`} className="tabular text-caption text-text-2">
          {clip.in_s.toFixed(1)}–{clip.out_s.toFixed(1)}
        </span>
      </div>
      <div
        role="slider"
        tabIndex={0}
        aria-label="出点"
        aria-valuemin={0}
        aria-valuemax={duration}
        aria-valuenow={clip.out_s}
        aria-valuetext={`${clip.out_s.toFixed(1)} 秒`}
        data-testid={`clip-out-${clip.shot_id}`}
        className="hilatv-trim"
        onPointerDown={(event) =>
          trackPointer(event, clip.out_s, (value) => onPreview(replace(trimClip(clip, "out", value, duration))), (value) =>
            commitTrim("out", value),
          )
        }
        onKeyDown={(event) => {
          if (event.key === "ArrowLeft") commitTrim("out", clip.out_s - 0.1);
          if (event.key === "ArrowRight") commitTrim("out", clip.out_s + 0.1);
          if (event.key.startsWith("Arrow")) event.preventDefault();
        }}
      />
    </div>
  );
}

function trackPointer(
  event: ReactPointerEvent,
  startValue: number,
  onPreview: (value: number) => void,
  onCommit: (value: number) => void,
) {
  if (event.button !== 0) return;
  event.preventDefault();
  event.stopPropagation();
  const startX = event.clientX;
  const move = (ev: PointerEvent) => {
    onPreview(startValue + (ev.clientX - startX) / PIXELS_PER_SECOND);
  };
  const up = (ev: PointerEvent) => {
    onCommit(startValue + (ev.clientX - startX) / PIXELS_PER_SECOND);
    window.removeEventListener("pointermove", move);
    window.removeEventListener("pointerup", up);
  };
  window.addEventListener("pointermove", move);
  window.addEventListener("pointerup", up);
}

function dragReorder(
  event: ReactPointerEvent,
  index: number,
  clips: TimelineClip[],
  onPreview: (clips: TimelineClip[]) => void,
  onCommit: (clips: TimelineClip[]) => void,
) {
  if (event.button !== 0) return;
  event.preventDefault();
  const startX = event.clientX;
  const move = (ev: PointerEvent) => {
    const shift = Math.round((ev.clientX - startX) / 96);
    const to = Math.min(clips.length - 1, Math.max(0, index + shift));
    onPreview(reorderClips(clips, index, to));
  };
  const up = (ev: PointerEvent) => {
    const shift = Math.round((ev.clientX - startX) / 96);
    const to = Math.min(clips.length - 1, Math.max(0, index + shift));
    onCommit(reorderClips(clips, index, to));
    window.removeEventListener("pointermove", move);
    window.removeEventListener("pointerup", up);
  };
  window.addEventListener("pointermove", move);
  window.addEventListener("pointerup", up);
}
