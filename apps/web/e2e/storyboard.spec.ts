import { expect, type Page, test } from "@playwright/test";

const SENTENCE = "给我们的柱塞泵做个15秒宣传片，面向采购，风格稳重";
const MARKER = "分镜旁白标记甲乙丙丁";

async function expectNoHorizontalOverflow(page: Page) {
  const extra = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(extra).toBeLessThanOrEqual(1);
}

test("storyboard cards can be read and the narration edited", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("一句话").fill(SENTENCE);
  await page.getByRole("radio", { name: "先看分镜" }).check();
  await page.getByRole("button", { name: "开始生成" }).click();
  await page.waitForURL(/\/projects\/[0-9a-f-]+$/);

  const strip = page.getByTestId("storyboard");
  await expect(strip).toBeVisible({ timeout: 300_000 });
  const cards = page.getByTestId("storyboard-card");
  await expect(cards.first()).toBeVisible();
  const count = await cards.count();
  expect(count).toBeGreaterThan(1);
  await expect(page.getByTestId("storyboard-frame")).toHaveCount(0);
  await expect(page.getByText("这一镜还没有可看的画面").first()).toBeVisible();
  await expect(page.getByTestId("ai-label")).toHaveText("AI生成");
  await expect(page.getByRole("button", { name: /去掉.*AI生成|移除AI生成/ })).toHaveCount(0);

  const box = cards.first().getByRole("textbox");
  const original = await box.inputValue();
  expect(original.trim().length).toBeGreaterThan(0);
  await box.fill(`${original}${MARKER}`);
  await cards.first().getByRole("button", { name: "保存旁白" }).click();
  await expect(box).toHaveValue(new RegExp(MARKER), { timeout: 180_000 });
  await expect(page.getByTestId("ai-label")).toHaveText("AI生成");
  await expectNoHorizontalOverflow(page);
});
