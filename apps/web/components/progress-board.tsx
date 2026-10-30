"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { useShellStage } from "@/components/hilatv/shell-stage";
import { StoryboardStrip } from "@/components/storyboard-strip";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { apiFetch, ensureSession, withSession, wsUrl } from "@/lib/api";
import { readCards, type StoryboardCard } from "@/lib/storyboard";
import {
  attachmentLabel,
  latestMessage,
  latestPhase,
  mergeEvents,
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
import { PROJECT_COPY, SHOT_STATUS, shotStatus, stageProgress, STAGES } from "@/lib/status-copy";

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

  const phase = latestPhase(events, snapshot?.phase || STAGES[0]);
  const status = projectStatus(snapshot?.status, events);
  useShellStage(missing ? null : phase, status === "completed");

  if (missing) {
    return (
      <div className="mx-auto max-w-xl">
        <h1 className="text-h1 font-medium">{PROJECT_COPY.missing}</h1>
        <Button asChild className="mt-6">
          <Link href="/">{PROJECT_COPY.backHome}</Link>
        </Button>
      </div>
    );
  }

  const headline = latestMessage(events, snapshot?.message || PROJECT_COPY.queued);
  const rows = shotViews(shots, events);
  const failed = status === "failed";

  return (
    <div className="mx-auto grid w-full min-w-0 max-w-300 gap-6">
      <div>
        <p className="text-small text-text-2">生成进度</p>
        <h1 className="mt-2 text-h1 font-medium tracking-wide">正在做这条片</h1>
        {snapshot?.sentence ? (
          <p className="mt-2 break-words text-body text-text-2">{snapshot.sentence}</p>
        ) : null}
      </div>

      <Card className="grid gap-3 p-4 md:p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p
            data-testid="current-message"
            role={failed ? "alert" : "status"}
            className={failed ? "text-h3 font-medium text-danger" : "text-h3 font-medium"}
          >
            {headline}
          </p>
          {typeof snapshot?.elapsed_s === "number" ? (
            <p className="tabular text-caption text-text-3">
              已用时 {Math.max(0, Math.round(snapshot.elapsed_s))} 秒
            </p>
          ) : null}
        </div>
        <Progress label="总进度" value={stageProgress(phase, status)} />
      </Card>

      {snapshot?.status === "paused" && cards.length > 0 ? (
        <StoryboardStrip projectId={projectId} cards={cards} onSaved={() => setTick((value) => value + 1)} />
      ) : null}

      {rows.length > 0 ? (
        <ol data-testid="shot-list" aria-label="分镜进度" className="grid gap-2">
          {rows.map((shot) => {
            const tag = SHOT_STATUS[shotStatus(shot.stage, status)];
            return (
              <li
                key={shot.key}
                className="flex min-w-0 items-center gap-3 rounded-md border border-border bg-surface px-3 py-3 md:px-4"
              >
                <span className="tabular flex size-8 shrink-0 items-center justify-center rounded-sm bg-hover text-caption text-text-2">
                  {shot.order}
                </span>
                <div className="min-w-0 flex-1">
                  {shot.purpose ? <p className="text-caption text-text-3">{shot.purpose}</p> : null}
                  <p data-testid="shot-stage" className="break-words text-body">
                    {shot.stage}
                  </p>
                </div>
                <Badge tone={tag.tone} className="shrink-0">
                  {tag.label}
                </Badge>
              </li>
            );
          })}
        </ol>
      ) : (
        <p className="text-small text-text-2">{PROJECT_COPY.shotsLater}</p>
      )}

      {attachments.length > 0 ? (
        <div>
          <h2 className="text-h3 font-medium">已提交的素材</h2>
          <ul className="mt-2 flex flex-wrap gap-2">
            {attachments.map((item) => (
              <li key={item.upload_id || item.filename || item.uri} className="max-w-full">
                <Badge className="break-all">{attachmentLabel(item)}</Badge>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className="flex flex-wrap gap-3">
        <Button asChild variant="secondary" size="lg" className="w-full sm:w-auto">
          <Link href={`/projects/${projectId}/expert`}>专家模式</Link>
        </Button>
        {status === "needs_human_review" ? (
          <Button
            data-testid="release-review"
            size="lg"
            className="w-full sm:w-auto"
            onClick={() => {
              void apiFetch(`/v1/projects/${encodeURIComponent(projectId)}/human-review/release`, {
                method: "POST",
              });
            }}
          >
            放行并成片
          </Button>
        ) : null}
        {status === "completed" ? (
          <Button asChild size="lg" className="w-full sm:w-auto">
            <Link href={`/projects/${projectId}/film`}>观看成片</Link>
          </Button>
        ) : null}
      </div>
    </div>
  );
}
