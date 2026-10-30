"use client";

import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { apiUrl, errorMessage } from "@/lib/api";
import { cardMedia, type StoryboardCard } from "@/lib/storyboard";

export function StoryboardStrip({
  projectId,
  cards,
  onSaved,
}: {
  projectId: string;
  cards: StoryboardCard[];
  onSaved: () => void;
}) {
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [dirty, setDirty] = useState<Record<string, boolean>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setDrafts((current) => {
      const next = { ...current };
      for (const card of cards) {
        if (!dirty[card.shot_id]) next[card.shot_id] = card.voiceover;
      }
      return next;
    });
  }, [cards, dirty]);

  async function save(shotId: string) {
    const voiceover = (drafts[shotId] || "").trim();
    if (!voiceover) {
      setError("旁白不能是空的");
      return;
    }
    setBusy(shotId);
    setError(null);
    try {
      const response = await fetch(
        apiUrl(`/v1/projects/${encodeURIComponent(projectId)}/storyboard/${encodeURIComponent(shotId)}`),
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ voiceover }),
        },
      );
      if (!response.ok) throw new Error(await errorMessage(response));
      setDirty((current) => ({ ...current, [shotId]: false }));
      onSaved();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "旁白没有保存");
    } finally {
      setBusy(null);
    }
  }

  async function continueFilm() {
    setBusy("continue");
    setError(null);
    try {
      const response = await fetch(
        apiUrl(`/v1/projects/${encodeURIComponent(projectId)}/storyboard/continue`),
        { method: "POST" },
      );
      if (!response.ok) throw new Error(await errorMessage(response));
      onSaved();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "没有继续");
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="min-w-0" aria-label="分镜预览">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-lg font-medium">看分镜</h2>
          <p className="mt-1 text-sm text-muted-foreground">改旁白只重做这一镜。画面上的字仍由后期叠。</p>
        </div>
        <p data-testid="ai-label" className="rounded-md bg-accent px-2 py-1 text-sm font-medium">
          AI生成
        </p>
      </div>
      <div
        data-testid="storyboard"
        className="mt-4 flex min-w-0 gap-3 overflow-x-auto pb-2"
      >
        {cards.map((card) => {
          const media = cardMedia(card);
          const value = drafts[card.shot_id] ?? card.voiceover;
          return (
            <article
              key={card.shot_id}
              data-testid="storyboard-card"
              className="w-64 shrink-0 rounded-lg border border-border bg-card p-3"
            >
              <p className="text-sm text-muted-foreground">第 {card.order} 镜 · {card.duration_s} 秒</p>
              {card.purpose ? <p className="mt-1 text-sm font-medium">{card.purpose}</p> : null}
              <div className="mt-3 flex h-36 items-center justify-center rounded-md border border-dashed border-border bg-muted px-3 text-center text-sm text-muted-foreground">
                {media.showImage && card.frame_url ? (
                  // The frame URL is this project's API. It is not a remote host.
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    data-testid="storyboard-frame"
                    src={apiUrl(card.frame_url)}
                    alt=""
                    className="h-full w-full rounded-md object-cover"
                  />
                ) : (
                  <span>{media.note}</span>
                )}
              </div>
              {media.showImage ? (
                <p className="mt-2 text-xs text-muted-foreground">{media.note}</p>
              ) : (
                <p className="mt-2 text-xs text-muted-foreground">画面预览：未测</p>
              )}
              <label className="mt-3 grid gap-1 text-sm">
                旁白
                <textarea
                  aria-label={`第 ${card.order} 镜旁白`}
                  className="min-h-24 w-full rounded-md border border-border bg-background px-2 py-1 text-sm"
                  maxLength={400}
                  value={value}
                  onChange={(event) => {
                    const next = event.target.value;
                    setDrafts((current) => ({ ...current, [card.shot_id]: next }));
                    setDirty((current) => ({ ...current, [card.shot_id]: true }));
                  }}
                />
              </label>
              <Button
                type="button"
                variant="outline"
                className="mt-3 w-full"
                disabled={busy !== null || !(dirty[card.shot_id] && value.trim())}
                onClick={() => void save(card.shot_id)}
              >
                {busy === card.shot_id ? "正在保存" : "保存旁白"}
              </Button>
            </article>
          );
        })}
      </div>
      {error ? (
        <p role="alert" className="mt-3 text-sm text-destructive">
          {error}
        </p>
      ) : null}
      <Button type="button" className="mt-4" disabled={busy !== null} onClick={() => void continueFilm()}>
        {busy === "continue" ? "正在继续" : "继续生成"}
      </Button>
    </section>
  );
}
