import { test } from "@playwright/test";

test("legacy live expert canvas stays paused while the page canvas is the P0 mock", () => {
  test.skip(true, "专家画布已改为整页节点。界面演示在 canvas-demo.spec.ts；已有重跑接口在项目存在时仍会调用。");
});
