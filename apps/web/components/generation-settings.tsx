"use client";

import { Check, ChevronDown, X } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";

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
  const [mounted, setMounted] = useState(false);
  const [custom, setCustom] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { setMounted(true); }, []);

  useEffect(() => {
    if (!mounted || !open || disabled) return;
    const dialog = dialogRef.current;
    if (!dialog) return;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    dialog.showModal();
    (dialog.querySelector<HTMLInputElement>("input:checked")
      || (open === "duration" ? dialog.querySelector<HTMLInputElement>('input[type="number"]') : null)
      || dialog.querySelector<HTMLButtonElement>("button"))?.focus();
    return () => {
      if (dialog.open) dialog.close();
      document.body.style.overflow = overflow;
      triggerRef.current?.focus();
    };
  }, [mounted, open, disabled]);

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
    const selected = settings.aspect_ratio === ratio;
    const [width, height] = ratio ? ratio.split(":").map(Number) : [1, 1];
    const orientation = width === height ? "方形" : width > height ? "横屏" : "竖屏";
    return <label key={ratio || "auto"} className={cn(
      "relative cursor-pointer rounded-md border text-small has-focus-visible:ring-2 has-focus-visible:ring-blue",
      ratio ? "flex min-h-16 items-center gap-2 px-3 py-2 sm:min-h-20 sm:flex-col sm:justify-center sm:gap-0 sm:px-2" : "flex min-h-11 items-center justify-between gap-3 px-3 py-2",
      selected && ratio ? "border-blue bg-surface ring-1 ring-blue" : "border-transparent bg-hover hover:bg-surface",
    )}>
      <input type="radio" name={`${id}-ratio`} value={ratio || "auto"} aria-label={ratio || "自动"} checked={selected} disabled={disabled} className="sr-only" onChange={() => onChange({ ...settings, aspect_ratio: ratio })} />
      {ratio ? <>
        <RatioShape ratio={ratio} />
        <span className="flex flex-col sm:flex-row sm:items-baseline sm:gap-1.5"><span className="tabular font-medium">{ratio}</span><span className="text-caption text-text-3">{orientation}</span></span>
        {selected ? <Check aria-hidden="true" className="absolute top-2 right-2 size-3.5 text-blue-text" /> : null}
      </> : <>
        <span className="flex items-baseline gap-2"><span className="font-medium">自动</span><span className="text-caption text-text-3">按内容决定</span></span>
        {selected ? <Check aria-hidden="true" className="size-4 text-blue-text" /> : null}
      </>}
    </label>;
  }

  function durationOption(seconds: number | null) {
    return <label key={seconds || "auto"} className={cn("tabular flex min-h-11 cursor-pointer items-center justify-center rounded-sm px-2 py-2 text-small has-focus-visible:ring-2 has-focus-visible:ring-blue", settings.duration_s === seconds ? "bg-surface font-medium text-text-1" : "text-text-2 hover:text-text-1")}>
      <input type="radio" name={`${id}-duration`} value={seconds === null ? "auto" : String(seconds)} aria-label={seconds === null ? "自动" : `${seconds} 秒`} checked={settings.duration_s === seconds} disabled={disabled} className="sr-only" onChange={() => { onChange({ ...settings, duration_s: seconds }); setError(null); }} />
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
    {mounted && open && !disabled ? createPortal(<dialog ref={dialogRef} id={`${id}-settings`} aria-modal="true" aria-labelledby={`${id}-title`} aria-describedby={`${id}-hint`} className="fixed inset-4 z-40 m-auto max-h-full w-auto max-w-120 overflow-y-auto rounded-lg border border-border bg-raised p-4 text-text-1 shadow-pop backdrop:bg-overlay sm:p-5" onCancel={(event) => { event.preventDefault(); setOpen(null); }} onClose={() => setOpen(null)} onKeyDown={(event) => {
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
      <div className="flex items-start justify-between gap-3">
        <div><h2 id={`${id}-title`} className="text-h2 font-medium">{open === "ratio" ? "画面比例" : "视频时长"}</h2>
          <p className="mt-1 text-caption text-text-2">{open === "ratio" ? "选择适合内容的画幅" : "设置整条视频的目标时长"}</p>
        </div>
        <Button type="button" variant="ghost" className="size-11 shrink-0 p-0" aria-label="关闭生成设置" onClick={() => setOpen(null)}><X aria-hidden="true" className="size-4" /></Button>
      </div>
      {open === "ratio" ? <fieldset className="mt-3">
        <legend className="sr-only">画面比例</legend>
        {ratioOption(null)}
        <div data-testid="common-ratios" className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4">{ASPECT_RATIOS.slice(0, 4).map(ratioOption)}</div>
        <details className="group mt-2" open={settings.aspect_ratio !== null && ASPECT_RATIOS.indexOf(settings.aspect_ratio) >= 4 ? true : undefined}>
          <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between gap-2 text-small text-text-2">更多比例<ChevronDown aria-hidden="true" className="size-4 transition-transform duration-120 group-open:rotate-180 motion-reduce:transition-none" /></summary>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">{ASPECT_RATIOS.slice(4).map(ratioOption)}</div>
        </details>
      </fieldset> : <div className="mt-3">
        <fieldset className="grid grid-cols-4 gap-1 rounded-md bg-hover p-1"><legend className="sr-only">视频时长</legend>
          {[null, 15, 30, 60].map(durationOption)}
        </fieldset>
        <details className="group mt-2" open={(settings.duration_s !== null && ![15, 30, 60].includes(settings.duration_s)) || error ? true : undefined}>
          <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between gap-2 text-small text-text-2"><span>自定义时长</span><span className="flex items-center gap-2 text-caption text-text-3">{settings.duration_s !== null && ![15, 30, 60].includes(settings.duration_s) ? `${settings.duration_s} 秒` : "5–180 秒"}<ChevronDown aria-hidden="true" className="size-4 transition-transform duration-120 group-open:rotate-180 motion-reduce:transition-none" /></span></summary>
        <label htmlFor={`${id}-custom`} className="mt-4 block text-small text-text-2">自定义时长（5–180 秒）</label>
        <div className="mt-2 flex items-start gap-2">
          <Input id={`${id}-custom`} type="number" inputMode="numeric" min={5} max={180} step={1} value={custom} onChange={(event) => setCustom(event.target.value)} aria-invalid={Boolean(error)} aria-describedby={error ? `${id}-error` : undefined} className="min-h-11 min-w-0 flex-1" />
          <Button type="button" variant="secondary" className="min-h-11 shrink-0 px-3" onClick={applyDuration}>应用时长</Button>
        </div>
        {error ? <p id={`${id}-error`} role="alert" className="mt-2 text-small text-danger">{error}</p> : null}
        </details>
      </div>}
      <p id={`${id}-hint`} className="mt-3 text-caption text-text-3">{open === "ratio" ? "手动选择优先于输入文字；参考图完整保留，必要时补边。" : "手动选择优先于输入文字，自动按内容决定。"}</p>
      <div className="mt-4 flex items-center justify-between gap-3 border-t border-border pt-3">
        <span className="text-caption text-text-3">更改会自动保存</span>
        <Button type="button" variant="secondary" className="min-h-11 px-5" onClick={() => setOpen(null)}>完成</Button>
      </div>
    </dialog>, document.body) : null}
  </>;
}
