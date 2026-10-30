"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { StoryboardStrip } from "@/components/storyboard-strip";
import { Button } from "@/components/ui/button";
import { apiFetch, ensureSession, withSession, wsUrl } from "@/lib/api";
import { readCards, type StoryboardCard } from "@/lib/storyboard";
import {
  attachmentLabel,
  latestMessage,
  latestPhase,
  mergeEvents,
  PHASES,
  projectStatus,
  readAttachments,
  readEvents,
  readShots,
  shotViews,
  type AttachmentView,
  type ProgressEvent,
  type ProjectSnapshot,
  type ShotSummary,
} from "@/lib/progress";

export function ProgressBoard({ projectId }: { projectId: string }) {
  const [snapshot, setSnapshot] = useState<ProjectSnapshot | null>(null);
  const [events, setEvents] = useState<ProgressEvent[]>([]);
  const [shots, setShots] = useState<ShotSummary[]>([]);
  const [attachments, setAttachments] = useState<AttachmentView[]>([]);
  const [cards, setCards] = useState<StoryboardCard[]>([]);
  const [missing, setMissing] = useState(false);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let closed = false;
    let socket: WebSocket | null = null;
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
        setAttachments(readAttachments(body.attachments));
        setCards(readCards(body.storyboard));
        setEvents((current) => mergeEvents(current, readEvents(body.events)));
      } catch (caught) {
        if (caught instanceof DOMException && caught.name === "AbortError") return;
      }
    }

    void pull();
    const timer = window.setInterval(() => {
      void pull();
    }, 700);

    void ensureSession().then((token) => {
      if (closed || !token) return;
      socket = new WebSocket(
        withSession(wsUrl(`/v1/projects/${encodeURIComponent(projectId)}/progress`), token),
      );
      socket.onmessage = onSocket;
    });

    function onSocket(message: MessageEvent) {
      let data: ProgressEvent;
      try {
        data = JSON.parse(String(message.data)) as ProgressEvent;
      } catch {
        return;
      }
      if (data.type === "error") {
        setMissing(true);
        return;
      }
      setEvents((current) => mergeEvents(current, [data]));
      if (data.status === "completed" || data.status === "failed") void pull();
    }

    return () => {
      closed = true;
      controller.abort();
      window.clearInterval(timer);
      socket?.close();
    };
  }, [projectId, tick]);

  if (missing) {
    return (
      <div className="mx-auto max-w-xl">
        <h1 className="text-3xl font-semibold">项目不存在</h1>
        <Button asChild className="mt-6">
          <Link href="/">返回输入</Link>
        </Button>
      </div>
    );
  }

  const phase = latestPhase(events, snapshot?.phase || "理解需求");
  const status = projectStatus(snapshot?.status, events);
  const headline = latestMessage(events, snapshot?.message || "正在排队");
  const rows = shotViews(shots, events);
  const phaseIndex = PHASES.indexOf(phase as (typeof PHASES)[number]);

  return (
    <div className="mx-auto grid min-w-0 max-w-3xl gap-6">
      <div>
        <p className="text-sm text-muted-foreground">生成进度</p>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight">正在做这条片</h1>
        {snapshot?.sentence ? (
          <p className="mt-3 break-words text-base leading-7 text-muted-foreground">{snapshot.sentence}</p>
        ) : null}
      </div>

      <ol aria-label="进度" className="flex flex-wrap gap-2">
        {PHASES.map((item, index) => {
          const active = item === phase;
          const done = phaseIndex > index;
          return (
            <li
              key={item}
              aria-current={active ? "step" : undefined}
              className={`rounded-full px-3 py-1.5 text-sm ${
                active
                  ? "bg-primary text-primary-foreground"
                  : done
                    ? "bg-accent text-foreground"
                    : "bg-muted text-muted-foreground"
              }`}
            >
              {item}
            </li>
          );
        })}
      </ol>

      <p data-testid="current-message" role={status === "failed" ? "alert" : "status"} className="text-lg">
        {headline}
      </p>
      {typeof snapshot?.elapsed_s === "number" ? (
        <p className="text-sm text-muted-foreground">已用时 {Math.max(0, Math.round(snapshot.elapsed_s))} 秒</p>
      ) : null}

      {snapshot?.status === "paused" && cards.length > 0 ? (
        <StoryboardStrip projectId={projectId} cards={cards} onSaved={() => setTick((value) => value + 1)} />
      ) : null}

      {rows.length > 0 ? (
        <ol data-testid="shot-list" aria-label="分镜进度" className="grid gap-3">
          {rows.map((shot) => (
            <li key={shot.key} className="min-w-0 rounded-lg border border-border bg-card px-4 py-3">
              {shot.purpose ? <p className="text-sm text-muted-foreground">{shot.purpose}</p> : null}
              <p data-testid="shot-stage" className="mt-1 break-words text-base font-medium">
                {shot.stage}
              </p>
            </li>
          ))}
        </ol>
      ) : (
        <p className="text-sm text-muted-foreground">镜头会在分镜排好后逐条出现在这里。</p>
      )}

      {attachments.length > 0 ? (
        <div>
          <h2 className="text-sm font-medium">已提交的素材</h2>
          <ul className="mt-2 grid gap-1">
            {attachments.map((item) => (
              <li
                key={item.upload_id || item.filename || item.uri}
                className="break-all text-sm text-muted-foreground"
              >
                {attachmentLabel(item)}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {status === "completed" ? (
        <Button asChild size="lg" className="w-full sm:w-auto">
          <Link href={`/projects/${projectId}/film`}>观看成片</Link>
        </Button>
      ) : null}
    </div>
  );
}
