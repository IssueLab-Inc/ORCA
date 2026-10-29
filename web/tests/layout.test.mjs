import assert from "node:assert/strict";
import test from "node:test";
import { compiled } from "./app-host.mjs";

const react = `data:text/javascript;base64,${Buffer.from("export const useState=()=>[];export const useEffect=()=>{};").toString("base64")}`;
const layout = await import(await compiled("../src/layout.ts", { react }));

test("window widths map to desktop, tablet and phone at the CSS's breakpoints", () => {
  assert.equal(layout.layoutFor(1440), "desktop");
  assert.equal(layout.layoutFor(1101), "desktop");
  assert.equal(layout.layoutFor(1100), "tablet");
  assert.equal(layout.layoutFor(761), "tablet");
  assert.equal(layout.layoutFor(760), "phone");
  assert.equal(layout.layoutFor(320), "phone");
});

const heights = { peek: 130, half: 460, full: 780 };

test("a released drag settles at the nearest height", () => {
  assert.equal(layout.nearestSnap(150, 0, heights, "half"), "peek");
  assert.equal(layout.nearestSnap(400, 0, heights, "peek"), "half");
  assert.equal(layout.nearestSnap(700, 0, heights, "half"), "full");
});

test("a flick goes one step its way, past the nearest height", () => {
  assert.equal(layout.nearestSnap(200, 1.2, heights, "peek"), "half");    // up from peek, still near peek
  assert.equal(layout.nearestSnap(500, 1.2, heights, "half"), "full");    // up from half
  assert.equal(layout.nearestSnap(420, -1.2, heights, "half"), "peek");   // down from half
  assert.equal(layout.nearestSnap(780, 2, heights, "full"), "full");      // nothing above full
  assert.equal(layout.nearestSnap(130, -2, heights, "peek"), "peek");     // nothing below peek
});

test("a tap on the handle steps peek → half → full → peek", () => {
  assert.equal(layout.nextSnap("peek"), "half");
  assert.equal(layout.nextSnap("half"), "full");
  assert.equal(layout.nextSnap("full"), "peek");
});

test("the sheet follows what happens, and leaves a raised sheet where the visitor put it", () => {
  assert.deepEqual(layout.follow("report", "peek"), { list: true, snap: "half" });
  assert.deepEqual(layout.follow("report", "full"), { list: true, snap: null });
  assert.deepEqual(layout.follow("select", "peek"), { list: false, snap: "half" });
  assert.deepEqual(layout.follow("select", "full"), { list: false, snap: null });
  assert.deepEqual(layout.follow("work", "full"), { list: false, snap: "peek" });   // out of the way: ORCA drives the model
  assert.deepEqual(layout.follow("result", "peek"), { list: false, snap: "half" });
});
