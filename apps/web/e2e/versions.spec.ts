import { expect, type Page, type Route, test } from "@playwright/test";

const PROJECT = "filmversion01";

test("aspect, language, and duration each load that cut", async ({ page }) => {
  await stubFilm(page);
  await page.goto(`/projects/${PROJECT}/film`);

  const player = page.getByTestId("film-player");
  await expect(player).toBeVisible();
  await expect(player).toHaveAttribute("data-aspect", "master");
  await expect(page.getByLabel("文件", { exact: true })).toHaveValue("master");
  await expect(page.getByLabel("比例")).toBeDisabled();
  await expect(page.getByRole("button", { name: "保存预览", exact: true })).toBeVisible();
  const wide = page.waitForRequest((request) => new URL(request.url()).pathname === `/v1/projects/${PROJECT}/versions/wide/preview`);
  await page.getByLabel("文件", { exact: true }).selectOption("export");
  await wide;
  await expect(page.getByLabel("比例")).toHaveValue("16:9");
  await expect(page.getByLabel("语种")).toHaveValue("zh");
  await expect(page.getByLabel("时长")).toHaveValue("15");
  await expect(player).toHaveAttribute("data-aspect", "16:9");
  await expect(page.getByRole("heading", { name: "成片已通过审核" })).toBeVisible();
  await expect(page.getByRole("button", { name: "下载成片", exact: true })).toBeVisible();
  await expect(page.getByLabel("改稿", { exact: true })).toBeDisabled();

  const tall = page.waitForRequest((request) => request.url().includes("/versions/tall/preview"));
  await page.getByLabel("比例").selectOption("9:16");
  await tall;
  await expect(player).toHaveAttribute("data-aspect", "9:16");
  await expect(page.getByLabel("语种")).toHaveValue("zh");
  await expect(page.getByRole("option", { name: "English" })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "模拟成片，可预览" })).toBeVisible();
  await expect(page.getByRole("button", { name: "保存预览", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "下载成片", exact: true })).toHaveCount(0);

  await page.getByLabel("比例").selectOption("16:9");
  const english = page.waitForRequest((request) => request.url().includes("/versions/english/preview"));
  await page.getByLabel("语种").selectOption("en");
  await english;
  await expect(player).toHaveAttribute("data-aspect", "16:9");

  await page.getByLabel("语种").selectOption("zh");
  const short = page.waitForRequest((request) => request.url().includes("/versions/short/preview"));
  await page.getByLabel("时长").selectOption("5");
  await short;
  await expect(page.getByLabel("时长")).toHaveValue("5");
  await expect(page.getByRole("heading", { name: "成片已通过审核" })).toBeVisible();
  const downloadRequest = page.waitForRequest((request) => new URL(request.url()).pathname === `/v1/projects/${PROJECT}/versions/short/download`);
  const downloadEvent = page.waitForEvent("download");
  await page.getByRole("button", { name: "下载成片", exact: true }).click();
  await downloadRequest;
  const download = await downloadEvent;
  expect(download.suggestedFilename()).toBe("hilatv-16x9-zh-5s.mp4");
  expect(await download.failure()).toBeNull();
  await page.getByLabel("文件", { exact: true }).selectOption("master");
  await expect(player).toHaveAttribute("data-aspect", "master");
  await expect(page.getByRole("button", { name: "保存预览", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "下载成片", exact: true })).toHaveCount(0);
});

async function stubFilm(page: Page) {
  await page.addInitScript(() => localStorage.setItem("hilatv.session", "versions-test-session"));
  const versions = [
    cut("wide", "16:9", "zh", 15, 320, 180),
    cut("short", "16:9", "zh", 5, 320, 180),
    cut("english", "16:9", "en", 15, 320, 180),
    cut("tall", "9:16", "zh", 15, 180, 320),
    cut("square", "1:1", "zh", 15, 320, 320),
  ];
  await page.route(`**/v1/projects/${PROJECT}/versions/*/download`, fulfillMp4);
  await page.route(`**/v1/projects/${PROJECT}/versions/*/preview`, fulfillMp4);
  await page.route(`**/v1/projects/${PROJECT}/download`, fulfillMp4);
  await page.route(`**/v1/projects/${PROJECT}/preview`, fulfillMp4);
  await page.route(`**/v1/projects/${PROJECT}/revisions`, (route) => route.fulfill({ json: { versions: [] } }));
  await page.route(`**/v1/projects/${PROJECT}/versions`, (route) => route.fulfill({ json: { versions } }));
  await page.route(`**/v1/projects/${PROJECT}`, (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return route.fulfill({
      json: {
        status: "completed", sentence: "柱塞泵宣传片", shots: [{ shot_id: "S01", order: 1, purpose: "产品" }],
        preview_available: true, preview_path: `/v1/projects/${PROJECT}/preview`, media_hash: "mock-master-hash",
        delivery_status: "preview", quality_pass: false, media_provenance: "mock", download_path: null,
      },
    });
  });
}

function cut(
  id: string,
  aspect: string,
  language: string,
  duration: number,
  width: number,
  height: number,
) {
  return {
    version_id: id,
    aspect_ratio: aspect,
    language,
    duration_s: duration,
    width,
    height,
    download_path: `/v1/projects/${PROJECT}/versions/${id}/download`,
    preview_path: `/v1/projects/${PROJECT}/versions/${id}/preview`,
    preview_available: true,
    media_hash: `cut-${id}-hash`,
    delivery_status: id === "tall" ? "preview" : "ready",
    quality_pass: id !== "tall",
    media_provenance: id === "tall" ? "mock" : "live",
    qa_status: id === "tall" ? "needs_review" : "passed",
    share_path: null,
  };
}

function fulfillMp4(route: Route) {
  return route.fulfill({
    status: 200,
    contentType: "video/mp4",
    body: Buffer.from("fake-mp4"),
  });
}
