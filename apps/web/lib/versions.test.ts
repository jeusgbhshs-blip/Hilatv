import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  aspectLabel,
  defaultChoice,
  downloadName,
  durationLabel,
  languageLabel,
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
  });

  it("starts on the wide Chinese cut and the longest duration", () => {
    const choice = defaultChoice(VERSIONS);
    assert.deepEqual(choice, { aspect: "16:9", language: "zh", duration: 15 });
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
