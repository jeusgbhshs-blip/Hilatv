import { expect, type Page, test } from "@playwright/test";

const projectId = process.env.HILATV_EXPERT_PROJECT;

async function expectNoHorizontalOverflow(page: Page) {
  const extra = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(extra).toBeLessThanOrEqual(1);
}

test("expert canvas shows candidates and a re-run charges the budget", async ({ page }) => {
  test.skip(!projectId, "needs HILATV_EXPERT_PROJECT");
  await page.goto(`/projects/${projectId}/expert`);
  if (test.info().project.name === "mobile") {
    expect(page.viewportSize()?.width).toBe(390);
  }
  await expect(page.getByRole("heading", { name: "节点画布" })).toBeVisible();
  await page.getByTestId("node-n08_keyframe").click();
  await expect(page.getByText("3 个关键帧候选")).toBeVisible();
  const candidates = page.getByTestId("candidate");
  await expect(candidates).toHaveCount(3);
  await expect(candidates.first()).toContainText("未评审");
  await expect(candidates.first()).toContainText("画面中不要出现任何文字");
  await expect(page.getByTestId("master-reason")).toContainText("未评审");
  await expectNoHorizontalOverflow(page);

  const before = await page.getByTestId("regen-used").innerText();
  await page.getByRole("button", { name: "重跑此节点" }).click();
  await expect(page.getByTestId("regen-used")).not.toHaveText(before, { timeout: 180_000 });
  await expect(page.getByTestId("candidate").first()).toContainText("未评审");
  await expect(page.locator("p[role=alert]")).toHaveCount(0);
  await expectNoHorizontalOverflow(page);
});
