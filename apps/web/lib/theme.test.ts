import assert from "node:assert/strict";
import { describe, it } from "node:test";
import vm from "node:vm";

import {
  DEFAULT_SCHEDULE,
  readMode,
  readSchedule,
  resolveTheme,
  SCHEDULE_KEY,
  THEME_KEY,
  THEME_SCRIPT,
  themeAt,
  type ThemeMode,
} from "./theme.ts";

function at(hours: number, minutes = 0): Date {
  return new Date(2026, 9, 31, hours, minutes, 0);
}

function runScript(store: Record<string, string>, now: Date, prefersDark = false): string | null {
  const attrs: Record<string, string> = {};
  const RealDate = Date;
  class FakeDate extends RealDate {
    constructor() {
      super(now.getTime());
    }
  }
  const context = {
    document: {
      documentElement: {
        setAttribute: (name: string, value: string) => {
          attrs[name] = value;
        },
        style: {} as Record<string, string>,
      },
    },
    localStorage: { getItem: (key: string) => (key in store ? store[key] : null) },
    window: { matchMedia: () => ({ matches: prefersDark }) },
    Date: FakeDate,
    String,
  };
  vm.runInNewContext(THEME_SCRIPT, context);
  return attrs["data-theme"] ?? null;
}

describe("theme by local time", () => {
  it("is light from 07:00 to 18:59 and dark otherwise", () => {
    assert.equal(themeAt(at(6, 59)), "dark");
    assert.equal(themeAt(at(7, 0)), "light");
    assert.equal(themeAt(at(12, 30)), "light");
    assert.equal(themeAt(at(18, 59)), "light");
    assert.equal(themeAt(at(19, 0)), "dark");
    assert.equal(themeAt(at(23, 59)), "dark");
    assert.equal(themeAt(at(0, 0)), "dark");
  });

  it("follows a custom schedule, including one that wraps midnight", () => {
    assert.equal(themeAt(at(8, 0), { light: "09:00", dark: "17:30" }), "dark");
    assert.equal(themeAt(at(17, 29), { light: "09:00", dark: "17:30" }), "light");
    assert.equal(themeAt(at(23, 0), { light: "22:00", dark: "06:00" }), "light");
    assert.equal(themeAt(at(12, 0), { light: "22:00", dark: "06:00" }), "dark");
  });

  it("reads bad stored values as the defaults", () => {
    assert.equal(readMode(null), "auto");
    assert.equal(readMode("purple"), "auto");
    assert.equal(readMode("dark"), "dark");
    assert.deepEqual(readSchedule("nonsense"), DEFAULT_SCHEDULE);
    assert.deepEqual(readSchedule("07:00-07:00"), DEFAULT_SCHEDULE);
    assert.deepEqual(readSchedule("8:00-20:00"), { light: "08:00", dark: "20:00" });
  });

  it("fixed and system modes ignore the clock", () => {
    assert.equal(resolveTheme("light", DEFAULT_SCHEDULE, at(23), true), "light");
    assert.equal(resolveTheme("dark", DEFAULT_SCHEDULE, at(12), false), "dark");
    assert.equal(resolveTheme("system", DEFAULT_SCHEDULE, at(12), true), "dark");
    assert.equal(resolveTheme("system", DEFAULT_SCHEDULE, at(23), false), "light");
  });
});

describe("head script", () => {
  it("matches resolveTheme for every mode across the day", () => {
    const modes: (ThemeMode | null)[] = [null, "auto", "system", "light", "dark"];
    const schedules = [null, "09:00-17:30", "22:00-06:00"];
    for (const mode of modes) {
      for (const schedule of schedules) {
        for (const prefersDark of [false, true]) {
          for (let hour = 0; hour < 24; hour += 1) {
            for (const minute of [0, 59]) {
              const store: Record<string, string> = {};
              if (mode) store[THEME_KEY] = mode;
              if (schedule) store[SCHEDULE_KEY] = schedule;
              const now = at(hour, minute);
              const expected = resolveTheme(readMode(mode), readSchedule(schedule), now, prefersDark);
              assert.equal(
                runScript(store, now, prefersDark),
                expected,
                `${mode} ${schedule} ${prefersDark} ${hour}:${minute}`,
              );
            }
          }
        }
      }
    }
  });
});
