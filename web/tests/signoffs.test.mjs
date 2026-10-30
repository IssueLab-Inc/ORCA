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

test("an imported report keeps them by its title and files, so opening it again finds them", () => {
  const a = s.signoffScope({ id: "abc", title: "northbank", sources: ["x.xml", "a.png"], origin: "navisworks" });
  assert.equal(s.signoffScope({ id: "def", title: "northbank", sources: ["a.png", "x.xml"], origin: "navisworks" }), a);
  assert.notEqual(s.signoffScope({ id: "abc", title: "northbank", sources: ["y.xml"], origin: "navisworks" }), a);
  assert.notEqual(s.signoffScope({ id: "abc", title: "other", sources: ["x.xml", "a.png"] }), a);  // no origin: imported
  assert.equal(s.signoffScope(null), null);
});

test("a detection run keeps them per clash id: a rerun, other requirements or fewer models open still find them", () => {
  globalThis.localStorage = storage();
  try {
    s.saveSignoffs(s.signoffScope(run()), { s1: [review] });
    const rerun = run({ id: "r2", requirements_id: "0123456789abcdef" });                 // a rerun under new rules
    assert.deepEqual(s.loadSignoffs(s.signoffScope(rerun), ["s1", "s2"]), { s1: [review] });
    const fewer = run({ id: "r3", sources: ["A.ifc"] });                                   // the same pair, one file less
    assert.deepEqual(s.loadSignoffs(s.signoffScope(fewer), ["s1"]), { s1: [review] });
    const elsewhere = run({ id: "r9", sources: ["X.ifc", "Y.ifc"] });                      // same title, other models
    assert.deepEqual(s.loadSignoffs(s.signoffScope(elsewhere), ["s7"]), {});                // their ids are their own
    assert.ok([...localStorage.map.keys()].every((k) => k.startsWith("sightline.signoffs:clash:")));
  } finally { delete globalThis.localStorage; }
});

test("saving drops clashes with no review left, and an import's key with them; loading survives junk", () => {
  globalThis.localStorage = storage();
  try {
    const imp = s.signoffScope({ title: "northbank", sources: ["x.xml"], origin: "navisworks" });
    s.saveSignoffs(imp, { c1: [review], c2: [] });
    assert.deepEqual(JSON.parse(localStorage.getItem(`sightline.signoffs:${imp}`)), { c1: [review] });
    assert.deepEqual(s.loadSignoffs(imp, ["c1", "c2"]), { c1: [review] });
    assert.deepEqual(s.loadSignoffs(imp, ["c2"]), {});                    // only the report's own clashes
    s.saveSignoffs(imp, { c1: [] });
    assert.equal(localStorage.getItem(`sightline.signoffs:${imp}`), null);
    const scope = s.signoffScope(run());
    s.saveSignoffs(scope, { s1: [review] });
    s.saveSignoffs(scope, { s1: [] });
    assert.equal(localStorage.getItem("sightline.signoffs:clash:s1"), null);
    localStorage.setItem(`sightline.signoffs:${imp}`, "[1, 2]");
    assert.deepEqual(s.loadSignoffs(imp, ["c1"]), {});
    localStorage.setItem("sightline.signoffs:clash:s1", "{not json");
    assert.deepEqual(s.loadSignoffs(scope, ["s1"]), {});
    assert.deepEqual(s.loadSignoffs(null, ["s1"]), {});
  } finally { delete globalThis.localStorage; }
  assert.deepEqual(s.loadSignoffs("run:[]", ["s1"]), {});  // no storage at all (a private window): nothing, no throw
  s.saveSignoffs("run:[]", { s1: [review] });
  s.migrateTitleKeyed(run({ clashes: [{ id: "s1" }] }));
});

test("title-keyed sign-offs move to the clashes a report has; the rest stay for theirs, newer ones win", () => {
  const ana = review, ben = { ...review, name: "Ben" }, cy = { ...review, name: "Cy" };
  globalThis.localStorage = storage({
    "sightline.signoffs.Coordination · 2 models": JSON.stringify({ s1: [ana], s2: [ben], s9: [cy] }),
    "sightline.signoffs:clash:s2": JSON.stringify([cy]), "sightline.reviewer": "Ana" });
  try {
    s.migrateTitleKeyed(run({ clashes: [{ id: "s1" }, { id: "s2" }] }));
    assert.deepEqual(JSON.parse(localStorage.getItem("sightline.signoffs:clash:s1")), [ana]);
    assert.deepEqual(JSON.parse(localStorage.getItem("sightline.signoffs:clash:s2")), [cy]);   // already there: kept
    assert.deepEqual(JSON.parse(localStorage.getItem("sightline.signoffs.Coordination · 2 models")), { s9: [cy] });
    s.migrateTitleKeyed(run({ id: "r9", sources: ["X.ifc"], clashes: [{ id: "s9" }] }));        // another project
    assert.equal(localStorage.getItem("sightline.signoffs.Coordination · 2 models"), null);
    assert.equal(localStorage.getItem("sightline.reviewer"), "Ana");
    localStorage.setItem("sightline.signoffs.northbank", JSON.stringify({ c0053: [ana] }));       // an imported report
    const imp = { id: "u1", title: "northbank", sources: ["x.xml"], origin: "navisworks", clashes: [{ id: "c0053" }] };
    s.migrateTitleKeyed(imp);
    assert.deepEqual(s.loadSignoffs(s.signoffScope(imp), ["c0053"]), { c0053: [ana] });
    assert.equal(localStorage.getItem("sightline.signoffs.northbank"), null);
  } finally { delete globalThis.localStorage; }
});

test("the page shows each run its own sign-offs, moves the old ones over and writes new ones per clash", async () => {
  const clash = { id: "s1", number: 1, name: "Duct × Girder", a: {}, b: {}, images: [] };
  const theirs = { ...clash, id: "s7" };   // another project's run: same title, its own clash ids
  const mine = run({ clashes: [clash] });
  const other = run({ id: "r9", sources: ["X.ifc", "Y.ifc"], clashes: [theirs] });
  globalThis.localStorage = storage({
    "sightline.signoffs.Coordination · 2 models": JSON.stringify({ s1: [review], s7: [{ ...review, name: "Someone else" }] }) });
  try {
    const host = await appHost({ initial: { report: mine, clash } });
    assert.deepEqual(host.state.signoffs, { s1: [review] });
    const block = host.component("ReviewBlock");
    block.props.onAdd({ ...review, team: "Structure", name: "Ben" });
    host.render();
    assert.deepEqual(JSON.parse(localStorage.getItem("sightline.signoffs:clash:s1")).map((r) => r.name), ["Ana", "Ben"]);
    host.unmount();

    const elsewhere = await appHost({ initial: { report: other, clash: theirs } });
    assert.deepEqual(elsewhere.state.signoffs, { s7: [{ ...review, name: "Someone else" }] });   // its own, not mine
    assert.equal(localStorage.getItem("sightline.signoffs.Coordination · 2 models"), null);
    elsewhere.unmount();
  } finally { delete globalThis.localStorage; }
});
