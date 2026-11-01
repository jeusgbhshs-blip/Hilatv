"use client";

import { useEffect, useState } from "react";

import { apiFetch, errorMessage } from "@/lib/api";

type Member = { member_id: string; name: string; role: string; status: string };

const ROLE_COPY: Record<string, string> = { owner: "管理员", editor: "可编辑", viewer: "只读" };
const ROLES = ["editor", "viewer"];

/** 团队设置：成员与角色、离职交接（当前是本地 mock 成员表，等登录体系接入）。 */
export function TeamSettings() {
  const [rows, setRows] = useState<Member[] | null>(null);
  const [name, setName] = useState("");
  const [role, setRole] = useState("editor");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const [target, setTarget] = useState<Record<string, string>>({});

  async function load() {
    try {
      const response = await apiFetch("/v1/members");
      if (!response.ok) throw new Error(await errorMessage(response));
      const body = (await response.json()) as { members?: Member[] };
      setRows(body.members ?? []);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "没有拿到成员");
      setRows([]);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function add() {
    setError(null);
    try {
      const response = await apiFetch("/v1/members", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, role }),
      });
      if (!response.ok) throw new Error(await errorMessage(response));
      setName("");
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "添加失败");
    }
  }

  async function changeRole(member: Member, next: string) {
    try {
      const response = await apiFetch(`/v1/members/${member.member_id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ role: next }),
      });
      if (!response.ok) throw new Error(await errorMessage(response));
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "改角色失败");
    }
  }

  async function handover(member: Member) {
    const to = target[member.member_id];
    if (!to) {
      setError("先选一个接手人");
      return;
    }
    try {
      const response = await apiFetch(`/v1/members/${member.member_id}/handover`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ to_member_id: to }),
      });
      if (!response.ok) throw new Error(await errorMessage(response));
      const body = (await response.json()) as { projects_moved?: number };
      setNotice(`已交接 ${body.projects_moved ?? 0} 个项目`);
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "交接失败");
    }
  }

  return (
    <div className="mx-auto w-full max-w-195">
      <header>
        <h1 className="text-h1 font-medium tracking-wide">团队设置</h1>
        <p className="mt-2 text-small text-text-2">
          成员与角色先按本地 mock 保存；接入登录后换成真正的账号与权限控制。
        </p>
      </header>

      <section className="mt-6 flex flex-wrap items-end gap-2 rounded-lg border border-border bg-surface p-4">
        <label className="grid gap-1 text-caption text-text-3">
          成员名字
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="例如：小王"
            className="hilatv-member-input"
          />
        </label>
        <label className="grid gap-1 text-caption text-text-3">
          角色
          <select value={role} onChange={(event) => setRole(event.target.value)} className="hilatv-member-input">
            {ROLES.map((item) => (
              <option key={item} value={item}>
                {ROLE_COPY[item]}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          className="inline-flex min-h-10 items-center rounded-full border border-border-strong px-4 text-small text-text-1 hover:border-text-3 disabled:cursor-not-allowed disabled:text-text-disabled"
          disabled={!name.trim()}
          onClick={() => void add()}
        >
          添加成员
        </button>
      </section>

      {error ? <p className="mt-3 text-caption text-danger">{error}</p> : null}
      {notice ? <p className="mt-3 text-caption text-blue-text">{notice}</p> : null}

      {rows === null ? (
        <p className="mt-8 text-small text-text-3">正在读取成员</p>
      ) : (
        <ul className="mt-6 grid gap-2">
          {rows.map((member) => (
            <li key={member.member_id} className="flex flex-wrap items-center gap-3 rounded-lg border border-border bg-surface p-3">
              <span className="min-w-0 flex-1 truncate text-body text-text-1">{member.name}</span>
              {member.status === "departed" ? (
                <span className="text-caption text-text-3">已离职</span>
              ) : (
                <select
                  aria-label={`${member.name} 的角色`}
                  value={member.role}
                  onChange={(event) => void changeRole(member, event.target.value)}
                  className="hilatv-member-input"
                  disabled={member.role === "owner"}
                >
                  <option value="owner">管理员</option>
                  <option value="editor">可编辑</option>
                  <option value="viewer">只读</option>
                </select>
              )}
              {member.role !== "owner" && member.status !== "departed" ? (
                <span className="flex items-center gap-2">
                  <select
                    aria-label={`${member.name} 的接手人`}
                    value={target[member.member_id] ?? ""}
                    onChange={(event) =>
                      setTarget((current) => ({ ...current, [member.member_id]: event.target.value }))
                    }
                    className="hilatv-member-input"
                  >
                    <option value="">选接手人</option>
                    {rows
                      .filter((item) => item.member_id !== member.member_id && item.status !== "departed")
                      .map((item) => (
                        <option key={item.member_id} value={item.member_id}>
                          {item.name}
                        </option>
                      ))}
                  </select>
                  <button
                    type="button"
                    className="rounded-full border border-border-strong px-3 py-1 text-caption text-text-1 hover:border-text-3"
                    onClick={() => void handover(member)}
                  >
                    交接项目
                  </button>
                </span>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
