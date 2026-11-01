# HP06 API: previews and verified delivery

Generation completion and formal delivery are separate. Public project, canvas
and version metadata derive `delivery_status`, `quality_pass`, `preview_available`,
`media_provenance`, `media_hash` and reasons from server readiness evidence. Internal
`media_path`, master/held/previous filesystem paths are not project DTO fields.
Project `deliverable` remains a compatibility field containing a download API path
only when the current file is actually ready.

Owner preview routes:

- `GET|HEAD /v1/projects/{project_id}/preview`
- `GET|HEAD /v1/projects/{project_id}/versions/{version_id}/preview`

Both accept the existing protected-media session query or bearer credential, check
enterprise ownership, and serve actual MP4 bytes with native Range/206 support,
inline disposition and `private, no-store`. Export versions and archived revision
masters are supported. The version DTO retains `download_path` and adds
`preview_path`; its geometry-only `qa_status` cannot establish `quality_pass`.
Canvas additionally returns saved `draft_revision` or null; no submission internals
are exposed. Existing Agent clients must save a modern draft before starting it.

Formal master/version downloads always assess the exact requested media. They
return 409 with public readiness reasons when incomplete, mocked, source-unknown,
unreviewed or invalidated by a human continuation. They do not return file bytes
on a failure. A master review is not inherited by an export with a different hash.
Mock exports can continue to produce owner previews without claiming delivery.
Archived masters use their archived state and manifest intent rather than current
draft flags, while current ownership, authorization and release revocations remain
in effect.

Before FileResponse opens a file asynchronously, the response pins the assessed
bytes into a private immutable hash-named copy and verifies the copied digest.
The response opens that copy rather than the mutable render/playback path. A
source change during copying fails closed; a later replacement cannot substitute
unreviewed bytes in an already authorized response. These bounded streaming copies
are reused by hash; they do not contain credentials or have a public static route.

Both existing share URL families retain their routes. Original media behind them
uses the same formal readiness gate. Version tokens also bind the exact hash and
owner; changed versions and revoked tokens cannot silently serve a new file.
Legacy version tokens without a bound owner/hash require reissue rather than an
unsafe bypass. Project share writes are atomic under the project lock.

`view_no_download` currently exposes only review metadata. It never returns original
media, even with Range or a known candidate ID. Metadata explicitly reports that a
restricted preview derivative has not been generated, and gives an owner-only
preview path with that explanation. This does not claim to prevent screen capture;
a full review/share experience and visibly marked derivatives remain HP21 work.

The regression suite uses rendered real MP4s, actual HTTP Range bytes, enterprise
credentials, server evidence fixtures and controlled original-file replacement.
Simulated verifier records establish permission mechanics, not commercial model
quality. No provider request or paid generation is performed.

Validation: all API and expert tests pass (**158 cases**, including 14 new
permission/preview/Range/replacement cases). Python lint passes. Formatting passes
for API-owned files; the upstream HP06 implementation document has a Python-code
fence formatting fix coordinated with the pipeline audit patch. The final combined
gate must be rerun after that evidence-contract patch is integrated.
