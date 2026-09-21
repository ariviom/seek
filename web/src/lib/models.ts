import type { EngineName, ModelChoice } from "@/lib/api";

// Display copies of engines.py's tables, which are the source of truth: the server resolves the model a turn
// actually asks for, and nothing here can change that. The Anthropic API takes full model ids and the Claude CLI
// aliases, and a value from one table is never offered to the other engine.
export const engineModels: Record<EngineName, { value: string; name: string }[]> = {
  api: [
    { value: "claude-sonnet-5", name: "Sonnet 5" },
    { value: "claude-opus-5", name: "Opus 5" },
  ],
  cli: [
    { value: "opus", name: "Opus" },
    { value: "sonnet", name: "Sonnet" },
    { value: "haiku", name: "Haiku" },
  ],
};

// Which model each engine runs for the fast and deep defaults.
export const defaultModels: Record<EngineName, Record<ModelChoice, string>> = {
  api: { fast: "claude-sonnet-5", deep: "claude-opus-5" },
  cli: { fast: "sonnet", deep: "opus" },
};

export const modelChoices = ["fast", "deep"] as const;
export const choiceNames: Record<ModelChoice, string> = { fast: "Fast", deep: "Deep" };

// Claude models an engine doesn't offer but a pin may still name: the CLI passes unknown names through, and
// engines.py translates these between the two vocabularies.
const otherNames: { value: string; name: string }[] = [{ value: "claude-haiku-4-5", name: "Haiku" }];

// The name a model is known by. A Conversation can hold a pin the active engine doesn't offer, so the other
// engine's vocabulary is searched too, and anything unknown is shown as stored rather than lost.
export function modelName(model: string, engine: EngineName | null): string {
  const first = engine === null ? [] : engineModels[engine];
  const known = [...first, ...engineModels.api, ...engineModels.cli, ...otherNames];
  return known.find((m) => m.value === model)?.name ?? model;
}

// The name, marked when this model is what one of the two defaults runs.
export function modelLabel(model: string, engine: EngineName | null): string {
  const choice = engine === null ? undefined : modelChoices.find((c) => defaultModels[engine][c] === model);
  return choice === undefined ? modelName(model, engine) : `${modelName(model, engine)} (${choice})`;
}

// What "fast" or "deep" means on the engine that would answer; just the choice while no engine can. A null
// choice is a default Mentor hasn't loaded yet, which is never guessed at.
export function choiceLabel(choice: ModelChoice | null, engine: EngineName | null): string {
  if (choice === null) return "your default";
  return engine === null ? choiceNames[choice] : modelLabel(defaultModels[engine][choice], engine);
}

// The bare model a choice runs on an engine, for wording that already says which choice it is.
export function choiceModelName(choice: ModelChoice, engine: EngineName): string {
  return modelName(defaultModels[engine][choice], engine);
}

// A Conversation's model, saying whether it is pinned or following the default setting: the two behave
// differently on the next question, so they never read the same.
export function conversationModel(
  model: string | null,
  choice: ModelChoice | null,
  engine: EngineName | null,
): string {
  return model === null ? `Default: ${choiceLabel(choice, engine)}` : `Pinned: ${modelLabel(model, engine)}`;
}
