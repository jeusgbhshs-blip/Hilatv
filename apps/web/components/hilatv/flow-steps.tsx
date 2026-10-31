"use client";

import { useEffect, useRef, useState } from "react";

import { FLOW_STEPS } from "@/lib/home-entries";
import { cn } from "@/lib/utils";

/** Three beats from a sentence to a finished film. The dashed line is the only blue. */
export function FlowSteps() {
  const ref = useRef<HTMLDivElement>(null);
  const [lit, setLit] = useState(0);

  useEffect(() => {
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce) {
      setLit(FLOW_STEPS.length);
      return;
    }
    const node = ref.current;
    if (!node) return;
    const timers: number[] = [];
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (!entry?.isIntersecting) return;
        FLOW_STEPS.forEach((_, index) => {
          timers.push(window.setTimeout(() => setLit(index + 1), index * 320));
        });
        observer.disconnect();
      },
      { threshold: 0.35 },
    );
    observer.observe(node);
    return () => {
      observer.disconnect();
      for (const timer of timers) window.clearTimeout(timer);
    };
  }, []);

  return (
    <section aria-labelledby="how-it-works" className="border-t border-border px-4 py-16 md:px-6">
      <div className="mx-auto w-full max-w-270">
        <h2 id="how-it-works" className="text-center text-h1 font-medium tracking-wide">
          三步出片
        </h2>
        <p className="mt-3 text-center text-body text-text-2">从一句话到成片，全程在一张画布上完成</p>
        <div
          ref={ref}
          className={cn("flow-steps relative mt-12", lit > 0 && "is-in")}
          data-testid="home-flow"
        >
          <svg
            className="pointer-events-none absolute top-1/2 hidden h-1 w-full -translate-y-1/2 md:block"
            aria-hidden="true"
            preserveAspectRatio="none"
          >
            <line className="flow-line" x1="0" y1="2" x2="100%" y2="2" />
            <line className="flow-run" x1="0" y1="2" x2="100%" y2="2" />
          </svg>
          <ol className="relative grid gap-6 md:grid-cols-3">
            {FLOW_STEPS.map((step, index) => (
              <li
                key={step.title}
                className={cn(
                  "flow-node rounded-md border border-border bg-surface p-4",
                  index < lit && "is-lit",
                )}
              >
                <div className="flex items-center justify-between">
                  <p className="text-body font-medium">{step.title}</p>
                  <span className="step-dot size-2 rounded-full" aria-hidden="true" />
                </div>
                {step.kind === "sentence" ? (
                  <p className="mt-3 min-h-24 text-small text-text-2">{step.body}</p>
                ) : null}
                {step.kind === "board" ? (
                  <div className="mt-3 grid min-h-24 grid-cols-3 gap-1" aria-hidden="true">
                    {Array.from({ length: 6 }, (_, cell) => (
                      <span key={cell} className="rounded-xs bg-hover" />
                    ))}
                  </div>
                ) : null}
                {step.kind === "film" ? (
                  <div className="mt-3 flex min-h-24 items-end" aria-hidden="true">
                    <div className="film-meter w-full">
                      <i />
                    </div>
                  </div>
                ) : null}
                <p className="mt-3 text-caption text-text-3">{step.note}</p>
              </li>
            ))}
          </ol>
        </div>
      </div>
    </section>
  );
}
