/** Coordination requirements in the browser (server: requirements.py; docs/requirements.md): kept in this browser,
 *  downloaded and uploaded as a file, edited a cell at a time. Pure functions, so the panel and App share them. */
import type { Pattern, PatternVerdict, ReqCheck, ReqMover, Requirements, Strictness } from "./api";

export const FORMAT = "orca-requirements/1";
const STORE = "sightline.requirements";
export const STRICTNESS: Strictness[] = ["lenient", "relaxed", "balanced", "strict", "exacting"];
export const STRICTNESS_NAME: Record<Strictness, string> = {
  lenient: "Lenient", relaxed: "Relaxed", balanced: "Balanced", strict: "Strict", exacting: "Exacting",
};
export const LEVEL_NAME: Record<number, string> = { 1: "Concept", 2: "Developed", 3: "Coordinated", 4: "Production", 5: "As-built" };

/** What this browser keeps: the file, and whether it is in use (off is ORCA's defaults, the file stays). */
export interface Saved { doc: Requirements; enabled: boolean }

export function load(storage: Pick<Storage, "getItem"> | null = safeStorage()): Saved | null {
  try {
    const raw = storage?.getItem(STORE);
    if (!raw) return null;
    const v = JSON.parse(raw) as Saved;
    return v && v.doc && v.doc.format === FORMAT ? { doc: v.doc, enabled: !!v.enabled } : null;
  } catch { return null; }  // private window, or something else wrote the key
}

export function save(saved: Saved | null, storage: Pick<Storage, "setItem" | "removeItem"> | null = safeStorage()) {
  try {
    if (saved) storage?.setItem(STORE, JSON.stringify(saved));
    else storage?.removeItem(STORE);
  } catch { /* private window */ }
}

function safeStorage(): Storage | null {
  try { return typeof localStorage === "undefined" ? null : localStorage; } catch { return null; }
}

/** "L3 · Strict": the level and strictness, short. */
export function shortLabel(doc: Pick<Requirements, "level" | "strictness">): string {
  return `L${doc.level} · ${STRICTNESS_NAME[doc.strictness] ?? doc.strictness}`;
}

export function fileName(doc: Requirements): string {
  const base = (doc.name || "coordination requirements").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "requirements";
  return `${base}.orca-requirements.json`;
}

/** The file as text: what Download writes and Upload reads back. */
export function serialise(doc: Requirements): string {
  return JSON.stringify({ ...doc, format: FORMAT }, null, 2);
}

/** A file someone chose: ORCA requirements or an error saying why not. */
export function parseUpload(text: string): Requirements {
  let v: unknown;
  try { v = JSON.parse(text); } catch { throw new Error("That file is not JSON."); }
  if (!v || typeof v !== "object") throw new Error("That file is not a requirements file.");
  const d = v as Partial<Requirements>;
  if (d.format !== FORMAT) throw new Error(`Not an ORCA requirements file (expected format "${FORMAT}").`);
  if (!Array.isArray(d.groups)) throw new Error("The file has no groups.");
  return d as Requirements;
}

export function download(doc: Requirements) {
  const blob = new Blob([serialise(doc)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = fileName(doc);
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** The check between two groups (b null: a group against itself), either way round. */
export function cellFor(doc: Requirements, a: string, b: string | null): ReqCheck | undefined {
  return doc.checks.find((c) => (b === null || b === a)
    ? c.a === a && (c.b === null || c.b === a)
    : (c.a === a && c.b === b) || (c.a === b && c.b === a));
}

/** A copy with one cell changed (added when missing), marked as the user's; the version goes up once per edit. */
export function setCell(doc: Requirements, a: string, b: string | null, patch: Partial<ReqCheck>): Requirements {
  const same = b === null || b === a;
  const found = cellFor(doc, a, same ? null : b);
  const next: ReqCheck = { a, b: same ? null : b, check: "hard", clearance_mm: null, tolerance_mm: null, reason: "",
                           ...found, ...patch, source: "user" };
  if (next.check === "clearance" && next.clearance_mm == null) next.clearance_mm = 25;
  const checks = found ? doc.checks.map((c) => (c === found ? next : c)) : [...doc.checks, next];
  return bump({ ...doc, checks });
}

export function setMover(doc: Requirements, group: string, patch: Partial<ReqMover>): Requirements {
  const has = doc.who_moves.some((m) => m.group === group);
  const who_moves = has ? doc.who_moves.map((m) => (m.group === group ? { ...m, ...patch } : m))
    : [...doc.who_moves, { group, edits: "any" as const, max_move_mm: null, trims: true, ...patch }];
  return bump({ ...doc, who_moves });
}

/** Move a group up (-1) or down (+1) the who-moves order. */
export function shiftMover(doc: Requirements, index: number, by: -1 | 1): Requirements {
  const to = index + by;
  if (to < 0 || to >= doc.who_moves.length) return doc;
  const who_moves = [...doc.who_moves];
  [who_moves[index], who_moves[to]] = [who_moves[to], who_moves[index]];
  return bump({ ...doc, who_moves });
}

/** A by-design rule from an Insights pattern Muse read as by design: its two classes meet on purpose. */
export function addByDesign(doc: Requirements, pattern: Pick<Pattern, "classes">, verdict?: Pick<PatternVerdict, "cause" | "rule">): Requirements {
  const [a, b] = pattern.classes;
  if (!a || !b || hasByDesign(doc, pattern)) return doc;
  const reason = (verdict?.cause || verdict?.rule || "").slice(0, 240);
  return bump({ ...doc, by_design: [...doc.by_design, { a_classes: [a], b_classes: [b], reason, source: "triage" }] });
}

export function hasByDesign(doc: Requirements | null, pattern: Pick<Pattern, "classes">): boolean {
  const [a, b] = pattern.classes;
  return !!doc?.by_design.some((r) => (r.a_classes.includes(a) && r.b_classes.includes(b)) || (r.a_classes.includes(b) && r.b_classes.includes(a)));
}

export function removeByDesign(doc: Requirements, index: number): Requirements {
  return bump({ ...doc, by_design: doc.by_design.filter((_, i) => i !== index) });
}

function bump(doc: Requirements): Requirements {
  return { ...doc, version: (doc.version || 1) + 1 };
}
