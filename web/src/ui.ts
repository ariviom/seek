import { useState } from "react";
import { errorText, type Stage } from "./api";

export const inputClass =
  "rounded-[3px] border border-rule bg-white px-3 py-1.5 text-[15px] text-ink placeholder:text-pencil/70 focus:border-machine focus:ring-2 focus:ring-machine/20 focus:outline-none";
export const buttonClass =
  "rounded-[3px] bg-machine px-3.5 py-1.5 text-[15px] font-medium text-white hover:bg-machine-deep disabled:opacity-45";
export const outlineButtonClass =
  "rounded-[3px] border border-machine px-3 py-1 text-[15px] font-medium text-machine hover:bg-machine hover:text-white disabled:opacity-45";
export const quietButtonClass =
  "rounded-[3px] px-2 py-1 text-[15px] text-pencil hover:bg-ink/5 hover:text-ink disabled:opacity-45";
export const dangerButtonClass =
  "rounded-[3px] px-2 py-1 text-[15px] text-oxide hover:bg-oxide/10 disabled:opacity-45";
export const sectionHeadingClass = "font-condensed text-[1.75rem] leading-none font-semibold";
export const alertClass = "mt-3 rounded-[3px] border-l-4 border-oxide bg-oxide/10 px-3 py-2 text-sm text-oxide";
export const hintClass = "text-sm text-pencil";

// Runs one change at a time; resolves true when the change itself succeeded.
export type Act = (change: () => Promise<unknown>) => Promise<boolean>;

// Callers disable their controls while busy, so changes and their refreshes never interleave.
export function useChanges(refresh: () => Promise<void>, setError: (message: string | null) => void) {
  const [busy, setBusy] = useState(false);

  const act: Act = async (change) => {
    setError(null);
    setBusy(true);
    try {
      await change();
    } catch (e) {
      setError(errorText(e));
      return false;
    } finally {
      await refresh();
      setBusy(false);
    }
    return true;
  };

  return { act, busy };
}

export const stageLabels: Record<Stage, string> = {
  discovered: "Discovered",
  transcript_fetched: "Transcript fetched",
  segmented: "Segmented",
  embedded: "Embedded",
  done: "Done",
  failed: "Failed",
  excluded: "Excluded",
};

// Pipeline stages darken from pale to tape yellow to machine green as a Video nears done.
export const stageFill: Record<Stage, string> = {
  discovered: "bg-[#c9cec6]",
  transcript_fetched: "bg-[#efd592]",
  segmented: "bg-tape",
  embedded: "bg-[#8f9a4a]",
  done: "bg-machine",
  failed: "bg-oxide",
  excluded: "bg-[repeating-linear-gradient(135deg,#aab0a8_0_2px,transparent_2px_5px)]",
};
