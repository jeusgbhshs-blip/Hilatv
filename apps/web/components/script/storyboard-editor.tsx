"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { apiFetch, errorMessage } from "@/lib/api";

type ShotRow = {
  shot_id: string;
  order: number;
  duration_s: number;
  purpose: string;
  visual: string;
  shot_size: string;
  camera: string;
  voiceover: string;
  transition_out: string;
  on_screen_text?: { text: string; style: string; in: number; out: number }[];
  ext?: {
    lighting?: string;
    mood?: string;
    continuity_notes?: string;
    sfx?: string[];
    action?: string;
    emotion?: string;
    camera_angle?: string;
    color?: string;
    visual_effect?: string;
    bgm?: string;
    characters?: { name?: string; desc?: string }[];
    reference?: { first_frame?: string; role_sheet?: string; scene_anchor?: string };
    generation?: { model?: string; ratio?: string; resolution?: string; negative?: string };
  };
  prompt?: { prompt: string; negative_prompt: string; parts: { kind: string; text: string }[]; params: Record<string, unknown> };
};

type ScriptPayload = {
  revision: number;
  meta: Record<string, string>;
  styles: string[];
  shots: ShotRow[];
};

const FIELD_CLASS =
  "w-full rounded-xs border border-border bg-raised px-2 py-1 text-caption text-text-1 outline-none focus:border-blue-strong";

export function StoryboardEditor({ projectId }: { projectId: string }) {
  const [script, setScript] = useState<ScriptPayload | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [openPrompt, setOpenPrompt] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Record<string, ShotRow>>({});

  const load = useCallback(async () => {
    setError("");
    const response = await apiFetch(`/v1/projects/${encodeURIComponent(projectId)}/script`);
    if (!response.ok) {
      setError(await errorMessage(response));
      return;
    }
    const payload = (await response.json()) as ScriptPayload;
    setScript(payload);
    setDrafts(Object.fromEntries(payload.shots.map((shot) => [shot.shot_id, { ...shot }])));
  }, [projectId]);

  useEffect(() => {
    void load();
  }, [load]);

  const meta = script?.meta ?? {};
  const shots = useMemo(() => Object.values(drafts).sort((a, b) => a.order - b.order), [drafts]);

  function updateDraft(shotId: string, patch: Partial<ShotRow>) {
    setDrafts((current) => ({ ...current, [shotId]: { ...current[shotId], ...patch } }));
  }

  function updateExt(shotId: string, patch: Record<string, unknown>) {
    setDrafts((current) => ({
      ...current,
      [shotId]: { ...current[shotId], ext: { ...(current[shotId].ext ?? {}), ...patch } },
    }));
  }

  function updateCharacter(shotId: string, index: 0 | 1, field: "name" | "desc", value: string) {
    const shot = drafts[shotId];
    const characters = [...(shot?.ext?.characters ?? [])];
    characters[index] = { ...(characters[index] ?? {}), [field]: value };
    updateExt(shotId, { characters });
  }

  async function saveMeta(patch: Record<string, string>) {
    setBusy("meta");
    try {
      const response = await apiFetch(`/v1/projects/${encodeURIComponent(projectId)}/script/meta`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...meta, ...patch }),
      });
      if (!response.ok) throw new Error(await errorMessage(response));
      await load();
      setNotice("项目设置已保存");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "保存失败");
    } finally {
      setBusy(null);
    }
  }

  async function saveShot(shot: ShotRow) {
    setBusy(shot.shot_id);
    try {
      const response = await apiFetch(
        `/v1/projects/${encodeURIComponent(projectId)}/script/shots/${encodeURIComponent(shot.shot_id)}`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            revision: script?.revision,
            duration_s: shot.duration_s,
            purpose: shot.purpose,
            visual: shot.visual,
            shot_size: shot.shot_size,
            camera: shot.camera,
            voiceover: shot.voiceover,
            transition_out: shot.transition_out,
            ext: shot.ext ?? {},
          }),
        },
      );
      if (!response.ok) throw new Error(await errorMessage(response));
      await load();
      setNotice(`第 ${shot.order} 镜已保存`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "保存失败");
    } finally {
      setBusy(null);
    }
  }

  async function addShot() {
    setBusy("add");
    try {
      const response = await apiFetch(`/v1/projects/${encodeURIComponent(projectId)}/script/shots`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      if (!response.ok) throw new Error(await errorMessage(response));
      await load();
      setNotice("已添加一个镜头");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "添加失败");
    } finally {
      setBusy(null);
    }
  }

  async function removeShot(shotId: string) {
    if (!window.confirm("删除这一镜？")) return;
    setBusy(shotId);
    try {
      const response = await apiFetch(
        `/v1/projects/${encodeURIComponent(projectId)}/script/shots/${encodeURIComponent(shotId)}`,
        { method: "DELETE" },
      );
      if (!response.ok) throw new Error(await errorMessage(response));
      await load();
      setNotice("已删除镜头");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "删除失败");
    } finally {
      setBusy(null);
    }
  }

  async function move(shotId: string, direction: -1 | 1) {
    const ordered = [...shots].sort((a, b) => a.order - b.order).map((shot) => shot.shot_id);
    const index = ordered.indexOf(shotId);
    const target = index + direction;
    if (index < 0 || target < 0 || target >= ordered.length) return;
    [ordered[index], ordered[target]] = [ordered[target], ordered[index]];
    setBusy("reorder");
    try {
      const response = await apiFetch(`/v1/projects/${encodeURIComponent(projectId)}/script/reorder`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ shot_ids: ordered }),
      });
      if (!response.ok) throw new Error(await errorMessage(response));
      await load();
      setNotice("顺序已更新");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "排序失败");
    } finally {
      setBusy(null);
    }
  }

  async function generate(shot: ShotRow) {
    setBusy(`gen:${shot.shot_id}`);
    try {
      const response = await apiFetch(
        `/v1/projects/${encodeURIComponent(projectId)}/script/shots/${encodeURIComponent(shot.shot_id)}/generate`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ narration: shot.voiceover, prompt_suffix: "" }),
        },
      );
      if (!response.ok) throw new Error(await errorMessage(response));
      setNotice(`第 ${shot.order} 镜已重新生成`);
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "生成失败");
    } finally {
      setBusy(null);
    }
  }

  if (error && !script) {
    return (
      <div className="mx-auto w-full max-w-3xl px-6 py-10">
        <h1 className="text-h2 font-medium">分镜表</h1>
        <p className="mt-3 text-small text-danger">{error}</p>
        <p className="mt-2 text-small text-text-3">先回项目生成分镜，再回到这里编辑。</p>
      </div>
    );
  }
  if (!script) return <p className="px-6 py-10 text-small text-text-3">正在读取分镜…</p>;

  return (
    <div className="mx-auto w-full max-w-[1280px] px-4 py-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-h2 font-medium">分镜表</h1>
          <p className="mt-1 text-caption text-text-3">
            改字段 → 单镜保存 → 重新生成；提示词由字段自动编译，不需要手写。
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Link
            className="rounded-full border border-border-strong px-3 py-1 text-caption text-text-1 hover:bg-hover"
            href={`/projects/${encodeURIComponent(projectId)}/expert`}
          >
            回到画布
          </Link>
          <button
            type="button"
            className="rounded-full border border-border-strong px-3 py-1 text-caption text-text-1 hover:bg-hover"
            onClick={() => void addShot()}
            disabled={busy === "add"}
          >
            ＋ 添加镜头
          </button>
        </div>
      </div>

      <div className="mt-4 grid gap-2 rounded-lg border border-border bg-surface p-3 md:grid-cols-4">
        <label className="grid gap-1 text-caption text-text-3">
          标题
          <input
            className={FIELD_CLASS}
            value={meta.title ?? ""}
            onChange={(event) => void saveMeta({ title: event.target.value })}
          />
        </label>
        <label className="grid gap-1 text-caption text-text-3">
          体裁
          <input
            className={FIELD_CLASS}
            value={meta.genre ?? ""}
            onChange={(event) => void saveMeta({ genre: event.target.value })}
          />
        </label>
        <label className="grid gap-1 text-caption text-text-3">
          全片质感
          <select
            className={FIELD_CLASS}
            value={meta.style_bible ?? "写实电影感"}
            onChange={(event) => void saveMeta({ style_bible: event.target.value })}
          >
            {script.styles.map((style) => (
              <option key={style} value={style}>
                {style}
              </option>
            ))}
          </select>
        </label>
        <label className="grid gap-1 text-caption text-text-3">
          比例
          <select
            className={FIELD_CLASS}
            value={meta.aspect_ratio ?? "9:16"}
            onChange={(event) => void saveMeta({ aspect_ratio: event.target.value })}
          >
            {["9:16", "16:9", "1:1", "4:3", "3:4"].map((ratio) => (
              <option key={ratio} value={ratio}>
                {ratio}
              </option>
            ))}
          </select>
        </label>
      </div>

      {error ? <p className="mt-3 text-caption text-danger">{error}</p> : null}
      {notice ? <p className="mt-3 text-caption text-blue-text">{notice}</p> : null}

      <div className="mt-4 overflow-x-auto">
        <table className="w-full min-w-[2100px] border-collapse text-caption">
          <thead>
            <tr className="text-left text-text-3">
              <th className="border-b border-border py-2 pr-2">镜号</th>
              <th className="border-b border-border py-2 pr-2">时长</th>
              <th className="border-b border-border py-2 pr-2">目的</th>
              <th className="border-b border-border py-2 pr-2">画面</th>
              <th className="border-b border-border py-2 pr-2">角色1</th>
              <th className="border-b border-border py-2 pr-2">角色1描述</th>
              <th className="border-b border-border py-2 pr-2">角色2</th>
              <th className="border-b border-border py-2 pr-2">角色2描述</th>
              <th className="border-b border-border py-2 pr-2">参考图</th>
              <th className="border-b border-border py-2 pr-2">景别</th>
              <th className="border-b border-border py-2 pr-2">角色动作</th>
              <th className="border-b border-border py-2 pr-2">情绪</th>
              <th className="border-b border-border py-2 pr-2">机位角度</th>
              <th className="border-b border-border py-2 pr-2">运镜</th>
              <th className="border-b border-border py-2 pr-2">灯光</th>
              <th className="border-b border-border py-2 pr-2">色彩/光影</th>
              <th className="border-b border-border py-2 pr-2">视觉效果</th>
              <th className="border-b border-border py-2 pr-2">音效</th>
              <th className="border-b border-border py-2 pr-2">BGM</th>
              <th className="border-b border-border py-2 pr-2">台词</th>
              <th className="border-b border-border py-2 pr-2">转场</th>
              <th className="border-b border-border py-2 pr-2">操作</th>
            </tr>
          </thead>
          <tbody>
            {shots.map((shot) => (
              <tr key={shot.shot_id} className="align-top">
                <td className="border-b border-border py-2 pr-2 tabular text-text-2">{shot.order}</td>
                <td className="border-b border-border py-2 pr-2">
                  <input
                    className={FIELD_CLASS}
                    value={shot.duration_s}
                    onChange={(event) => updateDraft(shot.shot_id, { duration_s: Number(event.target.value) })}
                  />
                </td>
                <td className="border-b border-border py-2 pr-2">
                  <input
                    className={FIELD_CLASS}
                    value={shot.purpose}
                    onChange={(event) => updateDraft(shot.shot_id, { purpose: event.target.value })}
                  />
                </td>
                <td className="border-b border-border py-2 pr-2">
                  <textarea
                    className={`${FIELD_CLASS} min-h-16`}
                    value={shot.visual}
                    onChange={(event) => updateDraft(shot.shot_id, { visual: event.target.value })}
                  />
                </td>
                <td className="border-b border-border py-2 pr-2">
                  <input
                    className={FIELD_CLASS}
                    placeholder="角色1"
                    value={shot.ext?.characters?.[0]?.name ?? ""}
                    onChange={(event) => updateCharacter(shot.shot_id, 0, "name", event.target.value)}
                  />
                </td>
                <td className="border-b border-border py-2 pr-2">
                  <textarea
                    className={`${FIELD_CLASS} min-h-16`}
                    placeholder="角色1外形/服装"
                    value={shot.ext?.characters?.[0]?.desc ?? ""}
                    onChange={(event) => updateCharacter(shot.shot_id, 0, "desc", event.target.value)}
                  />
                </td>
                <td className="border-b border-border py-2 pr-2">
                  <input
                    className={FIELD_CLASS}
                    placeholder="角色2"
                    value={shot.ext?.characters?.[1]?.name ?? ""}
                    onChange={(event) => updateCharacter(shot.shot_id, 1, "name", event.target.value)}
                  />
                </td>
                <td className="border-b border-border py-2 pr-2">
                  <textarea
                    className={`${FIELD_CLASS} min-h-16`}
                    placeholder="角色2外形/服装"
                    value={shot.ext?.characters?.[1]?.desc ?? ""}
                    onChange={(event) => updateCharacter(shot.shot_id, 1, "desc", event.target.value)}
                  />
                </td>
                <td className="border-b border-border py-2 pr-2">
                  <input
                    className={FIELD_CLASS}
                    placeholder="首帧/角色卡/场景"
                    value={shot.ext?.reference?.first_frame ?? ""}
                    onChange={(event) =>
                      updateExt(shot.shot_id, {
                        reference: { ...(shot.ext?.reference ?? {}), first_frame: event.target.value },
                      })
                    }
                  />
                </td>
                <td className="border-b border-border py-2 pr-2">
                  <input
                    className={FIELD_CLASS}
                    value={shot.shot_size}
                    onChange={(event) => updateDraft(shot.shot_id, { shot_size: event.target.value })}
                  />
                </td>
                <td className="border-b border-border py-2 pr-2">
                  <input
                    className={FIELD_CLASS}
                    placeholder="这一镜发生什么"
                    value={shot.ext?.action ?? ""}
                    onChange={(event) => updateExt(shot.shot_id, { action: event.target.value })}
                  />
                </td>
                <td className="border-b border-border py-2 pr-2">
                  <input
                    className={FIELD_CLASS}
                    placeholder="压抑/兴奋…"
                    value={shot.ext?.emotion ?? ""}
                    onChange={(event) => updateExt(shot.shot_id, { emotion: event.target.value })}
                  />
                </td>
                <td className="border-b border-border py-2 pr-2">
                  <input
                    className={FIELD_CLASS}
                    placeholder="平视/俯拍…"
                    value={shot.ext?.camera_angle ?? ""}
                    onChange={(event) => updateExt(shot.shot_id, { camera_angle: event.target.value })}
                  />
                </td>
                <td className="border-b border-border py-2 pr-2">
                  <input
                    className={FIELD_CLASS}
                    value={shot.camera}
                    onChange={(event) => updateDraft(shot.shot_id, { camera: event.target.value })}
                  />
                </td>
                <td className="border-b border-border py-2 pr-2">
                  <input
                    className={FIELD_CLASS}
                    placeholder="冷光/暖光…"
                    value={shot.ext?.lighting ?? ""}
                    onChange={(event) => updateExt(shot.shot_id, { lighting: event.target.value })}
                  />
                </td>
                <td className="border-b border-border py-2 pr-2">
                  <input
                    className={FIELD_CLASS}
                    placeholder="色调/光影"
                    value={shot.ext?.color ?? ""}
                    onChange={(event) => updateExt(shot.shot_id, { color: event.target.value })}
                  />
                </td>
                <td className="border-b border-border py-2 pr-2">
                  <input
                    className={FIELD_CLASS}
                    placeholder="画面视觉"
                    value={shot.ext?.visual_effect ?? ""}
                    onChange={(event) => updateExt(shot.shot_id, { visual_effect: event.target.value })}
                  />
                </td>
                <td className="border-b border-border py-2 pr-2">
                  <input
                    className={FIELD_CLASS}
                    placeholder="音效"
                    value={(shot.ext?.sfx ?? []).join("、")}
                    onChange={(event) =>
                      updateExt(shot.shot_id, {
                        sfx: event.target.value
                          .split(/[、,，]/)
                          .map((item) => item.trim())
                          .filter(Boolean),
                      })
                    }
                  />
                </td>
                <td className="border-b border-border py-2 pr-2">
                  <input
                    className={FIELD_CLASS}
                    placeholder="BGM 情绪"
                    value={shot.ext?.bgm ?? ""}
                    onChange={(event) => updateExt(shot.shot_id, { bgm: event.target.value })}
                  />
                </td>
                <td className="border-b border-border py-2 pr-2">
                  <textarea
                    className={`${FIELD_CLASS} min-h-16`}
                    value={shot.voiceover}
                    onChange={(event) => updateDraft(shot.shot_id, { voiceover: event.target.value })}
                  />
                </td>
                <td className="border-b border-border py-2 pr-2">
                  <input
                    className={FIELD_CLASS}
                    value={shot.transition_out}
                    onChange={(event) => updateDraft(shot.shot_id, { transition_out: event.target.value })}
                  />
                </td>
                <td className="border-b border-border py-2 pr-2">
                  <div className="flex flex-col gap-1">
                    <button
                      type="button"
                      className="rounded-xs border border-blue-strong px-2 py-1 text-text-1 hover:bg-blue-hover"
                      onClick={() => void saveShot(shot)}
                      disabled={busy === shot.shot_id}
                    >
                      保存
                    </button>
                    <button
                      type="button"
                      className="rounded-xs border border-border-strong px-2 py-1 text-text-1 hover:bg-hover"
                      onClick={() => setOpenPrompt(openPrompt === shot.shot_id ? null : shot.shot_id)}
                    >
                      提示词
                    </button>
                    <button
                      type="button"
                      className="rounded-xs border border-border-strong px-2 py-1 text-text-1 hover:bg-hover"
                      onClick={() => void generate(shot)}
                      disabled={busy === `gen:${shot.shot_id}`}
                    >
                      重新生成
                    </button>
                    <div className="flex gap-1">
                      <button
                        type="button"
                        className="rounded-xs border border-border px-2 py-1 text-text-2 hover:bg-hover"
                        onClick={() => void move(shot.shot_id, -1)}
                        disabled={busy === "reorder"}
                      >
                        ↑
                      </button>
                      <button
                        type="button"
                        className="rounded-xs border border-border px-2 py-1 text-text-2 hover:bg-hover"
                        onClick={() => void move(shot.shot_id, 1)}
                        disabled={busy === "reorder"}
                      >
                        ↓
                      </button>
                      <button
                        type="button"
                        className="rounded-xs border border-border px-2 py-1 text-danger hover:bg-hover"
                        onClick={() => void removeShot(shot.shot_id)}
                        disabled={busy === shot.shot_id}
                      >
                        删
                      </button>
                    </div>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {openPrompt && script.shots.find((shot) => shot.shot_id === openPrompt)?.prompt ? (
        <div className="mt-4 rounded-lg border border-border bg-surface p-3">
          <div className="flex items-center justify-between">
            <h2 className="text-h3 font-medium">
              第 {script.shots.find((shot) => shot.shot_id === openPrompt)?.order} 镜的 Seedance 提示词
            </h2>
            <button type="button" className="text-caption text-text-2 hover:underline" onClick={() => setOpenPrompt(null)}>
              关闭
            </button>
          </div>
          <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap rounded-sm bg-raised p-2 text-caption text-text-1">
            {script.shots.find((shot) => shot.shot_id === openPrompt)?.prompt?.prompt}
          </pre>
          <p className="mt-2 text-caption text-text-3">
            负面约束：{script.shots.find((shot) => shot.shot_id === openPrompt)?.prompt?.negative_prompt}
          </p>
          <p className="mt-1 text-caption text-text-3">
            参数：{JSON.stringify(script.shots.find((shot) => shot.shot_id === openPrompt)?.prompt?.params)}
          </p>
        </div>
      ) : null}
    </div>
  );
}
