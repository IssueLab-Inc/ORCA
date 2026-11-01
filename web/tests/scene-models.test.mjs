import assert from "node:assert/strict";
import test from "node:test";
import { compiled } from "./app-host.mjs";

// Adding and removing models in an open scene (docs/add-and-remove-models.md): the page's side.
const m = await import(await compiled("../src/sceneModels.ts"));

test("a model taken out drops its hidden mark and moves the later ones down", () => {
  assert.deepEqual(m.shiftHidden([0, 2, 3], 2), [0, 2]);
  assert.deepEqual(m.shiftHidden(new Set([1, 3]), 0), [0, 2]);
  assert.deepEqual(m.shiftHidden([], 1), []);
});

test("only samples of the open models' kind that are not open yet can be added", () => {
  const samples = ["NB-Architecture.ifc", "NB-MEP.ifc", "NB-Structure.ifc", "Cell-RevA.step", "Cell-RevB.step"];
  assert.deepEqual(m.addableSamples(samples, ["NB-Structure.ifc", "NB-MEP.ifc"], []), ["NB-Architecture.ifc"]);
  assert.deepEqual(m.addableSamples(samples, ["Cell-RevA.step"], ["Cell-RevA.step"]), ["Cell-RevB.step"]);
  assert.equal(m.isMachine(["Cell-RevA.step"], ["Cell-RevA.step"]), true);
  assert.equal(m.isMachine(["NB-MEP.ifc"], []), false);
});

test("mixing STEP and IFC, or a name already open, is refused before anything is sent", () => {
  const building = ["NB-Structure.ifc", "NB-MEP.ifc"];
  assert.equal(m.addRefusal(["Cell.step"], building, []), "A STEP machine can't join building models yet: open it on its own.");
  assert.equal(m.addRefusal(["NB-Site.ifc"], ["Cell.step"], ["Cell.step"]), "A building model can't join a STEP machine yet: open it on its own.");
  assert.equal(m.addRefusal(["NB-MEP.ifc"], building, []), "NB-MEP.ifc is already open.");
  assert.equal(m.addRefusal(["NB-Architecture.ifc"], building, []), null);
});

test("adding and removing wait for what ORCA is doing, saying what", () => {
  assert.equal(m.waitFor({ proposing: true, detecting: true }), "Wait for the proposal to finish.");
  assert.equal(m.waitFor({ planning: true }), "Wait for the plan to finish.");
  assert.equal(m.waitFor({ triage: true }), "Wait for triage to finish.");
  assert.equal(m.waitFor({ detecting: true }), "Wait for the clash check to finish.");
  assert.equal(m.waitFor({ busy: "Undoing…" }), "Wait for ORCA to finish: undoing.");
  assert.equal(m.waitFor({}), null);
});

test("the warning names what goes with the model and suggests exporting first", () => {
  assert.equal(m.removalWarning("Northbank-Structure.ifc", 118, 2),
    "Remove Northbank-Structure? Its 2 kept edits and the 118 clashes with it go too. Export first to keep the edits.");
  assert.equal(m.removalWarning("Northbank-Structure.ifc", 0, 1),
    "Remove Northbank-Structure? Its 1 kept edit goes too. Export first to keep the edits.");
  assert.equal(m.removalWarning("Northbank-Architecture.ifc", 1, 0), "Remove Northbank-Architecture? The 1 clash with it goes too.");
  assert.equal(m.removalWarning("Northbank-Architecture.ifc", 12, 0), "Remove Northbank-Architecture? The 12 clashes with it go too.");
  assert.equal(m.removalWarning("Cell.step", 0, 0), "Remove Cell? Nothing kept goes with it.");
});

test("the counts come from the list and the edit log", () => {
  const clash = (fa, fb) => ({ a: { file: fa }, b: { file: fb } });
  assert.equal(m.clashesWith([clash("S.ifc", "M.ifc"), clash("M.ifc", "A.ifc"), clash("A.ifc", "S.ifc")], "S.ifc"), 2);
  const entry = (files, state = "kept", model_removed = null) => ({ files, state, model_removed });
  assert.equal(m.editsIn([entry([0]), entry([0, 1]), entry([1]), entry([0], "undone"), entry([0], "kept", "Old.ifc")], 0), 2);
});

const { api } = await import(await compiled("../src/api.ts"));

test("the add and remove calls go to the scene's own routes", async () => {
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push([url, init?.method, init?.body ?? null]);
    return new Response(JSON.stringify({ id: "s1", files: ["A.ifc", "B.ifc"], step: {}, revision: 2, layout: 1, added: [1] }), { status: 200 });
  };
  const added = await api.addModels("s1", ["B.ifc"]);
  assert.deepEqual(added.added, [1]);
  await api.removeModel("s1", 1, "B ifc.ifc");
  assert.deepEqual(calls, [["/api/scenes/s1/models", "POST", JSON.stringify({ samples: ["B.ifc"] })],
    ["/api/scenes/s1/models/1?name=B%20ifc.ifc", "DELETE", null]]);
});

test("an upload added streams to the scene and resolves with the files it added", async () => {
  const urls = [];
  globalThis.XMLHttpRequest = class {
    upload = {};
    open(method, url) { urls.push(url); }
    setRequestHeader() {}
    send() {
      this.status = 200;
      this.responseText = [{ type: "received", bytes: 9 }, { type: "boxes", done: 1, total: 1 },
        { type: "done", id: "s1", files: ["A.ifc", "Mine.ifc"], step: {}, revision: 3, layout: 2, added: [1] }]
        .map((e) => JSON.stringify(e)).join("\n") + "\n";
      queueMicrotask(() => this.onload());
    }
  };
  const seen = [];
  const out = await api.addModelsStream("s1", [new File(["ISO-10303-21;"], "Mine.ifc")], (e) => seen.push(e.type));
  assert.deepEqual(urls, ["/api/scenes/s1/models/upload/stream"]);
  assert.deepEqual(out, { id: "s1", files: ["A.ifc", "Mine.ifc"], step: {}, revision: 3, layout: 2, added: [1] });
  assert.deepEqual(seen, ["packing", "received", "boxes"]);
});
