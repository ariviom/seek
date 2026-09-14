import type { Selection } from "@/lib/url-state";
import { SyncPage, SyncsEmpty } from "./SyncPage";

export function SyncsMain({ selection }: { selection: Selection }) {
  if (selection.sync === undefined) return <SyncsEmpty />;
  return <SyncPage syncId={selection.sync} />;
}
