/** The name of the AI model behind each role, as the server reports it (`/api/models` labels: meta_client.labels), for
 * the words on screen. App sets them once it has asked; until then, the defaults ORCA ships with. */

export type AiRole = "proposal" | "escalation" | "triage" | "image" | "voice";
export type AiNames = Record<AiRole, string>;

export const DEFAULT_AI_NAMES: AiNames = {
  proposal: "Muse Spark", escalation: "Muse Wonder", triage: "Muse Spark", image: "Muse Image", voice: "Muse Voice Transcribe",
};

let names: AiNames = DEFAULT_AI_NAMES;

export function setAiNames(given: Partial<AiNames> | undefined): AiNames {
  names = { ...DEFAULT_AI_NAMES, ...(given ?? {}) };
  return names;
}

/** The model a role runs on, by name ("Muse Spark"). */
export function aiName(role: AiRole): string {
  return names[role];
}
