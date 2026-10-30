import assert from "node:assert/strict";
import test from "node:test";
import { compiled } from "./app-host.mjs";

const react = `data:text/javascript;base64,${Buffer.from("export const useState=(v)=>[v,()=>{}];export const Fragment=()=>null;").toString("base64")}`;
const props = await import(await compiled("../src/Properties.tsx", { react, "react/jsx-runtime": import.meta.resolve("react/jsx-runtime") }));

const girder = {
  global_id: "1eVHoPtl1IhAbbhivqVqb0", ifc_class: "IfcBeam",
  attributes: { Name: "Transfer plate girder", Tag: "TB-L02-01", PredefinedType: "BEAM", ObjectType: "Plate girder" },
  type: { ifc_class: "IfcBeamType", name: "PG 1000x400" }, materials: ["Steel S355"],
  psets: { "Model data": { Level: "Level 02", WebOpenings: "6" }, Pset_BeamCommon: { LoadBearing: true, Span: 12.0000004 } },
  quantities: { Qto_BeamBaseQuantities: { Length: { value: 12, unit: "m" }, NetVolume: { value: 0.6123456, unit: "m³" } } },
  size_m: [0.4, 12, 1], source: "Northbank-Structure.ifc",
};

test("values read as people say them", () => {
  assert.equal(props.shown(true), "Yes");
  assert.equal(props.shown(false), "No");
  assert.equal(props.shown(null), "—");
  assert.equal(props.shown(""), "—");
  assert.equal(props.shown(12.0000004), "12");
  assert.equal(props.shown(0.6123456, "m³"), "0.6123 m³");
  assert.equal(props.shown(["a", 2]), "a, 2");
});

test("the element first (type, material, size, attributes the card lacks), then each set", () => {
  const s = props.sections(girder);
  assert.deepEqual(s.map((x) => x.title), ["Element", "Model data", "Pset_BeamCommon", "Qto_BeamBaseQuantities"]);
  assert.deepEqual(s[0].rows, [
    { name: "Type", value: "PG 1000x400 · BeamType" }, { name: "Material", value: "Steel S355" },
    { name: "Size", value: "400 × 12000 × 1000 mm" }, { name: "Predefined type", value: "BEAM" }, { name: "Object type", value: "Plate girder" },
  ]);
  assert.deepEqual(s[2].rows, [{ name: "LoadBearing", value: "Yes" }, { name: "Span", value: "12" }]);
  assert.deepEqual(s[3].rows, [{ name: "Length", value: "12 m" }, { name: "NetVolume", value: "0.6123 m³" }]);
});

test("an element with nothing but geometry shows its size alone", () => {
  const s = props.sections({ ...girder, attributes: { Name: "Duct" }, type: null, materials: [], psets: {}, quantities: {} });
  assert.deepEqual(s, [{ title: "Element", rows: [{ name: "Size", value: "400 × 12000 × 1000 mm" }] }]);
});

test("the filter keeps matching rows, or a whole set whose name matches", () => {
  const s = props.sections(girder);
  assert.deepEqual(props.filtered(s, "  ").length, 4);
  assert.deepEqual(props.filtered(s, "steel").map((x) => [x.title, x.rows.map((r) => r.name)]), [["Element", ["Material"]]]);
  assert.deepEqual(props.filtered(s, "LEVEL").map((x) => x.title), ["Model data"]);
  assert.deepEqual(props.filtered(s, "qto").map((x) => x.rows.length), [2]);
  assert.deepEqual(props.filtered(s, "nothing like it"), []);
});
