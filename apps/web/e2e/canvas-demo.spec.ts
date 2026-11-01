import { expect, test } from "@playwright/test";

const projectId = "demo-canvas";
const storageKey = `hilatv.canvas.v0.${projectId}`;

test.beforeEach(({}, info) => {
  test.skip(info.project.name === "mobile", "画布演示用桌面视口");
});

test("expert canvas demo: connect, switch, trim, keep position, keep the AI label", async ({ page }) => {
  const shots = process.env.CANVAS_SHOTS;
  let step = 0;
  async function snap(name: string) {
    if (!shots) return;
    step += 1;
    await page.screenshot({ path: `${shots}/${String(step).padStart(2, "0")}-${name}.png` });
  }
  await page.addInitScript((key) => {
    localStorage.setItem("hilatv-theme", "light");
    if (!sessionStorage.getItem("r3-canvas-booted")) {
      localStorage.removeItem(key);
      sessionStorage.setItem("r3-canvas-booted", "1");
    }
  }, storageKey);

  await page.goto(`/projects/${projectId}/expert`);
  await expect(page.getByText("本地演示 · 修改仅保存在此浏览器")).toBeVisible();
  await expect(page.getByTestId("node-brief-1")).toBeVisible();
  await expect(page.getByTestId("node-ref-product")).toBeVisible();
  await expect(page.getByTestId("node-shot-1")).toBeVisible();
  await expect(page.getByTestId("node-shot-2")).toBeVisible();
  await expect(page.getByTestId("node-final-1")).toBeVisible();
  await expect(page.locator(".react-flow__minimap")).toBeVisible();
  await expect(page.getByTestId("node-shot-2")).toContainText("未评审");
  await expect(page.getByTestId("node-shot-2")).not.toContainText("质检通过");
  await expect(page.locator("body")).not.toContainText("补拍");
  await expect(page.getByText("no text, no letters")).toHaveCount(0);
  await snap("full-canvas");
  if (shots) {
    await page.getByTestId("node-shot-2").screenshot({ path: `${shots}/02b-shot-card.png` });
  }

  const source = page.getByTestId("handle-ref-product-source");
  const target = page.getByTestId("handle-shot-2-target");
  await source.dragTo(target);
  await expect(page.getByTestId("node-shot-2").getByAltText("已接入的参考图")).toBeVisible();
  await snap("connected");

  await page.getByTestId("node-shot-2").getByRole("button", { name: "选用另一张" }).click();
  await page.getByTestId("pick-shot2-b").click();
  await expect(page.getByTestId("node-shot-2")).toContainText("质检通过");
  await snap("candidate");

  const range = page.getByTestId("clip-range-shot-2");
  await expect(range).toHaveText("0.0–6.0");
  const handle = page.getByTestId("clip-in-shot-2");
  const box = await handle.boundingBox();
  if (!box) throw new Error("时间轴入点没有出现");
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + 48, box.y + box.height / 2, { steps: 8 });
  await page.mouse.up();
  await expect(range).not.toHaveText("0.0–6.0");
  if (shots) {
    await page.locator(".hilatv-timeline").screenshot({ path: `${shots}/04b-timeline.png` });
  }
  await snap("timeline");

  const shot = page.getByTestId("node-shot-1");
  const before = Number(await shot.getAttribute("data-x"));
  const version = page.getByTestId("layout-version");
  const versionBefore = await version.innerText();
  const shotBox = await shot.boundingBox();
  if (!shotBox) throw new Error("第 1 镜没有出现");
  await page.mouse.move(shotBox.x + 40, shotBox.y + 16);
  await page.mouse.down();
  await page.mouse.move(shotBox.x + 160, shotBox.y + 70, { steps: 8 });
  await page.mouse.up();
  await expect(version).not.toHaveText(versionBefore, { timeout: 10_000 });
  const after = Number(await shot.getAttribute("data-x"));
  expect(Math.abs(after - before)).toBeGreaterThan(10);

  await page.reload();
  await expect(page.getByTestId("node-shot-1")).toBeVisible();
  const reloaded = Number(await page.getByTestId("node-shot-1").getAttribute("data-x"));
  // 保存时坐标取整，拖动本身是亚像素，允许 2px 误差。
  expect(Math.abs(reloaded - after)).toBeLessThanOrEqual(2);
  await expect(page.getByTestId("node-shot-2").getByAltText("已接入的参考图")).toBeVisible();
  await expect(page.getByTestId("node-shot-2")).toContainText("质检通过");

  await expect(page.getByRole("button", { name: "导出", exact: true })).toBeDisabled();
  await expect(page.getByText("演示画布不生成文件。新建项目后可以制作和导出成片。")).toBeVisible();
  await expect(page.getByTestId("export-result")).toHaveCount(0);
  await snap("export");
  await expect(page.getByRole("switch")).toHaveCount(0);
  if (shots) {
    await page.evaluate(() => localStorage.setItem("hilatv-theme", "dark"));
    await page.reload();
    await expect(page.getByTestId("ai-label")).toHaveText("AI生成");
    await page.screenshot({ path: `${shots}/06-dark-shell.png` });
  }
});
