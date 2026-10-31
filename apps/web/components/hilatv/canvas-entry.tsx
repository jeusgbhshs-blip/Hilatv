"use client";

import { Clapperboard, Film, Image as ImageIcon, TextCursorInput } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { apiFetch, errorMessage } from "@/lib/api";

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
  const router = useRouter();
  const [projectId, setProjectId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setProjectId(window.localStorage.getItem(LAST_PROJECT_KEY));
  }, []);

  // LibTV 式入口：不先生成成片，直接开一块空白画布，在画布上搭节点。
  async function openBlankCanvas() {
    setBusy(true);
    setError(null);
    try {
      const response = await apiFetch("/v1/projects/blank", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sentence: "" }),
      });
      if (!response.ok) throw new Error(await errorMessage(response));
      const created = (await response.json()) as { project_id?: string };
      if (!created.project_id) throw new Error("没有拿到项目编号");
      window.localStorage.setItem(LAST_PROJECT_KEY, created.project_id);
      router.push(`/projects/${created.project_id}/expert`);
    } catch (caught) {
      setBusy(false);
      setError(caught instanceof Error ? caught.message : "打不开画布");
    }
  }

  const href = projectId ? `/projects/${projectId}/expert` : null;
  const label = projectId ? "打开专家画布" : "直接进画布";
  const hint = projectId ? "接着调这一条片的每一镜" : "不先生成成片，进画布再搭节点";

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
          {href ? (
            <Link
              href={href}
              className="mt-6 inline-flex min-h-11 items-center rounded-full border border-border-strong px-4 text-small text-text-1 transition-colors duration-fast hover:border-text-3"
            >
              {label}
            </Link>
          ) : (
            <button
              type="button"
              disabled={busy}
              onClick={() => void openBlankCanvas()}
              className="mt-6 inline-flex min-h-11 items-center rounded-full border border-border-strong px-4 text-small text-text-1 transition-colors duration-fast hover:border-text-3 disabled:cursor-not-allowed disabled:text-text-disabled"
            >
              {busy ? "正在开画布" : label}
            </button>
          )}
          <p className="mt-3 text-caption text-text-3">{hint}</p>
          {error ? <p className="mt-2 text-caption text-danger">{error}</p> : null}
          <div className="mt-3 flex items-center gap-4">
            <Link href="/projects" className="text-caption text-blue-text hover:underline">
              项目列表
            </Link>
            <button
              type="button"
              onClick={() => {
                window.localStorage.removeItem(LAST_PROJECT_KEY);
                setProjectId(null);
              }}
              className="text-caption text-text-3 hover:text-text-2"
            >
              换一块空白画布
            </button>
          </div>
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
