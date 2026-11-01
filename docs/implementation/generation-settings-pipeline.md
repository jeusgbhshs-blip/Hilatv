# Generation settings: planning and provider boundaries

Explicit primary frame and whole-film time are persisted user intent. New requests
also resolve automatic time from the brief; historical requests without the new
settings object retain their previous clock. N4 copy length and N5 shot allocation
use an optional `story_duration_s` after packaging reservation, while Brief keeps
the whole-film target. Their original 5% quality thresholds remain unchanged.
N6, music, packaging and composition share the production clock. A changed timing
or frame remains subject to the existing exact-media delivery gate.

N8 and N3 carry the target ratio into image calls. Seedream pixel-mode sizes make
the desired frame explicit; pricing preflight uses exactly that normalized size
without reading private references. Existing operator-verified size bounds remain
required and are not silently expanded. Mock image/video bytes and URIs now vary
with frame geometry. Candidate records retain requested ratios and source URIs.

Seedance's documented native ratios are used directly. Supported first-frame
routes can use adaptive for other supported HiLatv shapes: the actual first/last
frame is fitted with neutral padding to the target, retaining every source edge.
Unsupported text-to-video requests fail before submission. Reference data stays
private at the provider boundary and out of logs. No live supplier calls were made.

Primary API references used to check these contracts:

- [Seedream image generation API](https://docs.volcengine.com/docs/ark/image-generation-api?lang=en)
- [Seedance task API](https://docs.byteplus.com/en/docs/modelark/create-video-generation-task-api?redirect=1)

Tests compare actual encoded PNG/MP4 shapes, preserve distinct colored reference
corners, inspect provider payloads and bound parameters, and exercise N4→N5 story
budget with the original quality checks. The coordinator runs full integration and
browser verification after combining media and API work.
