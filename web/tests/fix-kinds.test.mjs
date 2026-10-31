import assert from "node:assert/strict";
import test from "node:test";
import { compiled } from "./app-host.mjs";

const kinds = await import(await compiled("../src/fixKinds.ts"));

test("each kind is described in one place, the newer kinds by the server's own summary", () => {
  assert.equal(kinds.editText({ kind: "offset", split_m: [2.6, 4.4], delta_m: [0, 0, 0.4] }), "offset 2.60–4.40 m by +400 mm");
  assert.equal(kinds.editText({ kind: "trim", split_m: null, delta_m: [0, 0, 0], trim: { end: "start", by_m: 0.04 } }), "trim one end 40 mm");
  assert.equal(kinds.editText({ kind: "move", split_m: null, delta_m: [0, 0, -0.15] }), "move down 150 mm");
  assert.equal(kinds.editText({ kind: "move", split_m: null, delta_m: [-0.1, 0.25, 0.0002] }), "move west 100 mm, north 250 mm");
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
  assert.equal(kinds.clearanceText({ kind: "route", min_clearance_m: 0.05 }), "50 mm");
  assert.equal(kinds.clearanceText({ kind: "move", min_clearance_m: null }), "nothing within 500 mm");
  assert.equal(kinds.needsText("move the run together, and re-fix anchors; none"), "move the run together, and re-fix anchors");
  assert.equal(kinds.needsText("None."), "");
  const offset = { kind: "offset", split_m: [2.6, 4.4], delta_m: [0, 0, 0.4], preview: new Array(9), moved: ["d"] };
  assert.equal(kinds.changeText(offset), "1.80 m of it raised 400 mm; 4 bends and 2 short risers");
  assert.equal(kinds.changeText({ kind: "resize", delta_m: [0, 0, -0.05], moved: ["d"], edit: { summary: "800×250 mm for 1.80 m" } }),
    "800×250 mm for 1.80 m");
  assert.equal(kinds.recEditText({ kind: "offset", delta_m: [0, 0, -0.25] }), "offset the middle down 250 mm");
  assert.equal(kinds.recEditText({ kind: "penetration", delta_m: [0, 0, 0] }), "opening");
  assert.match(kinds.reviewText("structure"), /structural engineer/);
  assert.equal(kinds.reviewText(null), "");
});

test("an opening's card shows its host's reading and the hole against its limits", () => {
  const o = { kind: "penetration", edit: { host_reading: "allowed with review, reviewed by structure (a hole at most 40% of its depth)",
    reading_source: "muse", numbers: ["hole 170 mm in 600 mm of host (28%)", "915 mm from its nearest end"] } };
  assert.deepEqual(kinds.hostRows(o), [["Host", "allowed with review, reviewed by structure (a hole at most 40% of its depth) (the AI's reading)"],
    ["Hole", "hole 170 mm in 600 mm of host (28%); 915 mm from its nearest end"]]);
  assert.deepEqual(kinds.hostRows({ kind: "offset", edit: o.edit }), []);
});

test("a combined fix (a second try's several elements at once) says each step and frames them all", () => {
  const o = { kind: "combined", split_m: null, delta_m: [0, 0, -0.5], moved: ["pipe", "duct"], preview: ["pipe", "duct"],
    edit: { summary: "LTHW pipe: move [0, 0, -500] mm; Supply duct: move [0, 0, -400] mm" } };
  assert.equal(kinds.kindLabel("combined"), "Combined");
  assert.equal(kinds.editText(o), "LTHW pipe: move [0, 0, -500] mm; Supply duct: move [0, 0, -400] mm");
  assert.equal(kinds.changeText(o), o.edit.summary);
  assert.deepEqual(kinds.framePieces(o), ["pipe", "duct"]);
});

test("rejected options are told to Muse in the next proposal's notes, with why when given", () => {
  assert.equal(kinds.rejectionNotes({}), "");
  const key = kinds.optionKey({ kind: "offset", title: "Offset duct up 400 mm" });
  assert.equal(key, "offset|Offset duct up 400 mm");
  assert.equal(kinds.rejectionNotes({
    [key]: { title: "Offset duct up 400 mm", kind: "offset", edit: "offset 1.00–2.40 m by +400 mm", why: " The void is for sprinklers " },
    "move|Lower": { title: "Lower", kind: "move", edit: "move down 150 mm", why: "" },
  }), 'The reviewer rejected these fixes, so propose different ones: offset "Offset duct up 400 mm" (offset 1.00–2.40 m by +400 mm), '
    + 'because The void is for sprinklers; move "Lower" (move down 150 mm).');
});

test("a seat is named, bears on the other and is framed where it meets it", () => {
  assert.equal(kinds.kindLabel("seat"), "Seat");
  assert.equal(kinds.clearanceText({ kind: "seat", min_clearance_m: 0 }), "bears on it");
  const summary = "seat 'Upstand U1' on 'Base B1': its foot cut where it is inside (0.20 x 0.50 x 0.65 m), so it bears on the top";
  assert.equal(kinds.editText({ kind: "seat", delta_m: [0, 0, 0], edit: { summary } }), summary);
  assert.deepEqual(kinds.framePieces({ kind: "seat", preview: [{ global_id: "u1" }] }), []);
});
