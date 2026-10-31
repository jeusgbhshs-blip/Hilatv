"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { apiFetch, errorMessage } from "@/lib/api";

type ProjectRow = {
  project_id: string;
  sentence: string;
  status: string;
  phase: string;
  message: string;
  updated_at: number;
  shot_count: number;
  has_film: boolean;
};

const LAST_PROJECT_KEY = "hilatv.lastProject";

const STATUS_COPY: Record<string, string> = {
  draft: "空白画布",
  running: "生成中",
  completed: "已完成",
  needs_human_review: "待人工复核",
  failed: "失败",
  paused: "已暂停",
};

/** 每个项目一块画布；从项目卡进画布，避免所有项目挤在一个专家画布里。 */
export function ProjectsIndex() {
  const router = useRouter();
  const [rows, setRows] = useState<ProjectRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function load() {
    try {
      const response = await apiFetch("/v1/projects");
      if (!response.ok) throw new Error(await errorMessage(response));
      const body = (await response.json()) as { projects?: ProjectRow[] };
      setRows(body.projects ?? []);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "没有拿到项目列表");
      setRows([]);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function copyProject(projectId: string) {
    try {
      const response = await apiFetch(`/v1/projects/${projectId}/copy`, { method: "POST" });
      if (!response.ok) throw new Error(await errorMessage(response));
      const created = (await response.json()) as { project_id?: string };
      if (created.project_id) router.push(`/projects/${created.project_id}/expert`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "复制没有成功");
    }
  }

  async function createBlank() {
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

  return (
    <div className="mx-auto w-full max-w-195">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-h1 font-medium tracking-wide">项目</h1>
          <p className="mt-2 text-small text-text-2">每个项目各自一块画布。从卡片直接进该项目的专家画布。</p>
        </div>
        <Button type="button" onClick={() => void createBlank()} disabled={busy}>
          {busy ? "正在开画布" : "新建空白画布"}
        </Button>
      </header>

      {error ? <p className="mt-4 text-caption text-danger">{error}</p> : null}

      {rows === null ? (
        <p className="mt-8 text-small text-text-3">正在读取项目</p>
      ) : rows.length === 0 ? (
        <div className="mt-8 rounded-lg border border-border bg-surface p-8 text-center">
          <p className="text-body text-text-1">还没有项目</p>
          <p className="mt-2 text-small text-text-3">点「新建空白画布」直接在画布里搭，或回首页写一句话生成。</p>
          <Link href="/" className="mt-4 inline-block text-small text-blue-text hover:underline">
            回首页写一句话
          </Link>
        </div>
      ) : (
        <ul className="mt-8 grid gap-3 md:grid-cols-2">
          {rows.map((row) => (
            <li key={row.project_id} className="rounded-lg border border-border bg-surface p-4">
              <div className="flex items-start justify-between gap-3">
                <p className="line-clamp-2 text-body text-text-1">{row.sentence || "未命名项目"}</p>
                <span className="shrink-0 rounded-full border border-border-strong px-2 py-0.5 text-caption text-text-2">
                  {STATUS_COPY[row.status] ?? row.status}
                </span>
              </div>
              <p className="mt-2 text-caption text-text-3">
                {row.shot_count} 个镜头 · {row.has_film ? "有成片" : "还没有成片"}
              </p>
              <div className="mt-4 flex flex-wrap gap-2">
                <Link
                  href={`/projects/${row.project_id}/expert`}
                  className="inline-flex min-h-10 items-center rounded-full border border-border-strong px-3 text-caption text-text-1 hover:border-text-3"
                >
                  打开画布
                </Link>
                <Link
                  href={`/projects/${row.project_id}`}
                  className="inline-flex min-h-10 items-center rounded-full px-3 text-caption text-text-2 hover:bg-hover hover:text-text-1"
                >
                  项目进度
                </Link>
                <button
                  type="button"
                  className="inline-flex min-h-10 items-center rounded-full px-3 text-caption text-text-2 hover:bg-hover hover:text-text-1"
                  onClick={() => void copyProject(row.project_id)}
                >
                  复制项目
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
