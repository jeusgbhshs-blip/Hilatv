import { expect, type Page, test } from "@playwright/test";

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

test("one sentence becomes a playable download", async ({ page }) => {
  const api = process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000";
  const link = `${api.replace(/\/$/, "")}/health`;

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "说一句话，做成一条片" })).toBeVisible();
  await page.getByRole("button", { name: "制造业" }).click();
  await expect(page.getByLabel("一句话")).toHaveValue(/柱塞泵/);
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

  const created = page.waitForRequest(
    (request) =>
      request.method() === "POST" && new URL(request.url()).pathname === "/v1/projects",
  );
  const socketWait = page.waitForEvent("websocket", {
    predicate: (socket) => socket.url().includes("/v1/projects/") && socket.url().includes("/progress"),
    timeout: 240_000,
  });
  await page.getByRole("button", { name: "开始生成" }).click();
  const request = await created;
  const body = request.postDataJSON() as {
    sentence: string;
    attachments: { kind: string; filename?: string; uri?: string; upload_id?: string }[];
  };
  expect(body.sentence).toBe(SENTENCE);
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

  await page.getByRole("link", { name: "观看成片" }).click();
  await page.waitForURL(/\/film$/);
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
  await page.getByRole("button", { name: "下载成片" }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe("master.mp4");
  expect(await download.failure()).toBeNull();
  expect(await download.path()).toBeTruthy();
});
