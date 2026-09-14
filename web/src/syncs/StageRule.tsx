import type { Stage } from "@/lib/api";
import { stageLabels } from "@/lib/format";

// Finished Videos fill the rule from its zero end, like work marked off along a tape.
const order: Stage[] = ["done", "embedded", "segmented", "transcript_fetched", "discovered", "failed", "excluded"];

export const stageFill: Record<Stage, string> = {
  done: "bg-emerald-500",
  embedded: "bg-emerald-500/60",
  segmented: "bg-amber-400",
  transcript_fetched: "bg-amber-300",
  discovered: "bg-zinc-400",
  failed: "bg-red-500",
  excluded: "bg-[repeating-linear-gradient(135deg,var(--muted-foreground)_0_2px,transparent_2px_5px)] opacity-50",
};

export function StageRule({ counts, detailed }: { counts: Record<Stage, number>; detailed: boolean }) {
  const shown = order.filter((stage) => counts[stage] > 0);
  const total = shown.reduce((sum, stage) => sum + counts[stage], 0);
  const summary = shown.map((stage) => `${counts[stage]} ${stageLabels[stage].toLowerCase()}`).join(", ");

  return (
    <div>
      <div
        role="img"
        aria-label={total === 0 ? "No Videos yet" : summary}
        className={`flex overflow-hidden rounded-full bg-muted ${detailed ? "h-2" : "h-1.5"}`}
      >
        {shown.map((stage) => (
          <span
            key={stage}
            className={`h-full ${stageFill[stage]} transition-[width] duration-700 ease-out motion-reduce:transition-none`}
            style={{ width: `${(counts[stage] / total) * 100}%` }}
          />
        ))}
      </div>
      {detailed && shown.length > 0 && (
        <ul className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
          {shown.map((stage) => (
            <li key={stage} className="flex items-center gap-1.5">
              <span aria-hidden className={`size-2 rounded-[2px] ${stageFill[stage]}`} />
              <span>
                <span className="font-medium tabular-nums text-foreground">{counts[stage]}</span>{" "}
                {stageLabels[stage].toLowerCase()}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
