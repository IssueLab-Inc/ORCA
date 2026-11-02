import assert from "node:assert/strict";
import test from "node:test";
import { appHost } from "./app-host.mjs";

/** A row's Isolate (owner request, Nov 1: "a new hover button that will isolate only the clashing elements, if its on
 * for a clash, clicking another clash should go straight to it and isolate it too, until the user removes the
 * isolation"). */

const clash = (id, number, a, b) => ({ id, number, name: `Clash ${number}`, title: null, test: "MEP vs Structure",
  a: { name: "A", global_id: a }, b: { name: "B", global_id: b }, images: [], guid: id, test_type: "hard", tolerance_m: 0.001,
  status: "active", distance_m: -0.3, point: [1, 2, 3], grid: null, source: "sightline", ref: null });
const A = clash("ca", 1, "duct", "girder"), B = clash("cb", 2, "tray", "girder"), C = clash("cc", 3, "pipe", "wall");
const report = { id: "r", title: "Coordination", sources: [], origin: "sightline", clashes: [A, B, C] };
const matches = { ca: { a: "duct", b: "girder", how: [] }, cb: { a: "tray", b: "girder", how: [] }, cc: { a: "pipe", b: "wall", how: [] } };

test("isolate a clash's elements; each clash opened after goes straight to its own pair, until everything is shown again", async () => {
  const host = await appHost({ initial: { report, matches, clash: null, a: null, b: null, sceneFiles: ["m.ifc"] }, api: { match: async () => matches } });
  await host.settle();
  const list = () => host.component("ReportList").props;
  const calls = [];
  host.viewer.focusClash = (...args) => { calls.push(args); return true; };   // ids, point, label, fly
  const flown = () => calls.map((x) => ["focusClash", ...x]);
  list().onIsolate(A); await host.settle();
  assert.equal(host.state.isolating, true);
  assert.deepEqual(host.state.temporary, { hidden: [], isolated: ["duct", "girder"] });
  assert.ok(flown().some((x) => x[3] === "#1" && x[4] === true), "straight to it");
  // Another clash opened: its own pair, isolated, and the views go to it; a kept fix's pieces of its element too.
  host.state.edits = { tray: ["tray-piece-2", "tray-piece-3"] };
  list().onSelect(B); await host.settle();
  assert.deepEqual(host.state.temporary.isolated, ["tray", "girder", "tray-piece-2", "tray-piece-3"]);
  assert.ok(flown().some((x) => x[3] === "#2" && x[4] === true));
  assert.equal(host.state.isolatedFor, 2);
  // Isolate on the clash already isolated: everything again, and the next clash opened isolates nothing.
  list().onIsolate(B); await host.settle();
  assert.equal(host.state.isolating, false);
  assert.deepEqual(host.state.temporary, { hidden: [], isolated: null });
  list().onSelect(C); await host.settle();
  assert.deepEqual(host.state.temporary, { hidden: [], isolated: null });
  host.unmount();
});

test("what a kept fix changed stays in its clash's isolation, from the edit log, until it is undone; the camera stays", async () => {
  // Snowdon #20 isolated and fixed: the drain tilts, its bend goes down, the stack below gets shorter. With only the
  // pair drawn, the tilted drain ended in mid-air.
  const host = await appHost({ initial: { report, matches, clash: null, a: null, b: null, sceneFiles: ["m.ifc"] }, api: { match: async () => matches } });
  await host.settle();
  const calls = [];
  host.viewer.focusClash = (...args) => { calls.push(args); return true; };
  host.component("ReportList").props.onIsolate(A); await host.settle();
  const flights = calls.length;
  assert.ok(flights > 0, "straight to it");
  const entry = (id, state, clashes, elements, created = []) => ({ id, state, clashes, elements, created });
  host.state.journal = { entries: [
    entry("E1", "kept", [{ id: "ca", pair: ["duct", "girder"] }], ["duct", "bend", "stack"]),
    entry("E2", "kept", [{ id: null, pair: ["girder", "duct"] }], ["hanger"], ["duct-piece"]),   // an agent's: its pair
    entry("E3", "undone", [{ id: "ca", pair: ["duct", "girder"] }], ["damper"]),
    entry("E4", "kept", [{ id: "cb", pair: ["tray", "girder"] }], ["tray", "rack"]),                // another clash's
  ], can_undo: true, can_redo: true, undo: "E2", redo: "E3" };
  host.render(); await host.settle();
  assert.deepEqual(host.state.temporary.isolated, ["duct", "girder", "bend", "stack", "hanger", "duct-piece"]);
  assert.equal(calls.length, flights, "the camera stays where the user has it");
  host.state.journal = { ...host.state.journal, entries: host.state.journal.entries.map((e) => e.id === "E1" ? { ...e, state: "undone" } : e) };
  host.render(); await host.settle();
  assert.deepEqual(host.state.temporary.isolated, ["duct", "girder", "hanger", "duct-piece"], "undone: its parts go");
  host.unmount();
});

test("the chip's Show all and the toolbar's Reset end it; another isolation of the user's replaces it", async () => {
  const host = await appHost({ initial: { report, matches, clash: null, a: null, b: null, sceneFiles: ["m.ifc"], stats: { elements: 3, triangles: 3, parseMs: 1 } },
    api: { match: async () => matches } });
  await host.settle();
  const list = () => host.component("ReportList").props;
  list().onIsolate(A); await host.settle();
  const chip = host.find((n) => n.props?.className === "temp-chip");
  assert.ok(chip, "the chip over the model says it");
  const showAll = host.find((n) => n.type === "button" && n.props?.children === "Show all");
  showAll.props.onClick(); await host.settle();
  assert.equal(host.state.isolating, false);
  assert.equal(host.state.temporary.isolated, null);
  list().onIsolate(A); await host.settle();
  host.component("ViewerToolbar").props.views.onResetTemporary(); await host.settle();
  assert.equal(host.state.isolating, false);
  assert.equal(host.state.temporary.isolated, null);
  // The element card's own Isolate replaces the clash's: the next clash opened isolates nothing of its own.
  list().onIsolate(A); await host.settle();
  host.state.selected = { globalId: "duct", info: null }; host.render(); await host.settle();
  host.component("ElementCard").props.actions.onIsolate(); await host.settle();
  assert.equal(host.state.isolating, false);
  assert.deepEqual(host.state.temporary.isolated, ["duct"]);
  list().onSelect(B); await host.settle();
  assert.deepEqual(host.state.temporary.isolated, ["duct"], "the user's isolation stays");
  host.unmount();
});
