# HP06 E2E contract update

- `main-flow.spec.ts` follows draft save → `film/start`, retains sentence, attachment, upload-ID and revision assertions, and expects a playable authenticated mock preview. It checks the explicit preview/readiness/provenance fields, “保存预览”, the private `/preview` request and `preview-master.mp4`; it never treats completion or human continuation as formal approval.
- `versions.spec.ts` starts on the current master and selects “文件 → 导出文件” before changing aspect, language or duration. Player requests use each file's `/preview`. Synthetic ready/live/quality-passed exports still assert “下载成片”, their `/download` route and filename, while a mock export and the mock master remain preview-only.
- `ui01-design.spec.ts` gives every completed fixture explicit file readiness and uses authenticated preview routes. Its formal-delivery screenshots use synthetic server `ready` + true quality + live provenance fields. Draft create/save/read routes are stubbed so the concept-page screenshot setup also follows the current draft contract.

Validation: `npx tsc --noEmit`, ESLint on these three E2E files and `git diff --check` passed. No Playwright browser, E2E run, build, server restart, live provider or paid request was performed for this change. Browser acceptance remains the coordinator's integration check.
