import assert from "node:assert/strict";
import test from "node:test";
import { appHost, compiled, find, hasText } from "./app-host.mjs";

/** Kept checks (docs/detection.md, "Kept checks"): ORCA keeps each check's latest run for the open models, and the list
 * holds every kept check's clashes, one row per clash; a picker narrows it to one check. */

const filters = await compiled("../src/filters.ts", {});
const checks = await import(await compiled("../src/checks.ts", { "./filters": filters }));

const FIRST = { new: [], resolved: [], no_longer_checked: [], first: true };
const kept = (key, name, extra = {}) => ({ key, name, title: `Coordination · ${name}`, tests: null, requirements: null, revision: 0,
  stale: false, ran_at: 1, seconds: 1, elements: 2, coverage: [], diff: FIRST, clashes: 1, ...extra });
const MODELS = kept("models", "The open models");
const DUCTS = kept("filter:abc", "Ducts vs Everything", { tests: [{ id: "filter:abc" }] });
const row = (id, number, found) => ({ id, number, name: id, title: null, test: Object.values(found)[0], checks: found, a: {}, b: {},
  images: [], guid: id, test_type: "hard", tolerance_m: 0.001, status: "active", distance_m: -0.1, point: null, grid: null, source: "sightline", ref: null });
const list = (id, serial, kept, clashes) => ({ id, title: "Coordination", clashes, origin: "sightline", sources: ["model.ifc"], scene_id: "scene", serial, checks: kept });
const done = (report, check, kept) => ({ type: "done", report, check, ran: check ? [check] : kept.map((c) => c.key), checks: kept,
  coverage: [], diff: FIRST, elements: 2, seconds: 1, tests: null });

const BOTH = row("c1", 1, { models: "MEP vs Structure", "filter:abc": "Ducts vs Everything" });
const ONLY_MODELS = row("c2", 2, { models: "Structure (within)" });
const ONLY_DUCTS = row("c3", 3, { "filter:abc": "Ducts vs Everything" });

test("the list as one check shows it: its clashes under its tests; an import or All checks unchanged", () => {
  const r = list("r", 1, [MODELS, DUCTS], [BOTH, ONLY_MODELS, ONLY_DUCTS]);
  const ducts = checks.narrow(r, "filter:abc");
  assert.deepEqual(ducts.clashes.map((c) => [c.id, c.test]), [["c1", "Ducts vs Everything"], ["c3", "Ducts vs Everything"]]);
  assert.equal(ducts.id, "r", "the same report: pictures and triage are by its id");
  assert.equal(checks.narrow(r, null), r);
  const imported = { ...r, origin: "navisworks" };
  assert.equal(checks.narrow(imported, "filter:abc"), imported);
  assert.equal(checks.checkLabel({ ...DUCTS, clashes: 1200, stale: true }), "Ducts vs Everything · 1,200 · ran before a fix");
});

test("a fix's mark stays until the check that lists its clash runs again", () => {
  const after = list("r2", 2, [MODELS, DUCTS], [BOTH, ONLY_MODELS]);
  const fixes = { c1: "Raise the duct", c2: "Trim the strut", c3: "Lower the duct" };
  // The ducts check ran again: it still finds c1 (not fixed), c3 has gone (resolved); c2 is only the open models'.
  assert.deepEqual(checks.pruneFixes(fixes, after, ["filter:abc"]), { c2: "Trim the strut" });
  assert.deepEqual(checks.pruneFixes(fixes, after, []), { c1: "Raise the duct", c2: "Trim the strut" }, "a check removed: only what left goes");
  assert.deepEqual(checks.pruneFixes(fixes, after, ["models", "filter:abc"]), {}, "every check ran");
});

test("a run keeps the work on the list; a late older list is ignored; Remove shows what is left", async () => {
  const first = list("r1", 1, [MODELS], [BOTH, ONLY_MODELS]);
  const both = list("r2", 2, [MODELS, DUCTS], [BOTH, ONLY_MODELS, ONLY_DUCTS]);
  const left = list("r3", 3, [MODELS], [BOTH, ONLY_MODELS]);
  let answer = done(both, "filter:abc", both.checks);
  const removed = [];
  const host = await appHost({
    initial: { sceneFiles: ["model.ifc"], report: first, checks: [MODELS], clash: ONLY_MODELS, chatReport: "r1",
      fixes: { c2: "Trim the strut" }, reviewed: { c1: { kind: "by_design", note: "meant to meet" } } },
    api: { detect: async () => answer, removeCheck: async (_sid, key) => { removed.push(key); return { report: left, checks: left.checks }; },
      detectTests: async () => ({ tests: [], teams: {}, elements: 2, rules: {} }) } });
  await host.settle();
  find(host.menu(), (n) => n.type === "button" && hasText(n, "Check the open models")).props.onClick();
  await host.settle();
  assert.equal(host.state.report.id, "r2");
  assert.equal(host.state.clash.id, "c2", "the selected clash stays");
  assert.deepEqual(host.state.fixes, { c2: "Trim the strut" }, "the ducts check does not list it: its mark stays");
  assert.deepEqual(Object.keys(host.state.reviewed), ["c1"]);
  assert.equal(host.state.chatReport, "r1", "the chat goes on");
  // A list made before this one (another tab's run, a slow answer) changes nothing.
  answer = done(first, "models", first.checks);
  find(host.menu(), (n) => n.type === "button" && hasText(n, "Run all 2 checks again")).props.onClick();
  await host.settle();
  assert.equal(host.state.report.id, "r2");
  host.component("ReportList").props.picker.props.onRemove("filter:abc");
  await host.settle();
  assert.deepEqual(removed, ["filter:abc"]);
  assert.equal(host.state.report.id, "r3");
  assert.deepEqual(host.state.checks.map((c) => c.key), ["models"]);
  assert.equal(host.state.viewCheck, null);
  assert.equal(host.component("ReportList").props.picker, false, "one check: no picker");
  host.unmount();
});

test("triage reads the unread clashes of the check on screen", async () => {
  const streams = [];
  const both = list("r2", 2, [MODELS, DUCTS], [BOTH, ONLY_MODELS, ONLY_DUCTS]);
  const host = await appHost({
    initial: { sceneFiles: ["model.ifc"], report: both, checks: both.checks, viewCheck: "filter:abc",
      triage: { c1: { verdict: "real_clash", source: "model", carried: true } } },
    api: { triage: async () => ({ results: { c1: { verdict: "real_clash", source: "model", carried: true } }, done: true, model: "m", total: 3, unread: 2 }),
      triageStream: async (rid, sid, _on, rerun, scope) => { streams.push({ rid, sid, rerun, scope }); } } });
  await host.settle();
  const card = host.component("ReportList").props.triageCard;
  assert.equal(card.props.total, 2, "the clashes on screen");
  assert.equal(card.props.unread, 1, "c3: no reading holds for it");
  assert.deepEqual(Object.keys(card.props.results), ["c1"]);
  card.props.onRun(false);
  await host.settle();
  assert.deepEqual(streams, [{ rid: "r2", sid: "scene", rerun: false, scope: "filter:abc" }]);
  host.unmount();
});

/** A browser's localStorage, enough for the page. */
function storage(entries = {}) {
  const m = new Map(Object.entries(entries));
  return { map: m, get length() { return m.size; }, key: (i) => [...m.keys()][i] ?? null,
    getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => { m.set(k, String(v)); }, removeItem: (k) => { m.delete(k); } };
}

test("a reload resumes the list of kept checks on the check it showed; a list the server let go is made again", async () => {
  const both = list("r9", 9, [MODELS, DUCTS], [BOTH, ONLY_MODELS, ONLY_DUCTS]);
  globalThis.localStorage = storage({ "sightline.session": JSON.stringify({ scene_id: "scene-1", report_id: "r2", files: ["model.ifc"],
    fixes: { c2: "Trim the strut" }, link: null, saved_at: 1, check: "filter:abc" }) });
  const asked = [];
  try {
    const host = await appHost({
      initial: { report: null, clash: null, sceneId: null, stats: null },
      api: { sceneInfo: async () => ({ id: "scene-1", files: ["model.ifc"], step: {}, revision: 0, report_id: "r9", checks: both.checks }),
        report: async (id) => { asked.push(id); if (id === "r9") return both; throw new Error("gone"); },
        open: async (names) => ({ id: "scene-1", files: names }), detect: async () => { throw new Error("no run on resume"); } } });
    await host.settle();
    assert.equal(host.state.resumable.clashes, 3, "the landing counts the list the server holds now");
    host.component("About").props.start.resume.onResume();   // the landing's Pick up
    await host.settle();
    assert.deepEqual(asked.slice(-1), ["r9"], "the list the scene's checks make now (the old one is gone)");
    assert.equal(host.state.report?.id, "r9");
    assert.equal(host.state.viewCheck, "filter:abc");
    assert.deepEqual(host.state.checks.map((c) => c.key), ["models", "filter:abc"]);
    assert.deepEqual(host.state.fixes, { c2: "Trim the strut" });
    const saved = JSON.parse(localStorage.getItem("sightline.session"));
    assert.equal(saved.check, "filter:abc");
    host.unmount();
  } finally { delete globalThis.localStorage; }
});

test("a list the server let go of while the models are held is made again, with no check run", async () => {
  const first = list("r1", 1, [MODELS, DUCTS], [BOTH, ONLY_MODELS]);
  const again = list("r5", 5, [MODELS, DUCTS], [BOTH, ONLY_MODELS]);
  const ran = [];
  const host = await appHost({
    initial: { sceneFiles: ["model.ifc"], report: first, checks: first.checks },
    api: { checks: async () => ({ report_id: "r5", checks: again.checks }), report: async () => again,
      sceneInfo: async () => ({ id: "scene", files: ["model.ifc"], step: {}, revision: 0, report_id: "r5", checks: again.checks }),
      detect: async () => { ran.push(1); return done(again, "models", again.checks); } } });
  await host.settle();
  host.gone({ kind: "report", id: "r1", detail: "Clash report not loaded. Open it again." });
  assert.ok(host.button("Open it again"));
  host.button("Open it again").props.onClick();
  await host.settle();
  assert.equal(host.state.report.id, "r5");
  assert.deepEqual(ran, [], "no detection run is spent");
  host.unmount();
});

test("from an imported report, back to ORCA's checks", async () => {
  const both = list("r2", 2, [MODELS, DUCTS], [BOTH, ONLY_MODELS, ONLY_DUCTS]);
  const imported = { id: "nw", title: "northbank", clashes: [], origin: "navisworks", sources: ["a.xml"] };
  const host = await appHost({
    initial: { sceneFiles: ["model.ifc"], report: imported, checks: both.checks },
    api: { checks: async () => ({ report_id: "r2", checks: both.checks }), report: async () => both } });
  await host.settle();
  find(host.menu(), (n) => n.type === "button" && hasText(n, "Back to ORCA's checks (2)")).props.onClick();
  await host.settle();
  assert.equal(host.state.report.id, "r2");
  assert.deepEqual(host.state.checks.map((c) => c.key), ["models", "filter:abc"]);
  host.unmount();
});

test("a verdict holds only for a clash that did not change; a titling run of an earlier list is followed, then asked again", async () => {
  const moved = (c, d) => ({ ...c, distance_m: d, a: { global_id: "ga" }, b: { global_id: `gb-${c.id}` } });
  const was = list("r1", 1, [MODELS], [moved(BOTH, -0.1), moved(ONLY_MODELS, -0.2)]);
  const now = list("r2", 2, [MODELS], [moved(BOTH, -0.1005), moved(ONLY_MODELS, -0.25)]);
  assert.equal(checks.sameClash(was.clashes[0], now.clashes[0]), true, "half a millimetre: the same clash");
  assert.equal(checks.sameClash(was.clashes[1], now.clashes[1]), false, "50 mm: read again");
  const titled = [];
  const host = await appHost({
    initial: { sceneFiles: ["model.ifc"], report: was, checks: was.checks },
    api: { detect: async () => done(now, "models", now.checks), triage: () => new Promise(() => {}),
      titles: async (rid, on) => { titled.push(rid); on({ type: "start", total: 2, missing: 2, model: "m", report_id: titled.length === 1 ? "r1" : rid }); on({ type: "done", titled: 2, seconds: 1 }); } } });
  await host.settle();
  titled.length = 0;
  host.state.triage = { c1: { verdict: "real_clash", source: "model" }, c2: { verdict: "real_clash", source: "model" } };
  host.render();
  find(host.menu(), (n) => n.type === "button" && hasText(n, "Check the open models")).props.onClick();
  await host.settle(); await host.settle();
  assert.equal(host.state.report.id, "r2");
  assert.deepEqual(Object.keys(host.state.triage), ["c1"], "the moved clash's verdict is dropped");
  assert.deepEqual(titled, ["r2", "r2"], "it followed the earlier list's titling, then asked for this list's");
  host.unmount();
});
