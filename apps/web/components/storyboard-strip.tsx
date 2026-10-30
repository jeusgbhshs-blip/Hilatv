"use client";

import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { apiFetch, apiUrl, ensureSession, errorMessage, withSession } from "@/lib/api";
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
  const [token, setToken] = useState("");

  useEffect(() => {
    void ensureSession()
      .then(setToken)
      .catch(() => setToken(""));
  }, []);

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
      const response = await apiFetch(
        `/v1/projects/${encodeURIComponent(projectId)}/storyboard/${encodeURIComponent(shotId)}`,
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
      const response = await apiFetch(`/v1/projects/${encodeURIComponent(projectId)}/storyboard/continue`, {
        method: "POST",
      });
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
          <h2 className="text-h2 font-medium">看分镜</h2>
          <p className="mt-1 text-small text-text-2">改旁白只重做这一镜。画面上的字仍由后期叠。</p>
        </div>
        <p data-testid="ai-label" className="rounded-full bg-hover px-2.5 py-0.5 text-caption text-text-2">
          AI生成
        </p>
      </div>
      <div data-testid="storyboard" className="mt-4 flex min-w-0 gap-3 overflow-x-auto pb-2">
        {cards.map((card) => {
          const media = cardMedia(card);
          const value = drafts[card.shot_id] ?? card.voiceover;
          return (
            <article
              key={card.shot_id}
              data-testid="storyboard-card"
              className="w-64 shrink-0 rounded-md border border-border bg-surface p-3"
            >
              <p className="tabular text-caption text-text-3">
                第 {card.order} 镜 · {card.duration_s} 秒
              </p>
              {card.purpose ? <p className="mt-1 text-h3 font-medium">{card.purpose}</p> : null}
              <div
                data-theme="dark"
                data-stage="storyboard"
                className="mt-3 flex aspect-video items-center justify-center overflow-hidden rounded-sm bg-stage px-3 text-center text-small text-text-2"
              >
                {media.showImage && card.frame_url ? (
                  // The frame URL is this project's API. It is not a remote host.
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    data-testid="storyboard-frame"
                    src={token ? withSession(apiUrl(card.frame_url), token) : undefined}
                    alt=""
                    className="h-full w-full object-contain"
                  />
                ) : (
                  <span>{media.note}</span>
                )}
              </div>
              {media.showImage ? (
                <p className="mt-2 text-caption text-text-3">{media.note}</p>
              ) : (
                <p className="mt-2 text-caption text-text-3">画面预览：未测</p>
              )}
              <label className="mt-3 grid gap-1 text-small text-text-2">
                旁白
                <textarea
                  aria-label={`第 ${card.order} 镜旁白`}
                  className="min-h-24 w-full rounded-sm border border-border-strong bg-raised px-2 py-1.5 text-body text-text-1"
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
                variant="secondary"
                className="mt-3 w-full"
                disabled={busy !== null || !(dirty[card.shot_id] && value.trim())}
                loading={busy === card.shot_id}
                onClick={() => void save(card.shot_id)}
              >
                {busy === card.shot_id ? "正在保存" : "保存旁白"}
              </Button>
            </article>
          );
        })}
      </div>
      {error ? (
        <p role="alert" className="mt-3 text-caption text-danger">
          {error}
        </p>
      ) : null}
      <Button
        type="button"
        className="mt-4"
        disabled={busy !== null}
        loading={busy === "continue"}
        onClick={() => void continueFilm()}
      >
        {busy === "continue" ? "正在继续" : "继续生成"}
      </Button>
    </section>
  );
}
