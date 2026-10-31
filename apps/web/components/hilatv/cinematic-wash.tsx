"use client";

import { useEffect, useRef, useState } from "react";

function channel(hex: string, shift: number): number {
  const raw = hex.trim().replace("#", "");
  if (raw.length < 6) return 0;
  return (Number.parseInt(raw.slice(0, 6), 16) >> shift) & 255;
}

/**
 * One still frame of film grain, plus a paper-tinted light that drifts in CSS.
 * No blue, purple, or glow. The light does not move when motion is reduced.
 */
export function CinematicWash() {
  const ref = useRef<HTMLCanvasElement>(null);
  const [frozen, setFrozen] = useState(false);

  useEffect(() => {
    const canvas = ref.current;
    const parent = canvas?.parentElement;
    if (!canvas || !parent) return;
    const context = canvas.getContext("2d");
    if (!context) return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    setFrozen(reduce);

    const inkHex = getComputedStyle(parent).getPropertyValue("--bg").trim();
    if (!inkHex.startsWith("#") || inkHex.length < 7) return;
    const ink = [channel(inkHex, 16), channel(inkHex, 8), channel(inkHex, 0)];
    const tile = document.createElement("canvas");
    tile.width = 128;
    tile.height = 128;
    const tileContext = tile.getContext("2d");
    if (tileContext) {
      const image = tileContext.createImageData(128, 128);
      for (let pixel = 0; pixel < image.data.length; pixel += 4) {
        const value = Math.random() * 255;
        image.data[pixel] = value;
        image.data[pixel + 1] = value;
        image.data[pixel + 2] = value;
        image.data[pixel + 3] = 18;
      }
      tileContext.putImageData(image, 0, 0);
    }

    const draw = () => {
      const ratio = Math.min(window.devicePixelRatio || 1, 1.5);
      const width = Math.max(1, Math.floor(canvas.clientWidth * ratio));
      const height = Math.max(1, Math.floor(canvas.clientHeight * ratio));
      canvas.width = width;
      canvas.height = height;
      context.fillStyle = `rgb(${ink[0]},${ink[1]},${ink[2]})`;
      context.fillRect(0, 0, width, height);
      const pattern = tileContext ? context.createPattern(tile, "repeat") : null;
      if (pattern) {
        context.fillStyle = pattern;
        context.fillRect(0, 0, width, height);
      }
    };

    draw();
    window.addEventListener("resize", draw);
    return () => window.removeEventListener("resize", draw);
  }, []);

  return (
    <>
      <canvas
        ref={ref}
        data-testid="cinematic-wash"
        data-static={frozen ? "true" : "false"}
        className="pointer-events-none absolute inset-0 h-full w-full"
        aria-hidden="true"
      />
      <div className="home-lights pointer-events-none absolute inset-0" aria-hidden="true" />
    </>
  );
}
