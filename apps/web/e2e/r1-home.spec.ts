/**
 * R1: home shell.
 * The API is stubbed, so this spec does not spend and does not need a live key.
 * Screenshots land in R1_SHOTS_DIR or /opt/cursor/artifacts/r1-home.
 */
import fs from "node:fs";
import path from "node:path";

import { expect, type Page, test } from "@playwright/test";

const PROJECT = "11111111-1111-4111-8111-111111111111";
const UPLOAD = "a".repeat(32);
const SHOTS = process.env.R1_SHOTS_DIR || "/opt/cursor/artifacts/r1-home";

const PRESETS: Record<string, string> = {
  电商带货: "给这款商品做一条 30 秒带货短视频，口播卖点，价格用后期字幕",
  房产案场: "黑石公寓的奢华样板间，傍晚光线",
  餐饮探店: "重庆火锅沸腾特写，门店探店 30 秒",
  美妆种草: "一瓶香水的高级感广告，夜色，丝绒质感",
  图生视频: "根据上传的产品图生成 30 秒展示视频，镜头缓慢推进，画面不要文字",
  智能剪辑: "把上传的图片和资料剪成一条 30 秒成片，配上口播",
  专家画布: "逐镜查看候选、时长和评分，在专家画布里调整",
};

const PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
  "base64",
);

async function stubApi(page: Page) {
  await page.routeWebSocket(/\/v1\/projects\/.+\/progress/, () => {});
  await page.route(/\/v1\//, async (route) => {
    const url = new URL(route.request().url());
    const pathname = url.pathname;
    const method = route.request().method();
    if (pathname === "/v1/session" && method === "POST") {
      return route.fulfill({
        json: { token: "r1-session", enterprise_id: "ent", member_id: "mem" },
      });
    }
    if (pathname === "/v1/uploads" && method === "POST") {
      return route.fulfill({
        json: { upload_id: UPLOAD, kind: "image", filename: "product.png" },
      });
    }
    if (pathname === "/v1/projects" && method === "POST") {
      return route.fulfill({
        status: 202,
        json: { project_id: PROJECT, workflow_id: "wf", status: "running" },
      });
    }
    if (pathname === `/v1/projects/${PROJECT}` && method === "GET") {
      return route.fulfill({
        json: {
          status: "running",
          phase: "理解需求",
          message: "正在理解你的需求",
          sentence: "stub",
          shots: [],
          events: [],
          attachments: [],
          storyboard: [],
        },
      });
    }
    if (pathname === `/v1/projects/${PROJECT}/canvas`) {
      return route.fulfill({
        json: {
          project_id: PROJECT,
          sentence: PRESETS["专家画布"],
          status: "running",
          budget: { used: 0, limit: 3, remaining: 3 },
          nodes: [],
          edges: [],
          shots: [],
          timeline: { present: false, ai_label: true, duration_s: null, clips: [], overlays: [] },
          master: { ready: false, qa_passed: false, blocked: false, reason: "未评审" },
        },
      });
    }
    return route.fulfill({ status: 404, json: { detail: "未桩" } });
  });
}

async function noOverflow(page: Page) {
  const extra = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(extra).toBeLessThanOrEqual(1);
}

async function shoot(page: Page, name: string) {
  fs.mkdirSync(SHOTS, { recursive: true });
  const file = path.join(SHOTS, `${name}.png`);
  await page.screenshot({ path: file, fullPage: false, animations: "disabled" });
  await test.info().attach(name, { path: file, contentType: "image/png" });
}

test.beforeEach(async ({ page }, info) => {
  test.skip(info.project.name !== "desktop", "R1 sets its own viewport");
  await page.addInitScript(() => {
    window.localStorage.setItem("hilatv-theme", "dark");
  });
});

test("home generate posts the existing project API", async ({ page }) => {
  await stubApi(page);
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "一句话，拍出你的成片" })).toBeVisible();
  await expect(page.getByTestId("credits-pill")).toContainText("积分");
  await expect(page.getByTestId("credits-pill")).toContainText("—");
  await expect(page.getByRole("button", { name: "登录" })).toBeVisible();

  const sentence = "给我们的柱塞泵做个 15 秒宣传片，面向采购，风格稳重";
  await page.getByLabel("一句话").fill(sentence);
  await page.getByLabel("上传素材").setInputFiles({
    name: "product.png",
    mimeType: "image/png",
    buffer: PNG,
  });
  await expect(page.getByText("product.png")).toBeVisible();
  await page.getByLabel("素材链接").fill("https://example.com/pump");
  await page.getByRole("button", { name: "添加链接" }).click();
  await page.getByRole("radio", { name: "直接出片" }).check();
  for (const label of ["比例", "时长", "语言", "品牌资料"]) {
    await expect(page.getByRole("button", { name: `${label} · 建设中` })).toBeDisabled();
  }

  const created = page.waitForRequest(
    (request) => request.method() === "POST" && new URL(request.url()).pathname === "/v1/projects",
  );
  await page.getByRole("button", { name: "生成", exact: true }).click();
  const request = await created;
  const body = request.postDataJSON() as {
    sentence: string;
    skip_storyboard?: boolean;
    attachments: { kind: string; filename?: string; uri?: string; upload_id?: string }[];
    aspect_ratio?: string;
    duration_s?: number;
    language?: string;
    brand_id?: string;
    brand_kit?: unknown;
  };
  expect(body.sentence).toBe(sentence);
  expect(body.skip_storyboard).toBe(true);
  expect(body.aspect_ratio).toBeUndefined();
  expect(body.duration_s).toBeUndefined();
  expect(body.language).toBeUndefined();
  expect(body.brand_id).toBeUndefined();
  expect(body.brand_kit).toBeUndefined();
  expect(body.attachments).toEqual(
    expect.arrayContaining([
      expect.objectContaining({ kind: "image", filename: "product.png", upload_id: UPLOAD }),
      expect.objectContaining({ kind: "url", uri: "https://example.com/pump" }),
    ]),
  );
  await page.waitForURL(new RegExp(`/projects/${PROJECT}$`));
  await expect(page.getByText("补拍")).toHaveCount(0);
});

test("seven entries apply presets and expert opens the expert page", async ({ page }) => {
  await stubApi(page);
  await page.goto("/");
  const box = page.getByLabel("一句话");
  for (const [label, sentence] of Object.entries(PRESETS)) {
    if (label === "专家画布") continue;
    await page.getByRole("button", { name: label }).click();
    await expect(box).toHaveValue(sentence);
  }

  await box.fill("");
  const created = page.waitForRequest(
    (request) => request.method() === "POST" && new URL(request.url()).pathname === "/v1/projects",
  );
  await page.getByRole("button", { name: "专家画布" }).click();
  const request = await created;
  expect((request.postDataJSON() as { sentence: string }).sentence).toBe(PRESETS["专家画布"]);
  await page.waitForURL(new RegExp(`/projects/${PROJECT}/expert$`));
});

test("placeholder routes say 建设中 and the old pages stay linked", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.getByRole("button", { name: "全部导航" }).click();
  const menu = page.getByRole("navigation", { name: "全部导航" });
  await menu.getByRole("link", { name: "项目" }).click();
  await expect(page.getByRole("heading", { name: "项目" })).toBeVisible();
  await expect(page.getByText("建设中")).toBeVisible();
  await expect(page.getByText("示例·")).toHaveCount(0);

  for (const [href, heading] of [
    ["/assets", "素材库"],
    ["/templates", "模板"],
    ["/academy", "学院"],
  ] as const) {
    await page.goto(href);
    await expect(page.getByRole("heading", { name: heading })).toBeVisible();
    await expect(page.getByText("建设中")).toBeVisible();
    await expect(page.getByText("示例·")).toHaveCount(0);
  }

  await page.goto("/brand");
  await expect(page.getByRole("heading", { name: "品牌资料" })).toBeVisible();
  await page.goto("/concepts");
  await expect(page.getByRole("heading", { name: "选一张方案卡" })).toBeVisible();
  await page.goto("/settings/appearance");
  await expect(page.getByRole("heading", { name: "外观" })).toBeVisible();
});

test("390 layout keeps the composer and seven entries on screen", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "一句话，拍出你的成片" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "底部导航" })).toBeVisible();
  await expect(page.getByRole("complementary", { name: "主导航" })).toBeHidden();
  await expect(page.getByRole("button", { name: "生成", exact: true })).toBeVisible();
  await expect(page.getByTestId("credits-pill")).toBeVisible();
  const widths: number[] = [];
  for (const label of Object.keys(PRESETS)) {
    const tile = page.getByRole("button", { name: label });
    await expect(tile).toBeVisible();
    const box = await tile.boundingBox();
    expect(box?.height ?? 0).toBeGreaterThanOrEqual(44);
    widths.push(Math.round(box?.width ?? 0));
  }
  expect(Math.max(...widths) - Math.min(...widths)).toBeLessThanOrEqual(1);
  const composer = await page.locator("form").boundingBox();
  const grid = await page.locator("#expert-entry").boundingBox();
  expect(Math.abs((composer?.x ?? 0) - (grid?.x ?? 0))).toBeLessThanOrEqual(1);
  expect(Math.abs((composer?.width ?? 0) - (grid?.width ?? 0))).toBeLessThanOrEqual(1);
  await noOverflow(page);
  await page.locator("#expert-entry").screenshot({
    path: `${SHOTS}/home-390-entries.png`,
    animations: "disabled",
  });
  await shoot(page, "home-390");
});

test("reduced motion shows the hero at rest", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  const wash = page.getByTestId("cinematic-wash");
  await expect(wash).toHaveAttribute("data-static", "true");
  const motion = await page.getByRole("heading", { name: "一句话，拍出你的成片" }).evaluate((element) => {
    const style = getComputedStyle(element);
    return { opacity: style.opacity, name: style.animationName };
  });
  expect(Number(motion.opacity)).toBe(1);
  expect(motion.name).toBe("none");
  await expect(page.getByTestId("home-flow").locator(".flow-node").first()).toBeVisible();
  const nodeOpacity = await page
    .getByTestId("home-flow")
    .locator(".flow-node")
    .first()
    .evaluate((element) => getComputedStyle(element).opacity);
  expect(Number(nodeOpacity)).toBe(1);
});

test("desktop dark and light home screenshots", async ({ page }) => {
  test.skip(test.info().project.name !== "desktop", "screenshots use the desktop project");
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "一句话，拍出你的成片" })).toBeVisible();
  const desktopWidths: number[] = [];
  for (const label of Object.keys(PRESETS)) {
    const box = await page.getByRole("button", { name: label }).boundingBox();
    desktopWidths.push(Math.round(box?.width ?? 0));
  }
  expect(Math.max(...desktopWidths) - Math.min(...desktopWidths)).toBeLessThanOrEqual(1);
  const composer = await page.locator("form").boundingBox();
  const grid = await page.locator("#expert-entry").boundingBox();
  expect(Math.abs((composer?.x ?? 0) - (grid?.x ?? 0))).toBeLessThanOrEqual(1);
  expect(Math.abs((composer?.width ?? 0) - (grid?.width ?? 0))).toBeLessThanOrEqual(1);
  await page.getByRole("button", { name: "房产案场" }).click();
  await page.locator("#expert-entry").screenshot({
    path: `${SHOTS}/home-desktop-entries.png`,
    animations: "disabled",
  });
  await page.locator("form").screenshot({
    path: `${SHOTS}/home-desktop-options.png`,
    animations: "disabled",
  });
  await shoot(page, "home-desktop-dark");
  await page.getByTestId("home-flow").scrollIntoViewIfNeeded();
  await expect(page.locator(".flow-node.is-lit")).toHaveCount(3);
  await shoot(page, "home-desktop-flow");

  await page.evaluate(() => window.localStorage.setItem("hilatv-theme", "light"));
  await page.addInitScript(() => {
    window.localStorage.setItem("hilatv-theme", "light");
  });
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.evaluate(() => window.scrollTo(0, 0));
  await shoot(page, "home-desktop-light");
});
