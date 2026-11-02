import { expect, type Page, test } from "@playwright/test";

const PROJECT = "settingsdemo";
type Settings = { aspect_ratio: string | null; duration_s: number | null };

async function stubDraft(page: Page, theme: string) {
  await page.addInitScript((mode) => { localStorage.setItem("hilatv.session", "settings-test-session"); localStorage.setItem("hilatv-theme", mode); }, theme);
  let draft: Record<string, unknown> = { project_id: PROJECT, status: "draft", draft_revision: 1, sentence: "", attachments: [], generation_settings: { aspect_ratio: null, duration_s: null } };
  const filmStarts: unknown[] = [];
  const conceptRequests: Record<string, unknown>[] = [];
  await page.route("**/v1/**", async (route) => {
    const request = route.request(); const path = new URL(request.url()).pathname;
    if (path === "/v1/projects/drafts") {
      draft = { ...draft, ...request.postDataJSON(), project_id: PROJECT, draft_revision: 1 };
      return route.fulfill({ status: 201, json: { project_id: PROJECT, draft_revision: 1, snapshot: draft } });
    }
    if (path === `/v1/projects/${PROJECT}/draft`) {
      const next = request.postDataJSON();
      if (next.draft_revision !== draft.draft_revision) return route.fulfill({ status: 409, json: { detail: { code: "draft_conflict", snapshot: draft } } });
      if (JSON.stringify(next.generation_settings) !== JSON.stringify(draft.generation_settings)) {
        delete draft.concept_preview; delete draft.concept_preview_sentence; delete draft.concept_preview_generation_settings;
      }
      draft = { ...draft, ...next, draft_revision: Number(draft.draft_revision) + 1 };
      return route.fulfill({ json: { project_id: PROJECT, draft_revision: draft.draft_revision, snapshot: draft } });
    }
    if (path === `/v1/projects/${PROJECT}`) return route.fulfill({ json: draft });
    if (path === "/v1/concepts") {
      conceptRequests.push(request.postDataJSON());
      const settings = draft.generation_settings as Settings;
      const concept = { selection: "你帮我选", auto: true, aspect_ratio: settings.aspect_ratio || "16:9", duration_s: settings.duration_s || 15,
        directions: [1, 2, 3].map((index) => ({ direction_id: `d${index}`, title: `方向${index}`, idea: "产品宣传", aspect_ratio: settings.aspect_ratio || "16:9", duration_s: settings.duration_s || 15 })) };
      draft = { ...draft, concept_preview: concept, concept_preview_sentence: draft.sentence, concept_preview_generation_settings: { ...settings } };
      return route.fulfill({ json: { concept, generation_settings: settings } });
    }
    if (path.endsWith("/film/start")) { filmStarts.push(request.postDataJSON()); return route.fulfill({ status: 500, json: { detail: "This test must not submit a film" } }); }
    return route.fulfill({ status: 404, json: { detail: "No fixture for this request" } });
  });
  return { filmStarts, conceptRequests };
}

for (const theme of ["light", "dark"]) {
  test(`settings survive navigation and invalidate stale plans, ${theme}`, async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    const fixture = await stubDraft(page, theme);
    await page.goto("/");
    const ratio = page.getByRole("button", { name: "比例 · 自动", exact: true });
    await expect(ratio).toBeEnabled(); await ratio.click();
    const ratioDialog = page.getByRole("dialog", { name: "画面比例" });
    // The creator retains its local dark stage; settings follow app appearance.
    expect(await ratioDialog.evaluate((dialog) => dialog.parentElement === document.body)).toBe(true);
    expect(await ratioDialog.evaluate((dialog) => getComputedStyle(dialog).backgroundColor)).toBe(theme === "light" ? "rgb(255, 255, 255)" : "rgb(28, 28, 33)");
    await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
    expect(await page.getByTestId("home-hero").evaluate((hero) => hero.closest('[data-theme="dark"]') !== null)).toBe(true);
    await expect(ratioDialog.getByRole("radio", { name: "自动", exact: true })).toBeFocused();
    await page.keyboard.press("ArrowRight");
    await expect(ratioDialog.getByRole("radio", { name: "16:9", exact: true })).toBeChecked();
    await ratioDialog.getByRole("radio", { name: "9:16", exact: true }).check();
    await expect(ratioDialog.getByRole("radio", { name: "4:3", exact: true })).toBeVisible();
    expect(await ratioDialog.getByTestId("common-ratios").evaluate((grid) => getComputedStyle(grid).gridTemplateColumns.split(" ").length)).toBe(2);
    const touch = await ratioDialog.getByRole("radio", { name: "9:16", exact: true }).evaluate((input) => input.closest("label")!.getBoundingClientRect().toJSON());
    expect(touch.width).toBeGreaterThanOrEqual(44); expect(touch.height).toBeGreaterThanOrEqual(44);
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await expect(page.getByRole("button", { name: "比例 · 9:16", exact: true })).toBeFocused();
    await page.getByRole("button", { name: "时长 · 自动", exact: true }).click();
    await page.getByRole("radio", { name: "30 秒", exact: true }).check();
    await page.keyboard.press("Escape");
    await page.getByLabel("一句话", { exact: true }).fill("给产品做一条15秒横屏宣传片");
    await expect(page.getByText("草稿已保存", { exact: true })).toBeVisible();
    await page.reload();
    await expect(page.getByRole("button", { name: "比例 · 9:16", exact: true })).toBeEnabled();
    await expect(page.getByRole("button", { name: "时长 · 30 秒", exact: true })).toBeVisible();
    await page.getByRole("button", { name: "先看三个方案", exact: true }).click();
    await page.waitForURL(/\/concepts\?project=/);
    await page.getByRole("button", { name: "生成三个方案", exact: true }).click();
    await expect(page.getByTestId("concept-card")).toHaveCount(3);
    await expect(page.getByTestId("concept-card").first().getByText("30 秒", { exact: true })).toBeVisible();
    await expect(page.getByTestId("concept-card").first().getByText("9:16", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "用这个方向开始", exact: true })).toBeEnabled();
    await page.getByRole("button", { name: "时长 · 30 秒", exact: true }).click();
    await page.getByRole("radio", { name: "60 秒", exact: true }).check(); await page.keyboard.press("Escape");
    await expect(page.getByTestId("concept-card")).toHaveCount(0);
    await expect(page.getByRole("button", { name: "用这个方向开始", exact: true })).toHaveCount(0);
    await expect(page.getByText("草稿已保存", { exact: true })).toBeVisible();
    await page.reload(); await expect(page.getByTestId("concept-card")).toHaveCount(0);
    await expect(page.getByRole("button", { name: "时长 · 60 秒", exact: true })).toBeVisible();
    await page.getByRole("button", { name: "生成三个方案", exact: true }).click();
    await expect(page.getByTestId("concept-card").first().getByText("60 秒", { exact: true })).toBeVisible();
    expect(fixture.conceptRequests.every((body) => body.project_id === PROJECT && typeof body.draft_revision === "number" && !("generation_settings" in body))).toBe(true);
    await page.goto("/");
    await expect(page.getByRole("button", { name: "时长 · 60 秒", exact: true })).toBeEnabled();
    await page.getByRole("button", { name: "时长 · 60 秒", exact: true }).click();
    await page.getByText("自定义时长", { exact: true }).click();
    const customDuration = page.getByLabel("自定义时长（5–180 秒）", { exact: true });
    await customDuration.fill("17"); await page.keyboard.press("Enter");
    await page.keyboard.press("Escape");
    await expect(page.getByRole("button", { name: "时长 · 17 秒", exact: true })).toBeFocused();
    await page.getByRole("button", { name: "时长 · 17 秒", exact: true }).click();
    await expect(customDuration).toBeFocused();
    await expect(customDuration).toBeVisible();
    await expect(customDuration).toHaveValue("17");
    await page.getByLabel("自定义时长（5–180 秒）", { exact: true }).fill("181"); await page.keyboard.press("Enter");
    await expect(page.getByRole("alert")).toContainText("5 到 180");
    expect(fixture.filmStarts).toEqual([]);
    await page.keyboard.press("Escape");
    expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1);
  });
}

test("desktop ratio choices use four columns in the standard dialog width", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await stubDraft(page, "light");
  await page.goto("/");
  await page.getByRole("button", { name: "比例 · 自动", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "画面比例" });
  const box = await dialog.boundingBox();
  expect(box?.width).toBe(480);
  expect(await dialog.getByTestId("common-ratios").evaluate((grid) => getComputedStyle(grid).gridTemplateColumns.split(" ").length)).toBe(4);
  await expect(dialog.getByRole("radio", { name: "自动", exact: true })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("button", { name: "比例 · 自动", exact: true })).toBeFocused();
});
