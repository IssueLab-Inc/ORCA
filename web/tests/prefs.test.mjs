import assert from "node:assert/strict";
import { readdir, readFile } from "node:fs/promises";
import test from "node:test";
import { compiled } from "./app-host.mjs";

const prefs = await import(await compiled("../src/prefs.ts"));

/** A browser's Storage, enough for the page: a Map behind the methods prefs.ts calls. */
function storage(entries = {}) {
  const m = new Map(Object.entries(entries));
  return { map: m, getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => { m.set(k, String(v)); },
    removeItem: (k) => { m.delete(k); } };
}
/** A private window's: every call throws. */
const refusing = () => ({ getItem() { throw new Error("SecurityError"); }, setItem() { throw new Error("QuotaExceededError"); },
  removeItem() { throw new Error("SecurityError"); } });

function withStorage(local, session, fn) {
  const before = { local: Object.getOwnPropertyDescriptor(globalThis, "localStorage"), session: Object.getOwnPropertyDescriptor(globalThis, "sessionStorage") };
  globalThis.localStorage = local;
  globalThis.sessionStorage = session;
  try { return fn(); } finally {
    for (const [name, d] of [["localStorage", before.local], ["sessionStorage", before.session]]) {
      if (d) Object.defineProperty(globalThis, name, d); else delete globalThis[name];
    }
  }
}

/** Every key the page kept before prefs.ts, by the name it had: none may change, or what people saved is lost. */
const TODAY = {
  session: "sightline.session", requirements: "sightline.requirements", reviewer: "sightline.reviewer", owner: "sightline.owner",
  leftWidth: "sightline.left-w", rightWidth: "sightline.right-w", triageCompact: "sightline.triage.compact",
  handsFree: "sightline.voice.handsfree", agentSetup: "sightline.agent.setup", fly: "sightline.views.fly",
  viewLayout: "sightline.views.layout", snap: "sightline.measure.snap", measureAt: "sightline.measure.at",
  workings: "sightline.workings", dockProperties: "sightline.dock.properties", dockLayout: "sightline.dock.v1",
  dockClassic: "sightline.dock.classic", editCarry: "orca.edit.carry",
};

test("every key keeps the name it had, and says whose it is and where it lives", () => {
  assert.deepEqual(prefs.KEYS, TODAY);
  assert.deepEqual(Object.keys(prefs.REGISTRY).sort(), Object.keys(TODAY).sort());
  for (const [name, entry] of Object.entries(prefs.REGISTRY)) {
    assert.ok(["person", "device", "project", "tab"].includes(entry.scope), name);
    assert.equal(entry.area, entry.scope === "tab" ? "session" : "local", `${name}: only a tab's key is in sessionStorage`);
  }
  // docs/accounts.md, "Preferences": what follows the person, what stays on the device, what waits for projects.
  const by = (scope) => Object.keys(prefs.REGISTRY).filter((k) => prefs.REGISTRY[k].scope === scope).sort();
  assert.deepEqual(by("device"), ["dockLayout", "handsFree", "leftWidth", "measureAt", "rightWidth"]);
  assert.deepEqual(by("project"), ["requirements", "session"]);
  assert.deepEqual(by("tab"), ["editCarry"]);
  assert.deepEqual(prefs.familyKey("views", "Northbank"), "sightline.views.Northbank");
  assert.deepEqual(prefs.familyKey("filters", "Northbank"), "sightline.filters.Northbank");
  assert.deepEqual(prefs.familyKey("signoffs", "clash:s1"), "sightline.signoffs:clash:s1");
  assert.deepEqual(prefs.familyKey("signoffsByTitle", "Coordination"), "sightline.signoffs.Coordination");
  assert.ok(Object.values(prefs.FAMILIES).every((f) => f.scope === "project"));
});

test("text and JSON go in and come back, each key in its own storage", () => {
  const local = storage(), session = storage();
  withStorage(local, session, () => {
    prefs.pref.set("viewLayout", "two");
    assert.equal(prefs.pref.get("viewLayout"), "two");
    assert.equal(local.map.get("sightline.views.layout"), "two");
    prefs.pref.set("editCarry", "1");
    assert.equal(session.map.get("orca.edit.carry"), "1");
    assert.equal(local.map.has("orca.edit.carry"), false);
    prefs.pref.setJSON("workings", { on: false, view: "steps" });
    assert.deepEqual(prefs.pref.getJSON("workings"), { on: false, view: "steps" });
    assert.equal(local.map.get("sightline.workings"), '{"on":false,"view":"steps"}');
    prefs.setJSON(prefs.familyKey("views", "P"), { home: null, saved: [] });
    assert.deepEqual(prefs.getJSON("sightline.views.P"), { home: null, saved: [] });
    prefs.pref.remove("viewLayout");
    assert.equal(prefs.pref.get("viewLayout"), null);
    prefs.removeItem("sightline.views.P");
    assert.equal(local.map.has("sightline.views.P"), false);
    assert.equal(prefs.getItem("orca.edit.carry", "session"), "1");
  });
});

test("junk, a missing key, a refusing storage or none at all read as nothing and never throw", () => {
  withStorage(storage({ "sightline.workings": "{not json", "sightline.owner": "null" }), storage(), () => {
    assert.equal(prefs.pref.getJSON("workings"), null);
    assert.equal(prefs.pref.getJSON("owner"), null);
    assert.equal(prefs.pref.get("fly"), null);
  });
  withStorage(refusing(), refusing(), () => {
    assert.equal(prefs.pref.get("fly"), null);
    assert.equal(prefs.pref.getJSON("session"), null);
    prefs.pref.set("fly", "0");
    prefs.pref.setJSON("session", { scene_id: "x" });
    prefs.pref.remove("session");
    prefs.pref.set("editCarry", "1");
  });
  withStorage(undefined, undefined, () => {
    assert.equal(prefs.storage(), null);
    assert.equal(prefs.storage("session"), null);
    assert.equal(prefs.pref.get("reviewer"), null);
    prefs.pref.set("reviewer", "Ana");
    prefs.setJSON("k", 1n);   // not JSON: nothing kept, nothing thrown
  });
});

test("storage is looked up at each call, so one installed after import is used", () => {
  const later = storage({ "sightline.reviewer": "Ana" });
  withStorage(later, storage(), () => {
    assert.equal(prefs.pref.get("reviewer"), "Ana");
    assert.equal(prefs.storage(), later);
  });
  withStorage(undefined, undefined, () => assert.equal(prefs.pref.get("reviewer"), null));
});

test("nothing in web/src but prefs.ts touches the browser's storage", async () => {
  const root = new URL("../src/", import.meta.url);
  const files = (await readdir(root, { recursive: true })).filter((f) => /\.(ts|tsx)$/.test(f));
  const touching = [];
  for (const f of files) {
    if (f === "prefs.ts") continue;
    const text = await readFile(new URL(f, root), "utf8");
    if (/\b(localStorage|sessionStorage)\b/.test(text)) touching.push(f);
  }
  assert.deepEqual(touching, [], "use prefs.ts (and add the key to its registry)");
});

test("every stored key the page names is in the registry", async () => {
  const root = new URL("../src/", import.meta.url);
  const files = (await readdir(root, { recursive: true })).filter((f) => /\.(ts|tsx)$/.test(f) && f !== "prefs.ts");
  const known = new Set(Object.values(prefs.KEYS));
  const prefixes = Object.values(prefs.FAMILIES).map((f) => f.prefix);
  const strays = [];
  for (const f of files) {
    const text = await readFile(new URL(f, root), "utf8");
    for (const [, key] of text.matchAll(/["'`]((?:sightline|orca)\.[\w.:-]+)["'`]/g)) {
      if (!known.has(key) && !prefixes.some((p) => key.startsWith(p))) strays.push(`${f}: ${key}`);
    }
  }
  assert.deepEqual(strays, [], "a storage key outside prefs.ts's registry");
});
