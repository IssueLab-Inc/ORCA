// Adding models to the open scene and taking one out (docs/add-and-remove-models.md): what the page works out before
// it asks the server, and the words it says. No React, no viewer: App and the toolbar call these.
import type { JournalEntry } from "./api";

const STEP = /\.(step|stp)$/i;

/** Model positions shown hidden, after the one at `index` was taken out: it goes, every one after it moves down one. */
export function shiftHidden(hidden: Iterable<number>, index: number): number[] {
  return [...hidden].filter((i) => i !== index).map((i) => (i > index ? i - 1 : i));
}

/** Whether the open models are a STEP machine: every one came from STEP. */
export function isMachine(files: readonly string[], stepFiles: readonly string[]): boolean {
  return files.length > 0 && stepFiles.length === files.length;
}

/** The samples that may join the open models: not open already, and of their kind (STEP joins a machine, IFC joins
 * building models; the server refuses the rest in words too). */
export function addableSamples(samples: readonly string[], files: readonly string[], stepFiles: readonly string[]): string[] {
  const machine = isMachine(files, stepFiles);
  return samples.filter((f) => !files.includes(f) && STEP.test(f) === machine);
}

/** Why these files may not join the open models, as the server would say it, or null: a STEP machine among building
 * models or the reverse, a name already open. Checked here first so nothing is uploaded or charged for it. */
export function addRefusal(names: readonly string[], files: readonly string[], stepFiles: readonly string[]): string | null {
  const machine = isMachine(files, stepFiles);
  if (names.some((n) => STEP.test(n)) && !machine) return "A STEP machine can't join building models yet: open it on its own.";
  if (names.some((n) => !STEP.test(n)) && stepFiles.length) return "A building model can't join a STEP machine yet: open it on its own.";
  const open = names.find((n) => files.includes(n));
  return open ? `${open} is already open.` : null;
}

/** What ORCA is busy with that adding or removing a model must wait for, in words, or null. */
export function waitFor(work: { busy?: string | null; detecting?: boolean; proposing?: boolean; planning?: boolean;
  triage?: boolean }): string | null {
  if (work.proposing) return "Wait for the proposal to finish.";
  if (work.planning) return "Wait for the plan to finish.";
  if (work.triage) return "Wait for triage to finish.";
  if (work.detecting) return "Wait for the clash check to finish.";
  if (work.busy) return `Wait for ORCA to finish: ${work.busy.replace(/…$/, "").toLowerCase()}.`;
  return null;
}

/** The kept edits in the model at `index` (they go with it and can't be undone after). */
export function editsIn(entries: readonly JournalEntry[], index: number): number {
  return entries.filter((e) => e.state === "kept" && !e.model_removed && e.files.includes(index)).length;
}

/** The clashes in the list with an element of the file `name`. */
export function clashesWith(clashes: readonly { a: { file?: string | null }; b: { file?: string | null } }[], name: string): number {
  return clashes.filter((c) => c.a.file === name || c.b.file === name).length;
}

const plural = (n: number, one: string, many = `${one}s`) => `${n.toLocaleString()} ${n === 1 ? one : many}`;

/** What removing a model takes with it, asked before it goes: "Remove Northbank-Structure? Its 2 kept edits and the 118
 * clashes with it go too. Export first to keep the edits." */
export function removalWarning(name: string, clashes: number, edits: number): string {
  const ask = `Remove ${name.replace(/\.(ifc|step|stp)$/i, "")}?`;
  const kept = `${plural(edits, "kept edit")}`, found = `${plural(clashes, "clash", "clashes")} with it`;
  const goes = (one: boolean) => (one ? "goes" : "go");
  if (edits && clashes) return `${ask} Its ${kept} and the ${found} go too. Export first to keep the edits.`;
  if (edits) return `${ask} Its ${kept} ${goes(edits === 1)} too. Export first to keep the edits.`;
  if (clashes) return `${ask} The ${found} ${goes(clashes === 1)} too.`;
  return `${ask} Nothing kept goes with it.`;
}
