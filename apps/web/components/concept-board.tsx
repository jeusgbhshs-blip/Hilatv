"use client";

import { Check } from "lucide-react";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { useShellStage } from "@/components/hilatv/shell-stage";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { apiFetch, errorMessage } from "@/lib/api";
import { chooseCard, type DirectionCard } from "@/lib/selection";
import { cn } from "@/lib/utils";

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

export function ConceptBoard({ initialSentence }: { initialSentence: string }) {
  const router = useRouter();
  const [sentence, setSentence] = useState(initialSentence);
  const [cards, setCards] = useState<DirectionCard[]>([]);
  const [duration, setDuration] = useState<number | null>(null);
  const [aspect, setAspect] = useState("");
  const [picked, setPicked] = useState<string | null>(null);
  const [brandApplied, setBrandApplied] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [skipStoryboard, setSkipStoryboard] = useState(false);

  const choice = cards.length ? chooseCard(cards, picked) : null;
  useShellStage("选方案");

  async function onGenerate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const text = sentence.trim();
    if (!text) {
      setError("先写一句话");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const response = await apiFetch("/v1/concepts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sentence: text }),
      });
      if (!response.ok) throw new Error(await errorMessage(response));
      const body = (await response.json()) as ConceptResponse;
      setCards(body.concept.directions);
      setDuration(body.concept.duration_s);
      setAspect(body.concept.aspect_ratio);
      setBrandApplied(body.brand_applied === true);
      setPicked("你帮我选");
    } catch (caught) {
      setCards([]);
      setError(caught instanceof Error ? caught.message : "方案没有生成");
    } finally {
      setBusy(false);
    }
  }

  async function startFilm() {
    if (!choice) return;
    setBusy(true);
    setError(null);
    try {
      const response = await apiFetch("/v1/projects", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sentence: sentence.trim(),
          concept_selection: choice.id,
          skip_storyboard: skipStoryboard,
        }),
      });
      if (!response.ok) throw new Error(await errorMessage(response));
      const created = (await response.json()) as { project_id?: string };
      if (!created.project_id) throw new Error("没有拿到项目编号");
      router.push(`/projects/${created.project_id}`);
    } catch (caught) {
      setBusy(false);
      setError(caught instanceof Error ? caught.message : "提交没有成功");
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
          onChange={(event) => setSentence(event.target.value)}
        />
        <div>
          <Button
            type="submit"
            variant={cards.length > 0 ? "secondary" : "primary"}
            disabled={busy}
            loading={busy && cards.length === 0}
          >
            {busy ? "正在生成方案" : cards.length > 0 ? "重新出方案" : "生成三个方案"}
          </Button>
        </div>
      </form>

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
              aria-pressed={Boolean(choice?.auto)}
              className={cn(choice?.auto && "border-blue text-blue-text")}
              onClick={() => setPicked("你帮我选")}
            >
              你帮我选
            </Button>
            <fieldset className="flex items-center gap-1 rounded-sm bg-hover p-0.75">
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
            <Button type="button" onClick={startFilm} disabled={busy || !choice} loading={busy}>
              用这个方向开始
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
