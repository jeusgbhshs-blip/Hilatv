# Generation settings: media geometry and whole-film duration

Explicit settings are a whole-film promise. The selected duration includes the opening and closing cards, at 30 fps. A 15-second selection with the default direct hook and 2.4-second closing card therefore reserves 378 body frames and 72 closing frames. Missing `target_duration_s` retains the legacy timing policy; this work does not change SPEC thresholds.

The default ending reserves at least four seconds for the story, preserving N5's existing minimum. At five seconds it uses four seconds of story plus a one-second ending; at six seconds it uses four plus two. An explicit ending override is never silently shortened, and a budget that leaves less than four seconds of story fails. Opening/ending overrides of zero are actual zero, not a request to restore the template default.

## Internal contracts

- `workers.media.timing.duration_budget(target_duration_s, intro_s=0, outro_s=None)` returns immutable total/intro/body/outro frame counts and corresponding `_s` properties. `None` ending uses the packaging template; explicit zero remains zero.
- N6 and N12 accept optional `target_duration_s`, `intro_s=0`, `outro_s=None`. N14 accepts the same target with optional opening/ending overrides. N15 accepts the target and its existing opening/ending fields. The workflow must forward the same reserved times to every consumer, and N4/N5 must plan against the body budget while retaining the user's whole-film Brief duration.
- N15 emits private `exports.clean_picture` plus the normal master/no-subtitle/no-voiceover files. The clean picture contains no raster overlays or audio; it shares the master's canvas and clock. It is an internal N17 input, not a new delivery permission.
- N17 accepts internal `picture_path` and `source_timeline` alongside `target_duration_s`, `intro_s`, `outro_s`. It can also resolve the private clean export/timeline from the current server N15 node record. An older burned master without a clean source is rejected before any gateway call; recomposition is required.

The public generation-settings schema, API, and workflow wiring are separate commits owned by the coordinating agents.

## Geometry

The shared canvas helper represents 16:9, 9:16, 1:1, 4:3, 3:4, 3:2, 2:3, 4:5, and 21:9 as exact rational dimensions with even pixels. Resolutions are bounded by the long edge, so a ratio such as 21:9 may use 1274×546 instead of falsely labelling a rounded 1280×548 frame as exact 21:9. N17 uses the same geometry helper.

Explicit width/height pairs must match the selected ratio. Global render dimensions apply only when they preserve that ratio and reduce the default size; stale landscape environment values cannot turn a portrait project into landscape. Legacy inputs without a ratio still accept their existing explicit/environment canvas.

N13 uses the short side for its base subtitle font. N14/N15 fit the actual raster text inside platform safe rectangles, retain real Logo proportions/transparency, and keep the canonical AI label's minimum measured ink height. Impossible tiny safe areas fail explicitly instead of clipping text. N17 rebuilds subtitles and brand overlays at its output ratio, using the clean picture rather than carrying old burned text into a new frame.

## Duration and speech

N6 fits actual decoded speech and picture holds to an exact body-frame allocation. Its existing maximum intelligible speed boost remains unchanged; an explicit budget uses stricter admission instead of permitting the legacy 5% overrun. Speech that still cannot fit is returned for copy shortening. It is never cut to a requested file duration.

N12 chooses feasible beat boundaries inside the immutable body budget. Its dynamic program can redistribute picture holds, but every shot retains enough frames for its actual audio. The requested music tempo is adjusted slightly before generation so a beat can land at the body/closing boundary; the returned bytes still undergo the existing independent beat/onset, loudness and ducking checks. The music mix covers the closing card and its licence-use duration records that full use. If the requested endpoint is also the end of the film (zero outro), it is not reported as a picture transition requiring a later beat sample.

N15 rejects a mismatched frame budget before replacing outputs. Explicit dissolves preserve the storyboard clock by padding the outgoing picture before their short overlap. Setting fps before padding is necessary after concat: without that, the unlettered source can end before the outro even though looping overlay inputs keep the lettered export alive. Actual clean-source decode and clock checks cover this case. The 80 ms beat threshold, loudness windows, ducking limits, ASR/CER and subtitle alignment limits remain unchanged.

N17 preserves the clean timeline's body source offsets and its actual intro/outro. It reburns only fresh layers, shifts narration/subtitle clocks by the reserved intro, and checks the actual decoded whole-file duration. A different explicit duration requires another planned story; this change does not silently cut a hook or accelerate an arbitrarily long translation. New exact-budget dubbing fails when a line cannot fit its shot. Older non-explicit exports retain their previous duration/localization policy.

## Evidence and limitations

All new media tests use original procedural PCM/pictures and fake, zero-cost gateway adapters. They prove real encoding, decoding, dimensions, audio content, safe geometry and clocks, not real supplier aspect support or speech/VLM accuracy. Mock/mixed/unknown media do not gain formal delivery permission from successful rendering. Exact-budget N17 variants remain `needs_review` and require independent per-file review/hash/source/rights evidence under the existing delivery gate.

The dedicated regression covers nine actual N17 export ratios, 4:3 and 9:16 complete N6→N12→N13→N14→N15 15-second movies including the outro, five/six-second movies with their real shortened default endings, actual AAC/PCM duration and content, a 15-second 4:3→9:16 N17 export, safe subtitles, unavailable clean sources, overlong speech, infeasible beat cuts, and retaining prior movie bytes on a failed duration request. An additional actual-film test measures at least eight decoded low-contrast picture cuts against independently decoded music onsets, including two dissolves, at the unchanged 80 ms limit.

Validation uses `HILATV_LIVE=0`, the shared project Python environment and isolated basetemp. No .env, service ports, vendor APIs, global installations, or SPEC values are modified.

Validation result: **271 passed**, three existing FastAPI/Temporal warnings, for N6/N12/N13/N14/N15/N17 plus workflow and fallback tests. The dedicated generation-media file contains 19 cases, including actual nine-ratio exports and five/six/fifteen-second decoded movies. Ruff check/format and whitespace checks also pass. The full regression log is stored outside the checkout at the workspace's `work/generation-media-tests.log`.
