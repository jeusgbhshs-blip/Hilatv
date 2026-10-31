"use client";

import { useState } from "react";

const LESSONS = [
  {
    title: "一句话出片：从输入到成片",
    minutes: 3,
    body: "在首页写清楚：给谁看、卖什么、多长、什么风格。点生成后会依次跑需求理解、脚本、分镜、关键帧、视频、配音、字幕、包装和合成。跑完在成片页可以播放和下载。",
  },
  {
    title: "在专家画布里改一镜",
    minutes: 5,
    body: "从项目里打开画布，镜头卡上有生成器：改「这一镜的话」或「补充提示词」，点「生成这一镜」只会重做这一镜，其他镜头不动，重生次数从同一个账本扣。",
  },
  {
    title: "用图片节点生成素材",
    minutes: 4,
    body: "空白画布双击加「图片节点」，写提示词点生成；「✦ 专业功能」里有九宫格多机位、剧情推演四宫格、角色三视图等模板，选中会填好提示词再生成。",
  },
  {
    title: "把工作流存进工具箱",
    minutes: 2,
    body: "框选两个以上节点（按住 Cmd 点选），底部会出现「打组存入工具箱」。下次在别的项目里打开工具箱点「套用」，节点和连线会重新搭出来。",
  },
  {
    title: "人工放行是怎么回事",
    minutes: 2,
    body: "自动出片会在「画面未评审」时停下等你确认，这是交付前的质检门。确认没问题后点「人工放行，继续出片」，系统再合成最终成片。",
  },
];

/** 学院：教程正文先放标注「示例」的占位内容，等市场营销部给正式稿再替换。 */
export function AcademyIndex() {
  const [open, setOpen] = useState<number | null>(0);
  return (
    <div className="mx-auto w-full max-w-195">
      <header>
        <h1 className="text-h1 font-medium tracking-wide">学院</h1>
        <p className="mt-2 text-small text-text-2">几分钟学会用 HiLatv 出好片。当前教程正文是示例稿。</p>
      </header>
      <ul className="mt-8 grid gap-3">
        {LESSONS.map((lesson, index) => (
          <li key={lesson.title} className="rounded-lg border border-border bg-surface">
            <button
              type="button"
              className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left"
              aria-expanded={open === index}
              onClick={() => setOpen(open === index ? null : index)}
            >
              <span className="text-body text-text-1">{lesson.title}</span>
              <span className="shrink-0 text-caption text-text-3">约 {lesson.minutes} 分钟</span>
            </button>
            {open === index ? (
              <div className="border-t border-border px-4 py-3">
                <p className="text-small text-text-2">{lesson.body}</p>
                <p className="mt-2 text-caption text-text-3">示例内容，正式版本以市场营销部提供的文案为准。</p>
              </div>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  );
}
