"use client";

import { ImagePlus, Link as LinkIcon } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useEffect, useRef, useState } from "react";

import { IndustryShortcut } from "@/components/hilatv/industry-shortcut";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { apiFetch, errorMessage } from "@/lib/api";
import { INDUSTRIES } from "@/lib/industries";
import { cn } from "@/lib/utils";

type PickedFile = {
  id: string;
  file: File;
  preview: string | null;
};

type LinkItem = {
  id: string;
  uri: string;
};

const STEPS = [
  "写下一句话，可以带上产品图和资料链接。",
  "进度按镜头展开，能看见每一镜正在做哪一步。",
  "成片可以播放，也可以下载。改稿以后再接。",
];

export function InputStudio() {
  const router = useRouter();
  const filesRef = useRef<PickedFile[]>([]);
  const uploadRef = useRef<HTMLInputElement>(null);
  const [sentence, setSentence] = useState("");
  const [industryId, setIndustryId] = useState<string | null>(null);
  const [files, setFiles] = useState<PickedFile[]>([]);
  const [linkDraft, setLinkDraft] = useState("");
  const [links, setLinks] = useState<LinkItem[]>([]);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [skipStoryboard, setSkipStoryboard] = useState(false);
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

  function addLink() {
    const uri = linkDraft.trim();
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

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const text = sentence.trim();
    if (!text) {
      setError("先写一句话");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const uploaded: { kind: string; upload_id: string; filename: string }[] = [];
      for (const item of files) {
        const body = new FormData();
        body.append("file", item.file, item.file.name);
        const response = await apiFetch("/v1/uploads", { method: "POST", body });
        if (!response.ok) throw new Error(await errorMessage(response));
        const stored = (await response.json()) as {
          kind?: string;
          upload_id?: string;
          filename?: string;
        };
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
      router.push(`/projects/${created.project_id}`);
    } catch (caught) {
      setBusy(false);
      setError(caught instanceof Error ? caught.message : "提交没有成功");
    }
  }

  return (
    <div className="mx-auto grid w-full max-w-195 gap-8">
      <form className="min-w-0" onSubmit={onSubmit}>
        <p className="text-small text-text-2">企业短视频</p>
        <h1 className="mt-2 text-h1 font-medium tracking-wide md:text-display">说一句话，做成一条片</h1>
        <p className="mt-2 text-body text-text-2">
          画面上的字、Logo、价格和电话由后期叠上去，不会画进画面里。
        </p>

        <div
          className={cn(
            "mt-6 rounded-xl border bg-raised p-4 transition-colors duration-120 md:p-5",
            dragging ? "border-dashed border-blue" : "border-border-strong",
          )}
        >
          <Label htmlFor="sentence" className="sr-only">
            一句话
          </Label>
          <Textarea
            id="sentence"
            name="sentence"
            maxLength={4000}
            value={sentence}
            placeholder="例如：给我们的柱塞泵做个 15 秒宣传片，面向采购，风格稳重"
            onChange={(event) => setSentence(event.target.value)}
            className="min-h-28 resize-none border-0 bg-transparent px-0 py-0 text-body-lg"
          />
          <p className="tabular mt-1 text-right text-caption text-text-3">{sentence.length}/4000</p>

          {files.length > 0 || links.length > 0 ? (
            <ul className="mt-3 flex flex-wrap gap-2" aria-label="已添加的素材">
              {files.map((item) => (
                <li
                  key={item.id}
                  className="flex min-w-0 max-w-full items-center gap-2 rounded-sm border border-border bg-surface py-1 pr-1 pl-1"
                >
                  {item.preview ? (
                    // User-picked local preview. next/image cannot take a blob URL.
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
                <li key={item.id} className="max-w-full">
                  <Badge className="min-h-8 gap-2 pr-1">
                    <LinkIcon aria-hidden="true" className="size-3.5 shrink-0" />
                    <span className="max-w-full break-all">{item.uri}</span>
                    <button
                      type="button"
                      className="flex min-h-8 shrink-0 items-center rounded-full px-2 text-text-1 underline hover:bg-surface"
                      onClick={() => setLinks((current) => current.filter((link) => link.id !== item.id))}
                    >
                      移除
                    </button>
                  </Badge>
                </li>
              ))}
            </ul>
          ) : null}

          <div className="mt-4 grid gap-3">
            <Label htmlFor="upload" className="sr-only">
              上传素材
            </Label>
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
              className={cn(
                "flex min-h-11 cursor-pointer flex-wrap items-center gap-x-3 gap-y-1 rounded-sm border border-dashed px-3 py-2 text-small transition-colors duration-120",
                dragging ? "border-blue bg-blue-soft" : "border-border-strong hover:bg-hover",
              )}
            >
              <ImagePlus aria-hidden="true" className="size-4.5 text-text-2" />
              <span>{dragging ? "松开即可上传" : "拖拽图片到这里，或点击选择"}</span>
              <span className="text-caption text-text-3">PNG、JPG、WEBP、GIF 或 PDF</span>
            </div>
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
                <Button type="button" variant="secondary" className="sm:w-28" onClick={addLink}>
                  添加链接
                </Button>
              </div>
            </div>
          </div>

          <div className="mt-4 flex flex-col gap-3 border-t border-border pt-4 sm:flex-row sm:items-center sm:justify-between">
            <fieldset className="flex min-w-0 items-center gap-2">
              <legend className="sr-only">分镜</legend>
              <span aria-hidden="true" className="text-caption text-text-3">
                分镜
              </span>
              <div className="flex rounded-sm bg-hover p-0.75">
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
            <Button
              type="submit"
              size="lg"
              className="w-full rounded-full px-6 sm:w-auto"
              disabled={busy}
              loading={busy}
            >
              {busy ? "正在提交" : "开始生成"}
            </Button>
          </div>
        </div>

        {error ? (
          <p role="alert" className="mt-3 text-caption text-danger">
            {error}
          </p>
        ) : null}

        <p className="mt-3 text-small">
          <Link
            className="text-blue-text hover:underline"
            href={sentence.trim() ? `/concepts?sentence=${encodeURIComponent(sentence.trim())}` : "/concepts"}
          >
            先看三个方案
          </Link>
        </p>

        <fieldset className="mt-8">
          <legend className="text-h3 font-medium">行业快捷入口</legend>
          <p className="mt-1 text-small text-text-2">点一下填入示例，还可以再改。</p>
          <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
            {INDUSTRIES.map((item) => (
              <IndustryShortcut
                key={item.id}
                id={item.id}
                label={item.label}
                pressed={industryId === item.id}
                onClick={() => {
                  setIndustryId(item.id);
                  setSentence(item.sentence);
                  setError(null);
                }}
              />
            ))}
          </div>
        </fieldset>
      </form>

      <section aria-labelledby="how-it-works">
        <h2 id="how-it-works" className="text-h3 font-medium">
          这条片怎么出来
        </h2>
        <ol className="mt-3 grid gap-2 md:grid-cols-3">
          {STEPS.map((step, index) => (
            <li key={step}>
              <Card className="flex h-full gap-3 p-3 text-small text-text-2 md:p-4">
                <span className="tabular flex size-6 shrink-0 items-center justify-center rounded-full bg-hover text-caption text-text-1">
                  {index + 1}
                </span>
                <span>{step}</span>
              </Card>
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}
