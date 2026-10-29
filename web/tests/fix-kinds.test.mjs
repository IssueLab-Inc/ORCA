import assert from "node:assert/strict";
import test from "node:test";
import { compiled } from "./app-host.mjs";

const kinds = await import(await compiled("../src/fixKinds.ts"));

test("each kind is described in one place, the newer kinds by the server's own summary", () => {
  assert.equal(kinds.editText({ kind: "offset", split_m: [2.6, 4.4], delta_m: [0, 0, 0.4] }), "offset 2.60–4.40 m by +400 mm");
  assert.equal(kinds.editText({ kind: "trim", split_m: null, delta_m: [0, 0, 0], trim: { end: "start", by_m: 0.04 } }), "trim one end 40 mm");
  assert.equal(kinds.editText({ kind: "move", split_m: null, delta_m: [0, 0, -0.15] }), "move 0 mm · 0 mm · -150 mm");
  assert.equal(kinds.editText({ kind: "route", split_m: null, delta_m: [0, 0.3, 0.4], edit: { summary: "route up 400 mm, then side 300 mm" } }),
    "route up 400 mm, then side 300 mm");
  assert.equal(kinds.kindLabel("penetration"), "Opening");
  assert.equal(kinds.kindLabel("something new"), "something new");
});

test("framing shows a split run's new pieces, an opening whole, and a move or trim where it meets the other side", () => {
  const preview = ["first", "bend", "middle", "bend", "last"];
  assert.deepEqual(kinds.framePieces({ kind: "route", preview }), ["bend", "middle", "bend"]);
  assert.deepEqual(kinds.framePieces({ kind: "offset", preview }), ["bend", "middle", "bend"]);
  assert.deepEqual(kinds.framePieces({ kind: "penetration", preview: ["provision", "wall"] }), ["provision"]);
  assert.deepEqual(kinds.framePieces({ kind: "trim", preview: ["member"] }), []);
  assert.deepEqual(kinds.framePieces({ kind: "move", preview: null }), []);
});

test("clearance, change and recommendation lines for every kind", () => {
  assert.equal(kinds.clearanceText({ kind: "trim", min_clearance_m: 0 }), "butt joint");
  assert.equal(kinds.clearanceText({ kind: "route", min_clearance_m: 0.05 }), "+50 mm");
  const offset = { kind: "offset", split_m: [2.6, 4.4], delta_m: [0, 0, 0.4], preview: new Array(9), moved: ["d"] };
  assert.equal(kinds.changeText(offset), "1.80 m of it raised 400 mm; 4 bends and 2 short risers");
  assert.equal(kinds.changeText({ kind: "resize", delta_m: [0, 0, -0.05], moved: ["d"], edit: { summary: "800×250 mm for 1.80 m" } }),
    "800×250 mm for 1.80 m");
  assert.equal(kinds.recEditText({ kind: "offset", delta_m: [0, 0, -0.25] }), "offset the middle down 250 mm");
  assert.equal(kinds.recEditText({ kind: "penetration", delta_m: [0, 0, 0] }), "opening");
  assert.match(kinds.reviewText("structure"), /structural engineer/);
  assert.equal(kinds.reviewText(null), "");
});
