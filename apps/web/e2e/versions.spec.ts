import { expect, type Page, type Route, test } from "@playwright/test";

const PROJECT = "filmversion01";

test("aspect, language, and duration each load that cut", async ({ page }) => {
  await stubFilm(page);
  await page.goto(`/projects/${PROJECT}/film`);

  const player = page.getByTestId("film-player");
  await expect(player).toBeVisible();
  await expect(page.getByLabel("比例")).toHaveValue("16:9");
  await expect(page.getByLabel("语种")).toHaveValue("zh");
  await expect(page.getByLabel("时长")).toHaveValue("15");
  await expect(player).toHaveAttribute("data-aspect", "16:9");

  const tall = page.waitForRequest((request) => request.url().includes("/versions/tall/download"));
  await page.getByLabel("比例").selectOption("9:16");
  await tall;
  await expect(player).toHaveAttribute("data-aspect", "9:16");
  await expect(page.getByLabel("语种")).toHaveValue("zh");
  await expect(page.getByRole("option", { name: "English" })).toHaveCount(0);

  await page.getByLabel("比例").selectOption("16:9");
  const english = page.waitForRequest((request) => request.url().includes("/versions/english/download"));
  await page.getByLabel("语种").selectOption("en");
  await english;
  await expect(player).toHaveAttribute("data-aspect", "16:9");

  await page.getByLabel("语种").selectOption("zh");
  const short = page.waitForRequest((request) => request.url().includes("/versions/short/download"));
  await page.getByLabel("时长").selectOption("5");
  await short;
  await expect(page.getByLabel("时长")).toHaveValue("5");
});

async function stubFilm(page: Page) {
  const versions = [
    cut("wide", "16:9", "zh", 15, 320, 180),
    cut("short", "16:9", "zh", 5, 320, 180),
    cut("english", "16:9", "en", 15, 320, 180),
    cut("tall", "9:16", "zh", 15, 180, 320),
    cut("square", "1:1", "zh", 15, 320, 320),
  ];
  await page.route(`**/v1/projects/${PROJECT}/versions/*/download`, fulfillMp4);
  await page.route(`**/v1/projects/${PROJECT}/download`, fulfillMp4);
  await page.route(`**/v1/projects/${PROJECT}/versions`, (route) => route.fulfill({ json: { versions } }));
  await page.route(`**/v1/projects/${PROJECT}`, (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return route.fulfill({
      json: { status: "completed", sentence: "柱塞泵宣传片", shots: [{ shot_id: "S01", order: 1, purpose: "产品" }] },
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
