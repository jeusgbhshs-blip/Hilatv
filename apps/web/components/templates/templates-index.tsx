"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { apiFetch, errorMessage } from "@/lib/api";

type Template = {
  template_id: string;
  industry: string;
  title: string;
  summary: string;
  default_sentence: string;
  shot_count: number;
  duration_s: number;
  platforms: string[];
};

/** 行业模板：套用后直接生成一条该行业的片子。 */
export function TemplatesIndex() {
  const router = useRouter();
  const [rows, setRows] = useState<Template[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    void (async () => {
      try {
        const response = await apiFetch("/v1/templates");
        if (!response.ok) throw new Error(await errorMessage(response));
        const body = (await response.json()) as { templates?: Template[] };
        setRows(body.templates ?? []);
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : "没有拿到模板");
        setRows([]);
      }
    })();
  }, []);

  async function apply(template: Template) {
    setBusy(template.template_id);
    setError(null);
    try {
      const response = await apiFetch(`/v1/templates/${template.template_id}/apply`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sentence: "" }),
      });
      if (!response.ok) throw new Error(await errorMessage(response));
      const created = (await response.json()) as { project_id?: string };
      if (!created.project_id) throw new Error("没有拿到项目编号");
      window.localStorage.setItem("hilatv.lastProject", created.project_id);
      router.push(`/projects/${created.project_id}/expert`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "套用没有成功");
      setBusy(null);
    }
  }

  return (
    <div className="mx-auto w-full max-w-195">
      <header>
        <h1 className="text-h1 font-medium tracking-wide">模板</h1>
        <p className="mt-2 text-small text-text-2">按行业套用成熟结构，一句话就能出片。</p>
      </header>
      {error ? <p className="mt-4 text-caption text-danger">{error}</p> : null}
      {rows === null ? (
        <p className="mt-8 text-small text-text-3">正在读取模板</p>
      ) : (
        <ul className="mt-8 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {rows.map((row) => (
            <li key={row.template_id} className="rounded-lg border border-border bg-surface p-4">
              <p className="text-h3 font-medium text-text-1">{row.title}</p>
              <p className="mt-1 text-small text-text-2">{row.summary}</p>
              <p className="mt-3 text-caption text-text-3">
                {row.shot_count} 个镜头 · {row.duration_s} 秒
                {row.platforms.length ? ` · ${row.platforms.join(" / ")}` : ""}
              </p>
              <p className="mt-2 line-clamp-2 text-caption text-text-3">“{row.default_sentence}”</p>
              <button
                type="button"
                className="mt-4 inline-flex min-h-10 items-center rounded-full border border-border-strong px-4 text-small text-text-1 hover:border-text-3 disabled:cursor-not-allowed disabled:text-text-disabled"
                disabled={busy !== null}
                onClick={() => void apply(row)}
              >
                {busy === row.template_id ? "正在套用" : "套用这个模板"}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
