import path from "node:path";

import { expect, type Page, test } from "@playwright/test";

const logo = path.join(process.cwd(), "e2e/fixtures/mark.png");

async function expectNoHorizontalOverflow(page: Page) {
  const extra = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(extra).toBeLessThanOrEqual(1);
}

test("brand kit is saved once and three concept cards can be chosen", async ({ page }) => {
  await page.goto("/brand");
  await expect(page.getByRole("heading", { name: "品牌资料" })).toBeVisible();
  await page.getByLabel("企业名称").fill("青岛测试机械");
  await page.getByRole("button", { name: "制造业" }).click();
  await page.getByLabel("Logo").setInputFiles(logo);
  await page.getByLabel("产品名称").fill("测试泵 TP-1");
  await page.getByLabel("产品图").setInputFiles(logo);
  await page.getByLabel("卖点，一行一条").fill("压力 30MPa");
  await page.getByLabel("人物身份").fill("老板");
  await expect(page.getByLabel("声音编号")).toBeDisabled();
  await page.getByRole("button", { name: "保存品牌资料" }).click();
  await expect(page.getByText("已保存。之后新建的项目会自动套用")).toBeVisible();
  await expect(page.getByText(/主色 #/)).toBeVisible();
  await expect(page.getByText("未勾选肖像授权的人物不会出镜")).toBeVisible();
  await expectNoHorizontalOverflow(page);

  await page.goto("/concepts");
  await expect(page.getByRole("heading", { name: "选一张方案卡" })).toBeVisible();
  await page.getByLabel("一句话").fill("给测试泵做一条15秒宣传片，面向采购，风格稳重");
  await page.getByRole("button", { name: "生成三个方案" }).click();
  await expect(page.getByTestId("concept-card")).toHaveCount(3);
  await expect(page.getByText("将套用已保存的 Logo、色彩、字体、行动号召和卖点。")).toBeVisible();
  await page.getByRole("button", { name: "你帮我选" }).click();
  await expect(page.getByText("已选择：你帮我选")).toBeVisible();
  await page.getByRole("button", { name: "选这个" }).first().click();
  await expect(page.getByText("已选择：产品宣传主结构")).toBeVisible();
  await expectNoHorizontalOverflow(page);
});
