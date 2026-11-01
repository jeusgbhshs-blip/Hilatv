import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  aspectLabel,
  ASPECT_RATIOS,
  defaultChoice,
  choiceAfterExport,
  choiceForVersion,
  exportResultLabel,
  currentExportLanguage,
  defaultExportAspect,
  deliveryRequest,
  downloadName,
  durationLabel,
  languageLabel,
  generationTargetSummary,
  mediaMetadata,
  mediaOrientation,
  pickVersion,
  readVersions,
  reconcile,
  uniqueDurations,
  uniqueLanguages,
  type FilmVersion,
} from "./versions.ts";

const VERSIONS: FilmVersion[] = [
  version("wide-zh", "16:9", "zh", 15),
  version("tall-zh", "9:16", "zh", 15),
  version("square-zh", "1:1", "zh", 15),
  version("wide-en", "16:9", "en", 15),
  version("wide-zh-short", "16:9", "zh", 5),
];

describe("delivery versions", () => {
  it("reads the deliveries list and drops a row without a download path", () => {
    const parsed = readVersions({
      versions: [
        ...VERSIONS,
        { version_id: "bad", aspect_ratio: "16:9", language: "zh", duration_s: 1, width: 1, height: 1 },
      ],
    });
    assert.equal(parsed.length, VERSIONS.length);
    assert.equal(aspectLabel("9:16"), "9:16 竖屏");
    assert.equal(languageLabel("zh-CN"), "中文");
    assert.equal(durationLabel(15), "15 秒");
    assert.equal(durationLabel(2.5), "2.5 秒");
    assert.equal(durationLabel(43 / 30), "1.4 秒");
    assert.equal(durationLabel(142 / 30), "4.7 秒");
  });

  it("starts on the wide Chinese cut and the longest duration", () => {
    const choice = defaultChoice(VERSIONS);
    assert.deepEqual(choice, { aspect: "16:9", language: "zh", duration: 15, version_id: "wide-zh" });
    assert.equal(pickVersion(VERSIONS, choice)?.version_id, "wide-zh");
    assert.equal(downloadName(pickVersion(VERSIONS, choice)), "hilatv-16x9-zh-15s.mp4");
  });

  it("keeps a language only when that aspect has it", () => {
    const tall = reconcile(VERSIONS, { aspect: "9:16", language: "en", duration: 15 });
    assert.equal(tall.language, "zh");
    assert.deepEqual(uniqueLanguages(VERSIONS, "9:16"), ["zh"]);
    assert.equal(pickVersion(VERSIONS, tall)?.version_id, "tall-zh");
  });

  it("switches duration without leaving the chosen aspect and language", () => {
    const short = reconcile(VERSIONS, { aspect: "16:9", language: "zh", duration: 5 });
    assert.deepEqual(uniqueDurations(VERSIONS, "16:9", "zh"), [5, 15]);
    assert.equal(pickVersion(VERSIONS, short)?.version_id, "wide-zh-short");
    const english = pickVersion(VERSIONS, { aspect: "16:9", language: "en", duration: 15 });
    assert.equal(english?.version_id, "wide-en");
  });
});

function version(id: string, aspect: string, language: string, duration: number): FilmVersion {
  const tall = aspect === "9:16";
  const square = aspect === "1:1";
  return {
    version_id: id,
    aspect_ratio: aspect,
    language,
    duration_s: duration,
    width: tall ? 180 : 320,
    height: tall ? 320 : square ? 320 : 180,
    download_path: `/v1/projects/p/versions/${id}/download`,
    share_path: null,
  };
}


describe("version preview evidence", () => {
  it("retains the selected file gate and rejects external preview URLs", () => {
    const [parsed] = readVersions([{ ...VERSIONS[0], preview_path: "/v1/projects/p/versions/wide-zh/preview", preview_available: true, media_hash: "file-hash", delivery_status: "needs_verification", quality_pass: false, media_provenance: "mock" }]);
    assert.equal(parsed.preview_available, true);
    assert.equal(parsed.preview_path, "/v1/projects/p/versions/wide-zh/preview");
    assert.equal(parsed.media_hash, "file-hash");
    assert.equal(parsed.delivery_status, "needs_verification");
    assert.equal(parsed.quality_pass, false);
    assert.equal(parsed.media_provenance, "mock");
    assert.equal(readVersions([{ ...VERSIONS[0], preview_path: "//external.test/preview" }])[0].preview_path, null);
    assert.equal(readVersions([{ ...VERSIONS[0], download_path: "//external.test/download" }]).length, 0);
  });
});

describe("generation target, actual media and explicit exports", () => {
  it("never presents the requested ratio or target duration as actual media geometry", () => {
    const snapshot = { generation_settings: { aspect_ratio: "9:16", duration_s: 30 }, width: 1920, height: 1080, duration_s: 18.4 };
    assert.equal(generationTargetSummary(snapshot), "主画幅 · 9:16；目标时长 · 30 秒");
    assert.deepEqual(mediaMetadata(snapshot), { width: 1920, height: 1080, duration_s: 18.4 });
    assert.equal(mediaOrientation(mediaMetadata(snapshot)), "landscape");
    assert.equal(defaultExportAspect(snapshot), "9:16");
  });
  it("uses resolved automatic targets without inventing file dimensions", () => {
    const snapshot = { generation_settings: { aspect_ratio: null, duration_s: null }, resolved_generation_settings: { aspect_ratio: "4:3", duration_s: 60, language: "en" } };
    assert.equal(generationTargetSummary(snapshot), "主画幅 · 4:3；目标时长 · 60 秒");
    assert.deepEqual(mediaMetadata(snapshot), { width: null, height: null, duration_s: null });
    assert.equal(mediaOrientation(mediaMetadata(snapshot)), "unknown");
    assert.equal(defaultExportAspect(snapshot), "4:3");
  });
  it("uses decoded or probed portrait and square dimensions rather than assuming every file is 16:9", () => {
    assert.equal(mediaOrientation(mediaMetadata({ width: 720, height: 1280, duration_s: 18.4 })), "portrait");
    assert.equal(mediaOrientation(mediaMetadata({ width: 1080, height: 1080 })), "square");
    assert.equal(defaultExportAspect({ width: 720, height: 1280 }), "9:16");
    assert.equal(defaultExportAspect({ width: 854, height: 480 }), "16:9");
    assert.equal(mediaOrientation(mediaMetadata({ width: 0, height: 1280 })), "unknown");
    assert.equal(mediaMetadata({ width: NaN, height: 1080, duration_s: Infinity }).duration_s, null);
  });
  it("exports only the explicitly selected ratio and one existing language for all nine supported frames", () => {
    for (const ratio of ASPECT_RATIOS) {
      assert.deepEqual(deliveryRequest(ratio, "zh"), { aspect_ratios: [ratio], languages: ["zh"] });
      assert.ok(aspectLabel(ratio).startsWith(ratio));
    }
    assert.deepEqual(deliveryRequest("21:9", "en"), { aspect_ratios: ["21:9"], languages: ["en"] });
    assert.equal(currentExportLanguage({ resolved_generation_settings: { language: "en" } }, "zh"), "en");
    assert.equal(currentExportLanguage({}, "en"), "en");
    assert.equal(currentExportLanguage({}), "zh");
    assert.throws(() => deliveryRequest("10:1", "zh"));
    assert.throws(() => deliveryRequest("16:9", ""));
    assert.throws(() => deliveryRequest("16:9", "zh,en"));
  });
  it("rejects exported rows with invalid dimensions", () => {
    assert.deepEqual(readVersions([{ ...VERSIONS[0], width: 0 }, { ...VERSIONS[0], height: -1 }]), []);
  });
});

describe("exact exported file identity", () => {
  const older = { ...version("older-source", "16:9", "zh", 15), delivery_status: "ready", quality_pass: true, media_provenance: "live", source_media_hash: "a".repeat(64) };
  const newer = { ...version("newer-source", "16:9", "zh", 15), delivery_status: "needs_verification", quality_pass: false, media_provenance: "unknown", source_media_hash: "b".repeat(64) };
  const request = { aspect: "16:9", language: "zh", source_media_hash: newer.source_media_hash };

  it("uses the latest matching row for a filter without pinning an older same-spec file", () => {
    assert.equal(pickVersion([older, newer], { aspect: "16:9", language: "zh", duration: 15 })?.version_id, newer.version_id);
    assert.equal(defaultChoice([older, newer]).version_id, newer.version_id);
  });
  it("keeps an exact selected ID and its own gate when GET reorders or adds same-spec results", () => {
    const choice = choiceForVersion(older);
    const refreshed = [newer, { ...older, quality_pass: false, delivery_status: "needs_verification" }, { ...newer, version_id: "another-new-source" }];
    const settled = reconcile(refreshed, choice);
    assert.equal(settled.version_id, older.version_id);
    assert.equal(pickVersion(refreshed, settled)?.quality_pass, false);
    assert.equal(pickVersion(refreshed, settled)?.delivery_status, "needs_verification");
  });
  it("chooses the explicit POST result even if it is an existing ID and another new row is later", () => {
    const concurrent = { ...newer, version_id: "concurrent-export" };
    const found = [older, newer, concurrent];
    const next = choiceAfterExport(found, new Set([older.version_id, newer.version_id]), request, [older.version_id]);
    assert.equal(next?.version_id, older.version_id);
    assert.equal(pickVersion(found, next!)?.download_path, older.download_path);
  });
  it("uses new matching IDs for legacy POSTs while ignoring other aspect or language rows", () => {
    const wrongRatio = version("tall-new", "9:16", "zh", 15);
    const wrongLanguage = version("english-new", "16:9", "en", 15);
    const next = choiceAfterExport([older, newer, wrongRatio, wrongLanguage], new Set([older.version_id]), request);
    assert.equal(next?.version_id, newer.version_id);
  });
  it("handles an idempotent legacy export by matching its source without requiring a new ID", () => {
    const next = choiceAfterExport([newer, older], new Set([older.version_id, newer.version_id]), request);
    assert.equal(next?.version_id, newer.version_id);
  });
  it("does not substitute another file when a pinned ID or an explicit POST result is missing", () => {
    const choice = choiceForVersion(older);
    assert.equal(pickVersion([newer], reconcile([newer], choice)), null);
    assert.equal(reconcile([newer], choice).version_id, older.version_id);
    assert.equal(choiceAfterExport([older, newer], new Set(), request, []), null);
    assert.equal(choiceAfterExport([older, newer], new Set(), request, ["missing-id"]), null);
  });
  it("updates exact-file metadata without losing identity and only changes file on a new filter choice", () => {
    const choice = choiceForVersion(older);
    const updated = { ...older, duration_s: 15.4 };
    assert.equal(reconcile([updated, newer], choice).duration, 15.4);
    const tall = version("tall", "9:16", "zh", 15);
    assert.equal(reconcile([older, newer, tall], { ...choice, version_id: undefined, aspect: "9:16" }).version_id, tall.version_id);
  });
  it("retains valid source hashes for matching but never puts identifiers in ordinary labels", () => {
    const [parsed] = readVersions([{ ...newer, source_key: "c".repeat(64) }]);
    assert.equal(parsed.source_key, "c".repeat(64));
    assert.equal(parsed.source_media_hash, newer.source_media_hash);
    assert.equal(exportResultLabel(parsed, 1), "导出 2 · 16:9 · 中文 · 15 秒");
    assert.ok(!exportResultLabel(parsed, 1).includes(parsed.version_id));
    const [invalid] = readVersions([{ ...newer, source_key: "/private/path", source_media_hash: "not-a-hash" }]);
    assert.equal(invalid.source_key, null);
    assert.equal(invalid.source_media_hash, null);
  });
});
