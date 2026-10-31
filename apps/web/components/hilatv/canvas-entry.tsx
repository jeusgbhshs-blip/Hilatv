"use client";

import { Clapperboard, Film, Image as ImageIcon, TextCursorInput } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

const LAST_PROJECT_KEY = "hilatv.lastProject";

const NODES = [
  { icon: TextCursorInput, label: "需求文本", note: "那句话" },
  { icon: ImageIcon, label: "参考图", note: "产品图" },
  { icon: Film, label: "镜头卡", note: "候选 · 时长" },
  { icon: Clapperboard, label: "成片", note: "AI生成" },
];

/**
 * DESIGN.md §9.2 CanvasNode：画布不是一排工序，是可以拖的节点。
 * 首页只放一个入口模块，点进去才是整页画布。
 */
export function CanvasEntry() {
  const [projectId, setProjectId] = useState<string | null>(null);

  useEffect(() => {
    setProjectId(window.localStorage.getItem(LAST_PROJECT_KEY));
  }, []);

  const href = projectId ? `/projects/${projectId}/expert` : "/projects";
  const label = projectId ? "打开专家画布" : "先去生成一条片子";
  const hint = projectId ? "接着调这一条片的每一镜" : "生成完成后，这里会直接进画布";

  return (
    <section aria-labelledby="expert-entry-title" className="border-t border-border px-4 py-16 md:px-6">
      <div className="mx-auto flex w-full max-w-195 flex-col gap-8 md:flex-row md:items-center">
        <div className="md:w-1/2">
          <p className="text-caption tracking-widest text-text-3">专家画布</p>
          <h2 id="expert-entry-title" className="mt-3 text-h1 font-medium text-text-1">
            像剪片一样，拖节点改片子
          </h2>
          <p className="mt-3 text-body text-text-2">
            需求、参考图、镜头、成片都是可以拖动和连线的卡片。换候选、重做其中一镜、拖时间轴，都在一张画布上完成。画面上的字和价格仍然由后期叠上去。
          </p>
          <Link
            href={href}
            className="mt-6 inline-flex min-h-11 items-center rounded-full border border-border-strong px-4 text-small text-text-1 transition-colors duration-fast hover:border-text-3"
          >
            {label}
          </Link>
          <p className="mt-3 text-caption text-text-3">{hint}</p>
        </div>

        <div aria-hidden="true" className="md:w-1/2">
          <div className="rounded-lg border border-border bg-surface p-4">
            <div className="grid grid-cols-2 gap-3">
              {NODES.map((item) => (
                <div key={item.label} className="rounded-md border border-border bg-raised px-3 py-3">
                  <item.icon aria-hidden="true" className="size-5 text-text-2" strokeWidth={1.5} />
                  <p className="mt-2 text-small text-text-1">{item.label}</p>
                  <p className="text-caption text-text-3">{item.note}</p>
                </div>
              ))}
            </div>
            <p className="mt-3 text-center text-caption text-text-3">
              拖动空白处平移 · 滚轮缩放 · 从圆点拖到另一张卡连线
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}
