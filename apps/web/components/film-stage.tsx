"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { apiUrl } from "@/lib/api";
import { readShots, type ProjectSnapshot, type ShotSummary } from "@/lib/progress";

export function FilmStage({ projectId }: { projectId: string }) {
  const [snapshot, setSnapshot] = useState<ProjectSnapshot | null>(null);
  const [shots, setShots] = useState<ShotSummary[]>([]);
  const [missing, setMissing] = useState(false);
  const [src, setSrc] = useState<string | null>(null);
  const [downloadError, setDownloadError] = useState<string | null>(null);

  useEffect(() => {
    let closed = false;
    const controller = new AbortController();

    async function pull() {
      try {
        const response = await fetch(apiUrl(`/v1/projects/${encodeURIComponent(projectId)}`), {
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

  useEffect(() => {
    if (!ready) return;
    let closed = false;
    let objectUrl = "";
    const controller = new AbortController();
    void (async () => {
      try {
        const response = await fetch(apiUrl(`/v1/projects/${encodeURIComponent(projectId)}/download`), {
          signal: controller.signal,
        });
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
  }, [projectId, ready]);

  async function downloadFilm() {
    setDownloadError(null);
    try {
      const response = await fetch(apiUrl(`/v1/projects/${encodeURIComponent(projectId)}/download`));
      if (!response.ok) throw new Error("下载没有成功");
      const blob = await response.blob();
      const objectUrl = URL.createObjectURL(new Blob([blob], { type: blob.type || "video/mp4" }));
      const anchor = document.createElement("a");
      anchor.href = objectUrl;
      anchor.download = "master.mp4";
      document.body.append(anchor);
      anchor.click();
      anchor.remove();
      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 4000);
    } catch (caught) {
      setDownloadError(caught instanceof Error ? caught.message : "下载没有成功");
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

  return (
    <div className="grid min-w-0 items-start gap-8 lg:grid-cols-[minmax(0,1.4fr)_minmax(16rem,0.8fr)]">
      <div className="min-w-0">
        <p className="text-sm text-muted-foreground">成片</p>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight">可以发布了</h1>
        {snapshot?.sentence ? (
          <p className="mt-3 break-words text-base leading-7 text-muted-foreground">{snapshot.sentence}</p>
        ) : null}
        <div className="mt-6 overflow-hidden rounded-lg border border-border bg-black">
          <video
            data-testid="film-player"
            className="aspect-video w-full"
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
              {shots.map((shot) => (
                <li key={shot.shot_id || shot.order} className="rounded-full bg-muted px-3 py-1 text-sm">
                  第 {shot.order} 镜{shot.purpose ? ` · ${shot.purpose}` : ""}
                </li>
              ))}
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

        <div className="grid gap-2">
          <Label htmlFor="version">版本</Label>
          <select
            id="version"
            defaultValue="current"
            aria-describedby="version-note"
            className="h-11 w-full rounded-md border border-input bg-card px-3 text-base"
          >
            <option value="current">当前成片</option>
            <option value="previous" disabled>
              上一版（即将开放）
            </option>
          </select>
          <p id="version-note" className="text-sm text-muted-foreground">
            版本切换会在改稿上线后启用。
          </p>
        </div>

        <div className="grid gap-2">
          <Label htmlFor="revision">改稿</Label>
          <Textarea id="revision" disabled placeholder="点某一镜，说出要改的地方。对话改稿尚未开放。" />
          <Button type="button" variant="outline" disabled>
            发送改稿
          </Button>
        </div>
      </div>
    </div>
  );
}
