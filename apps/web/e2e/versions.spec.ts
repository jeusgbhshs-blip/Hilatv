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
  await expect(player).toHaveAttribute("data-orientation", "portrait");
  await expect(page.getByTestId("generation-target")).toHaveText("主画幅 · 9:16；目标时长 · 30 秒");
  await expect(page.getByTestId("actual-media")).toContainText("720 × 1280 · 18.4 秒");
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
  await expect(page.getByLabel("语种").getByRole("option", { name: "English" })).toHaveCount(0);
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
  await expect(page.getByLabel("导出画幅", { exact: true })).toHaveValue("9:16");
  await page.getByLabel("导出画幅", { exact: true }).selectOption("21:9");
  const exportRequest = page.waitForRequest((request) => request.method() === "POST" && new URL(request.url()).pathname === `/v1/projects/${PROJECT}/deliveries`);
  await page.getByRole("button", { name: "导出其他版本", exact: true }).click();
  expect((await exportRequest).postDataJSON()).toEqual({ aspect_ratios: ["21:9"], languages: ["zh"] });
  await expect(page.getByText("导出已完成，当前播放导出文件。", { exact: true })).toBeVisible();
  await expect(player).toHaveAttribute("data-version-id", "exported-1");
});

test("same-spec exports keep an exact selection and never inherit the master approval", async ({ page }) => {
  const fixture = await stubFilm(page, { duplicate: true, masterReady: true });
  await page.goto(`/projects/${PROJECT}/film`);
  await expect(page.getByRole("heading", { name: "成片已通过审核" })).toBeVisible();
  await page.getByLabel("文件", { exact: true }).selectOption("export");
  const player = page.getByTestId("film-player");
  await expect(page.getByLabel("导出结果", { exact: true })).toHaveValue("wide-new");
  await expect(player).toHaveAttribute("data-version-id", "wide-new");
  await expect(page.getByRole("heading", { name: "已生成，待核验" })).toBeVisible();
  await expect(page.getByRole("button", { name: "下载成片", exact: true })).toHaveCount(0);
  await page.getByLabel("导出结果", { exact: true }).selectOption("wide");
  await expect(player).toHaveAttribute("data-version-id", "wide");
  await expect(page.getByRole("button", { name: "下载成片", exact: true })).toBeVisible();
  fixture.reverseVersions();
  await page.waitForResponse((response) => new URL(response.url()).pathname === `/v1/projects/${PROJECT}/versions`);
  await expect(page.getByLabel("导出结果", { exact: true })).toHaveValue("wide");
  await expect(player).toHaveAttribute("data-version-id", "wide");
  await page.getByLabel("导出画幅", { exact: true }).selectOption("16:9");
  await page.getByRole("button", { name: "导出其他版本", exact: true }).click();
  await expect(page.getByLabel("导出结果", { exact: true })).toHaveValue("exported-1");
  await expect(player).toHaveAttribute("data-version-id", "exported-1");
  fixture.reverseVersions();
  await page.waitForResponse((response) => new URL(response.url()).pathname === `/v1/projects/${PROJECT}/versions`);
  await expect(player).toHaveAttribute("data-version-id", "exported-1");
  await expect(page.getByLabel("导出结果", { exact: true }).getByRole("option")).toHaveCount(8);
});

test("an older export response cannot switch away from a newly rendered master", async ({ page }) => {
  const fixture = await stubFilm(page);
  await page.goto(`/projects/${PROJECT}/film`);
  const player = page.getByTestId("film-player");
  await expect(player).toBeVisible();
  await page.getByLabel("文件", { exact: true }).selectOption("export");
  await expect(player).toHaveAttribute("data-version-id", "wide");
  const release = fixture.holdNextExport();
  await page.getByRole("button", { name: "导出其他版本", exact: true }).click();
  await expect(page.getByRole("button", { name: "正在导出", exact: true })).toBeDisabled();
  fixture.setMasterHash("new-master-hash");
  await expect(page.getByLabel("文件", { exact: true })).toHaveValue("master");
  release();
  await expect(page.getByText("导出文件已保留。母版已更新，当前显示新母版。", { exact: true })).toBeVisible();
  await expect(player).toHaveAttribute("data-version-id", "master");
  await expect(page.getByLabel("文件", { exact: true })).toHaveValue("master");
});

async function stubFilm(page: Page, options: { duplicate?: boolean; masterReady?: boolean } = {}) {
  await page.addInitScript(() => localStorage.setItem("hilatv.session", "versions-test-session"));
  let versions = [
    cut("wide", "16:9", "zh", 15, 320, 180),
    cut("short", "16:9", "zh", 5, 320, 180),
    cut("english", "16:9", "en", 15, 320, 180),
    cut("tall", "9:16", "zh", 15, 180, 320),
    cut("square", "1:1", "zh", 15, 320, 320),
  ];
  if (options.duplicate) versions.push({ ...cut("wide-new", "16:9", "zh", 15, 320, 180), delivery_status: "needs_verification", quality_pass: false, media_provenance: "unknown" });
  let masterHash = "mock-master-hash";
  let exportCount = 0;
  let exportGate: Promise<void> | null = null;
  await page.route(`**/v1/projects/${PROJECT}/versions/*/download`, fulfillMp4);
  await page.route(`**/v1/projects/${PROJECT}/versions/*/preview`, fulfillMp4);
  await page.route(`**/v1/projects/${PROJECT}/download`, fulfillMp4);
  await page.route(`**/v1/projects/${PROJECT}/preview`, fulfillMp4);
  await page.route(`**/v1/projects/${PROJECT}/revisions`, (route) => route.fulfill({ json: { versions: [] } }));
  await page.route(`**/v1/projects/${PROJECT}/versions`, (route) => route.fulfill({ json: { versions } }));
  await page.route(`**/v1/projects/${PROJECT}/deliveries`, async (route) => {
    const gate = exportGate; exportGate = null;
    if (gate) await gate;
    const body = route.request().postDataJSON();
    const version = cut(`exported-${++exportCount}`, body.aspect_ratios[0], body.languages[0], 15, 420, 180);
    versions = [...versions, version];
    await route.fulfill({ json: { versions, exported_version_ids: [version.version_id] } });
  });
  await page.route(`**/v1/projects/${PROJECT}`, (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return route.fulfill({
      json: {
        status: "completed", sentence: "柱塞泵宣传片", shots: [{ shot_id: "S01", order: 1, purpose: "产品" }],
        preview_available: true, preview_path: `/v1/projects/${PROJECT}/preview`, media_hash: masterHash,
        delivery_status: options.masterReady ? "ready" : "preview", quality_pass: options.masterReady === true, media_provenance: options.masterReady ? "live" : "mock", download_path: options.masterReady ? `/v1/projects/${PROJECT}/download` : null,
        generation_settings: { aspect_ratio: "9:16", duration_s: 30 },
        resolved_generation_settings: { aspect_ratio: "9:16", duration_s: 30, language: "zh" },
        width: 720, height: 1280, duration_s: 18.4,
      },
    });
  });
  return {
    reverseVersions: () => { versions = [...versions].reverse(); },
    setMasterHash: (hash: string) => { masterHash = hash; },
    holdNextExport: () => { let release!: () => void; exportGate = new Promise<void>((resolve) => { release = resolve; }); return release; },
  };
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
