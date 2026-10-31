"use client";

import { Link2, Share2, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { apiFetch, errorMessage } from "@/lib/api";

type ShareRow = { token: string; role: string; url: string };

const ROLES = [
  { value: "view", label: "只读查看" },
  { value: "view_no_download", label: "只读，禁止下载" },
];

/** 项目分享：生成只读链接（不需要对方登录）。 */
export function SharePanel({ projectId }: { projectId: string }) {
  const [open, setOpen] = useState(false);
  const [role, setRole] = useState("view");
  const [rows, setRows] = useState<ShareRow[]>([]);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const response = await apiFetch(`/v1/projects/${projectId}/shares`);
      if (!response.ok) throw new Error(await errorMessage(response));
      const body = (await response.json()) as { shares?: ShareRow[] };
      setRows(body.shares ?? []);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "没有拿到分享列表");
    }
  }, [projectId]);

  useEffect(() => {
    if (open) void load();
  }, [open, load]);

  async function create() {
    setError(null);
    try {
      const response = await apiFetch(`/v1/projects/${projectId}/shares`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ role }),
      });
      if (!response.ok) throw new Error(await errorMessage(response));
      const body = (await response.json()) as { token?: string };
      if (!body.token) throw new Error("没有拿到分享链接");
      const url = `${window.location.origin}/share/${body.token}`;
      try {
        await navigator.clipboard.writeText(url);
        setNotice("链接已复制，发给对方就能看");
      } catch {
        setNotice(`链接已生成：${url}`);
      }
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "生成分享链接失败");
    }
  }

  async function revoke(token: string) {
    try {
      const response = await apiFetch(`/v1/projects/${projectId}/shares/${token}`, { method: "DELETE" });
      if (!response.ok) throw new Error(await errorMessage(response));
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "撤销失败");
    }
  }

  return (
    <span className="relative">
      <button type="button" className="hilatv-canvas-back" aria-expanded={open} onClick={() => setOpen((value) => !value)}>
        <Share2 aria-hidden="true" className="mr-1 size-4" strokeWidth={1.5} />
        分享
      </button>
      {open ? (
        <div className="hilatv-share-panel" role="dialog" aria-label="分享项目">
          <p className="text-caption text-text-3">只读链接，对方不用登录</p>
          <div className="mt-2 flex items-center gap-2">
            <select
              aria-label="分享权限"
              value={role}
              onChange={(event) => setRole(event.target.value)}
              className="hilatv-share-select"
            >
              {ROLES.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
            <button type="button" className="hilatv-share-create" onClick={() => void create()}>
              <Link2 aria-hidden="true" className="size-4" strokeWidth={1.5} /> 生成链接
            </button>
          </div>
          {notice ? <p className="mt-2 text-caption text-blue-text">{notice}</p> : null}
          {error ? <p className="mt-2 text-caption text-danger">{error}</p> : null}
          <ul className="mt-3 space-y-1">
            {rows.map((row) => (
              <li key={row.token} className="flex items-center gap-2 text-caption text-text-2">
                <span className="min-w-0 flex-1 truncate">
                  {row.role === "view_no_download" ? "只读 · 禁下载" : "只读"} · {row.token.slice(0, 8)}…
                </span>
                <button
                  type="button"
                  aria-label="撤销这个分享"
                  className="rounded-sm p-1 hover:bg-hover hover:text-danger"
                  onClick={() => void revoke(row.token)}
                >
                  <Trash2 aria-hidden="true" className="size-3.5" strokeWidth={1.5} />
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </span>
  );
}
