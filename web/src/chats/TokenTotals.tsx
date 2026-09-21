import type { TokenUsage } from "@/lib/api";
import { formatCount } from "@/lib/format";

// What this Conversation's turns reported, and nothing else: no price, no estimate for what a provider never
// said. `complete` is false when a turn ended before all its usage arrived, or reported none at all — an older
// Conversation, or one that failed or was stopped — so the totals read as the floor they are.
export function TokenTotals({ usage }: { usage: TokenUsage | null }) {
  if (usage === null) return null;
  const counted = usage.input_tokens + usage.output_tokens + usage.cache_read_tokens;
  if (counted === 0) {
    if (usage.complete) return null;
    return (
      <p className="text-center text-[11px] text-muted-foreground">
        Token usage wasn’t recorded for this chat.
      </p>
    );
  }
  return (
    <p className="text-center text-[11px] text-muted-foreground">
      {usage.complete ? "Tokens: " : "Tokens: at least "}
      {formatCount(usage.input_tokens)} in · {formatCount(usage.output_tokens)} out ·{" "}
      {formatCount(usage.cache_read_tokens)} cache read
      {usage.complete ? "" : " — some of this chat’s turns didn’t report what they used"}.
    </p>
  );
}
