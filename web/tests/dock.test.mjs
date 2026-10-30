import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { compiled } from "./app-host.mjs";

const dock = await import(await compiled("../src/dockLayout.ts"));

/** A layout as dockview's toJSON writes it: the model in the grid, the side bars, and what floats or pops out. */
function layout({ grid = ["model"], left = ["clashes"], right = ["clash", "plan", "chat"], bottom = ["activity"], floating = [], popout = [] } = {}) {
  const ids = [...grid, ...left, ...right, ...bottom, ...floating, ...popout];
  const edge = (views, id) => ({ size: 300, visible: true, group: { id, views, activeView: views[0] } });
  return {
    grid: { root: { type: "branch", data: [{ type: "leaf", data: { views: grid, id: "1" } }] }, width: 800, height: 600, orientation: "HORIZONTAL" },
    panels: Object.fromEntries(ids.map((id) => [id, { id, contentComponent: "panel", title: id }])),
    floatingGroups: floating.length ? [{ data: { views: floating, id: "2" }, position: { top: 0, left: 0, width: 300, height: 300 } }] : [],
    popoutGroups: popout.length ? [{ data: { views: popout, id: "3" }, url: "/popout.html" }] : [],
    edgeGroups: { left: edge(left, "edge-left"), right: edge(right, "edge-right"), bottom: edge(bottom, "edge-bottom") },
  };
}

test("every panel has a home, and only the model lives in the middle", () => {
  assert.deepEqual(dock.PANEL_IDS, ["model", "clashes", "clash", "plan", "chat", "activity"]);
  assert.equal(dock.homeOf("model"), "centre");
  assert.equal(dock.homeOf("clashes"), "left");
  for (const id of ["clash", "plan", "chat"]) assert.equal(dock.homeOf(id), "right");
  assert.equal(dock.homeOf("activity"), "bottom");
  assert.ok(dock.isPanel("chat") && !dock.isPanel("viewer"));
});

test("the default layout as saved loads; floating panels and closed ones too", () => {
  assert.ok(dock.validLayout(layout()));
  assert.ok(dock.validLayout(layout({ right: ["plan", "chat"], floating: ["clash"] })));
  assert.ok(dock.validLayout(layout({ bottom: [] })), "a closed panel is simply absent");
  assert.ok(dock.validLayout(layout({ grid: ["model", "chat"], right: ["clash", "plan"] })), "a panel docked beside the model");
});

test("a layout that can't be ORCA's gives way to the default", () => {
  assert.ok(!dock.validLayout(null) && !dock.validLayout("x") && !dock.validLayout({}));
  assert.ok(!dock.validLayout(layout({ grid: ["clash"], right: ["model", "plan", "chat"] })), "the model must stay in the grid");
  assert.ok(!dock.validLayout(layout({ grid: [], floating: ["model"] })), "the model never floats");
  const twice = layout(); twice.edgeGroups.left.group.views = ["clashes", "chat"];
  assert.ok(!dock.validLayout(twice), "a panel in two places");
  const stranger = layout(); stranger.panels.viewer = { id: "viewer", contentComponent: "panel" }; stranger.edgeGroups.left.group.views.push("viewer");
  assert.ok(!dock.validLayout(stranger), "a panel ORCA doesn't have");
  const unplaced = layout(); unplaced.edgeGroups.bottom.group.views = [];
  assert.ok(!dock.validLayout(unplaced), "a panel listed but placed nowhere");
  const other = layout(); other.panels.chat.contentComponent = "default";
  assert.ok(!dock.validLayout(other), "drawn by another component");
});

test("a saved layout puts what was in its own window back in its side bar", () => {
  const saved = dock.withoutPopouts(layout({ right: ["clash", "plan"], popout: ["chat"] }));
  assert.deepEqual(saved.popoutGroups, []);
  assert.deepEqual(saved.edgeGroups.right.group.views, ["clash", "plan", "chat"]);
  assert.ok(dock.validLayout(saved));
  const noBar = layout({ bottom: [], popout: ["activity"] }); delete noBar.edgeGroups.bottom;
  const back = dock.withoutPopouts(noBar);
  assert.deepEqual(back.edgeGroups.bottom.group, { id: "edge-bottom", views: ["activity"], activeView: "activity" });
  assert.ok(dock.validLayout(back));
  const plain = layout();
  assert.equal(dock.withoutPopouts(plain), plain, "nothing to move: the same layout");
});

test("the layout is kept per browser, versioned, and a bad one reads as none", () => {
  const store = new Map();
  const storage = { getItem: (k) => store.get(k) ?? null, setItem: (k, v) => store.set(k, v) };
  dock.writeLayout(storage, layout({ right: ["clash", "plan"], popout: ["chat"] }));
  const read = dock.readLayout(storage);
  assert.deepEqual(read.edgeGroups.right.group.views, ["clash", "plan", "chat"]);
  store.set(dock.LAYOUT_KEY, JSON.stringify({ v: 2, layout: layout() }));
  assert.equal(dock.readLayout(storage), null, "another version");
  store.set(dock.LAYOUT_KEY, "{not json");
  assert.equal(dock.readLayout(storage), null);
  assert.equal(dock.readLayout(null), null);
  assert.doesNotThrow(() => dock.writeLayout({ setItem() { throw new Error("quota"); } }, layout()));
});

test("showing a panel: reopen, open its bar, bring its window forward, or bring it home for the tour", () => {
  assert.deepEqual(dock.showSteps({ open: false }), ["add", "expand", "activate"]);
  assert.deepEqual(dock.showSteps({ open: true, location: "edge", collapsed: true }), ["expand", "activate"]);
  assert.deepEqual(dock.showSteps({ open: true, location: "edge", collapsed: false }), ["activate"]);
  assert.deepEqual(dock.showSteps({ open: true, location: "floating" }), ["activate"]);
  assert.deepEqual(dock.showSteps({ open: true, location: "popout" }), ["window", "activate"]);
  assert.deepEqual(dock.showSteps({ open: true, location: "popout" }, true), ["home", "expand", "activate"]);
});

test("the dock uses dockview's free core only (the public repo must build for anyone)", async () => {
  const pkg = JSON.parse(await readFile(new URL("../package.json", import.meta.url), "utf8"));
  assert.equal(pkg.dependencies["dockview-react"], "8.5.1");
  assert.deepEqual(pkg.overrides, { dockview: "8.5.1", "dockview-core": "8.5.1" });
  assert.ok(!JSON.stringify(pkg).includes("dockview-enterprise"));
  const source = await readFile(new URL("../src/dock.tsx", import.meta.url), "utf8");
  assert.ok(!source.includes("dockview-enterprise"));
  for (const option of ["autoHideEdgeGroups", "dockToEdgeGroups", "layoutHistory", "smartGuides", "dndCompass", "keyboardNavigation"]) {
    assert.ok(!source.includes(option), `${option} needs the paid modules`);
  }
});
