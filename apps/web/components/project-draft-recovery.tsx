"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import type { ProjectDraft } from "@/lib/project-draft";
import type { useProjectDraft } from "@/lib/use-project-draft";
import { settingsSummary } from "@/lib/generation-settings";

function DraftContents({ draft }: { draft: ProjectDraft }) {
  return <div className="mt-2 space-y-2 text-small">
    <p className="whitespace-pre-wrap break-words text-text-1">{draft.sentence || "还没有输入文字"}</p>
    <p className="text-caption text-text-3">{draft.skip_storyboard ? "直接出片" : "先看分镜"}</p>
    <p className="text-caption text-text-3">{settingsSummary(draft.generation_settings)}</p>
    {draft.files.length || draft.links.length ? <ul className="space-y-1 text-text-2" aria-label="这个版本的附件">
      {draft.files.map((item) => <li className="break-all" key={item.id}>{item.file.name} · {item.uploaded ? "已上传" : "保留在本机"}</li>)}
      {draft.links.map((item) => <li className="break-all" key={item.id}>{item.uri}</li>)}
    </ul> : <p className="text-caption text-text-3">没有附件</p>}
  </div>;
}

export function ProjectDraftRecovery({ drafts, busy = false }: { drafts: ReturnType<typeof useProjectDraft>; busy?: boolean }) {
  const [actionError, setActionError] = useState<string | null>(null);
  useEffect(() => setActionError(null), [drafts.identity]);
  async function act(action: () => Promise<unknown>) {
    const current = drafts.ticket();
    setActionError(null);
    try { await action(); }
    catch (caught) { if (current()) setActionError(caught instanceof Error ? caught.message : "恢复未完成，原输入仍保留"); }
  }
  const locked = busy || drafts.saving || drafts.resolving;
  return <div className="mt-3 space-y-3">
    {drafts.error && !drafts.conflict ? <div role="alert" className="rounded-md border border-border bg-surface p-3 text-small text-danger">
      <p>{drafts.error}</p>
      <div className="mt-2 flex flex-wrap gap-2">
        {!drafts.ready ? <Button type="button" variant="secondary" disabled={locked} onClick={() => void act(drafts.retryRestore)}>重新恢复草稿</Button>
          : <Button type="button" variant="secondary" disabled={locked} onClick={() => void act(drafts.flush)}>重新保存</Button>}
        {drafts.ready && drafts.draft.project_id ? <Button type="button" variant="secondary" disabled={locked} onClick={() => void act(drafts.inspectServer)}>核对服务器版本</Button> : null}
      </div>
    </div> : null}
    {drafts.conflict ? <section aria-label="核对草稿版本" className="rounded-md border border-border-strong bg-surface p-4">
      <h2 className="text-h3 font-medium">这份草稿有两个版本</h2>
      <p role="alert" className="mt-2 text-small text-text-2">请核对文字、附件、比例和时长。采用服务器版本前，会先保留可恢复的本地副本。</p>
      <div className="mt-3 grid gap-4 sm:grid-cols-2">
        <div className="min-w-0 rounded-sm border border-border p-3"><h3 className="text-small font-medium">我的本地修改</h3><DraftContents draft={drafts.draft} /></div>
        <div className="min-w-0 rounded-sm border border-border p-3"><h3 className="text-small font-medium">服务器已保存的内容</h3><DraftContents draft={drafts.conflict} /></div>
      </div>
      {drafts.conflict.submission_pending ? <p className="mt-3 text-small text-text-2">这个项目已经提交，不能再覆盖草稿。你的本地修改仍保留，请打开原项目核对。</p> : <div className="mt-3 flex flex-wrap gap-2">
        <Button type="button" variant="secondary" disabled={locked} onClick={() => void act(() => drafts.resolveConflict("server"))}>采用服务器版本，保留本地副本</Button>
        <Button type="button" disabled={locked} onClick={() => void act(() => drafts.resolveConflict("mine"))}>用我的修改继续保存</Button>
      </div>}
    </section> : null}
    {(drafts.draft.submission_pending || drafts.conflict?.submission_pending) && drafts.draft.project_id ? <div role="status" className="rounded-md border border-border bg-surface p-3 text-small text-text-2">
      <p>原提交的文字、附件、生成设置和操作编号会用于同一次确认。请查看这个项目，避免重复新建。</p>
      <Button type="button" variant="secondary" className="mt-2 mr-3" disabled={locked} onClick={() => void act(drafts.inspectServer)}>核对服务器状态</Button>
      <Link className="mt-2 inline-flex min-h-11 items-center text-text-1 underline" href={`/projects/${encodeURIComponent(drafts.draft.project_id)}`}>打开这个项目</Link>
    </div> : null}
    {drafts.backups.length ? <details className="rounded-md border border-border bg-surface p-3">
      <summary className="cursor-pointer text-small text-text-2">已保留的本地副本（{drafts.backups.length}）</summary>
      <ul className="mt-3 space-y-3">{drafts.backups.map((backup) => <li key={backup.id} className="rounded-sm border border-border p-3">
        <p className="text-caption text-text-3">{backup.reason} · {new Date(backup.created_at).toLocaleString()}</p>
        <DraftContents draft={backup.draft} />
        <Button type="button" variant="secondary" className="mt-2" disabled={!drafts.editable || locked} onClick={() => void act(() => drafts.restoreBackup(backup))}>恢复这份副本并核对</Button>
      </li>)}</ul>
    </details> : null}
    {actionError ? <p role="alert" className="text-small text-danger">{actionError}</p> : null}
  </div>;
}
