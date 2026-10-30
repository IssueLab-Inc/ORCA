import assert from "node:assert/strict";
import test from "node:test";
import { compiled } from "./app-host.mjs";

const up = await import(await compiled("../src/uploads.ts"));
const file = (name, size) => ({ name, size });

test("files are checked against the server's cap before anything is sent", () => {
  assert.equal(up.uploadRefusal([file("A.ifc", 300e6), file("B.step", 100e6)], 500), null);
  assert.equal(up.uploadRefusal([file("A.ifc", 400e6), file("B.ifc", 200e6)], 500),
    "These files are 600 MB together: the limit here is 500 MB.");
  assert.equal(up.uploadRefusal([file("notes.txt", 10)], 500), "notes.txt is not an IFC or STEP file (.ifc, .step, .stp).");
  assert.equal(up.uploadRefusal(Array.from({ length: 9 }, (_, i) => file(`M${i}.ifc`, 1)), 500), "Choose up to 8 model files at once.");
  assert.equal(up.uploadRefusal([file("A.ifc", 900e6)], null), null);   // the cap not known yet: the server checks
});

test("each stage of a big upload says how far it has got", () => {
  assert.equal(up.uploadStatus({ type: "upload", loaded: 25e6, total: 100e6 }, false), "Uploading 25% (25 of 100 MB)…");
  assert.equal(up.uploadStatus({ type: "received", bytes: 512e6 }, false), "Received 512 MB: reading the models…");
  assert.equal(up.uploadStatus({ type: "received", bytes: 3e6 }, true), "Received: converting the STEP…");
  assert.equal(up.uploadStatus({ type: "boxes", done: 12000, total: 137181 }, false), "Measuring elements: 12,000 of 137,181…");
  assert.equal(up.uploadStatus({ type: "tick" }, false), null);
});

test("an uploaded IFC is read from the visitor's file; a converted STEP is not", () => {
  const files = [{ name: "MEP.ifc" }, { name: "Cell.step" }];
  assert.equal(up.localFile(files, ["MEP.ifc", "Cell.step"], { 1: "Cell.step" }, 0), files[0]);
  assert.equal(up.localFile(files, ["MEP.ifc", "Cell.step"], { 1: "Cell.step" }, 1), null);
});
