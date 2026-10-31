"use client";

import { useEffect, useState } from "react";

import { apiFetch, errorMessage } from "@/lib/api";

type Row = { project_id: string; sentence: string; status: string; used: number; limit: number; remaining: number };
type Usage = { budget: { used: number; limit: number; remaining: number }; projects: Row[]; note: string };

/** 用量与账单：读现有预算账本（mock 下费用 0）。 */
export function UsagePage() {
  const [data, setData] = useState<Usage | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void (async () => {
      try {
        const response = await apiFetch("/v1/usage");
        if (!response.ok) throw new Error(await errorMessage(response));
        setData((await response.json()) as Usage);
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : "没有拿到用量");
      }
    })();
  }, []);

  const percent =
    data && data.budget.limit > 0 ? Math.min(100, Math.round((data.budget.used / data.budget.limit) * 100)) : 0;

  return (
    <div className="mx-auto w-full max-w-195">
      <header>
        <h1 className="text-h1 font-medium tracking-wide">用量与账单</h1>
        <p className="mt-2 text-small text-text-2">重生次数按项目记账，接真实模型后费用按网关日志统计。</p>
      </header>

      {error ? <p className="mt-4 text-caption text-danger">{error}</p> : null}
      {!data ? (
        <p className="mt-8 text-small text-text-3">正在读取用量</p>
      ) : (
        <>
          <section className="mt-6 rounded-lg border border-border bg-surface p-4">
            <p className="text-caption text-text-3">总用量</p>
            <p className="mt-1 tabular text-h2 font-medium">
              {data.budget.used} / {data.budget.limit} 次
            </p>
            <div className="mt-3 h-1 rounded-full bg-raised">
              <div className="h-full rounded-full bg-blue" style={{ width: `${percent}%` }} />
            </div>
            <p className="mt-2 text-caption text-text-3">{data.note}</p>
          </section>

          <section className="mt-8">
            <h2 className="text-h2 font-medium">按项目</h2>
            {data.projects.length === 0 ? (
              <p className="mt-3 text-small text-text-3">还没有项目用量。</p>
            ) : (
              <ul className="mt-3 grid gap-2">
                {data.projects.map((row) => (
                  <li key={row.project_id} className="flex flex-wrap items-center gap-3 rounded-lg border border-border bg-surface p-3">
                    <span className="min-w-0 flex-1 truncate text-small text-text-1">{row.sentence || "未命名项目"}</span>
                    <span className="text-caption text-text-3">{row.status}</span>
                    <span className="tabular text-small text-text-2">
                      {row.used} / {row.limit} 次
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </>
      )}
    </div>
  );
}
