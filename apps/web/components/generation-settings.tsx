"use client";

import { X } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ASPECT_RATIOS, generationSettings, type AspectRatio, type GenerationSettings } from "@/lib/generation-settings";
import { cn } from "@/lib/utils";

function RatioShape({ ratio }: { ratio: AspectRatio | null }) {
  const [width, height] = ratio ? ratio.split(":").map(Number) : [1, 1];
  const scale = 28 / Math.max(width, height);
  return <svg aria-hidden="true" viewBox="0 0 40 40" className="size-10 shrink-0 text-text-2">
    <rect x={(40 - width * scale) / 2} y={(40 - height * scale) / 2} width={width * scale} height={height * scale} rx="2" fill="none" stroke="currentColor" strokeWidth="1.5" strokeDasharray={ratio ? undefined : "3 3"} />
  </svg>;
}

export function GenerationSettingsPicker({ value, disabled = false, onChange }: {
  value: GenerationSettings; disabled?: boolean; onChange: (next: GenerationSettings) => void;
}) {
  const settings = generationSettings(value);
  const id = useId();
  const dialogRef = useRef<HTMLDialogElement>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const [open, setOpen] = useState<"ratio" | "duration" | null>(null);
  const [custom, setCustom] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open || disabled) return;
    const dialog = dialogRef.current;
    if (!dialog) return;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    dialog.showModal();
    (dialog.querySelector<HTMLInputElement>("input:checked") || dialog.querySelector<HTMLButtonElement>("button"))?.focus();
    return () => {
      if (dialog.open) dialog.close();
      document.body.style.overflow = overflow;
      triggerRef.current?.focus();
    };
  }, [open, disabled]);

  function show(kind: "ratio" | "duration", trigger: HTMLButtonElement) {
    if (disabled) return;
    triggerRef.current = trigger;
    setCustom(settings.duration_s === null ? "" : String(settings.duration_s));
    setError(null);
    setOpen(kind);
  }

  function applyDuration() {
    const seconds = Number(custom);
    if (!/^\d+$/.test(custom) || !Number.isInteger(seconds) || seconds < 5 || seconds > 180) { setError("请输入 5 到 180 之间的整数秒数"); return; }
    onChange({ ...settings, duration_s: seconds }); setError(null);
  }

  function ratioOption(ratio: AspectRatio | null) {
    return <label key={ratio || "auto"} className={cn("flex min-h-16 cursor-pointer items-center gap-2 rounded-sm border px-3 py-2 text-small has-focus-visible:ring-2 has-focus-visible:ring-blue", settings.aspect_ratio === ratio ? "border-blue bg-blue-soft" : "border-border hover:bg-hover")}>
      <input type="radio" name={`${id}-ratio`} value={ratio || "auto"} checked={settings.aspect_ratio === ratio} disabled={disabled} className="accent-text-1" onChange={() => onChange({ ...settings, aspect_ratio: ratio })} />
      <RatioShape ratio={ratio} />
      <span>{ratio || "自动"}</span>
    </label>;
  }

  function durationOption(seconds: number | null) {
    return <label key={seconds || "auto"} className={cn("flex min-h-11 cursor-pointer items-center gap-2 rounded-sm border px-3 py-2 text-small has-focus-visible:ring-2 has-focus-visible:ring-blue", settings.duration_s === seconds ? "border-blue bg-blue-soft" : "border-border hover:bg-hover")}>
      <input type="radio" name={`${id}-duration`} value={seconds === null ? "auto" : String(seconds)} checked={settings.duration_s === seconds} disabled={disabled} className="accent-text-1" onChange={() => { onChange({ ...settings, duration_s: seconds }); setError(null); }} />
      {seconds === null ? "自动" : `${seconds} 秒`}
    </label>;
  }

  return <>
    <button type="button" disabled={disabled} aria-haspopup="dialog" aria-expanded={open === "ratio" && !disabled} aria-controls={`${id}-settings`} onClick={(event) => show("ratio", event.currentTarget)} className="inline-flex min-h-11 items-center rounded-full border border-border px-3 text-caption text-text-2 hover:bg-hover disabled:cursor-not-allowed disabled:text-text-disabled">
      比例 · {settings.aspect_ratio || "自动"}
    </button>
    <button type="button" disabled={disabled} aria-haspopup="dialog" aria-expanded={open === "duration" && !disabled} aria-controls={`${id}-settings`} onClick={(event) => show("duration", event.currentTarget)} className="inline-flex min-h-11 items-center rounded-full border border-border px-3 text-caption text-text-2 hover:bg-hover disabled:cursor-not-allowed disabled:text-text-disabled">
      时长 · {settings.duration_s === null ? "自动" : `${settings.duration_s} 秒`}
    </button>
    {open && !disabled ? <dialog ref={dialogRef} id={`${id}-settings`} aria-modal="true" aria-labelledby={`${id}-title`} aria-describedby={`${id}-hint`} className="fixed inset-4 z-40 m-auto max-h-full w-auto max-w-sm overflow-y-auto rounded-lg border border-border bg-raised p-4 text-text-1 shadow-pop backdrop:bg-overlay" onCancel={(event) => { event.preventDefault(); setOpen(null); }} onClose={() => setOpen(null)} onKeyDown={(event) => {
      // This picker sits inside the composer form. Enter must not start a film.
      if (event.key === "Enter" && event.target instanceof HTMLInputElement) {
        event.preventDefault();
        if (event.target.type === "number" && !event.nativeEvent.isComposing && event.nativeEvent.keyCode !== 229) applyDuration();
      }
    }} onClick={(event) => {
      if (event.target !== event.currentTarget) return;
      const box = event.currentTarget.getBoundingClientRect();
      if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) setOpen(null);
    }}>
      <div className="flex items-center justify-between gap-3">
        <h2 id={`${id}-title`} className="text-h2 font-medium">{open === "ratio" ? "画面比例" : "视频时长"}</h2>
        <Button type="button" variant="ghost" className="size-11 shrink-0 p-0" aria-label="关闭生成设置" onClick={() => setOpen(null)}><X aria-hidden="true" className="size-4" /></Button>
      </div>
      <p id={`${id}-hint`} className="mt-2 text-small text-text-2">选择后自动保存。明确选择会优先于输入文字；自动则由内容决定。</p>
      {open === "ratio" ? <p className="mt-2 text-caption text-text-3">参考图片比例不同时，会保留完整画面并补边适配。</p> : null}
      {open === "ratio" ? <fieldset className="mt-4">
        <legend className="sr-only">画面比例</legend>
        {ratioOption(null)}
        <div className="mt-2 grid grid-cols-2 gap-2">{ASPECT_RATIOS.slice(0, 4).map(ratioOption)}</div>
        <details className="mt-2" open={settings.aspect_ratio !== null && ASPECT_RATIOS.indexOf(settings.aspect_ratio) >= 4 ? true : undefined}>
          <summary className="flex min-h-11 cursor-pointer items-center text-small text-text-2 underline">更多比例</summary>
          <div className="grid grid-cols-2 gap-2">{ASPECT_RATIOS.slice(4).map(ratioOption)}</div>
        </details>
      </fieldset> : <div className="mt-4">
        <fieldset className="grid grid-cols-2 gap-2"><legend className="sr-only">视频时长</legend>
          {[null, 15, 30, 60].map(durationOption)}
          {settings.duration_s !== null && ![15, 30, 60].includes(settings.duration_s) ? durationOption(settings.duration_s) : null}
        </fieldset>
        <label htmlFor={`${id}-custom`} className="mt-4 block text-small text-text-2">自定义时长（5–180 秒）</label>
        <div className="mt-2 flex items-start gap-2">
          <Input id={`${id}-custom`} type="number" inputMode="numeric" min={5} max={180} step={1} value={custom} onChange={(event) => setCustom(event.target.value)} aria-invalid={Boolean(error)} aria-describedby={error ? `${id}-error` : undefined} className="min-h-11 min-w-0 flex-1" />
          <Button type="button" variant="secondary" className="min-h-11 shrink-0" onClick={applyDuration}>应用时长</Button>
        </div>
        {error ? <p id={`${id}-error`} role="alert" className="mt-2 text-small text-danger">{error}</p> : null}
      </div>}
      <Button type="button" variant="secondary" className="mt-4 min-h-11 w-full" onClick={() => setOpen(null)}>完成</Button>
    </dialog> : null}
  </>;
}
