/**
 * Theme rules from DESIGN.md chapter 4.
 *
 * Modes: auto (default, by local clock), system (prefers-color-scheme), light, dark.
 * The preference lives in localStorage under THEME_KEY. The two switch times live
 * under SCHEDULE_KEY as "HH:MM-HH:MM" (light starts, dark starts).
 *
 * THEME_SCRIPT is the inline <head> script. It repeats resolveTheme() in plain
 * ES5 so it can run before React and before first paint. lib/theme.test.ts runs
 * the script and resolveTheme() side by side to keep the two in step.
 */

export const THEME_KEY = "hilatv-theme";
export const SCHEDULE_KEY = "hilatv-theme-schedule";

export type ThemeMode = "auto" | "system" | "light" | "dark";
export type Theme = "light" | "dark";

export const THEME_MODES: ThemeMode[] = ["auto", "system", "light", "dark"];

export type ThemeSchedule = {
  /** Local time the light theme starts, "HH:MM". */
  light: string;
  /** Local time the dark theme starts, "HH:MM". */
  dark: string;
};

export const DEFAULT_SCHEDULE: ThemeSchedule = { light: "07:00", dark: "19:00" };

export function readMode(value: string | null | undefined): ThemeMode {
  return value === "system" || value === "light" || value === "dark" ? value : "auto";
}

function minutes(value: string): number | null {
  const match = /^(\d{1,2}):(\d{2})$/.exec(value.trim());
  if (!match) return null;
  const hours = Number(match[1]);
  const mins = Number(match[2]);
  if (hours > 23 || mins > 59) return null;
  return hours * 60 + mins;
}

export function readSchedule(value: string | null | undefined): ThemeSchedule {
  if (!value) return DEFAULT_SCHEDULE;
  const [light, dark] = value.split("-");
  if (!light || !dark) return DEFAULT_SCHEDULE;
  const lightAt = minutes(light);
  const darkAt = minutes(dark);
  if (lightAt === null || darkAt === null || lightAt === darkAt) return DEFAULT_SCHEDULE;
  return { light: light.trim().padStart(5, "0"), dark: dark.trim().padStart(5, "0") };
}

export function writeSchedule(schedule: ThemeSchedule): string {
  return `${schedule.light}-${schedule.dark}`;
}

/** Light between schedule.light (inclusive) and schedule.dark (exclusive), local clock. */
export function themeAt(now: Date, schedule: ThemeSchedule = DEFAULT_SCHEDULE): Theme {
  const lightAt = minutes(schedule.light) ?? 7 * 60;
  const darkAt = minutes(schedule.dark) ?? 19 * 60;
  const current = now.getHours() * 60 + now.getMinutes();
  const light =
    lightAt <= darkAt ? current >= lightAt && current < darkAt : current >= lightAt || current < darkAt;
  return light ? "light" : "dark";
}

export function resolveTheme(
  mode: ThemeMode,
  schedule: ThemeSchedule,
  now: Date,
  prefersDark: boolean,
): Theme {
  if (mode === "light" || mode === "dark") return mode;
  if (mode === "system") return prefersDark ? "dark" : "light";
  return themeAt(now, schedule);
}

export const MODE_LABELS: Record<ThemeMode, string> = {
  auto: "自动",
  system: "跟随系统",
  light: "浅色",
  dark: "深色",
};

export const THEME_LABELS: Record<Theme, string> = {
  light: "浅色",
  dark: "深色",
};

/** Runs in <head> before first paint. Keep in step with resolveTheme(). */
export const THEME_SCRIPT = `(function(){var d=document.documentElement;function m(v){var r=/^(\\d{1,2}):(\\d{2})$/.exec(String(v||"").trim());if(!r)return null;var h=+r[1],n=+r[2];if(h>23||n>59)return null;return h*60+n}try{var s=localStorage.getItem("${THEME_KEY}");var mode=s==="system"||s==="light"||s==="dark"?s:"auto";var t;if(mode==="light"||mode==="dark"){t=mode}else if(mode==="system"){t=window.matchMedia&&window.matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light"}else{var p=String(localStorage.getItem("${SCHEDULE_KEY}")||"").split("-");var a=m(p[0]),b=m(p[1]);if(a===null||b===null||a===b){a=420;b=1140}var now=new Date();var c=now.getHours()*60+now.getMinutes();var l=a<=b?(c>=a&&c<b):(c>=a||c<b);t=l?"light":"dark"}d.setAttribute("data-theme",t);d.style.colorScheme=t}catch(e){d.setAttribute("data-theme","light")}})();`;
