# HP06 owner preview and formal delivery

The film player and “保存预览” read the authenticated private preview routes. Only the current file's server `ready` status, true quality verdict and live provenance permit “下载成片”; master approval is never inherited by another export. Invalid, empty, failed or non-media responses remain errors. Preview filenames have a `preview-` prefix.

The current master is the initial file selection. A changed master hash returns to that file. Existing exports remain explicitly selectable and never carry the current edit index or editable master timeline. Their independent delivery gates refresh every three seconds without replacing a Blob URL when bytes are unchanged. Exporting more versions remains available. The owner can keep watching an earlier valid preview while a new render runs.

Authenticated Blob requests use normal identity headers. Failed playback exposes a reload action; aborted/unmounted requests cannot leak a Blob URL or automatically save after leaving the page. Read errors downgrade the displayed delivery state. Share copy explains missing restricted previews without promising that a browser can prevent screen recording.

Validation: 30 Node tests and 45 Vitest tests passed; TypeScript and targeted ESLint passed. New evidence tests cover selected-file isolation, stale crop hints versus the release gate, metadata parsing, and external-path rejection. Coordinator runs the combined build, API tests and browser flow after integration. Live model quality and the P1 final-review implementation remain separate work.
