import assert from "node:assert/strict";
import test from "node:test";
import { compiled } from "./app-host.mjs";

const req = await import(await compiled("../src/reqFile.ts"));

const doc = () => ({
  format: "orca-requirements/1", name: "Northbank coordination", version: 1, level: 3, strictness: "balanced",
  groups: [{ id: "structure", name: "Structure", role: "structure", teams: ["Structure"], classes: [], exclude_classes: [], systems: [], files: [], source: "level" },
           { id: "mep", name: "MEP", role: "services", teams: ["MEP"], classes: [], exclude_classes: [], systems: [], files: [], source: "level" }],
  checks: [{ a: "structure", b: null, check: "hard", clearance_mm: null, tolerance_mm: null, reason: "", source: "level" },
           { a: "structure", b: "mep", check: "hard", clearance_mm: null, tolerance_mm: null, reason: "", source: "level" }],
  duplicates: true, rules: { same_element: true, connected: true, assembly: true, host: true },
  who_moves: [{ group: "structure", edits: "any", max_move_mm: null, trims: true }, { group: "mep", edits: "any", max_move_mm: null, trims: true }],
  by_design: [], guidance: { triage: "", fixes: "" }, notes: "",
});

test("a file round-trips through download text and upload", () => {
  const d = doc();
  assert.deepEqual(req.parseUpload(req.serialise(d)), d);
  assert.equal(req.fileName(d), "northbank-coordination.orca-requirements.json");
  assert.equal(req.shortLabel({ level: 4, strictness: "strict" }), "L4 · Strict");
});

test("upload refuses what is not a requirements file", () => {
  assert.throws(() => req.parseUpload("not json"), /not JSON/);
  assert.throws(() => req.parseUpload(JSON.stringify({ format: "ids/1" })), /Not an ORCA requirements file/);
  assert.throws(() => req.parseUpload(JSON.stringify({ format: "orca-requirements/1" })), /no groups/);
});

test("a cell is found either way round, changed as the user's, and the version goes up", () => {
  const d = doc();
  assert.equal(req.cellFor(d, "mep", "structure"), d.checks[1]);
  assert.equal(req.cellFor(d, "structure", null), d.checks[0]);
  const next = req.setCell(d, "mep", "structure", { check: "clearance" });
  const c = req.cellFor(next, "structure", "mep");
  assert.equal(c.check, "clearance");
  assert.equal(c.clearance_mm, 25);
  assert.equal(c.source, "user");
  assert.equal(next.version, 2);
  assert.equal(d.checks[1].check, "hard");                       // the original is left alone
  const added = req.setCell(d, "mep", null, { check: "off" });
  assert.equal(added.checks.length, 3);
});

test("who moves: reorder and limit", () => {
  const d = req.shiftMover(doc(), 1, -1);
  assert.deepEqual(d.who_moves.map((m) => m.group), ["mep", "structure"]);
  assert.equal(req.shiftMover(d, 0, -1), d);                     // already first
  const limited = req.setMover(d, "mep", { max_move_mm: 300, trims: false });
  assert.deepEqual(limited.who_moves[0], { group: "mep", edits: "any", max_move_mm: 300, trims: false });
});

test("a by-design pattern becomes a rule once, and can be removed", () => {
  const p = { classes: ["IfcColumn", "IfcSlab"] };
  const d = req.addByDesign(doc(), p, { cause: "Columns run through slabs", rule: "" });
  assert.deepEqual(d.by_design, [{ a_classes: ["IfcColumn"], b_classes: ["IfcSlab"], reason: "Columns run through slabs", source: "triage" }]);
  assert.ok(req.hasByDesign(d, { classes: ["IfcSlab", "IfcColumn"] }));
  assert.equal(req.addByDesign(d, p), d);                         // already there
  assert.equal(req.removeByDesign(d, 0).by_design.length, 0);
});

test("this browser keeps the file and whether it is in use", () => {
  const store = new Map();
  const storage = { getItem: (k) => store.get(k) ?? null, setItem: (k, v) => store.set(k, v), removeItem: (k) => store.delete(k) };
  assert.equal(req.load(storage), null);
  req.save({ doc: doc(), enabled: false }, storage);
  assert.deepEqual(req.load(storage), { doc: doc(), enabled: false });
  req.save(null, storage);
  assert.equal(req.load(storage), null);
  store.set("sightline.requirements", "{broken");
  assert.equal(req.load(storage), null);
});

test("a group's rule for openings is set, cleared, and added from an opening's host reading", () => {
  let d = req.setPenetration(doc(), "structure", { rule: "never" });
  assert.deepEqual(d.penetrations, [{ group: "structure", rule: "never", max_mm: null, reviewer: null, reason: "", source: "user" }]);
  d = req.setPenetration(d, "structure", { rule: "review", max_mm: 150 });
  assert.equal(d.penetrations[0].max_mm, 150);
  assert.equal(req.setPenetration(d, "structure", null).penetrations.length, 0);   // Muse decides again
  const edit = { host_group: "structure", host_kind: "ab12", host_kind_name: "gland plate", verdict: "with_review",
    host_reading: "allowed with review, reviewed by structure" };
  assert.equal(req.addPenetration(doc(), { ...edit, host_kind: undefined }, "structure").penetrations, undefined);  // never group-wide
  const added = req.addPenetration(doc(), edit, "structure");
  assert.deepEqual(added.penetrations, [{ group: "structure", rule: "review", max_mm: null, reviewer: "structure",
    reason: "allowed with review, reviewed by structure", source: "orca", kind: "ab12", kind_name: "gland plate" }]);
  assert.ok(req.hasPenetration(added, "structure", "ab12") && !req.hasPenetration(added, "structure"));
  assert.ok(!req.hasPenetration(added, "mep", "ab12"));
  const both = req.setPenetration(added, "structure", { rule: "never" });   // the group-wide rule sits beside it
  assert.equal(both.penetrations.length, 2);
  assert.equal(req.setPenetration(both, "structure", null, "ab12").penetrations[0].rule, "never");
  assert.equal(req.addPenetration(doc(), { ...edit, host_group: "nowhere" }, null).penetrations, undefined);  // no such group
});
