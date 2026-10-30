"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";

import {
  DEFAULT_SCHEDULE,
  readMode,
  readSchedule,
  resolveTheme,
  SCHEDULE_KEY,
  THEME_KEY,
  writeSchedule,
  type Theme,
  type ThemeMode,
  type ThemeSchedule,
} from "@/lib/theme";

/** How often auto mode looks at the clock (DESIGN.md §4.2). */
const CHECK_MS = 60_000;
/** Matches --duration-theme in globals.css. */
const TRANSITION_MS = 400;

type ThemeState = {
  mode: ThemeMode;
  schedule: ThemeSchedule;
  theme: Theme;
  setPreference: (mode: ThemeMode, schedule: ThemeSchedule) => void;
};

const ThemeContext = createContext<ThemeState | null>(null);

function prefersDark(): boolean {
  return (
    typeof window !== "undefined" && window.matchMedia?.("(prefers-color-scheme: dark)").matches === true
  );
}

function reducedMotion(): boolean {
  return (
    typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches === true
  );
}

function currentTheme(): Theme {
  if (typeof document === "undefined") return "light";
  return document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light";
}

/** Typing, a full-screen video, or a drag in progress: switch later (DESIGN.md §4.2). */
function busyUser(pointerDown: boolean): boolean {
  if (typeof document === "undefined") return false;
  if (document.fullscreenElement) return true;
  if (pointerDown) return true;
  const active = document.activeElement as HTMLElement | null;
  if (!active) return false;
  if (active.isContentEditable) return true;
  const tag = active.tagName;
  if (tag === "TEXTAREA") return true;
  if (tag === "INPUT") {
    const type = (active as HTMLInputElement).type;
    return !["button", "checkbox", "radio", "submit", "reset", "file", "color"].includes(type);
  }
  return false;
}

function paint(theme: Theme, animate: boolean) {
  const root = document.documentElement;
  if (root.getAttribute("data-theme") === theme) return;
  if (animate && !reducedMotion()) {
    root.classList.add("theme-transition");
    window.setTimeout(() => root.classList.remove("theme-transition"), TRANSITION_MS);
  }
  root.setAttribute("data-theme", theme);
  root.style.colorScheme = theme;
}

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [mode, setMode] = useState<ThemeMode>("auto");
  const [schedule, setSchedule] = useState<ThemeSchedule>(DEFAULT_SCHEDULE);
  const [theme, setTheme] = useState<Theme>("light");
  const [loaded, setLoaded] = useState(false);
  const pointerDown = useRef(false);
  const pending = useRef(false);

  // Read the stored preference once the page is live. The head script already painted it.
  useEffect(() => {
    try {
      setMode(readMode(window.localStorage.getItem(THEME_KEY)));
      setSchedule(readSchedule(window.localStorage.getItem(SCHEDULE_KEY)));
    } catch {
      // Private mode: keep the defaults.
    }
    setTheme(currentTheme());
    setLoaded(true);
  }, []);

  const apply = useCallback(
    (animate: boolean) => {
      const next = resolveTheme(mode, schedule, new Date(), prefersDark());
      if (next === currentTheme()) {
        pending.current = false;
        setTheme(next);
        return;
      }
      if (animate && busyUser(pointerDown.current)) {
        pending.current = true;
        return;
      }
      pending.current = false;
      paint(next, animate);
      setTheme(next);
    },
    [mode, schedule],
  );

  useEffect(() => {
    if (!loaded) return;
    apply(true);
    const timer = window.setInterval(() => apply(true), CHECK_MS);
    const media = window.matchMedia?.("(prefers-color-scheme: dark)");
    const onMedia = () => apply(true);
    media?.addEventListener?.("change", onMedia);

    const retry = () => {
      if (pending.current) window.setTimeout(() => apply(true), 0);
    };
    const onDown = () => {
      pointerDown.current = true;
    };
    const onUp = () => {
      pointerDown.current = false;
      retry();
    };
    const onStorage = (event: StorageEvent) => {
      if (event.key === THEME_KEY) setMode(readMode(event.newValue));
      if (event.key === SCHEDULE_KEY) setSchedule(readSchedule(event.newValue));
    };
    document.addEventListener("pointerdown", onDown, true);
    document.addEventListener("pointerup", onUp, true);
    document.addEventListener("pointercancel", onUp, true);
    document.addEventListener("focusout", retry, true);
    document.addEventListener("fullscreenchange", retry);
    window.addEventListener("storage", onStorage);
    return () => {
      window.clearInterval(timer);
      media?.removeEventListener?.("change", onMedia);
      document.removeEventListener("pointerdown", onDown, true);
      document.removeEventListener("pointerup", onUp, true);
      document.removeEventListener("pointercancel", onUp, true);
      document.removeEventListener("focusout", retry, true);
      document.removeEventListener("fullscreenchange", retry);
      window.removeEventListener("storage", onStorage);
    };
  }, [apply, loaded]);

  const setPreference = useCallback((nextMode: ThemeMode, nextSchedule: ThemeSchedule) => {
    try {
      window.localStorage.setItem(THEME_KEY, nextMode);
      window.localStorage.setItem(SCHEDULE_KEY, writeSchedule(nextSchedule));
    } catch {
      // Storage refused: the choice still holds for this tab.
    }
    setMode(nextMode);
    setSchedule(nextSchedule);
    // A choice the user just made applies now, even while a field has focus.
    const next = resolveTheme(nextMode, nextSchedule, new Date(), prefersDark());
    paint(next, true);
    setTheme(next);
  }, []);

  const value = useMemo(
    () => ({ mode, schedule, theme, setPreference }),
    [mode, schedule, theme, setPreference],
  );
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeState {
  const value = useContext(ThemeContext);
  if (!value) throw new Error("useTheme needs ThemeProvider");
  return value;
}
