"use client";

import { useEffect, useState } from "react";

import { useTheme } from "@/components/theme/theme-provider";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";
import {
  DEFAULT_SCHEDULE,
  MODE_LABELS,
  readSchedule,
  THEME_LABELS,
  THEME_MODES,
  writeSchedule,
  type ThemeMode,
} from "@/lib/theme";

const HINTS: Record<ThemeMode, string> = {
  auto: "白天浅色，晚上深色，按你设置的时间切换。",
  system: "跟随电脑或手机的深浅色设置。",
  light: "一直用浅色。",
  dark: "一直用深色。",
};

/** P12 外观设置 (DESIGN.md §4, §11). */
export function AppearanceSettings() {
  const { mode, schedule, theme, setPreference } = useTheme();
  const [draftMode, setDraftMode] = useState<ThemeMode>(mode);
  const [light, setLight] = useState(schedule.light);
  const [dark, setDark] = useState(schedule.dark);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setDraftMode(mode);
    setLight(schedule.light);
    setDark(schedule.dark);
  }, [mode, schedule]);

  function save() {
    const next = readSchedule(`${light}-${dark}`);
    if (writeSchedule(next) !== `${light}-${dark}` && draftMode === "auto") {
      setError("浅色和深色的开始时间不能相同");
      setSaved(false);
      return;
    }
    setError(null);
    setPreference(draftMode, next);
    setSaved(true);
  }

  return (
    <div className="mx-auto grid w-full max-w-180 gap-6">
      <div>
        <h1 className="text-h1 font-medium tracking-wide">外观</h1>
        <p className="mt-2 text-body text-text-2">视频舞台、分镜大图和专家画布始终是深色，不随主题变。</p>
      </div>

      <Card className="grid gap-5 p-4 md:p-5">
        <fieldset className="grid gap-3">
          <legend className="text-h3 font-medium">主题</legend>
          <div
            role="radiogroup"
            aria-label="主题"
            className="grid grid-cols-2 gap-1 rounded-sm bg-hover p-0.75 md:grid-cols-4"
          >
            {THEME_MODES.map((item) => {
              const checked = draftMode === item;
              return (
                <label
                  key={item}
                  className={cn(
                    "flex min-h-11 cursor-pointer items-center justify-center rounded-sm text-small md:min-h-8",
                    checked ? "bg-surface font-medium text-text-1 shadow-pop" : "text-text-2",
                  )}
                >
                  <input
                    type="radio"
                    name="theme-mode"
                    value={item}
                    className="sr-only"
                    checked={checked}
                    onChange={() => {
                      setDraftMode(item);
                      setSaved(false);
                    }}
                  />
                  {MODE_LABELS[item]}
                </label>
              );
            })}
          </div>
          <p className="text-small text-text-2">{HINTS[draftMode]}</p>
        </fieldset>

        <fieldset className="grid gap-3" disabled={draftMode !== "auto"}>
          <legend className="text-h3 font-medium">切换时间</legend>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="grid gap-2">
              <Label htmlFor="light-at">浅色开始</Label>
              <Input
                id="light-at"
                type="time"
                className="tabular"
                value={light}
                onChange={(event) => {
                  setLight(event.target.value);
                  setSaved(false);
                }}
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="dark-at">深色开始</Label>
              <Input
                id="dark-at"
                type="time"
                className="tabular"
                value={dark}
                onChange={(event) => {
                  setDark(event.target.value);
                  setSaved(false);
                }}
              />
            </div>
          </div>
          <p className="text-caption text-text-3">
            默认 {DEFAULT_SCHEDULE.light} 浅色、{DEFAULT_SCHEDULE.dark}{" "}
            深色。正在全屏播放、拖动时间轴或打字时，会等你停下再切换。
          </p>
        </fieldset>

        {error ? (
          <p role="alert" className="text-caption text-danger">
            {error}
          </p>
        ) : null}

        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border pt-4">
          <p className="text-small text-text-2" aria-live="polite">
            现在是{THEME_LABELS[theme]}
            {saved ? "，已保存" : ""}
          </p>
          <Button type="button" onClick={save}>
            保存
          </Button>
        </div>
      </Card>
    </div>
  );
}
