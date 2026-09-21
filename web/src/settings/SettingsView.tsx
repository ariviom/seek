import { useCallback, useEffect, useState, type ReactNode } from "react";
import { api, errorText, type CredentialStatus, type EngineName, type Health, type ModelChoice, type Settings } from "@/lib/api";
import { useServerEvents } from "@/lib/events";
import { choiceModelName, choiceNames, modelChoices } from "@/lib/models";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { describeEngine, describeModel, engineLabels, engineNames, modelLabels, modelRoles } from "@/shell/Notices";

const KEYS_URL = "https://console.anthropic.com/settings/keys";
// Sent as a null engine, which hands the choice back to Mentor.
const automatic = "automatic";

function Section({ title, description, children }: { title: string; description: string; children: ReactNode }) {
  return (
    <section className="space-y-3 rounded-xl border bg-card p-4">
      <div className="space-y-1">
        <h2 className="text-sm font-medium">{title}</h2>
        <p className="text-xs leading-5 text-muted-foreground">{description}</p>
      </div>
      {children}
    </section>
  );
}

// Everything a friend owns: which engine answers, the key it needs, and the model it runs by default.
// Ports, paths and ingestion knobs stay in the config file and are deliberately absent.
export function SettingsView({
  health,
  settings,
  onSettings,
}: {
  health: Health | null;
  settings: Settings | null;
  // The saved preferences, so the rest of the app follows without a reload.
  onSettings: (settings: Settings) => void;
}) {
  const [saving, setSaving] = useState<"engine" | "model" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const active = health?.chat.active ?? null;

  async function save(field: "engine" | "model", patch: Partial<Settings>) {
    setSaving(field);
    setError(null);
    try {
      onSettings(await api.updateSettings(patch));
    } catch (e) {
      setError(errorText(e));
    } finally {
      setSaving(null);
    }
  }

  return (
    // Named, so what belongs to the friend is one region of the page rather than loose cards.
    <section aria-label="Settings" className="space-y-4">
      <p className="text-sm text-muted-foreground">
        Your preferences, kept on this machine. Ports, directories and ingestion options belong to whoever runs
        Mentor and stay in its config file.
      </p>
      {error !== null && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      <Section
        title="Chat engine"
        description="Which engine answers your questions. Search, the Library and Syncs never need one."
      >
        {/* The trigger shows the choice itself, so its name comes from aria-label rather than a second
            copy of the heading beside it. */}
        <div className="flex items-center gap-2">
          <Select
            value={settings?.engine ?? automatic}
            disabled={settings === null || saving !== null}
            onValueChange={(value) =>
              void save("engine", { engine: value === automatic ? null : (value as EngineName) })
            }
          >
            <SelectTrigger size="sm" aria-label="Chat engine">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={automatic}>Whichever is ready</SelectItem>
              {engineNames.map((name) => (
                <SelectItem key={name} value={name}>
                  {engineLabels[name]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <dl className="grid gap-1 text-xs">
          {engineNames.map((name) => (
            <div key={name} className="flex min-w-0 gap-2">
              <dt className="w-32 shrink-0 text-muted-foreground">
                {engineLabels[name]}
                {name === active && " (answering)"}
              </dt>
              <dd className="min-w-0 break-words">
                {health === null ? "checking…" : describeEngine(health.chat.engines[name])}
              </dd>
            </div>
          ))}
        </dl>
        {health !== null && health.chat.active === null && (
          <p className="text-xs text-destructive">
            No engine can answer yet. Add an Anthropic API key below, or install the Claude CLI and log in with{" "}
            <code>claude login</code>.
          </p>
        )}
        {health !== null &&
          settings?.engine != null &&
          health.chat.engines[settings.engine].state !== "ready" && (
            <p className="text-xs text-destructive">
              You chose {engineLabels[settings.engine]}, which can’t answer yet. Mentor won’t quietly use the other
              engine instead.
            </p>
          )}
      </Section>

      <KeySection />

      <Section
        title="Default model"
        description="What a chat runs unless it pinned a model of its own. A chat following the default picks this up on its next question."
      >
        <div className="flex items-center gap-2">
          <Select
            value={settings?.model ?? "fast"}
            disabled={settings === null || saving !== null}
            onValueChange={(value) => void save("model", { model: value as ModelChoice })}
          >
            <SelectTrigger size="sm" aria-label="Default model">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {modelChoices.map((choice) => (
                <SelectItem key={choice} value={choice}>
                  {choiceNames[choice]}
                  {active !== null && ` — ${choiceModelName(choice, active)}`}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <p className="text-xs text-muted-foreground">
          {active === null
            ? "The model each choice runs depends on the engine that answers."
            : `On the ${engineLabels[active]}: fast runs ${choiceModelName("fast", active)}, deep runs ${choiceModelName("deep", active)}.`}
        </p>
      </Section>

      <Section
        title="Models on this machine"
        description="How search and ingestion are running here. These follow your hardware and aren’t a setting."
      >
        <dl className="grid gap-1 text-xs">
          {modelRoles.map((role) => {
            const status = health?.models[role];
            return (
              <div key={role} className="flex min-w-0 gap-2">
                <dt className="w-32 shrink-0 text-muted-foreground first-letter:uppercase">{modelLabels[role]}</dt>
                <dd className="min-w-0 break-words">
                  {status === undefined
                    ? "checking…"
                    : `${status.name} — ${describeModel(status)}${status.state === "failed" && status.error ? `: ${status.error}` : ""}`}
                </dd>
              </div>
            );
          })}
        </dl>
      </Section>
    </section>
  );
}

function validityNote(status: CredentialStatus): string {
  if (!status.present) return "No key saved yet.";
  switch (status.validity) {
    case "valid":
      return "A key is saved, and Anthropic accepted it.";
    case "invalid":
      return "The saved key was rejected. Replace it with a working one.";
    case "unverified":
      return "A key is saved, but Anthropic hasn’t confirmed it yet. Mentor will use it as it stands.";
  }
}

// The key is written to the server and never read back, and nothing here keeps it in the browser: the box is
// cleared as soon as it has been sent.
function KeySection() {
  const [status, setStatus] = useState<CredentialStatus | null>(null);
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState<"saving" | "deleting" | null>(null);
  const [outcome, setOutcome] = useState<{ tone: "ok" | "bad"; message: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);

  const load = useCallback(async () => {
    try {
      setStatus(await api.credentialStatus());
      setError(null);
    } catch (e) {
      // An unreadable credential store still allows replacement and deletion, so the section stays usable.
      setStatus(null);
      setError(errorText(e));
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);
  useServerEvents((event) => {
    if (event.type === "credentials" || event.type === "ready") void load();
  });

  async function saveKey() {
    const entered = key.trim();
    if (entered === "" || busy !== null) return;
    setBusy("saving");
    setOutcome(null);
    setError(null);
    try {
      const saved = await api.saveKey(entered);
      setKey("");
      setStatus(saved);
      setOutcome(
        saved.validity === "valid"
          ? { tone: "ok", message: "Key accepted. Chat can use the Anthropic API now." }
          : saved.validity === "invalid"
            ? { tone: "bad", message: "Anthropic rejected that key. Check you copied all of it, and that it is still active." }
            : { tone: "bad", message: "Saved, but Anthropic didn’t answer, so the key hasn’t been checked yet." },
      );
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(null);
    }
  }

  async function deleteKey() {
    setBusy("deleting");
    setOutcome(null);
    setError(null);
    try {
      setStatus(await api.deleteKey());
      setOutcome({ tone: "ok", message: "Key deleted." });
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(null);
    }
  }

  return (
    <Section
      title="Anthropic API key"
      description="Needed for the Anthropic API engine. Mentor stores it outside the knowledge base and never shows it again."
    >
      <p className="text-xs" role="status">
        {status === null ? "Checking the stored key…" : validityNote(status)}
      </p>
      {status !== null && (status.store === "file" || status.fallback_reason !== null) && (
        <p className="text-xs text-amber-600 dark:text-amber-500">
          {status.fallback_reason ??
            "The key is in a private file in Mentor’s data directory, readable only by your user account."}
        </p>
      )}
      {error !== null && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      {outcome !== null && (
        <Alert variant={outcome.tone === "ok" ? "default" : "destructive"}>
          <AlertDescription>{outcome.message}</AlertDescription>
        </Alert>
      )}
      <form
        className="flex flex-wrap items-center gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          void saveKey();
        }}
      >
        <Input
          type="password"
          className="w-full min-w-0 sm:w-80"
          aria-label="Anthropic API key"
          placeholder={status?.present ? "Paste a replacement key" : "sk-ant-…"}
          value={key}
          onChange={(event) => setKey(event.target.value)}
          spellCheck={false}
          autoComplete="off"
        />
        <Button type="submit" size="sm" disabled={key.trim() === "" || busy !== null}>
          {busy === "saving" ? "Checking your key…" : status?.present ? "Replace key" : "Save key"}
        </Button>
        {status?.present && (
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={busy !== null}
            onClick={() => setConfirming(true)}
          >
            Delete key
          </Button>
        )}
      </form>
      <p className="text-xs text-muted-foreground">
        Create one at{" "}
        <a className="underline underline-offset-2" href={KEYS_URL} target="_blank" rel="noreferrer">
          {KEYS_URL}
        </a>
        . Anthropic bills the key directly; Mentor only reports the tokens each chat used.
      </p>
      <ConfirmDialog
        title="Delete key"
        actionLabel="Delete key"
        open={confirming}
        busy={busy !== null}
        onOpenChange={(open) => !open && setConfirming(false)}
        onConfirm={async () => {
          await deleteKey();
          setConfirming(false);
        }}
      >
        Chat stops using the Anthropic API until you add another key.
      </ConfirmDialog>
    </Section>
  );
}
