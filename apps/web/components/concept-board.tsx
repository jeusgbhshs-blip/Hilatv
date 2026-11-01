"use client";

import { Check } from "lucide-react";
import { useRouter } from "next/navigation";
import { type FormEvent, useEffect, useRef, useState } from "react";

import { useShellStage } from "@/components/hilatv/shell-stage";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { ProjectDraftRecovery } from "@/components/project-draft-recovery";
import { GenerationSettingsPicker } from "@/components/generation-settings";
import { useProjectDraft } from "@/lib/use-project-draft";
import { apiFetch, errorMessage } from "@/lib/api";
import { chooseCard, type DirectionCard } from "@/lib/selection";
import { cn } from "@/lib/utils";
import { conceptInputKey } from "@/lib/generation-settings";
import { currentConceptCards } from "@/lib/project-draft";

type ConceptResponse = {
  brand_applied?: boolean;
  concept: {
    selection: string;
    auto: boolean;
    duration_s: number;
    aspect_ratio: string;
    directions: DirectionCard[];
  };
};

export function ConceptBoard({ initialSentence, initialProjectId }: { initialSentence: string; initialProjectId?: string }) {
  const router = useRouter();
  const drafts = useProjectDraft(initialSentence, initialProjectId);
  const { sentence, skip_storyboard: skipStoryboard } = drafts.draft;
  const cards = currentConceptCards(drafts.draft);
  const duration = cards[0]?.duration_s ?? null;
  const aspect = cards[0]?.aspect_ratio ?? "";
  const picked = drafts.draft.concept_selection;
  const brandApplied = drafts.draft.brand_applied === true;
  const setSentence = (value: string) => drafts.field("sentence", value);
  const setPicked = (value: string) => drafts.field("concept_selection", value);
  const setSkipStoryboard = (value: boolean) => drafts.field("skip_storyboard", value);
  const submitting = useRef(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { submitting.current = false; setBusy(false); setError(null); }, [drafts.identity]);

  const choice = cards.length ? chooseCard(cards, picked) : null;
  useShellStage("选方案");

  async function onGenerate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting.current || !drafts.editable || drafts.conflict) return;
    const current = drafts.ticket();
    const text = sentence.trim();
    if (!text) {
      setError("先写一句话");
      return;
    }
    submitting.current = true;
    setBusy(true);
    setError(null);
    try {
      const saved = await drafts.flush();
      if (!current()) return;
      const response = await apiFetch("/v1/concepts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sentence: text, project_id: saved.project_id, draft_revision: saved.draft_revision }),
      });
      if (!current()) return;
      if (!response.ok) throw new Error(await errorMessage(response));
      const body = (await response.json()) as ConceptResponse;
      if (!current()) return;
      if (!Array.isArray(body.concept?.directions) || body.concept.directions.length === 0) throw new Error("没有拿到有效方案，请重试");
      drafts.update({
        cards: body.concept.directions.map((card) => ({ ...card, duration_s: card.duration_s ?? body.concept.duration_s, aspect_ratio: card.aspect_ratio ?? body.concept.aspect_ratio })),
        cards_sentence: text, cards_input_key: conceptInputKey(saved.sentence, saved.generation_settings), brand_applied: body.brand_applied === true, concept_selection: "你帮我选",
      });
    } catch (caught) {
      if (current()) setError(caught instanceof Error ? caught.message : "方案没有生成");
    } finally {
      if (current()) { submitting.current = false; setBusy(false); }
    }
  }

  async function startFilm() {
    if (!choice || submitting.current || !drafts.ready || drafts.conflict || drafts.resolving) return;
    const current = drafts.ticket();
    submitting.current = true;
    setBusy(true);
    setError(null);
    try {
      drafts.update({ concept_selection: choice.id });
      const saved = await drafts.flush();
      if (!current()) return;
      if (!saved.project_id) throw new Error("草稿尚未确认保存，请重试");
      const submitted = await drafts.stageSubmission();
      if (!current()) return;
      const response = await apiFetch(`/v1/projects/${encodeURIComponent(submitted.project_id!)}/film/start`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ operation_id: submitted.start_operation_id, draft_revision: submitted.draft_revision }),
      });
      if (!current()) return;
      if (!response.ok) throw new Error(await errorMessage(response));
      const result = await response.json() as { submission_state?: string };
      if (!current()) return;
      if (result.submission_state !== "submitted") throw new Error("这次提交还在确认中，输入已保留。稍后重试会查询同一次提交。");
      await drafts.confirmSubmission(submitted);
      if (!current()) return;
      router.push(`/projects/${encodeURIComponent(saved.project_id)}`);
    } catch (caught) {
      if (current()) setError(caught instanceof Error ? caught.message : "提交没有成功");
    } finally {
      if (current()) { submitting.current = false; setBusy(false); }
    }
  }

  return (
    <div className="mx-auto w-full min-w-0 max-w-300">
      <p className="text-small text-text-2">三个方向</p>
      <h1 className="mt-2 text-h1 font-medium tracking-wide">选一张方案卡</h1>
      <p className="mt-2 max-w-xl text-body text-text-2">每张卡有封面、标题和一句话创意。也可以让系统选。</p>
      {brandApplied ? (
        <p className="mt-3">
          <Badge tone="blue">品牌资料 · 已套用</Badge>
          <span className="ml-2 text-small text-text-2">
            将套用已保存的 Logo、色彩、字体、行动号召和卖点。
          </span>
        </p>
      ) : null}

      <form className="mt-6 grid max-w-195 gap-2" onSubmit={onGenerate}>
        <Label htmlFor="concept-sentence">一句话</Label>
        <Textarea
          id="concept-sentence"
          value={sentence}
          maxLength={4000}
          className="min-h-24"
          disabled={busy || !drafts.editable}
          onChange={(event) => setSentence(event.target.value)}
        />
        <div className="flex flex-wrap gap-2" aria-label="生成选项">
          <GenerationSettingsPicker value={drafts.draft.generation_settings} disabled={busy || !drafts.editable || Boolean(drafts.conflict)} onChange={(value) => drafts.field("generation_settings", value)} />
        </div>
        <p className="text-caption text-text-3">比例和时长选择优先于输入文字；更改后需重新生成方案。</p>
        <div>
          <Button
            type="submit"
            variant={cards.length > 0 ? "secondary" : "primary"}
            disabled={busy || !drafts.editable || Boolean(drafts.conflict)}
            loading={busy && cards.length === 0}
          >
            {busy ? "正在生成方案" : cards.length > 0 ? "重新出方案" : "生成三个方案"}
          </Button>
        </div>
      </form>

      <p role="status" className="mt-3 text-caption text-text-3">{!drafts.ready ? drafts.error ? "草稿尚未恢复，请重试" : "正在恢复草稿" : drafts.draft.submission_pending ? "提交确认中，请保留此页面" : drafts.conflict ? "请核对两个草稿版本" : drafts.saving ? "正在保存草稿" : drafts.dirty ? "草稿未同步，请等待保存确认" : drafts.draft.project_id ? "草稿已保存" : "输入后自动保存"}</p>
      <ProjectDraftRecovery drafts={drafts} busy={busy} />
      {error ? (
        <p role="alert" className="mt-4 text-caption text-danger">
          {error}
        </p>
      ) : null}

      {busy && cards.length === 0 ? (
        <div className="mt-8 grid gap-4 md:grid-cols-3" aria-hidden="true">
          {[0, 1, 2].map((item) => (
            <Card key={item} className="p-3">
              <div className="aspect-video w-full animate-pulse rounded-sm bg-hover" />
              <div className="mt-3 h-4 w-2/3 animate-pulse rounded-xs bg-hover" />
              <div className="mt-2 h-3 w-full animate-pulse rounded-xs bg-hover" />
            </Card>
          ))}
        </div>
      ) : null}

      {cards.length > 0 ? (
        <div className="mt-8 grid gap-4">
          <div className="grid gap-4 md:grid-cols-3">
            {cards.map((card) => {
              const selected = choice?.id === card.direction_id;
              return (
                <Card
                  key={card.direction_id}
                  selected={selected}
                  className="flex min-w-0 flex-col p-3"
                  data-testid="concept-card"
                >
                  <div
                    data-theme="dark"
                    className="relative aspect-video w-full overflow-hidden rounded-sm bg-stage"
                  >
                    {card.cover_preview ? (
                      // Cover is a data URL from the mock or stored still. No remote host.
                      // eslint-disable-next-line @next/next/no-img-element
                      <img src={card.cover_preview} alt="" className="h-full w-full object-contain" />
                    ) : null}
                  </div>
                  <h2 className="mt-3 text-h3 font-medium">{card.title}</h2>
                  <p className="mt-1 flex-1 text-small text-text-2">{card.idea}</p>
                  <div className="mt-3 flex flex-wrap gap-1.5">
                    <Badge className="tabular">{card.duration_s ?? duration} 秒</Badge>
                    <Badge className="tabular">{card.aspect_ratio ?? aspect}</Badge>
                  </div>
                  <Button
                    type="button"
                    variant="secondary"
                    disabled={busy || !drafts.editable}
                    aria-pressed={selected}
                    className={cn("mt-3 w-full", selected && "border-blue text-blue-text")}
                    onClick={() => setPicked(card.direction_id)}
                  >
                    {selected ? <Check aria-hidden="true" className="size-4" /> : null}
                    选这个
                  </Button>
                </Card>
              );
            })}
          </div>
          <div className="flex flex-col gap-3 rounded-md border border-border bg-surface p-3 sm:flex-row sm:flex-wrap sm:items-center">
            <Button
              type="button"
              variant="secondary"
              disabled={busy || !drafts.editable}
              aria-pressed={Boolean(choice?.auto)}
              className={cn(choice?.auto && "border-blue text-blue-text")}
              onClick={() => setPicked("你帮我选")}
            >
              你帮我选
            </Button>
            <fieldset disabled={busy || !drafts.editable} className="flex items-center gap-1 rounded-sm bg-hover p-0.75">
              <legend className="sr-only">分镜</legend>
              <label
                className={cn(
                  "flex min-h-11 cursor-pointer items-center gap-1.5 rounded-sm px-3 text-small md:min-h-8",
                  !skipStoryboard ? "bg-surface text-text-1 shadow-pop" : "text-text-2",
                )}
              >
                <input
                  type="radio"
                  name="concept-storyboard"
                  className="accent-text-1"
                  checked={!skipStoryboard}
                  onChange={() => setSkipStoryboard(false)}
                />
                先看分镜
              </label>
              <label
                className={cn(
                  "flex min-h-11 cursor-pointer items-center gap-1.5 rounded-sm px-3 text-small md:min-h-8",
                  skipStoryboard ? "bg-surface text-text-1 shadow-pop" : "text-text-2",
                )}
              >
                <input
                  type="radio"
                  name="concept-storyboard"
                  className="accent-text-1"
                  checked={skipStoryboard}
                  onChange={() => setSkipStoryboard(true)}
                />
                直接出片
              </label>
            </fieldset>
            {choice ? (
              <p className="text-small text-text-2 sm:flex-1">已选择：{choice.label}</p>
            ) : (
              <span className="sm:flex-1" />
            )}
            <Button type="button" onClick={startFilm} disabled={busy || !choice || !drafts.ready || Boolean(drafts.conflict) || drafts.resolving || drafts.draft.started || Boolean(drafts.draft.submission_pending && !drafts.draft.start_operation_id)} loading={busy}>
              用这个方向开始
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
