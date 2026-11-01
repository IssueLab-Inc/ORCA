import assert from "node:assert/strict";
import test from "node:test";
import { compiled, find, hasText } from "./app-host.mjs";

/** The Edits panel (docs/manual-edits.md): an undone entry says so in its header, beside its id; Redo sits on the one
 * entry next to redo, Undo to here on the kept ones below the newest, both at the row's foot on the right. */

const url = (js) => `data:text/javascript;base64,${Buffer.from(js).toString("base64")}`;
const stub = (names) => url(names.map((n) => `export function ${n}(){return null;}`).join("\n"));
const { EditPanel } = await import(await compiled("../src/EditPanel.tsx", {
  "react/jsx-runtime": import.meta.resolve("react/jsx-runtime"),
  "lucide-react": stub(["Bot", "Download", "Hand", "Network", "Sparkles", "Wand2", "Wrench"]),
  "./editIcons": stub(["RedoIcon", "UndoIcon"]) }));

const entry = (id, state, extra = {}) => ({ id, seq: Number(id.slice(1)), when: "2026-11-01T12:00:00+00:00", source: "you", kind: "push_pull",
  title: `${id} edit`, summary: `${id} edit`, actor: null, params: {}, elements: [], created: [], removed: [], names: {}, files: [0],
  revision: 1, clashes: [], follows: [], check: null, warnings: [], requirements: null, state, picture: null,
  status: { resolved: false, depth_m: 0.3 }, ...extra });
const journal = (entries, redo) => ({ entries, can_undo: true, can_redo: !!redo, undo: "E2", redo });
const render = (j) => EditPanel({ journal: j, busy: false, csvUrl: null, clashLabel: () => null,
  onUndo() {}, onRedo() {}, onUndoTo() {}, onShow() {} });
const row = (tree, id) => find(tree, (n) => n.type === "li" && n.key === id);

test("an undone entry says so in its header, its stale clash state hidden; Redo only on the next to redo", () => {
  const tree = render(journal([entry("E1", "kept"), entry("E2", "kept"), entry("E3", "undone"), entry("E4", "undone")], "E3"));
  const e3 = row(tree, "E3"), e4 = row(tree, "E4");
  const head = find(e3, (n) => n.type === "button" && n.props.className === "edit-main");
  assert.ok(find(head, (n) => n.props?.className === "chip undone-chip"), "the Undone chip is in the row's header");
  assert.ok(!hasText(e3, "Its clash is still open"), "an undone entry hides its clash state");
  assert.ok(hasText(e3, "Redo") && !hasText(e4, "Redo"), "Redo on the entry next to redo only");
  const foot = find(e3, (n) => n.props?.className === "edit-row-actions");
  assert.ok(foot && hasText(foot, "Redo"), "its action is at the row's foot");
  assert.ok(hasText(row(tree, "E1"), "Undo to here") && !hasText(row(tree, "E2"), "Undo to here"), "the newest kept has none: Undo does it");
  assert.ok(hasText(row(tree, "E2"), "Its clash is still open"));
});

test("a hand edit's check counts its collisions only: a hit inside the clearance is not a clash", async () => {
  const { checkLine } = await import(await compiled("../src/EditPanel.tsx", {
    "react/jsx-runtime": import.meta.resolve("react/jsx-runtime"),
    "lucide-react": stub(["Bot", "Download", "Hand", "Network", "Sparkles", "Wand2", "Wrench"]),
    "./editIcons": stub(["RedoIcon", "UndoIcon"]) }));
  const near = entry("E1", "kept", { check: { verified: false, new: [{ kind: "clearance" }], worse: [], cleared: [], min_clearance_m: 0.01 } });
  assert.equal(checkLine(near), "Checked · clear · nearest 10 mm");
  const hit = entry("E2", "kept", { check: { verified: false, new: [{ kind: "collision" }], worse: [], cleared: [{}], accepted_clashes: 1 } });
  assert.equal(checkLine(hit), "Checked · cleared 1 · kept with 1 clash");
});
