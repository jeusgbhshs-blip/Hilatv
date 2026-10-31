"use client";

import {
  AudioLines,
  Clapperboard,
  FileStack,
  HelpCircle,
  History,
  Image as ImageIcon,
  Library,
  Sparkles,
  TextCursorInput,
} from "lucide-react";
import { useReactFlow } from "@xyflow/react";
import { useCallback, useEffect, useState } from "react";

import type { CanvasPoint } from "@/lib/canvas-contract";

const KINDS = [
  { kind: "brief", label: "文本", icon: TextCursorInput, ready: true },
  { kind: "image", label: "图片", icon: ImageIcon, ready: true },
  { kind: "video", label: "视频", icon: Clapperboard, ready: true },
  { kind: "ref_image", label: "参考图", icon: ImageIcon, ready: true },
  { kind: "audio", label: "音频", icon: AudioLines, ready: false },
  { kind: "script", label: "脚本", icon: Sparkles, ready: true },
] as const;

export const CANVAS_ADD_EVENT = "hilatv:canvas-add";

type Placeable = "brief" | "ref_image" | "image" | "video" | "script";

/**
 * LibTV 式「添加节点」面板：左侧工具栏的「＋」和双击画布都会打开它。
 * 真能落到后端的是文本和图片（R2 只接受这两类用户节点），其余标「建设中」。
 */
export function CanvasAddMenu({ onCreate }: { onCreate: (kind: Placeable, position: CanvasPoint) => void }) {
  const { screenToFlowPosition } = useReactFlow();
  const [spot, setSpot] = useState<{ x: number; y: number; flow: CanvasPoint } | null>(null);

  const openAt = useCallback(
    (clientX: number, clientY: number) => {
      setSpot({
        x: Math.min(clientX, window.innerWidth - 260),
        y: Math.min(clientY, window.innerHeight - 420),
        flow: screenToFlowPosition({ x: clientX, y: clientY }),
      });
    },
    [screenToFlowPosition],
  );

  useEffect(() => {
    function onDoubleClick(event: MouseEvent) {
      const target = event.target;
      if (!(target instanceof Element) || !target.closest(".react-flow__pane")) return;
      event.preventDefault();
      openAt(event.clientX, event.clientY);
    }
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") setSpot(null);
    }
    function onRail(event: Event) {
      const detail = (event as CustomEvent<{ x: number; y: number }>).detail;
      if (detail) openAt(detail.x, detail.y);
    }
    window.addEventListener("dblclick", onDoubleClick, true);
    window.addEventListener("keydown", onKey);
    window.addEventListener(CANVAS_ADD_EVENT, onRail);
    return () => {
      window.removeEventListener("dblclick", onDoubleClick, true);
      window.removeEventListener("keydown", onKey);
      window.removeEventListener(CANVAS_ADD_EVENT, onRail);
    };
  }, [openAt]);

  if (!spot) return null;

  return (
    <div
      role="dialog"
      aria-label="添加节点"
      data-testid="canvas-add-menu"
      className="hilatv-canvas-addmenu"
      style={{ left: spot.x, top: spot.y }}
      onMouseDown={(event) => event.stopPropagation()}
    >
      <p className="px-2 pb-1 text-caption text-text-3">添加节点</p>
      {KINDS.map((item) => (
        <button
          key={item.kind}
          type="button"
          disabled={!item.ready}
          className="hilatv-canvas-addmenu-row"
          onClick={() => {
            if (!item.ready) return;
            onCreate(item.kind as Placeable, spot.flow);
            setSpot(null);
          }}
        >
          <span className="hilatv-canvas-addmenu-icon">
            <item.icon aria-hidden="true" className="size-4" strokeWidth={1.5} />
          </span>
          <span className="text-small text-text-1">{item.label}</span>
          {item.ready ? null : <span className="ml-auto text-caption text-text-3">建设中</span>}
        </button>
      ))}
      <div className="hilatv-canvas-addmenu-sep" aria-hidden="true" />
      <p className="px-2 pb-1 text-caption text-text-3">添加资源</p>
      <button type="button" className="hilatv-canvas-addmenu-row" disabled>
        <span className="hilatv-canvas-addmenu-icon">
          <FileStack aria-hidden="true" className="size-4" strokeWidth={1.5} />
        </span>
        <span className="text-small text-text-1">上传</span>
        <span className="ml-auto text-caption text-text-3">建设中</span>
      </button>
      <button type="button" className="hilatv-canvas-addmenu-row" disabled>
        <span className="hilatv-canvas-addmenu-icon">
          <Library aria-hidden="true" className="size-4" strokeWidth={1.5} />
        </span>
        <span className="text-small text-text-1">从素材库选择</span>
        <span className="ml-auto text-caption text-text-3">建设中</span>
      </button>
    </div>
  );
}

/** 左侧竖工具栏：加节点、工具箱、素材、历史、帮助。只有「＋」现在真能用。 */
export function CanvasToolRail() {
  const items = [
    { label: "添加节点", icon: Sparkles, primary: true },
    { label: "工具箱", icon: FileStack, primary: false },
    { label: "我的素材", icon: Library, primary: false },
    { label: "历史素材", icon: History, primary: false },
    { label: "常见问题", icon: HelpCircle, primary: false },
  ] as const;
  return (
    <aside className="hilatv-canvas-rail" aria-label="画布工具">
      {items.map((item) =>
        item.primary ? (
          <button
            key={item.label}
            type="button"
            className="hilatv-canvas-rail-btn hilatv-canvas-rail-primary"
            aria-label={item.label}
            title={item.label}
            onClick={() => {
              window.dispatchEvent(new CustomEvent(CANVAS_ADD_EVENT, { detail: { x: 88, y: 180 } }));
            }}
          >
            <span aria-hidden="true" className="text-h2 leading-none">
              ＋
            </span>
          </button>
        ) : (
          <button
            key={item.label}
            type="button"
            className="hilatv-canvas-rail-btn"
            aria-label={item.label}
            title={`${item.label}（建设中）`}
            disabled
          >
            <item.icon aria-hidden="true" className="size-4" strokeWidth={1.5} />
          </button>
        ),
      )}
    </aside>
  );
}
