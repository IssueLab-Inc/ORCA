import assert from "node:assert/strict";
import test from "node:test";
import { compiled } from "./app-host.mjs";

const names = await import(await compiled("../src/names.ts"));

test("files lose the prefix their set shares, whatever the project is called", () => {
  assert.deepEqual(names.shortNames(["Northbank-Structure.ifc", "Northbank-MEP.ifc"]), ["Structure", "MEP"]);
  assert.deepEqual(names.shortNames(["Tower_A Structure.ifc", "Tower_A Services.ifc"]), ["Structure", "Services"]);
  assert.equal(names.sharedPrefix(["Tower_A Structure.ifc", "Tower_A Services.ifc"]), "Tower_A ");
});

test("a lone file, or files with nothing worth cutting, keep their names", () => {
  assert.deepEqual(names.shortNames(["PC-03-Palletising-Cell-RevA.step"]), ["PC-03-Palletising-Cell-RevA"]);
  assert.deepEqual(names.shortNames(["a-1.ifc", "a-2.ifc"]), ["a-1", "a-2"]);
  // The cut ends at a separator, never inside a word: "Site" and "Site-B" share no "Site-".
  assert.deepEqual(names.shortNames(["Site.ifc", "Site-B.ifc"]), ["Site", "Site-B"]);
  assert.deepEqual(names.shortNames(["Plant-A.ifc", "Plant-A-B.ifc"]), ["A", "A-B"]);
});
