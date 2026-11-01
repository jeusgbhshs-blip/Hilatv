"use client";

import { Trash2, Upload } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { apiFetch, errorMessage } from "@/lib/api";

type Kind = "product_image" | "brand_doc" | "music" | "font";

type Asset = {
  asset_id: string;
  kind: Kind;
  filename: string;
  size: number;
};

const TABS: { kind: Kind; label: string; hint: string }[] = [
  { kind: "product_image", label: "产品图", hint: "PNG / JPG / WEBP" },
  { kind: "brand_doc", label: "品牌资料", hint: "PDF / 文档 / 图片" },
  { kind: "music", label: "音乐", hint: "MP3 / WAV / M4A" },
  { kind: "font", label: "字体", hint: "TTF / OTF / WOFF2" },
];

function sizeLabel(size: number): string {
  if (size > 1024 * 1024) return `${(size / 1024 / 1024).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(size / 1024))} KB`;
}

function AssetImage({ assetId, filename }: { assetId: string; filename: string }) {
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    let objectUrl: string | null = null;
    setUrl(null);
    setFailed(false);
    async function preview() {
      try {
        const response = await apiFetch(`/v1/assets/${assetId}/file`, { signal: controller.signal });
        if (!response.ok) throw new Error("预览读取失败");
        const blob = await response.blob();
        if (!blob.type.startsWith("image/") || !blob.size) throw new Error("图片内容无效");
        if (controller.signal.aborted) return;
        objectUrl = URL.createObjectURL(blob);
        setUrl(objectUrl);
      } catch {
        if (!controller.signal.aborted) setFailed(true);
      }
    }
    void preview();
    return () => {
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [assetId, retry]);

  if (url) {
    // eslint-disable-next-line @next/next/no-img-element
    return <img src={url} alt={filename} className="aspect-video w-full rounded-sm bg-stage object-contain" />;
  }
  return (
    <div className="flex aspect-video w-full flex-col items-center justify-center gap-2 rounded-sm bg-stage text-caption text-text-3">
      <span role="status">{failed ? "图片预览没有载入" : "正在载入预览"}</span>
      {failed ? <button type="button" className="min-h-11 rounded-sm px-3 text-text-1 hover:bg-hover" onClick={() => setRetry((value) => value + 1)}>重试预览</button> : null}
    </div>
  );
}

/** 企业素材库：按类型上传、查看、删除。mock 存储在本地，不用真实客户图片。 */
export function AssetsLibrary() {
  const [kind, setKind] = useState<Kind>("product_image");
  const [rows, setRows] = useState<Asset[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const kindRef = useRef(kind);
  const requestRef = useRef(0);

  async function load(next: Kind) {
    if (kindRef.current !== next) return;
    const request = ++requestRef.current;
    setRows(null);
    try {
      const response = await apiFetch(`/v1/assets?kind=${next}`);
      if (!response.ok) throw new Error(await errorMessage(response));
      const body = (await response.json()) as { assets?: Asset[] };
      if (requestRef.current === request) setRows(body.assets ?? []);
    } catch (caught) {
      if (requestRef.current === request) {
        setError(caught instanceof Error ? caught.message : "没有拿到素材");
        setRows([]);
      }
    }
  }

  useEffect(() => {
    kindRef.current = kind;
    setError(null);
    void load(kind);
    return () => { requestRef.current += 1; };
  }, [kind]);

  async function upload(file: File) {
    setBusy(true);
    setError(null);
    try {
      const form = new FormData();
      form.append("file", file, file.name);
      form.append("kind", kind);
      const response = await apiFetch("/v1/assets", { method: "POST", body: form });
      if (!response.ok) throw new Error(await errorMessage(response));
      await load(kind);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "上传没有成功");
    } finally {
      setBusy(false);
    }
  }

  async function remove(assetId: string) {
    try {
      const response = await apiFetch(`/v1/assets/${assetId}`, { method: "DELETE" });
      if (!response.ok) throw new Error(await errorMessage(response));
      await load(kind);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "删除没有成功");
    }
  }

  return (
    <div className="mx-auto w-full max-w-195">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-h1 font-medium tracking-wide">素材库</h1>
          <p className="mt-2 text-small text-text-2">上传一次，项目里可以直接引用。测试环境请勿上传真实客户素材。</p>
        </div>
        <button
          type="button"
          className="inline-flex min-h-11 items-center gap-2 rounded-full border border-border-strong px-4 text-small text-text-1 hover:border-text-3 disabled:cursor-not-allowed disabled:text-text-disabled"
          disabled={busy}
          onClick={() => inputRef.current?.click()}
        >
          <Upload aria-hidden="true" className="size-4" strokeWidth={1.5} />
          {busy ? "正在上传" : `上传${TABS.find((item) => item.kind === kind)?.label}`}
        </button>
        <input
          ref={inputRef}
          type="file"
          className="sr-only"
          aria-label="选择素材文件"
          onChange={(event) => {
            const file = event.target.files?.[0];
            event.target.value = "";
            if (file) void upload(file);
          }}
        />
      </header>

      <div className="mt-6 flex flex-wrap gap-2" role="tablist" aria-label="素材类型">
        {TABS.map((item) => (
          <button
            key={item.kind}
            type="button"
            role="tab"
            aria-selected={kind === item.kind}
            className={
              kind === item.kind
                ? "rounded-full border border-blue px-4 py-2 text-small text-text-1"
                : "rounded-full border border-border px-4 py-2 text-small text-text-2 hover:border-border-strong hover:text-text-1"
            }
            onClick={() => setKind(item.kind)}
          >
            {item.label}
          </button>
        ))}
      </div>

      {error ? <p className="mt-4 text-caption text-danger">{error}</p> : null}

      {rows === null ? (
        <p className="mt-8 text-small text-text-3">正在读取素材</p>
      ) : rows.length === 0 ? (
        <div className="mt-8 rounded-lg border border-border bg-surface p-8 text-center">
          <p className="text-body text-text-1">还没有{TABS.find((item) => item.kind === kind)?.label}</p>
          <p className="mt-2 text-small text-text-3">
            支持 {TABS.find((item) => item.kind === kind)?.hint}，单个不超过 20 MB。
          </p>
        </div>
      ) : (
        <ul className="mt-8 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {rows.map((row) => (
            <li key={row.asset_id} className="rounded-lg border border-border bg-surface p-3">
              {row.kind === "product_image" ? (
                <AssetImage assetId={row.asset_id} filename={row.filename} />
              ) : (
                <div className="flex aspect-video w-full items-center justify-center rounded-sm bg-stage text-caption text-text-3">
                  {TABS.find((item) => item.kind === row.kind)?.label}
                </div>
              )}
              <div className="mt-2 flex items-center justify-between gap-2">
                <p className="min-w-0 flex-1 truncate text-small text-text-1">{row.filename}</p>
                <span className="shrink-0 text-caption text-text-3">{sizeLabel(row.size)}</span>
                <button
                  type="button"
                  aria-label={`删除 ${row.filename}`}
                  className="shrink-0 rounded-sm p-1 text-text-3 hover:bg-hover hover:text-danger"
                  onClick={() => void remove(row.asset_id)}
                >
                  <Trash2 aria-hidden="true" className="size-4" strokeWidth={1.5} />
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
