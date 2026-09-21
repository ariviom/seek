import type { EngineName, ModelChoice } from "@/lib/api";

// Mirrors engines.py: the Anthropic API takes full model ids and the Claude CLI aliases, and a value from one
// table is never offered to the other engine.
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

export const modelChoices: ModelChoice[] = ["fast", "deep"];
export const choiceNames: Record<ModelChoice, string> = { fast: "Fast", deep: "Deep" };

// The engine's own name for a model. A Conversation can hold a pin the active engine doesn't offer, so an
// unknown value is shown as stored rather than lost.
export function modelName(model: string, engine: EngineName | null): string {
  const known = engine === null ? [...engineModels.api, ...engineModels.cli] : engineModels[engine];
  return known.find((m) => m.value === model)?.name ?? model;
}

// The name, marked when this model is what one of the two defaults runs.
export function modelLabel(model: string, engine: EngineName | null): string {
  const choice = engine === null ? undefined : modelChoices.find((c) => defaultModels[engine][c] === model);
  return choice === undefined ? modelName(model, engine) : `${modelName(model, engine)} (${choice})`;
}

// What "fast" or "deep" means on the engine that would answer; just the choice while no engine can.
export function choiceLabel(choice: ModelChoice, engine: EngineName | null): string {
  return engine === null ? choiceNames[choice] : modelLabel(defaultModels[engine][choice], engine);
}

// The bare model a choice runs, for wording that already says which choice it is; empty while no engine can answer.
export function choiceModelName(choice: ModelChoice, engine: EngineName | null): string {
  return engine === null ? "" : modelName(defaultModels[engine][choice], engine);
}

// A Conversation's model, saying whether it is pinned or following the default setting: the two behave
// differently on the next question, so they never read the same.
export function conversationModel(
  model: string | null,
  choice: ModelChoice,
  engine: EngineName | null,
): string {
  return model === null ? `Default: ${choiceLabel(choice, engine)}` : `Pinned: ${modelLabel(model, engine)}`;
}
