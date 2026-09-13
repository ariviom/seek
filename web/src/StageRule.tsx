import type { Stage } from "./api";
import { stageFill, stageLabels } from "./ui";

// Finished Videos fill the rule from its zero end, like work marked off along a tape.
const order: Stage[] = ["done", "embedded", "segmented", "transcript_fetched", "discovered", "failed", "excluded"];

export function StageRule({ counts, detailed }: { counts: Record<Stage, number>; detailed: boolean }) {
  const shown = order.filter((stage) => counts[stage] > 0);
  const total = shown.reduce((sum, stage) => sum + counts[stage], 0);
  const summary = shown.map((stage) => `${counts[stage]} ${stageLabels[stage].toLowerCase()}`).join(", ");

  return (
    <div>
      <div
        role="img"
        aria-label={total === 0 ? "No Videos yet" : summary}
        className={`relative flex overflow-hidden rounded-[2px] bg-rule/70 ${detailed ? "h-4" : "h-2.5"}`}
      >
        {shown.map((stage) => (
          <span
            key={stage}
            className={`h-full ${stageFill[stage]} transition-[width] duration-700 ease-out motion-reduce:transition-none`}
            style={{ width: `${(counts[stage] / total) * 100}%` }}
          />
        ))}
        <span aria-hidden className="rule-ticks pointer-events-none absolute inset-0" />
      </div>
      {!detailed && shown.length > 0 && <p className="mt-1 text-[13px] text-pencil">{summary}</p>}
      {detailed && shown.length > 0 && (
        <ul className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[13px] text-pencil">
          {shown.map((stage) => (
            <li key={stage} className="flex items-center gap-1.5">
              <span aria-hidden className={`size-2.5 rounded-[1px] ${stageFill[stage]}`} />
              <span>
                <span className="font-condensed text-[15px] font-semibold text-ink tabular-nums">{counts[stage]}</span>{" "}
                {stageLabels[stage].toLowerCase()}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
