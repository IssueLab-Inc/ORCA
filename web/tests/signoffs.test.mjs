import assert from "node:assert/strict";
import test from "node:test";
import { appHost, compiled } from "./app-host.mjs";

const s = await import(await compiled("../src/signoffs.ts", {}));

/** A browser's localStorage, enough for the page: a Map behind the Storage methods it calls. */
function storage(entries = {}) {
  const m = new Map(Object.entries(entries));
  return { map: m, get length() { return m.size; }, key: (i) => [...m.keys()][i] ?? null,
    getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => { m.set(k, String(v)); }, removeItem: (k) => { m.delete(k); } };
}
const review = { team: "MEP", name: "Ana", decision: "approve", note: "", at: "2026-10-30T10:00:00Z" };
const run = (over = {}) => ({ id: "r1", title: "Coordination · 2 models", sources: ["B.ifc", "A.ifc"], origin: "sightline",
  requirements_id: null, clashes: [], ...over });

test("an imported report keeps its sign-offs by its id, never by its title", () => {
  const a = s.signoffKeyOf({ id: "abc", title: "northbank", sources: ["x.xml"], origin: "navisworks" });
  const b = s.signoffKeyOf({ id: "def", title: "northbank", sources: ["x.xml"], origin: "navisworks" });
  assert.equal(a, "sightline.signoffs:report:abc");
  assert.notEqual(a, b);
  assert.equal(s.signoffKeyOf({ id: "abc", title: "t", sources: [] }), a);  // no origin: an imported report
  assert.equal(s.signoffKeyOf(null), null);
});

test("a detection run keeps them by its models and requirements, so a rerun shares them and nothing else does", () => {
  const first = s.signoffKeyOf(run());
  assert.equal(s.signoffKeyOf(run({ id: "r2" })), first);                              // a rerun: a new report id
  assert.equal(s.signoffKeyOf(run({ id: "r3", sources: ["A.ifc", "B.ifc"] })), first);  // the same files in another order
  assert.notEqual(s.signoffKeyOf(run({ sources: ["A.ifc", "C.ifc"] })), first);         // other models, same title
  assert.notEqual(s.signoffKeyOf(run({ requirements_id: "0123456789abcdef" })), first); // other requirements
  assert.notEqual(s.signoffKeyOf(run({ requirements_id: "0123456789abcdef" })), s.signoffKeyOf(run({ requirements_id: "fedcba9876543210" })));
  assert.ok(!first.startsWith("sightline.signoffs."));  // never taken for a title-keyed one
});

test("saving drops clashes with no review left, and the key with them; loading survives junk", () => {
  globalThis.localStorage = storage();
  try {
    const key = s.signoffKeyOf(run());
    s.saveSignoffs(key, { s1: [review], s2: [] });
    assert.deepEqual(JSON.parse(localStorage.getItem(key)), { s1: [review] });
    assert.deepEqual(s.loadSignoffs(key), { s1: [review] });
    s.saveSignoffs(key, { s1: [] });
    assert.equal(localStorage.getItem(key), null);
    localStorage.setItem(key, "[1, 2]");
    assert.deepEqual(s.loadSignoffs(key), {});
    localStorage.setItem(key, "{not json");
    assert.deepEqual(s.loadSignoffs(key), {});
    assert.deepEqual(s.loadSignoffs(null), {});
  } finally { delete globalThis.localStorage; }
  assert.deepEqual(s.loadSignoffs("k"), {});  // no storage at all (a private window): nothing, no throw
  s.saveSignoffs("k", { s1: [review] });
  s.dropTitleKeyed();
});

test("title-keyed sign-offs are dropped; the new keys and other settings stay", () => {
  const kept = s.signoffKeyOf(run());
  globalThis.localStorage = storage({ "sightline.signoffs.Coordination · 4 models": "{}", "sightline.signoffs.northbank": "{}",
    [kept]: "{}", "sightline.reviewer": "Ana", "sightline.session": "{}" });
  try {
    s.dropTitleKeyed();
    assert.deepEqual([...localStorage.map.keys()].sort(), [kept, "sightline.reviewer", "sightline.session"].sort());
  } finally { delete globalThis.localStorage; }
});

test("the page shows each run its own sign-offs, writes new ones under its key and drops the old ones", async () => {
  const clash = { id: "s1", number: 1, name: "Duct × Girder", a: {}, b: {}, images: [] };
  const mine = run({ clashes: [clash] });
  const other = run({ id: "r9", sources: ["X.ifc", "Y.ifc"], clashes: [clash] });  // same title and clash id
  globalThis.localStorage = storage({ [s.signoffKeyOf(mine)]: JSON.stringify({ s1: [review] }),
    "sightline.signoffs.Coordination · 2 models": JSON.stringify({ s1: [{ ...review, name: "Someone else" }] }) });
  try {
    const host = await appHost({ initial: { report: mine, clash } });
    assert.deepEqual(host.state.signoffs, { s1: [review] });
    assert.equal(localStorage.getItem("sightline.signoffs.Coordination · 2 models"), null);
    const block = host.component("ReviewBlock");
    block.props.onAdd({ ...review, team: "Structure", name: "Ben" });
    host.render();
    assert.deepEqual(JSON.parse(localStorage.getItem(s.signoffKeyOf(mine))).s1.map((r) => r.name), ["Ana", "Ben"]);
    host.unmount();

    const elsewhere = await appHost({ initial: { report: other, clash } });
    assert.deepEqual(elsewhere.state.signoffs, {});
    elsewhere.unmount();
  } finally { delete globalThis.localStorage; }
});
