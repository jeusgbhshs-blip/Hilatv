"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { apiFetch, errorMessage } from "@/lib/api";
import { conceptNotice } from "@/lib/concept";
import { readShots, type ProjectSnapshot, type ShotSummary } from "@/lib/progress";
import {
  aspectLabel,
  defaultChoice,
  downloadName,
  durationLabel,
  languageLabel,
  pickVersion,
  readVersions,
  reconcile,
  uniqueAspects,
  uniqueDurations,
  uniqueLanguages,
  type FilmVersion,
  type VersionChoice,
} from "@/lib/versions";

type EditVersion = {
  version_id: string;
  index: number;
  current: boolean;
  quality_pass: boolean;
};

export function FilmStage({ projectId }: { projectId: string }) {
  const [snapshot, setSnapshot] = useState<ProjectSnapshot | null>(null);
  const [shots, setShots] = useState<ShotSummary[]>([]);
  const [missing, setMissing] = useState(false);
  const [src, setSrc] = useState<string | null>(null);
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const [versions, setVersions] = useState<FilmVersion[]>([]);
  const [choice, setChoice] = useState<VersionChoice>({ aspect: "", language: "", duration: null });
  const [exporting, setExporting] = useState(false);
  const [versionNote, setVersionNote] = useState<string | null>(null);
  const [edits, setEdits] = useState<EditVersion[]>([]);
  const [instruction, setInstruction] = useState("");
  const [shotId, setShotId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [editError, setEditError] = useState<string | null>(null);
  const [question, setQuestion] = useState<string | null>(null);
  const [playerToken, setPlayerToken] = useState(0);

  useEffect(() => {
    let closed = false;
    const controller = new AbortController();

    async function pull() {
      try {
        const response = await apiFetch(`/v1/projects/${encodeURIComponent(projectId)}`, {
          signal: controller.signal,
        });
        if (closed) return;
        if (response.status === 404) {
          setMissing(true);
          return;
        }
        if (!response.ok) return;
        const body = (await response.json()) as ProjectSnapshot;
        if (closed) return;
        setSnapshot(body);
        setShots(readShots(body.shots));
      } catch (caught) {
        if (caught instanceof DOMException && caught.name === "AbortError") return;
      }
    }

    void pull();
    const timer = window.setInterval(() => {
      void pull();
    }, 1000);
    return () => {
      closed = true;
      controller.abort();
      window.clearInterval(timer);
    };
  }, [projectId]);

  const ready = snapshot?.status === "completed";
  const selected = pickVersion(versions, choice);
  const mediaPath = selected
    ? selected.download_path
    : ready
      ? `/v1/projects/${encodeURIComponent(projectId)}/download`
      : null;

  useEffect(() => {
    if (!ready) return;
    let closed = false;
    const controller = new AbortController();
    void (async () => {
      try {
        const response = await apiFetch(`/v1/projects/${encodeURIComponent(projectId)}/versions`, {
          signal: controller.signal,
        });
        if (!response.ok || closed) return;
        const found = readVersions(await response.json());
        if (closed) return;
        setVersions(found);
        if (found.length > 0) setChoice(defaultChoice(found));
      } catch (caught) {
        if (caught instanceof DOMException && caught.name === "AbortError") return;
      }
    })();
    return () => {
      closed = true;
      controller.abort();
    };
  }, [projectId, ready, playerToken]);

  useEffect(() => {
    if (!ready) return;
    let closed = false;
    const controller = new AbortController();
    void (async () => {
      try {
        const response = await apiFetch(`/v1/projects/${encodeURIComponent(projectId)}/revisions`, {
          signal: controller.signal,
        });
        if (!response.ok || closed) return;
        const body = (await response.json()) as { versions?: EditVersion[] };
        if (!closed) setEdits(Array.isArray(body.versions) ? body.versions : []);
      } catch (caught) {
        if (caught instanceof DOMException && caught.name === "AbortError") return;
      }
    })();
    return () => {
      closed = true;
      controller.abort();
    };
  }, [projectId, ready, playerToken]);

  useEffect(() => {
    if (!mediaPath) return;
    let closed = false;
    let objectUrl = "";
    const controller = new AbortController();
    void (async () => {
      try {
        const response = await apiFetch(mediaPath, { signal: controller.signal });
        if (!response.ok || closed) return;
        const blob = await response.blob();
        objectUrl = URL.createObjectURL(new Blob([blob], { type: blob.type || "video/mp4" }));
        if (!closed) setSrc(objectUrl);
      } catch (caught) {
        if (caught instanceof DOMException && caught.name === "AbortError") return;
      }
    })();
    return () => {
      closed = true;
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [mediaPath, playerToken]);

  async function downloadFilm() {
    if (!mediaPath) return;
    setDownloadError(null);
    try {
      const response = await apiFetch(mediaPath);
      if (!response.ok) throw new Error("下载没有成功");
      const blob = await response.blob();
      const objectUrl = URL.createObjectURL(new Blob([blob], { type: blob.type || "video/mp4" }));
      const anchor = document.createElement("a");
      anchor.href = objectUrl;
      anchor.download = downloadName(selected);
      document.body.append(anchor);
      anchor.click();
      anchor.remove();
      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 4000);
    } catch (caught) {
      setDownloadError(caught instanceof Error ? caught.message : "下载没有成功");
    }
  }

  async function exportVersions() {
    setExporting(true);
    setVersionNote(null);
    try {
      const response = await apiFetch(`/v1/projects/${encodeURIComponent(projectId)}/deliveries`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          aspect_ratios: ["16:9", "9:16", "1:1"],
          languages: ["zh", "en"],
        }),
      });
      if (!response.ok) throw new Error(await errorMessage(response));
      const found = readVersions(await response.json());
      setVersions(found);
      if (found.length > 0) setChoice(defaultChoice(found));
    } catch (caught) {
      setVersionNote(caught instanceof Error ? caught.message : "导出没有成功");
    } finally {
      setExporting(false);
    }
  }

  function choose(next: Partial<VersionChoice>) {
    setChoice((current) => reconcile(versions, { ...current, ...next }));
  }

  async function chooseEdit(versionId: string) {
    const current = edits.find((item) => item.current);
    if (!versionId || current?.version_id === versionId) return;
    setBusy(true);
    setEditError(null);
    try {
      const response = await apiFetch(
        `/v1/projects/${encodeURIComponent(projectId)}/revisions/${encodeURIComponent(versionId)}/restore`,
        { method: "POST" },
      );
      if (!response.ok) throw new Error(await errorMessage(response));
      const body = (await response.json()) as { versions?: EditVersion[] };
      if (Array.isArray(body.versions)) setEdits(body.versions);
      setSrc(null);
      setPlayerToken((value) => value + 1);
    } catch (caught) {
      setEditError(caught instanceof Error ? caught.message : "没有回到那个版本");
    } finally {
      setBusy(false);
    }
  }

  async function sendEdit() {
    const text = instruction.trim();
    if (!text || busy) return;
    setBusy(true);
    setEditError(null);
    try {
      const response = await apiFetch(`/v1/projects/${encodeURIComponent(projectId)}/revisions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ instruction: text, shot_id: shotId }),
      });
      if (!response.ok) throw new Error(await errorMessage(response));
      const body = (await response.json()) as { status?: string; question?: string; notice?: string };
      setInstruction("");
      setQuestion(body.question || body.notice || null);
      if (body.status === "needs_clarification" || body.status === "not_supported") return;
      setSrc(null);
      setPlayerToken((value) => value + 1);
    } catch (caught) {
      setEditError(caught instanceof Error ? caught.message : "改稿没有成功");
    } finally {
      setBusy(false);
    }
  }

  if (missing) {
    return (
      <div>
        <h1 className="text-3xl font-semibold">项目不存在</h1>
        <Button asChild className="mt-6">
          <Link href="/">返回输入</Link>
        </Button>
      </div>
    );
  }

  if (!ready) {
    return (
      <div className="max-w-xl">
        <h1 className="text-3xl font-semibold">成片还没好</h1>
        <p className="mt-3 text-muted-foreground">生成结束后再来播放和下载。</p>
        <Button asChild className="mt-6" variant="outline">
          <Link href={`/projects/${projectId}`}>返回进度</Link>
        </Button>
      </div>
    );
  }

  const aspects = uniqueAspects(versions);
  const languages = uniqueLanguages(versions, choice.aspect);
  const durations = uniqueDurations(versions, choice.aspect, choice.language);
  const portrait = selected ? selected.height > selected.width : false;
  const notice = conceptNotice(snapshot);
  const currentEdit = edits.find((item) => item.current)?.version_id ?? "";
  const focused = shots.find((shot) => shot.shot_id && shot.shot_id === shotId);

  return (
    <div className="grid min-w-0 items-start gap-8 lg:grid-cols-[minmax(0,1.4fr)_minmax(16rem,0.8fr)]">
      <div className="min-w-0">
        <p className="text-sm text-muted-foreground">成片</p>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight">可以发布了</h1>
        {snapshot?.sentence ? (
          <p className="mt-3 break-words text-base leading-7 text-muted-foreground">{snapshot.sentence}</p>
        ) : null}
        {notice ? (
          <p
            role="status"
            data-testid="concept-degraded"
            className="mt-4 rounded-md border border-border bg-muted px-3 py-2 text-sm"
          >
            {notice}
          </p>
        ) : null}
        <div className="mt-6 overflow-hidden rounded-lg border border-border bg-black">
          <video
            data-testid="film-player"
            data-aspect={selected?.aspect_ratio ?? "master"}
            className={portrait ? "mx-auto aspect-[9/16] max-h-[70vh]" : "aspect-video w-full"}
            controls
            playsInline
            src={src ?? undefined}
            aria-label="成片播放器"
          />
        </div>
        {!src ? <p className="mt-2 text-sm text-muted-foreground">正在载入成片</p> : null}
        {shots.length > 0 ? (
          <div className="mt-4">
            <h2 className="text-sm font-medium">时间轴</h2>
            <ul className="mt-2 flex flex-wrap gap-2">
              {shots.map((shot) => {
                const pressed = Boolean(shot.shot_id && shot.shot_id === shotId);
                return (
                  <li key={shot.shot_id || shot.order}>
                    <button
                      type="button"
                      aria-pressed={pressed}
                      className={`rounded-full px-3 py-1 text-sm ${pressed ? "bg-foreground text-background" : "bg-muted"}`}
                      onClick={() => setShotId(shot.shot_id ?? null)}
                    >
                      第 {shot.order} 镜{shot.purpose ? ` · ${shot.purpose}` : ""}
                    </button>
                  </li>
                );
              })}
            </ul>
          </div>
        ) : null}
      </div>

      <div className="grid min-w-0 gap-5 rounded-lg border border-border bg-card p-5">
        <Button type="button" size="lg" onClick={() => void downloadFilm()}>
          下载成片
        </Button>
        {downloadError ? (
          <p role="alert" className="text-sm text-destructive">
            {downloadError}
          </p>
        ) : null}

        <fieldset className="grid gap-3">
          <legend className="text-sm font-medium">版本</legend>
          <VersionSelect
            id="aspect"
            label="比例"
            value={choice.aspect}
            disabled={aspects.length === 0}
            options={aspects.map((item) => ({ value: item, label: aspectLabel(item) }))}
            onChange={(value) => choose({ aspect: value })}
          />
          <VersionSelect
            id="language"
            label="语种"
            value={choice.language}
            disabled={languages.length === 0}
            options={languages.map((item) => ({ value: item, label: languageLabel(item) }))}
            onChange={(value) => choose({ language: value })}
          />
          <VersionSelect
            id="duration"
            label="时长"
            value={choice.duration === null ? "" : String(choice.duration)}
            disabled={durations.length === 0}
            options={durations.map((item) => ({ value: String(item), label: durationLabel(item) }))}
            onChange={(value) => choose({ duration: Number(value) })}
          />
          {versions.length === 0 ? (
            <Button type="button" variant="outline" disabled={exporting} onClick={() => void exportVersions()}>
              {exporting ? "正在导出" : "导出其他版本"}
            </Button>
          ) : null}
          <p id="version-note" className="text-sm text-muted-foreground">
            {versionNote ??
              (selected?.qa_status === "needs_review"
                ? "没有真实主体框，画面按整幅适配，需要再看一眼。"
                : versions.length > 0
                  ? "切换比例、语种或时长会换一条成片。"
                  : "当前播放的是母版。导出后可以换比例、语种和时长。")}
          </p>
        </fieldset>

        <div className="grid gap-2">
          <Label htmlFor="edit-version">改稿版本</Label>
          <select
            id="edit-version"
            value={currentEdit}
            disabled={busy || edits.length === 0}
            className="h-11 w-full rounded-md border border-input bg-card px-3 text-base disabled:opacity-60"
            onChange={(event) => void chooseEdit(event.target.value)}
          >
            {edits.length === 0 ? <option value="">正在读取改稿</option> : null}
            {edits.map((version) => (
              <option key={version.version_id} value={version.version_id}>
                {editLabel(version)}
              </option>
            ))}
          </select>
          <p className="text-sm text-muted-foreground">未通过质检的改稿不会被标成通过。</p>
        </div>

        <div className="grid gap-2">
          <Label htmlFor="revision">改稿</Label>
          <Textarea
            id="revision"
            value={instruction}
            disabled={busy}
            placeholder={
              focused
                ? `改第 ${focused.order} 镜，说要改什么、留下什么。`
                : "说要改什么。也可以先点时间轴上的某一镜。"
            }
            onChange={(event) => setInstruction(event.target.value)}
          />
          <Button
            type="button"
            variant="outline"
            disabled={busy || instruction.trim().length === 0}
            onClick={() => void sendEdit()}
          >
            {busy ? "正在改稿" : "发送改稿"}
          </Button>
          {question ? (
            <p role="status" data-testid="revision-notice" className="text-sm text-muted-foreground">
              {question}
            </p>
          ) : null}
          {snapshot?.revision_notice ? (
            <p role="status" className="text-sm text-muted-foreground">
              {snapshot.revision_notice}
            </p>
          ) : null}
          {editError ? (
            <p role="alert" className="text-sm text-destructive">
              {editError}
            </p>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function editLabel(version: EditVersion): string {
  const parts = [`版本 ${version.index}`];
  if (version.current) parts.push("当前");
  if (!version.quality_pass) parts.push("未通过质检");
  return parts.join("，");
}

function VersionSelect({
  id,
  label,
  value,
  disabled,
  options,
  onChange,
}: {
  id: string;
  label: string;
  value: string;
  disabled: boolean;
  options: { value: string; label: string }[];
  onChange: (value: string) => void;
}) {
  return (
    <div className="grid gap-2">
      <Label htmlFor={id}>{label}</Label>
      <select
        id={id}
        value={options.length === 0 ? "" : value}
        disabled={disabled}
        aria-describedby="version-note"
        onChange={(event) => onChange(event.target.value)}
        className="h-11 w-full rounded-md border border-input bg-card px-3 text-base disabled:opacity-60"
      >
        {options.length === 0 ? <option value="">当前成片</option> : null}
        {options.map((item) => (
          <option key={item.value} value={item.value}>
            {item.label}
          </option>
        ))}
      </select>
    </div>
  );
}
