/** Everything the page keeps in the browser, in one place (docs/accounts.md, "Preferences"). Every read and write of
 *  `localStorage` or `sessionStorage` goes through here, so each key's scope is written down once: a setting that will
 *  follow the person when they sign in, one that stays with this device, one that belongs to a project, or one for this
 *  tab only. Nothing is sent anywhere yet: this is the browser's storage, as before.
 *
 *  Storage is looked up at each call, never kept from import: a private window (or a test that installs a storage
 *  later) simply does without, and no read or write ever throws. */

/** Who a key belongs to. `person`: follows the person once accounts sync it. `device`: sizes and positions that depend
 *  on this screen or microphone. `project`: belongs to a set of models (saved projects will take these). `tab`: this tab
 *  only (`sessionStorage`). */
export type Scope = "person" | "device" | "project" | "tab";
export type Area = "local" | "session";

/** Every fixed key: the stored names never change, so nothing anyone has saved is lost. */
export const KEYS = {
  session: "sightline.session",            // the session to resume (App)
  requirements: "sightline.requirements",  // the requirements file and whether it is in use (reqFile)
  reviewer: "sightline.reviewer",          // the reviewer's name on sign-offs (ReportDoc, App)
  owner: "sightline.owner",                // the owner's own settings, sent as X-Sightline-Settings (Owner)
  leftWidth: "sightline.left-w",           // the side panes' widths (App)
  rightWidth: "sightline.right-w",
  triageCompact: "sightline.triage.compact",  // the Triage card folded (Triage)
  handsFree: "sightline.voice.handsfree",  // hands-free voice (Chat)
  agentSetup: "sightline.agent.setup",     // this browser has made an agent link (Agent)
  fly: "sightline.views.fly",              // fly to a clash (App)
  viewLayout: "sightline.views.layout",    // Single, Two or Quad (App)
  snap: "sightline.measure.snap",          // snapping while measuring (App)
  measureAt: "sightline.measure.at",       // where the Measure panel was dragged to (App)
  workings: "sightline.workings",          // Workings on or off, and the Activity panel's view (App)
  dockProperties: "sightline.dock.properties",  // where Properties opens (dock)
  dockLayout: "sightline.dock.v1",         // the desktop's panel layout (dockLayout)
  dockClassic: "sightline.dock.classic",   // the Classic layout (dockLayout, App)
  editCarry: "orca.edit.carry",            // the Edit tool's joined toggle, this tab only (EditTool)
} as const;
export type Key = keyof typeof KEYS;

export const REGISTRY: Record<Key, { scope: Scope; area: Area }> = {
  session: { scope: "project", area: "local" },
  requirements: { scope: "project", area: "local" },
  reviewer: { scope: "person", area: "local" },
  owner: { scope: "person", area: "local" },
  leftWidth: { scope: "device", area: "local" },
  rightWidth: { scope: "device", area: "local" },
  triageCompact: { scope: "person", area: "local" },
  handsFree: { scope: "device", area: "local" },
  agentSetup: { scope: "person", area: "local" },
  fly: { scope: "person", area: "local" },
  viewLayout: { scope: "person", area: "local" },
  snap: { scope: "person", area: "local" },
  measureAt: { scope: "device", area: "local" },
  workings: { scope: "person", area: "local" },
  dockProperties: { scope: "person", area: "local" },
  dockLayout: { scope: "device", area: "local" },
  dockClassic: { scope: "person", area: "local" },
  editCarry: { scope: "tab", area: "session" },
};

/** Keys made from a prefix and a name. A project is `About.projectName` of its files; `sightline.views.` shares its
 *  prefix with the fixed `fly` and `layout` keys above, as it always has. */
export const FAMILIES = {
  views: { prefix: "sightline.views.", scope: "project" },        // Home and the saved views, per project (App)
  filters: { prefix: "sightline.filters.", scope: "project" },    // the filters, per project (App)
  signoffs: { prefix: "sightline.signoffs:", scope: "project" },  // review sign-offs: per clash, or per imported report (signoffs)
  signoffsByTitle: { prefix: "sightline.signoffs.", scope: "project" },  // sign-offs kept by report title before Oct 30, moved on open
} as const satisfies Record<string, { prefix: string; scope: Scope }>;
export type Family = keyof typeof FAMILIES;

/** The key of a family's member: `familyKey("views", "Northbank")` is `sightline.views.Northbank`. */
export function familyKey(family: Family, name: string): string {
  return FAMILIES[family].prefix + name;
}

/** The browser's storage, or null where there is none (a private window that refuses it, a test without one). */
export function storage(area: Area = "local"): Storage | null {
  try {
    const s = area === "session" ? globalThis.sessionStorage : globalThis.localStorage;
    return s ?? null;
  } catch { return null; }
}

/** A key's text, or null when it is not there or storage is unavailable. */
export function getItem(key: string, area: Area = "local"): string | null {
  try { return storage(area)?.getItem(key) ?? null; } catch { return null; }
}

/** Keep a key's text; without storage it lasts this visit only (nothing is thrown). */
export function setItem(key: string, value: string, area: Area = "local"): void {
  try { storage(area)?.setItem(key, value); } catch { /* private window: kept for this visit */ }
}

export function removeItem(key: string, area: Area = "local"): void {
  try { storage(area)?.removeItem(key); } catch { /* private window */ }
}

/** A key's JSON, or null when it is missing, unreadable or not JSON (whatever else wrote it). */
export function getJSON<T = unknown>(key: string, area: Area = "local"): T | null {
  try { return JSON.parse(getItem(key, area) ?? "null") as T | null; } catch { return null; }
}

export function setJSON(key: string, value: unknown, area: Area = "local"): void {
  let text: string;
  try { text = JSON.stringify(value); } catch { return; }
  setItem(key, text, area);
}

/** A fixed key's text, in its own area. */
export const pref = {
  get: (name: Key) => getItem(KEYS[name], REGISTRY[name].area),
  set: (name: Key, value: string) => setItem(KEYS[name], value, REGISTRY[name].area),
  remove: (name: Key) => removeItem(KEYS[name], REGISTRY[name].area),
  getJSON: <T = unknown>(name: Key) => getJSON<T>(KEYS[name], REGISTRY[name].area),
  setJSON: (name: Key, value: unknown) => setJSON(KEYS[name], value, REGISTRY[name].area),
};
