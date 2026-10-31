"use client";

import { useEffect, useState } from "react";

type ShareBody = {
  role: string;
  sentence: string;
  status: string;
  phase: string;
  message: string;
  shots: { shot_id: string; index: number; duration_s?: number; voiceover?: string }[];
  ai_label: boolean;
  download_allowed: boolean;
  has_film: boolean;
};

/** 公开只读页：不需要登录，只能看，不能改。 */
export function ShareView({ token }: { token: string }) {
  const [body, setBody] = useState<ShareBody | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void (async () => {
      try {
        const response = await fetch(`/v1/share-links/${encodeURIComponent(token)}`);
        if (!response.ok) {
          setError(response.status === 404 ? "分享链接无效或已失效" : "打不开这条分享");
          return;
        }
        setBody((await response.json()) as ShareBody);
      } catch {
        setError("打不开这条分享");
      }
    })();
  }, [token]);

  return (
    <main data-theme="dark" className="min-h-dvh bg-stage px-4 py-10 text-text-1">
      <div className="mx-auto w-full max-w-195">
        <p className="text-caption tracking-widest text-text-3">HiLatv · 只读分享</p>
        {error ? (
          <p className="mt-6 text-body text-danger">{error}</p>
        ) : !body ? (
          <p className="mt-6 text-small text-text-3">正在打开</p>
        ) : (
          <>
            <h1 className="mt-3 text-h1 font-medium">{body.sentence || "未命名项目"}</h1>
            <p className="mt-2 text-small text-text-2">
              {body.status} {body.phase ? `· ${body.phase}` : ""} {body.message ? `· ${body.message}` : ""}
            </p>
            <section className="mt-8">
              <h2 className="text-h2 font-medium">分镜</h2>
              <ul className="mt-3 grid gap-2 sm:grid-cols-2">
                {body.shots.map((shot) => (
                  <li key={shot.shot_id} className="rounded-lg border border-border bg-surface p-3">
                    <p className="text-small text-text-1">第 {shot.index} 镜</p>
                    <p className="mt-1 text-caption text-text-2">{shot.voiceover || "（无旁白）"}</p>
                    <p className="mt-1 text-caption text-text-3">
                      {typeof shot.duration_s === "number" ? `${shot.duration_s.toFixed(1)} 秒` : "时长待定"}
                    </p>
                  </li>
                ))}
              </ul>
              {body.shots.length === 0 ? <p className="mt-2 text-small text-text-3">还没有分镜。</p> : null}
            </section>
            <p className="mt-8 text-caption text-text-2">
              {body.ai_label ? "本片含 AI 生成内容（AI生成标识不可关闭）" : ""}
            </p>
            <p className="mt-2 text-caption text-text-3">
              {body.download_allowed ? "可以下载成片（由项目负责人提供）。" : "分享者设置了禁止下载。"}
            </p>
          </>
        )}
      </div>
    </main>
  );
}
