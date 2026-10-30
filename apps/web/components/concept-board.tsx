"use client";

import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { apiUrl, errorMessage } from "@/lib/api";
import { chooseCard, type DirectionCard, rememberedEnterprise } from "@/lib/selection";

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
      const response = await fetch(apiUrl("/v1/concepts"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sentence: text, enterprise_id: rememberedEnterprise() }),
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
      const response = await fetch(apiUrl("/v1/projects"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sentence: sentence.trim(),
          enterprise_id: rememberedEnterprise(),
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
    <div className="min-w-0">
      <p className="text-sm text-muted-foreground">三个方向</p>
      <h1 className="mt-2 text-3xl font-semibold tracking-tight">选一张方案卡</h1>
      <p className="mt-3 max-w-xl text-base leading-7 text-muted-foreground">
        每张卡有封面、标题和一句话创意。也可以让系统选。
      </p>
      {brandApplied ? (
        <p className="mt-3 text-sm">将套用已保存的 Logo、色彩、字体、行动号召和卖点。</p>
      ) : null}

      <form className="mt-8 grid max-w-xl gap-2" onSubmit={onGenerate}>
        <Label htmlFor="concept-sentence">一句话</Label>
        <Textarea
          id="concept-sentence"
          value={sentence}
          maxLength={4000}
          onChange={(event) => setSentence(event.target.value)}
        />
        <Button type="submit" disabled={busy}>
          {busy ? "正在生成方案" : "生成三个方案"}
        </Button>
      </form>

      {error ? (
        <p role="alert" className="mt-4 text-sm text-destructive">
          {error}
        </p>
      ) : null}

      {cards.length > 0 ? (
        <div className="mt-8 grid gap-4">
          <div className="grid gap-4 md:grid-cols-3">
            {cards.map((card) => (
              <Card key={card.direction_id} className="min-w-0 p-4" data-testid="concept-card">
                {card.cover_preview ? (
                  // Cover is a data URL from the mock or stored still. No remote host.
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={card.cover_preview}
                    alt=""
                    className="mb-3 h-28 w-full rounded-md border border-border object-cover"
                  />
                ) : null}
                <h2 className="text-base font-medium">{card.title}</h2>
                <p className="mt-2 text-sm leading-6 text-muted-foreground">{card.idea}</p>
                <p className="mt-3 text-xs text-muted-foreground">
                  {card.duration_s ?? duration} 秒 · {card.aspect_ratio ?? aspect}
                </p>
                <Button
                  type="button"
                  variant={choice?.id === card.direction_id ? "default" : "outline"}
                  className="mt-4 w-full"
                  onClick={() => setPicked(card.direction_id)}
                >
                  选这个
                </Button>
              </Card>
            ))}
          </div>
          <div className="flex flex-col gap-3 sm:flex-row">
            <Button type="button" variant={choice?.auto ? "default" : "outline"} onClick={() => setPicked("你帮我选")}>
              你帮我选
            </Button>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="radio"
                name="concept-storyboard"
                checked={!skipStoryboard}
                onChange={() => setSkipStoryboard(false)}
              />
              先看分镜
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="radio"
                name="concept-storyboard"
                checked={skipStoryboard}
                onChange={() => setSkipStoryboard(true)}
              />
              直接出片
            </label>
            <Button type="button" onClick={startFilm} disabled={busy || !choice}>
              用这个方向开始
            </Button>
          </div>
          {choice ? <p className="text-sm">已选择：{choice.label}</p> : null}
        </div>
      ) : null}
    </div>
  );
}
