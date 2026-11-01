import { expect, type Page, type Request, test } from "@playwright/test";

const SENTENCE = "给我们的柱塞泵做个15秒宣传片，面向采购，风格稳重";
const PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
  "base64",
);

async function expectNoHorizontalOverflow(page: Page) {
  const extra = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(extra).toBeLessThanOrEqual(1);
}

test("one sentence becomes a playable private mock preview", async ({ page }) => {
  const api = process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000";
  const link = `${api.replace(/\/$/, "")}/health`;
  const draftWrites: Request[] = [];
  page.on("request", (request) => {
    if (request.method() === "PUT" && /^\/v1\/projects\/[^/]+\/draft$/.test(new URL(request.url()).pathname)) draftWrites.push(request);
  });

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "一句话，拍出你的成片" })).toBeVisible();
  await page.getByRole("button", { name: "电商带货" }).click();
  await expect(page.getByLabel("一句话")).toHaveValue(/带货/);
  await page.getByLabel("一句话").fill(SENTENCE);
  await page.getByLabel("上传素材").setInputFiles({
    name: "product.png",
    mimeType: "image/png",
    buffer: PNG,
  });
  await expect(page.getByText("product.png")).toBeVisible();
  await page.getByLabel("素材链接").fill(link);
  await page.getByRole("button", { name: "添加链接" }).click();
  await expect(page.getByText(link)).toBeVisible();
  await expectNoHorizontalOverflow(page);
  await expect(page.locator(".animate-spin")).toHaveCount(0);

  const started = page.waitForRequest(
    (request) =>
      request.method() === "POST" && /^\/v1\/projects\/[^/]+\/film\/start$/.test(new URL(request.url()).pathname),
  );
  const socketWait = page.waitForEvent("websocket", {
    predicate: (socket) => socket.url().includes("/v1/projects/") && socket.url().includes("/progress"),
    timeout: 240_000,
  });
  await page.getByRole("radio", { name: "直接出片" }).check();
  await page.getByRole("button", { name: "生成", exact: true }).click();
  const request = await started;
  const projectId = new URL(request.url()).pathname.split("/")[3];
  const savedRequest = draftWrites.findLast((item) => new URL(item.url()).pathname === `/v1/projects/${projectId}/draft`);
  expect(savedRequest, "generation must follow the final saved draft").toBeDefined();
  const body = savedRequest!.postDataJSON() as {
    sentence: string;
    attachments: { kind: string; filename?: string; uri?: string; upload_id?: string }[];
    skip_storyboard?: boolean;
  };
  expect(body.sentence).toBe(SENTENCE);
  expect(body.skip_storyboard).toBe(true);
  expect(body.attachments).toEqual(
    expect.arrayContaining([
      expect.objectContaining({ kind: "image", filename: "product.png" }),
      expect.objectContaining({ kind: "url", uri: link }),
    ]),
  );
  const image = body.attachments.find((item) => item.kind === "image");
  expect(image?.upload_id).toMatch(/^[a-f0-9]{32}$/);
  expect(image?.uri).toBeUndefined();
  expect(JSON.stringify(body)).not.toContain("/uploads/");
  const startBody = request.postDataJSON() as { operation_id: string; draft_revision: number };
  expect(startBody.operation_id).toMatch(/^[a-f0-9-]{36}$/);
  const savedResponse = await savedRequest!.response();
  expect(savedResponse?.ok()).toBe(true);
  expect(startBody.draft_revision).toBe((await savedResponse!.json()).draft_revision);
  await socketWait;
  await page.waitForURL(/\/projects\/[0-9a-f-]+$/);

  await expect(page.getByRole("list", { name: "进度" }).getByText("理解需求")).toBeVisible();
  await expect(page.getByRole("button", { name: "放行并成片" })).toBeVisible({ timeout: 240_000 });
  await page.getByRole("button", { name: "放行并成片" }).click();
  await expect(page.getByRole("list", { name: "进度" }).getByText("成片")).toBeVisible();
  await expect(page.getByRole("link", { name: "观看成片" })).toBeVisible({ timeout: 240_000 });
  await expect(page.locator(".animate-spin")).toHaveCount(0);
  const stages = page.getByTestId("shot-stage");
  await expect(stages.first()).toBeVisible();
  const count = await stages.count();
  expect(count).toBeGreaterThan(0);
  for (let index = 0; index < count; index += 1) {
    await expect(stages.nth(index)).toHaveText(/^第 \d+ 镜：.+/);
  }
  await expect(page.getByText("product.png").first()).toBeVisible();
  await expect(page.getByText(link)).toBeVisible();
  await expectNoHorizontalOverflow(page);

  const filmSnapshot = page.waitForResponse((response) => response.request().method() === "GET" && new URL(response.url()).pathname === `/v1/projects/${projectId}`);
  await page.getByRole("link", { name: "观看成片" }).click();
  await page.waitForURL(/\/film$/);
  const snapshot = await (await filmSnapshot).json();
  expect(snapshot.preview_available).toBe(true);
  expect(snapshot.preview_path).toBe(`/v1/projects/${projectId}/preview`);
  expect(snapshot.delivery_status).toBe("preview");
  expect(snapshot.quality_pass).toBe(false);
  expect(snapshot.media_provenance).toBe("mock");
  expect(snapshot.download_path).toBeNull();
  await expect(page.getByRole("heading", { name: "模拟成片，可预览" })).toBeVisible();
  const player = page.getByTestId("film-player");
  await expect(player).toBeVisible();
  await expect(player).toHaveAttribute("src", /^blob:/);
  await player.evaluate(async (element: HTMLVideoElement) => {
    element.muted = true;
    await element.play();
  });
  await expect
    .poll(async () => player.evaluate((element: HTMLVideoElement) => element.readyState))
    .toBeGreaterThanOrEqual(2);
  await expect
    .poll(async () => player.evaluate((element: HTMLVideoElement) => element.paused))
    .toBe(false);
  await expect(page.getByLabel("比例")).toBeVisible();
  await expect(page.getByLabel("文件", { exact: true })).toHaveValue("master");
  await expect(page.getByLabel("比例")).toBeDisabled();
  await expect(page.getByLabel("语种")).toBeVisible();
  await expect(page.getByLabel("时长")).toBeVisible();
  await expect(page.getByRole("button", { name: "导出其他版本" })).toBeVisible();
  await expect(page.getByLabel("改稿版本")).toBeVisible();
  await expect(page.getByRole("option", { name: /版本 1/ })).toBeEnabled();
  const edit = page.getByLabel("改稿", { exact: true });
  await expect(edit).toBeEnabled();
  await expect(page.getByRole("button", { name: "发送改稿" })).toBeDisabled();
  await edit.fill("第二个镜头太暗");
  await expect(page.getByRole("button", { name: "发送改稿" })).toBeEnabled();
  await edit.fill("");
  const shot = page.getByRole("button", { name: /第 \d+ 镜/ }).first();
  await shot.click();
  await expect(shot).toHaveAttribute("aria-pressed", "true");
  await expectNoHorizontalOverflow(page);

  const downloadPromise = page.waitForEvent("download");
  const previewRequest = page.waitForRequest((request) => new URL(request.url()).pathname === `/v1/projects/${projectId}/preview`);
  await expect(page.getByRole("button", { name: "下载成片", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "保存预览", exact: true }).click();
  await previewRequest;
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe("preview-master.mp4");
  expect(await download.failure()).toBeNull();
  expect(await download.path()).toBeTruthy();
});
