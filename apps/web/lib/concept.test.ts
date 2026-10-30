import assert from "node:assert/strict";
import test from "node:test";

import { conceptIsDegraded, conceptNotice } from "./concept.ts";

test("a template fallback is shown and is not a pass", () => {
  const status = {
    concept_degraded: true,
    concept_ok: false,
    concept_text_source: "template_fallback",
  };
  assert.equal(conceptIsDegraded(status), true);
  assert.match(conceptNotice(status) ?? "", /模板兜底/);
});

test("ok false is degraded even without the fallback label", () => {
  const status = { concept_ok: false, concept_text_source: "" };
  assert.equal(conceptIsDegraded(status), true);
  assert.match(conceptNotice(status) ?? "", /未通过/);
});

test("a missing marker is not called a fallback", () => {
  assert.equal(conceptIsDegraded({}), false);
  assert.equal(conceptNotice({ concept_ok: null }), null);
});
