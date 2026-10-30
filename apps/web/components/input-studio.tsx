"use client";

import { ImagePlus } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useEffect, useRef, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { apiUrl, errorMessage } from "@/lib/api";
import { INDUSTRIES } from "@/lib/industries";

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
      current.some((item) => item.uri === uri)
        ? current
        : [...current, { id: crypto.randomUUID(), uri }],
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
        const response = await fetch(apiUrl("/v1/uploads"), { method: "POST", body });
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
      const response = await fetch(apiUrl("/v1/projects"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sentence: text,
          attachments: [
            ...uploaded,
            ...links.map((item) => ({ kind: "url", uri: item.uri })),
          ],
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
    <div className="grid items-start gap-8 lg:grid-cols-[minmax(0,40rem)_18rem]">
      <form className="min-w-0" onSubmit={onSubmit}>
        <p className="text-sm text-muted-foreground">企业短视频</p>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight sm:text-4xl">说一句话，做成一条片</h1>
        <p className="mt-3 max-w-xl text-base leading-7 text-muted-foreground">
          画面上的字、Logo、价格和电话由后期叠上去，不会画进画面里。
        </p>

        <div className="mt-8 grid gap-2">
          <Label htmlFor="sentence">一句话</Label>
          <Textarea
            id="sentence"
            name="sentence"
            maxLength={4000}
            value={sentence}
            placeholder="例如：给我们的柱塞泵做个 15 秒宣传片，面向采购，风格稳重"
            onChange={(event) => setSentence(event.target.value)}
          />
          <p className="text-right text-xs text-muted-foreground">{sentence.length}/4000</p>
        </div>

        <div className="mt-2 grid gap-2">
          <Label htmlFor="upload">上传素材</Label>
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
            className={`flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border border-dashed px-4 py-8 text-center ${
              dragging ? "border-primary bg-accent" : "border-border bg-card"
            }`}
          >
            <ImagePlus aria-hidden="true" className="size-6 text-muted-foreground" />
            <span className="text-sm">拖拽图片到这里，或点击选择</span>
            <span className="text-xs text-muted-foreground">PNG、JPG、WEBP、GIF 或 PDF</span>
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
          {files.length > 0 ? (
            <ul className="grid gap-2">
              {files.map((item) => (
                <li key={item.id} className="flex min-w-0 items-center gap-3">
                  {item.preview ? (
                    // User-picked local preview. next/image cannot take a blob URL.
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      src={item.preview}
                      alt=""
                      className="size-12 shrink-0 rounded-md border border-border object-cover"
                    />
                  ) : (
                    <span className="flex size-12 shrink-0 items-center justify-center rounded-md border border-border text-xs">
                      PDF
                    </span>
                  )}
                  <span className="min-w-0 flex-1 truncate text-sm">{item.file.name}</span>
                  <Button type="button" variant="ghost" size="sm" onClick={() => removeFile(item.id)}>
                    移除
                  </Button>
                </li>
              ))}
            </ul>
          ) : null}
        </div>

        <div className="mt-6 grid gap-2">
          <Label htmlFor="source-url">素材链接</Label>
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
            <Button type="button" variant="outline" className="sm:w-28" onClick={addLink}>
              添加链接
            </Button>
          </div>
          {links.length > 0 ? (
            <ul className="flex flex-wrap gap-2">
              {links.map((item) => (
                <li key={item.id}>
                  <Badge className="gap-2">
                    <span className="max-w-full break-all">{item.uri}</span>
                    <button
                      type="button"
                      className="shrink-0 underline"
                      onClick={() => setLinks((current) => current.filter((link) => link.id !== item.id))}
                    >
                      移除
                    </button>
                  </Badge>
                </li>
              ))}
            </ul>
          ) : null}
        </div>

        <fieldset className="mt-8">
          <legend className="text-sm font-medium">行业快捷入口</legend>
          <p className="mt-1 text-sm text-muted-foreground">点一下填入示例，还可以再改。</p>
          <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3">
            {INDUSTRIES.map((item) => (
              <Button
                key={item.id}
                type="button"
                variant={industryId === item.id ? "default" : "outline"}
                aria-pressed={industryId === item.id}
                onClick={() => {
                  setIndustryId(item.id);
                  setSentence(item.sentence);
                  setError(null);
                }}
              >
                {item.label}
              </Button>
            ))}
          </div>
        </fieldset>

        {error ? (
          <p role="alert" className="mt-4 text-sm text-destructive">
            {error}
          </p>
        ) : null}

        <Button type="submit" size="lg" className="mt-6 w-full" disabled={busy}>
          {busy ? "正在提交" : "开始生成"}
        </Button>
        <p className="mt-3 text-center text-sm">
          <Link
            href={
              sentence.trim()
                ? `/concepts?sentence=${encodeURIComponent(sentence.trim())}`
                : "/concepts"
            }
          >
            先看三个方案
          </Link>
        </p>
      </form>

      <Card className="min-w-0 p-5">
        <h2 className="text-sm font-medium">这条片怎么出来</h2>
        <ol className="mt-4 grid gap-4">
          {STEPS.map((step, index) => (
            <li key={step} className="flex gap-3 text-sm leading-6">
              <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-accent text-xs">
                {index + 1}
              </span>
              <span>{step}</span>
            </li>
          ))}
        </ol>
      </Card>
    </div>
  );
}
