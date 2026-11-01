import { Check } from "lucide-react";

import { Progress } from "@/components/ui/progress";
import { cn } from "@/lib/utils";
import { STAGES, stageIndex, stageShort } from "@/lib/status-copy";

/**
 * DESIGN.md §9.2 StageStepper. Five steps, no node numbers.
 * Desktop: the whole row. Phone: "3/5 看分镜" and a thin bar; the other
 * steps stay in the list for screen readers but are not drawn.
 */
export function StageStepper({
  stage,
  complete = false,
  className,
}: {
  stage: string;
  /** Mark the last step as finished too (the film is ready). */
  complete?: boolean;
  className?: string;
}) {
  const current = stageIndex(stage);
  return (
    <div className={cn("min-w-0", className)}>
      <ol aria-label="进度" className="flex min-w-0 items-center gap-1 md:gap-2">
        {STAGES.map((item, index) => {
          const active = index === current;
          const done = index < current || (complete && active);
          return (
            <li
              key={item}
              aria-current={active ? "step" : undefined}
              data-state={done ? "done" : active ? "current" : "todo"}
              className={cn(
                "items-center gap-1.5 text-small",
                active ? "flex text-text-1" : "hidden md:flex",
                !active && (done ? "text-text-2" : "text-text-3"),
              )}
            >
              <span
                aria-hidden="true"
                className={cn(
                  "hidden size-4.5 shrink-0 items-center justify-center rounded-full text-micro md:flex",
                  active && !done && "bg-blue text-primary-foreground",
                  done && "bg-hover text-text-2",
                  !active && !done && "border border-border-strong",
                )}
              >
                {done ? <Check className="size-3" /> : active ? index + 1 : null}
              </span>
              <span aria-hidden="true" className="tabular text-text-3 md:hidden">
                {stageShort(item)}
              </span>
              <span className="whitespace-nowrap">{item}</span>
              {index < STAGES.length - 1 ? (
                <span aria-hidden="true" className="ml-1 hidden h-px w-3 bg-border-strong lg:block" />
              ) : null}
            </li>
          );
        })}
      </ol>
      <Progress className="mt-1.5 md:hidden" value={complete ? 1 : (current + 1) / STAGES.length} label="创作阶段" valueText={`第 ${current + 1}/${STAGES.length} 阶段：${STAGES[current]}`} />
    </div>
  );
}
