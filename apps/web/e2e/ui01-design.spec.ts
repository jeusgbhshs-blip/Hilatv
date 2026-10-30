/**
 * UI-01: DESIGN.md reskin.
 * P1 / P3 / P5 / P6 x light / dark x 1440 / 375 screenshots, the stage that
 * stays dark in the light theme, the time-based theme and the appearance page.
 * The API is stubbed, so this spec needs no backend state, key, or spend.
 * Screenshots go to the test output folder, or to UI01_SHOTS_DIR when set.
 */
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { expect, type Page, test } from "@playwright/test";

const PROJECT = "ui01design";
const SESSION = "ui01-session";
const fixtures = path.join(__dirname, "fixtures");
const frame = (name: string) =>
  `data:image/png;base64,${fs.readFileSync(path.join(fixtures, name)).toString("base64")}`;

/** A 2 s test-pattern clip made with ffmpeg (already required by the acceptance scripts). */
function stageClip(): Buffer {
  const file = path.join(os.tmpdir(), "hilatv-ui01-stage.mp4");
  if (!fs.existsSync(file)) {
    try {
      execFileSync("ffmpeg", [
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc2=size=320x180:rate=10",
        "-t",
        "2",
        "-pix_fmt",
        "yuv420p",
        "-c:v",
        "libx264",
        "-movflags",
        "+faststart",
        file,
      ]);
    } catch {
      return Buffer.from("fake-mp4");
    }
  }
  return fs.readFileSync(file);
}
const MP4 = stageClip();

type Theme = "light" | "dark";
const THEMES: Theme[] = ["light", "dark"];
const WIDTHS = [1440, 375];

const LIGHT_BG = "rgb(245, 245, 247)";
const DARK_BG = "rgb(12, 12, 14)";
const STAGE_DARK = "rgb(0, 0, 0)";

test.describe.configure({ mode: "serial" });

test.beforeEach(async ({}, info) => {
  // Widths are set inside each test. One project is enough.
  test.skip(info.project.name !== "desktop", "UI-01 sets its own viewport widths");
});

async function useTheme(page: Page, mode: string) {
  await page.addInitScript(
    ([themeMode, session]) => {
      window.localStorage.setItem("hilatv-theme", themeMode);
      window.localStorage.setItem("hilatv.session", session);
    },
    [mode, SESSION],
  );
}

async function stubApi(page: Page) {
  await page.routeWebSocket(/\/v1\/projects\/.+\/progress/, () => {
    // Accept and stay quiet: the snapshot below carries the state.
  });
  await page.route("**/v1/concepts", (route) =>
    route.fulfill({
      json: {
        brand_applied: true,
        concept: {
          selection: "你帮我选",
          auto: true,
          duration_s: 30,
          aspect_ratio: "16:9",
          directions: [
            {
              direction_id: "d1",
              title: "产品宣传主结构",
              idea: "开场直给产品，三个卖点逐个落地，结尾留电话。",
              duration_s: 30,
              aspect_ratio: "16:9",
              cover_preview: frame("frame-a.png"),
            },
            {
              direction_id: "d2",
              title: "工厂实力",
              idea: "从车间到出厂检验，用过程说明质量。",
              duration_s: 30,
              aspect_ratio: "16:9",
              cover_preview: frame("frame-b.png"),
            },
            {
              direction_id: "d3",
              title: "客户现场",
              idea: "在客户现场看产品怎么用，最后回到品牌。",
              duration_s: 30,
              aspect_ratio: "16:9",
              cover_preview: frame("frame-c.png"),
            },
          ],
        },
      },
    }),
  );
  await page.route(`**/v1/projects/${PROJECT}/versions`, (route) =>
    route.fulfill({
      json: {
        versions: [
          {
            version_id: "wide",
            aspect_ratio: "16:9",
            language: "zh",
            duration_s: 30,
            width: 1920,
            height: 1080,
            download_path: `/v1/projects/${PROJECT}/versions/wide/download`,
            share_path: null,
          },
        ],
      },
    }),
  );
  await page.route(`**/v1/projects/${PROJECT}/revisions`, (route) =>
    route.fulfill({
      json: { versions: [{ version_id: "r1", index: 1, current: true, quality_pass: true }] },
    }),
  );
  await page.route(`**/v1/projects/${PROJECT}/versions/*/download`, (route) =>
    route.fulfill({ status: 200, contentType: "video/mp4", body: MP4 }),
  );
  await page.route(`**/v1/projects/${PROJECT}/download`, (route) =>
    route.fulfill({ status: 200, contentType: "video/mp4", body: MP4 }),
  );
}

const SHOTS = [
  { shot_id: "S01", order: 1, purpose: "产品亮相" },
  { shot_id: "S02", order: 2, purpose: "工厂实力" },
  { shot_id: "S03", order: 3, purpose: "安装特写" },
  { shot_id: "S04", order: 4, purpose: "出口欧洲" },
];

async function stubProject(page: Page, state: "running" | "paused" | "completed") {
  const events =
    state === "completed"
      ? SHOTS.map((shot, index) => ({
          phase: "成片",
          shot_index: shot.order,
          shot_id: shot.shot_id,
          message: `第 ${shot.order} 镜：已完成`,
          ts: 10 + index,
        }))
      : [
          { phase: "生成中", shot_index: 1, shot_id: "S01", message: "第 1 镜：已完成", ts: 1 },
          { phase: "生成中", shot_index: 2, shot_id: "S02", message: "第 2 镜：正在生成视频", ts: 2 },
          {
            phase: "生成中",
            shot_index: 3,
            shot_id: "S03",
            message: "第 3 镜：画面不合格，已用备选方案",
            ts: 3,
          },
        ];
  const snapshot = {
    status: state,
    phase: state === "paused" ? "看分镜" : state === "completed" ? "成片" : "生成中",
    message: state === "paused" ? "分镜已排好，等你确认" : "第 2 镜：正在生成视频",
    elapsed_s: 96,
    sentence: "给我们的高压球阀做一条 30 秒宣传片，突出耐压 30MPa 和出口欧洲",
    shots: SHOTS,
    events: state === "paused" ? [] : events,
    attachments: [{ kind: "image", filename: "valve.png", uri: "", upload_id: "u1" }],
    storyboard:
      state === "paused"
        ? SHOTS.map((shot, index) => ({
            shot_id: shot.shot_id,
            order: shot.order,
            duration_s: 7,
            purpose: shot.purpose,
            voiceover: "耐压 30MPa，一次装好不渗漏。",
            preview_status: "ready",
            visual_reviewed: index === 0,
            frame_url: `/v1/projects/${PROJECT}/frames/${shot.shot_id}.png`,
          }))
        : [],
  };
  await page.route(`**/v1/projects/${PROJECT}/frames/*`, (route) =>
    route.fulfill({
      status: 200,
      contentType: "image/png",
      body: fs.readFileSync(path.join(fixtures, "frame-b.png")),
    }),
  );
  await page.route(`**/v1/projects/${PROJECT}`, (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return route.fulfill({ json: snapshot });
  });
}

async function settle(page: Page) {
  await page.evaluate(() => document.fonts.ready);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(250);
}

async function expectNoHorizontalOverflow(page: Page) {
  const extra = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(extra).toBeLessThanOrEqual(1);
}

/** DESIGN.md §0.3: at most one blue primary button on screen. */
async function expectOneBlueButton(page: Page) {
  const blue = await page.evaluate(() => {
    const probe = document.createElement("div");
    probe.style.color = "var(--blue)";
    document.body.append(probe);
    const target = getComputedStyle(probe).color;
    probe.remove();
    return [...document.querySelectorAll<HTMLElement>("button, a")].filter((element) => {
      const box = element.getBoundingClientRect();
      if (box.width === 0 || box.height === 0) return false;
      const style = getComputedStyle(element);
      return style.visibility !== "hidden" && style.backgroundColor === target;
    }).length;
  });
  expect(blue).toBeLessThanOrEqual(1);
}

async function shoot(page: Page, name: string) {
  await settle(page);
  const dir = process.env.UI01_SHOTS_DIR || test.info().outputDir;
  fs.mkdirSync(dir, { recursive: true });
  const file = path.join(dir, `${name}.png`);
  await page.screenshot({ path: file, fullPage: true, animations: "disabled" });
  await test.info().attach(name, { path: file, contentType: "image/png" });
}

async function expectTheme(page: Page, theme: Theme) {
  await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
  const background = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  expect(background).toBe(theme === "light" ? LIGHT_BG : DARK_BG);
}

for (const theme of THEMES) {
  for (const width of WIDTHS) {
    const tag = `${theme}-${width}`;

    test(`P1 home ${tag}`, async ({ page }) => {
      await page.setViewportSize({ width, height: width > 400 ? 900 : 812 });
      await useTheme(page, theme);
      await page.goto("/");
      await expectTheme(page, theme);
      await expect(page.getByRole("heading", { name: "说一句话，做成一条片" })).toBeVisible();
      await page.getByRole("button", { name: "制造业" }).click();
      await expectNoHorizontalOverflow(page);
      await expectOneBlueButton(page);
      if (width < 768) {
        await expect(page.getByRole("navigation", { name: "底部导航" })).toBeVisible();
        await expect(page.getByRole("complementary", { name: "主导航" })).toBeHidden();
      } else {
        await expect(page.getByRole("complementary", { name: "主导航" })).toBeVisible();
        await expect(page.getByRole("navigation", { name: "底部导航" })).toBeHidden();
      }
      await shoot(page, `p1-home-${tag}`);
    });

    test(`P3 plans ${tag}`, async ({ page }) => {
      await page.setViewportSize({ width, height: width > 400 ? 900 : 812 });
      await useTheme(page, theme);
      await stubApi(page);
      await page.goto("/concepts?sentence=" + encodeURIComponent("给高压球阀做一条 30 秒宣传片"));
      await expectTheme(page, theme);
      await page.getByRole("button", { name: "生成三个方案" }).click();
      await expect(page.getByTestId("concept-card")).toHaveCount(3);
      await page.getByRole("button", { name: "选这个" }).first().click();
      await expect(page.getByTestId("concept-card").first()).toHaveAttribute("data-selected", "true");
      await expect(page.getByRole("list", { name: "进度", exact: true }).getByText("选方案")).toBeVisible();
      await expectNoHorizontalOverflow(page);
      await expectOneBlueButton(page);
      await shoot(page, `p3-plans-${tag}`);
    });

    test(`P5 progress ${tag}`, async ({ page }) => {
      await page.setViewportSize({ width, height: width > 400 ? 900 : 812 });
      await useTheme(page, theme);
      await stubApi(page);
      await stubProject(page, "running");
      await page.goto(`/projects/${PROJECT}`);
      await expectTheme(page, theme);
      await expect(page.getByTestId("shot-stage")).toHaveCount(4);
      await expect(page.getByRole("list", { name: "进度", exact: true }).getByText("生成中")).toBeVisible();
      await expect(page.getByTestId("shot-list").getByText("已用备选方案", { exact: true })).toBeVisible();
      await expectNoHorizontalOverflow(page);
      await expectOneBlueButton(page);
      await shoot(page, `p5-progress-${tag}`);
    });

    test(`P6 film ${tag}`, async ({ page }) => {
      await page.setViewportSize({ width, height: width > 400 ? 900 : 812 });
      await useTheme(page, theme);
      await stubApi(page);
      await stubProject(page, "completed");
      await page.goto(`/projects/${PROJECT}/film`);
      await expectTheme(page, theme);
      const player = page.getByTestId("film-player");
      await expect(player).toHaveAttribute("src", /^blob:/);
      await expect
        .poll(async () => player.evaluate((element: HTMLVideoElement) => element.readyState))
        .toBeGreaterThanOrEqual(1);
      await page.getByRole("button", { name: /第 3 镜/ }).click();
      await expectNoHorizontalOverflow(page);
      await expectOneBlueButton(page);
      const stage = page.locator('[data-stage="film"]');
      await expect(stage).toHaveAttribute("data-theme", "dark");
      expect(await stage.evaluate((element) => getComputedStyle(element).backgroundColor)).toBe(STAGE_DARK);
      await shoot(page, `p6-film-${tag}`);
    });
  }
}

test("stage areas stay dark when the theme is light", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await useTheme(page, "light");
  await stubApi(page);
  await stubProject(page, "completed");
  await page.goto(`/projects/${PROJECT}/film`);
  await expectTheme(page, "light");
  const film = page.locator('[data-stage="film"]');
  await expect(film).toBeVisible();
  const colours = await film.evaluate((element) => ({
    stage: getComputedStyle(element).backgroundColor,
    text: getComputedStyle(element).color,
    page: getComputedStyle(document.body).backgroundColor,
  }));
  expect(colours.page).toBe(LIGHT_BG);
  expect(colours.stage).toBe(STAGE_DARK);
  // Text inside the stage uses the dark theme's Paper, not the light theme's Ink.
  expect(colours.text).toBe("rgb(245, 245, 247)");

  await page.unrouteAll({ behavior: "ignoreErrors" });
  await stubApi(page);
  await stubProject(page, "paused");
  await page.goto(`/projects/${PROJECT}`);
  await expectTheme(page, "light");
  const board = page.locator('[data-stage="storyboard"]').first();
  await expect(board).toBeVisible();
  expect(await board.evaluate((element) => getComputedStyle(element).backgroundColor)).toBe(STAGE_DARK);
  await shoot(page, "storyboard-light-1440");

  await page.route(`**/v1/projects/${PROJECT}/canvas`, (route) =>
    route.fulfill({
      json: {
        sentence: "高压球阀",
        nodes: [
          { id: "n08_keyframe", label: "关键帧", completed: true, generative: true },
          { id: "n10_video", label: "视频", completed: false, generative: true },
        ],
        edges: [{ source: "n08_keyframe", target: "n10_video" }],
        shots: [],
        budget: { used: 0, limit: 3 },
        timeline: { present: false, ai_label: true, clips: [], overlays: [] },
        master: { blocked: false, reason: "未评审" },
      },
    }),
  );
  await page.goto(`/projects/${PROJECT}/expert`);
  await expectTheme(page, "light");
  const canvas = page.locator('[data-stage="canvas"]');
  await expect(canvas).toBeVisible();
  expect(await canvas.evaluate((element) => getComputedStyle(element).backgroundColor)).toBe(STAGE_DARK);
});

test.describe("time-based theme", () => {
  test.use({ timezoneId: "Asia/Shanghai" });

  test("auto is light at noon and dark at night, before first paint", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.clock.setFixedTime(new Date("2026-10-31T12:00:00+08:00"));
    await page.goto("/");
    await expect(page.locator("head script#hilatv-theme-script")).toHaveCount(1);
    await expectTheme(page, "light");

    await page.clock.setFixedTime(new Date("2026-10-31T21:30:00+08:00"));
    await page.reload();
    await expectTheme(page, "dark");

    await page.clock.setFixedTime(new Date("2026-10-31T06:59:00+08:00"));
    await page.reload();
    await expectTheme(page, "dark");
  });

  test("auto switches at 19:00, colour only, and waits while typing", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.clock.install({ time: new Date("2026-10-31T18:58:30+08:00") });
    await page.goto("/");
    await expectTheme(page, "light");

    // Typing: the 19:00 switch waits.
    await page.getByLabel("一句话").click();
    await page.clock.runFor(120_000);
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");

    // Leave the field: the switch happens, with the colour-only transition class.
    await page.getByRole("heading", { name: "说一句话，做成一条片" }).click();
    await page.clock.runFor(10);
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    await expect(page.locator("html")).toHaveClass(/theme-transition/);
    await page.clock.runFor(500);
    await expect(page.locator("html")).not.toHaveClass(/theme-transition/);
  });
});

test("appearance page saves the choice under hilatv-theme", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await useTheme(page, "light");
  await page.goto("/settings/appearance");
  await expect(page.getByRole("heading", { name: "外观" })).toBeVisible();
  await page.locator('label:has(input[name="theme-mode"][value="dark"])').click();
  await page.getByRole("button", { name: "保存" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  expect(await page.evaluate(() => window.localStorage.getItem("hilatv-theme"))).toBe("dark");
  await expectOneBlueButton(page);
  await shoot(page, "p12-appearance-dark-1440");
});
