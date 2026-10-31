"use client";

import {
  Clapperboard,
  House,
  ImagePlus,
  Link as LinkIcon,
  Palette,
  Scissors,
  ShoppingBag,
  Utensils,
  Waypoints,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useEffect, useRef, useState } from "react";

import { CinematicWash } from "@/components/hilatv/cinematic-wash";
import { CanvasEntry } from "@/components/hilatv/canvas-entry";
import { FlowSteps } from "@/components/hilatv/flow-steps";
import { IndustryShortcut } from "@/components/hilatv/industry-shortcut";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { apiFetch, errorMessage } from "@/lib/api";
import { HOME_ENTRIES, TYPEWRITER_LINES, sentenceFor, type HomeEntry } from "@/lib/home-entries";
import { cn } from "@/lib/utils";

const ICONS: Record<string, LucideIcon> = {
  commerce: ShoppingBag,
  property: House,
  dining: Utensils,
  beauty: Palette,
  "image-video": Clapperboard,
  edit: Scissors,
  expert: Waypoints,
};

const RISE = ["rise-d5", "rise-d6", "rise-d7", "rise-d8", "rise-d9", "rise-d10", "rise-d11"];

/**
 * CreateProject (apps/api) accepts sentence, attachments, skip_storyboard,
 * brand_kit, brand_id, and concept_selection. It rejects any other field.
 * Aspect, duration, and language are not on that schema. brand_id is an id,
 * not the 「自动 / 不套用」 switch, and there is no field for “don’t apply”.
 * Those four chips stay visible but cannot be chosen.
 */
const FROZEN_OPTIONS = ["比例", "时长", "语言", "品牌资料"] as const;

type PickedFile = { id: string; file: File; preview: string | null };
type LinkItem = { id: string; uri: string };

function useTypewriter(paused: boolean) {
  const [line, setLine] = useState<string>(TYPEWRITER_LINES[0]);
  const [alive, setAlive] = useState(false);

  useEffect(() => {
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce || paused) {
      setAlive(false);
      setLine(TYPEWRITER_LINES[0]);
      return;
    }
    setAlive(true);
    let index = 0;
    let count = 0;
    let direction = 1;
    let timer = 0;
    const step = () => {
      const word = TYPEWRITER_LINES[index];
      count += direction;
      setLine(word.slice(0, Math.max(0, count)));
      let wait = direction > 0 ? 110 : 45;
      if (count >= word.length && direction > 0) {
        direction = -1;
        wait = 1800;
      } else if (count <= 0 && direction < 0) {
        direction = 1;
        index = (index + 1) % TYPEWRITER_LINES.length;
        wait = 400;
      }
      timer = window.setTimeout(step, wait);
    };
    timer = window.setTimeout(step, 400);
    return () => window.clearTimeout(timer);
  }, [paused]);

  return { line, alive };
}

function FrozenOption({ label }: { label: string }) {
  return (
    <button
      type="button"
      disabled
      className="inline-flex min-h-11 cursor-not-allowed items-center rounded-full border border-border px-3 text-caption text-text-disabled md:min-h-7"
    >
      {label} · 建设中
    </button>
  );
}

export function HomeStudio() {
  const router = useRouter();
  const filesRef = useRef<PickedFile[]>([]);
  const uploadRef = useRef<HTMLInputElement>(null);
  const [sentence, setSentence] = useState("");
  const [entryId, setEntryId] = useState<string | null>(null);
  const [files, setFiles] = useState<PickedFile[]>([]);
  const [linkDraft, setLinkDraft] = useState("");
  const [links, setLinks] = useState<LinkItem[]>([]);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [skipStoryboard, setSkipStoryboard] = useState(false);
  const typed = sentence.trim().length > 0;
  const placeholder = useTypewriter(typed);
  filesRef.current = files;

  useEffect(() => {
    return () => {
      for (const item of filesRef.current) {
        if (item.preview) URL.revokeObjectURL(item.preview);
      }
    };
  }, []);

  function addFiles(list: File[]) {
    const picked: PickedFile[] = [];
    let rejected = false;
    for (const file of list) {
      const image = file.type.startsWith("image/") || /\.(png|jpe?g|webp|gif)$/i.test(file.name);
      const pdf = file.type === "application/pdf" || /\.pdf$/i.test(file.name);
      if (!image && !pdf) {
        rejected = true;
        continue;
      }
      picked.push({
        id: crypto.randomUUID(),
        file,
        preview: image ? URL.createObjectURL(file) : null,
      });
    }
    if (rejected) setError("只接收图片或 PDF");
    else if (picked.length) setError(null);
    if (picked.length) setFiles((current) => [...current, ...picked]);
  }

  function removeFile(id: string) {
    setFiles((current) => {
      const target = current.find((item) => item.id === id);
      if (target?.preview) URL.revokeObjectURL(target.preview);
      return current.filter((item) => item.id !== id);
    });
  }

  function addLink(uri = linkDraft.trim()) {
    if (!uri) return;
    if (!/^https?:\/\//i.test(uri)) {
      setError("链接需要以 http:// 或 https:// 开头");
      return;
    }
    setError(null);
    setLinks((current) =>
      current.some((item) => item.uri === uri) ? current : [...current, { id: crypto.randomUUID(), uri }],
    );
    setLinkDraft("");
  }

  function applyEntry(entry: HomeEntry) {
    setEntryId(entry.id);
    setError(null);
    if (entry.destination === "compose") {
      setSentence(entry.sentence);
      return;
    }
    const text = sentenceFor(entry, sentence);
    if (!sentence.trim()) setSentence(text);
    void createProject(text, "expert");
  }

  async function createProject(text: string, destination: "progress" | "expert") {
    setBusy(true);
    setError(null);
    try {
      const uploaded: { kind: string; upload_id: string; filename: string }[] = [];
      for (const item of files) {
        const body = new FormData();
        body.append("file", item.file, item.file.name);
        const response = await apiFetch("/v1/uploads", { method: "POST", body });
        if (!response.ok) throw new Error(await errorMessage(response));
        const stored = (await response.json()) as { kind?: string; upload_id?: string; filename?: string };
        if (!stored.upload_id || !stored.kind) throw new Error("上传没有成功");
        uploaded.push({
          kind: stored.kind,
          upload_id: stored.upload_id,
          filename: stored.filename || item.file.name,
        });
      }
      const response = await apiFetch("/v1/projects", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sentence: text,
          attachments: [...uploaded, ...links.map((item) => ({ kind: "url", uri: item.uri }))],
          skip_storyboard: skipStoryboard,
        }),
      });
      if (!response.ok) throw new Error(await errorMessage(response));
      const created = (await response.json()) as { project_id?: string };
      if (!created.project_id) throw new Error("没有拿到项目编号");
      // 首页的「专家画布」模块靠这个编号直接进画布。
      window.localStorage.setItem("hilatv.lastProject", created.project_id);
      const path =
        destination === "expert"
          ? `/projects/${created.project_id}/expert`
          : `/projects/${created.project_id}`;
      router.push(path);
    } catch (caught) {
      setBusy(false);
      setError(caught instanceof Error ? caught.message : "提交没有成功");
    }
  }

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const text = sentence.trim();
    if (!text) {
      setError("先写一句话");
      return;
    }
    void createProject(text, "progress");
  }

  return (
    <div data-theme="dark" className="bg-bg text-text-1">
      <section className="home-stage relative flex flex-col items-center justify-center overflow-hidden px-4 py-8 md:px-6">
        <CinematicWash />
        <div className="home-vignette pointer-events-none absolute inset-0" aria-hidden="true" />
        <div className="relative flex w-full max-w-270 flex-col items-center" data-testid="home-hero">
          <p className="rise rise-d1 text-small tracking-wide text-text-2">一句成片 · AI 视频工作室</p>
          <h1 className="rise rise-d2 mt-4 text-center text-display font-medium tracking-wide">
            一句话，拍出你的成片
          </h1>
          <p className="rise rise-d3 mt-3 text-center text-body text-text-2">
            输入产品或场景，自动完成脚本、分镜、配音与剪辑
          </p>

          <form className="rise rise-d4 mt-8 w-full max-w-195" onSubmit={onSubmit}>
            <div
              className={cn(
                "rounded-xl border bg-raised p-4 md:p-5",
                dragging ? "border-dashed border-blue" : "border-border-strong",
              )}
              onDragOver={(event) => {
                event.preventDefault();
                setDragging(true);
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={(event) => {
                event.preventDefault();
                setDragging(false);
                addFiles(Array.from(event.dataTransfer.files));
              }}
            >
              <Label htmlFor="sentence" className="sr-only">
                一句话
              </Label>
              <div className="relative min-h-16">
                <Textarea
                  id="sentence"
                  name="sentence"
                  maxLength={4000}
                  value={sentence}
                  placeholder=""
                  onChange={(event) => setSentence(event.target.value)}
                  onPaste={(event) => {
                    const pasted = Array.from(event.clipboardData.files);
                    if (pasted.length) {
                      event.preventDefault();
                      addFiles(pasted);
                      return;
                    }
                    const text = event.clipboardData.getData("text").trim();
                    if (/^https?:\/\/\S+$/i.test(text)) {
                      event.preventDefault();
                      addLink(text);
                    }
                  }}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" && !event.shiftKey) {
                      event.preventDefault();
                      event.currentTarget.form?.requestSubmit();
                    }
                  }}
                  className="min-h-16 resize-none border-0 bg-transparent px-0 py-0 text-body-lg shadow-none"
                />
                {typed ? null : (
                  <p className="pointer-events-none absolute top-0 left-0 text-body-lg text-text-3" aria-hidden="true">
                    {placeholder.line}
                    {placeholder.alive ? <span className="type-caret" /> : null}
                  </p>
                )}
              </div>

              {files.length > 0 || links.length > 0 ? (
                <ul className="mt-3 flex flex-wrap gap-2" aria-label="已添加的素材">
                  {files.map((item) => (
                    <li
                      key={item.id}
                      className="flex min-w-0 max-w-full items-center gap-2 rounded-sm border border-border bg-surface py-1 pr-1 pl-1"
                    >
                      {item.preview ? (
                        // Local blob preview. next/image cannot take a blob URL.
                        // eslint-disable-next-line @next/next/no-img-element
                        <img src={item.preview} alt="" className="size-8 shrink-0 rounded-xs object-cover" />
                      ) : (
                        <span className="flex size-8 shrink-0 items-center justify-center rounded-xs bg-hover text-micro text-text-2">
                          PDF
                        </span>
                      )}
                      <span className="min-w-0 truncate text-small">{item.file.name}</span>
                      <Button type="button" variant="ghost" size="sm" onClick={() => removeFile(item.id)}>
                        移除
                      </Button>
                    </li>
                  ))}
                  {links.map((item) => (
                    <li
                      key={item.id}
                      className="flex max-w-full items-center gap-2 rounded-full bg-hover py-1 pr-1 pl-3 text-caption text-text-2"
                    >
                      <LinkIcon aria-hidden="true" className="size-3.5 shrink-0" />
                      <span className="max-w-full break-all">{item.uri}</span>
                      <button
                        type="button"
                        className="min-h-8 shrink-0 rounded-full px-2 text-text-1 underline"
                        onClick={() => setLinks((current) => current.filter((link) => link.id !== item.id))}
                      >
                        移除
                      </button>
                    </li>
                  ))}
                </ul>
              ) : null}

              <div className="mt-3 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
                <div className="flex flex-wrap gap-2" aria-label="生成选项">
                  {FROZEN_OPTIONS.map((label) => (
                    <FrozenOption key={label} label={label} />
                  ))}
                </div>
                <Button
                  type="submit"
                  size="lg"
                  className="btn-sheen w-full rounded-full px-6 sm:w-auto"
                  disabled={busy}
                  loading={busy}
                >
                  {busy ? "正在提交" : "生成"}
                </Button>
              </div>

              <div className="mt-4 grid gap-3 border-t border-border pt-4">
                <fieldset className="flex min-w-0 flex-wrap items-center gap-2">
                  <legend className="sr-only">分镜</legend>
                  <span aria-hidden="true" className="text-caption text-text-3">
                    分镜
                  </span>
                  <div className="flex rounded-sm bg-hover p-1">
                    <label
                      className={cn(
                        "flex min-h-11 cursor-pointer items-center gap-1.5 rounded-sm px-3 text-small md:min-h-8",
                        !skipStoryboard ? "bg-surface text-text-1 shadow-pop" : "text-text-2",
                      )}
                    >
                      <input
                        type="radio"
                        name="storyboard-choice"
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
                        name="storyboard-choice"
                        className="accent-text-1"
                        checked={skipStoryboard}
                        onChange={() => setSkipStoryboard(true)}
                      />
                      直接出片
                    </label>
                  </div>
                </fieldset>

                <div
                  data-testid="dropzone"
                  role="button"
                  tabIndex={0}
                  aria-label="选择图片或 PDF"
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      uploadRef.current?.click();
                    }
                  }}
                  onClick={() => uploadRef.current?.click()}
                  className={cn(
                    "flex min-h-11 cursor-pointer flex-wrap items-center gap-x-3 gap-y-1 rounded-sm border border-dashed px-3 py-2 text-small",
                    dragging ? "border-blue bg-blue-soft" : "border-border-strong hover:bg-hover",
                  )}
                >
                  <ImagePlus aria-hidden="true" className="size-4 text-text-2" />
                  <span>{dragging ? "松开即可上传" : "拖拽图片到这里，或点击选择"}</span>
                  <span className="text-caption text-text-3">PNG、JPG、WEBP、GIF 或 PDF</span>
                </div>
                <Label htmlFor="upload" className="sr-only">
                  上传素材
                </Label>
                <input
                  ref={uploadRef}
                  id="upload"
                  className="sr-only"
                  type="file"
                  accept="image/png,image/jpeg,image/webp,image/gif,application/pdf"
                  multiple
                  onChange={(event) => {
                    addFiles(Array.from(event.target.files ?? []));
                    event.target.value = "";
                  }}
                />

                <div className="grid gap-2">
                  <Label htmlFor="source-url" className="text-caption font-normal text-text-2">
                    素材链接
                  </Label>
                  <div className="flex flex-col gap-2 sm:flex-row">
                    <Input
                      id="source-url"
                      inputMode="url"
                      placeholder="https://"
                      value={linkDraft}
                      onChange={(event) => setLinkDraft(event.target.value)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter") {
                          event.preventDefault();
                          addLink();
                        }
                      }}
                    />
                    <Button type="button" variant="secondary" className="sm:w-28" onClick={() => addLink()}>
                      添加链接
                    </Button>
                  </div>
                </div>
              </div>
            </div>

            {error ? (
              <p role="alert" className="mt-3 text-caption text-danger">
                {error}
              </p>
            ) : null}
            <p className="rise rise-d5 mt-3 text-center text-caption text-text-3">
              按 Enter 生成 · 支持拖入图片和链接
            </p>
            <p className="mt-2 text-center text-caption text-text-3">
              画面上的字、Logo、价格和电话由后期叠上去，不会画进画面里。
            </p>
            <p className="mt-2 text-center text-small">
              <Link
                className="text-blue-text hover:underline"
                href={sentence.trim() ? `/concepts?sentence=${encodeURIComponent(sentence.trim())}` : "/concepts"}
              >
                先看三个方案
              </Link>
            </p>
          </form>

          <div id="expert-entry" className="entry-grid mt-10 w-full max-w-195 gap-3">
            {HOME_ENTRIES.map((item, index) => (
              <div key={item.id} className={cn("rise h-full min-w-0", RISE[index])}>
                <IndustryShortcut
                  id={item.id}
                  label={item.label}
                  hint={item.hint}
                  icon={ICONS[item.id]}
                  variant="tile"
                  pressed={entryId === item.id}
                  onClick={() => applyEntry(item)}
                />
              </div>
            ))}
          </div>
        </div>
      </section>
      <CanvasEntry />
      <FlowSteps />
      <footer className="border-t border-border px-4 py-6 text-center text-caption text-text-3">
        © 2026 HiLatv · 一句成片
      </footer>
    </div>
  );
}
