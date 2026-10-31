"use client";

import { EMPTY_FRAME_COPY } from "@/lib/canvas-contract";

export function FrameView({
  url,
  alt,
  testId,
}: {
  url?: string | null;
  alt: string;
  testId?: string;
}) {
  if (!url) {
    return (
      <div
        data-testid={testId ?? "frame-placeholder"}
        className="flex aspect-video w-full items-center justify-center rounded-sm bg-stage px-3 text-center text-caption text-text-3"
      >
        {EMPTY_FRAME_COPY}
      </div>
    );
  }
  return (
    // 占位和上传都是 data URL，不用 next/image。
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={url}
      alt={alt}
      data-testid={testId}
      className="aspect-video w-full rounded-sm bg-stage object-contain"
    />
  );
}
