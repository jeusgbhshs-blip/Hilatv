"use client";

import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { apiFetch, apiUrl, ensureSession, errorMessage, withSession } from "@/lib/api";
import { draftScope } from "@/lib/project-draft";
import { cardMedia, type StoryboardCard } from "@/lib/storyboard";
import { durationLabel } from "@/lib/versions";

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
  const [localReady, setLocalReady] = useState(false);
  const active = useRef(false);
  const cardsRef = useRef(cards);
  cardsRef.current = cards;
  const localKey = useRef("");
  const pending = useRef<Record<string, { value: string; base: string }>>({});
  const conflicts = useRef(new Set<string>());
  const acknowledged = useRef<Record<string, { base: string; value: string }>>({});

  function persistPending() {
    if (!localKey.current) return;
    try {
      if (Object.keys(pending.current).length) window.localStorage.setItem(localKey.current, JSON.stringify(pending.current));
      else window.localStorage.removeItem(localKey.current);
    } catch { setError("本地草稿未能保存，请先保存旁白再离开"); }
  }

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const scope = await draftScope();
        const key = `hilatv.storyboard-drafts.v1.${scope}.${projectId}`;
        const saved = JSON.parse(window.localStorage.getItem(key) || "{}");
        if (cancelled) return;
        localKey.current = key;
        const restored: Record<string, string> = {};
        const changed: Record<string, boolean> = {};
        for (const card of cardsRef.current) {
          const item = saved?.[card.shot_id];
          if (!item || typeof item.value !== "string" || typeof item.base !== "string" || item.value === card.voiceover) continue;
          pending.current[card.shot_id] = item;
          restored[card.shot_id] = item.value;
          changed[card.shot_id] = true;
          if (item.base !== card.voiceover) conflicts.current.add(card.shot_id);
        }
        setDrafts((current) => ({ ...current, ...restored }));
        setDirty((current) => ({ ...current, ...changed }));
        if (conflicts.current.size) setError("分镜已有新的修改。你的草稿已恢复，请逐镜核对并保存后再继续。");
      } catch { if (!cancelled) setError("本地草稿未能恢复，请先确认并保存旁白再离开"); }
      finally { if (!cancelled) setLocalReady(true); }
    })();
    return () => { cancelled = true; };
  }, [projectId]);

  useEffect(() => {
    void ensureSession()
      .then(setToken)
      .catch(() => setToken(""));
  }, []);

  useEffect(() => {
    setDrafts((current) => {
      const next = { ...current };
      for (const card of cards) {
        if (!dirty[card.shot_id]) {
          const ack = acknowledged.current[card.shot_id];
          next[card.shot_id] = ack && card.voiceover === ack.base ? ack.value : card.voiceover;
          if (ack && card.voiceover !== ack.base) delete acknowledged.current[card.shot_id];
        }
      }
      return next;
    });
  }, [cards, dirty]);

  async function saveOne(shotId: string, voiceover: string) {
    if (!voiceover.trim()) throw new Error("旁白不能是空的");
    const response = await apiFetch(`/v1/projects/${encodeURIComponent(projectId)}/storyboard/${encodeURIComponent(shotId)}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ voiceover: voiceover.trim() }),
    });
    if (!response.ok) throw new Error(await errorMessage(response));
    acknowledged.current[shotId] = { base: pending.current[shotId]?.base ?? cardsRef.current.find((card) => card.shot_id === shotId)?.voiceover ?? "", value: voiceover.trim() };
    if (pending.current[shotId]?.value === voiceover) delete pending.current[shotId];
    conflicts.current.delete(shotId);
    persistPending();
    setDirty((current) => ({ ...current, [shotId]: Boolean(pending.current[shotId]) }));
  }

  async function save(shotId: string) {
    if (active.current) return;
    active.current = true;
    setBusy(shotId);
    setError(null);
    try {
      await saveOne(shotId, pending.current[shotId]?.value ?? drafts[shotId] ?? "");
      onSaved();
    } catch (caught) { setError(caught instanceof Error ? caught.message : "旁白没有保存"); }
    finally { active.current = false; setBusy(null); }
  }

  async function continueFilm() {
    if (active.current) return;
    if (conflicts.current.size) { setError("请先核对并保存有冲突的旁白，再继续生成"); return; }
    active.current = true;
    setBusy("continue");
    setError(null);
    try {
      // All dirty shots must acknowledge before the workflow can resume.
      for (const [shotId, edit] of Object.entries(pending.current)) await saveOne(shotId, edit.value);
      const response = await apiFetch(`/v1/projects/${encodeURIComponent(projectId)}/storyboard/continue`, { method: "POST" });
      if (!response.ok) throw new Error(await errorMessage(response));
      onSaved();
    } catch (caught) { setError(caught instanceof Error ? caught.message : "没有继续，修改已保留"); }
    finally { active.current = false; setBusy(null); }
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
                第 {card.order} 镜 · {durationLabel(card.duration_s)}
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
                  disabled={busy !== null || !localReady}
                  onChange={(event) => {
                    const next = event.target.value;
                    pending.current[card.shot_id] = { value: next, base: pending.current[card.shot_id]?.base ?? acknowledged.current[card.shot_id]?.value ?? card.voiceover };
                    persistPending();
                    setDrafts((current) => ({ ...current, [card.shot_id]: next }));
                    setDirty((current) => ({ ...current, [card.shot_id]: true }));
                  }}
                />
              </label>
              <Button
                type="button"
                variant="secondary"
                className="mt-3 w-full"
                disabled={busy !== null || !localReady || !(dirty[card.shot_id] && value.trim())}
                loading={busy === card.shot_id}
                onClick={() => void save(card.shot_id)}
              >
                {busy === card.shot_id ? "正在保存" : "保存旁白"}
              </Button>
            </article>
          );
        })}
      </div>
      <p role="status" className="mt-3 text-caption text-text-3">{!localReady ? "正在恢复旁白草稿" : Object.values(dirty).some(Boolean) ? "有未保存旁白，继续生成前会先保存全部修改" : "旁白已同步"}</p>
      {error ? (
        <p role="alert" className="mt-3 text-caption text-danger">
          {error}
        </p>
      ) : null}
      <Button
        type="button"
        className="mt-4"
        disabled={busy !== null || !localReady}
        loading={busy === "continue"}
        onClick={() => void continueFilm()}
      >
        {busy === "continue" ? "正在继续" : "继续生成"}
      </Button>
    </section>
  );
}
