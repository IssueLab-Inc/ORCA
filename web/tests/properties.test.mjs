import assert from "node:assert/strict";
import test from "node:test";
import { compiled } from "./app-host.mjs";

const react = `data:text/javascript;base64,${Buffer.from("export const useState=(v)=>[v,()=>{}];export const Fragment=()=>null;").toString("base64")}`;
const stub = (names) => `data:text/javascript;base64,${Buffer.from(names.map((n) => `export function ${n}(){return null;}`).join("\n")).toString("base64")}`;
const props = await import(await compiled("../src/Properties.tsx", { react, "react/jsx-runtime": import.meta.resolve("react/jsx-runtime"),
  "lucide-react": stub(["Check", "ChevronsDownUp", "ChevronsUpDown", "Copy", "Focus", "ListFilter", "Palette", "Pencil", "X"]),
  "./ui": stub(["IconButton"]) }));

const storey = { global_id: "3DHpFFi5PGif08WLyvTtOv", ifc_class: "IfcBuildingStorey", name: "Level 02", file: 0 };
const girder = {
  global_id: "1eVHoPtl1IhAbbhivqVqb0", ifc_class: "IfcBeam", name: "Transfer plate girder", source: "Northbank-Structure.ifc", file: 0,
  attributes: [{ name: "Name", value: "Transfer plate girder" }, { name: "Tag", value: "TB-L02-01" },
    { name: "PredefinedType", value: "BEAM" }, { name: "ObjectType", value: "Plate girder" }],
  type: { global_id: "t", ifc_class: "IfcBeamType", name: "PG 1000x400", attributes: [{ name: "Name", value: "PG 1000x400" }] },
  storey, container: storey, path: [{ global_id: "p", ifc_class: "IfcProject", name: "Northbank", file: 0 }, storey],
  materials: [{ usage: "single", name: "Steel S355", from_type: false, items: [{ material: "Steel S355" }], sets: [] }],
  classifications: [{ system: "Uniclass 2015", identification: "Ss_20_10_75_35", name: "Steel beams", location: null }],
  groups: [{ global_id: "g", ifc_class: "IfcBuildingSystem", name: "Frame" }],
  documents: [{ identification: "S-201", name: "Beam schedule", location: "https://example.com/s201.pdf" }],
  sets: [
    { name: "Model data", kind: "pset", props: [{ name: "Level", value: "Level 02" }, { name: "WebOpenings", value: "6" }] },
    { name: "Pset_BeamCommon", kind: "pset", props: [{ name: "LoadBearing", value: true }, { name: "Span", value: 12.0000004, unit: "m" },
      { name: "Reference", value: "PG1000", from_type: true },
      { name: "Service temperature", kind: "bounded", value: { lower: 10, upper: 20, set_point: 18 }, unit: "°C" },
      { name: "Connection", kind: "complex", value: "End plate", rows: [{ name: "Torque", value: 210 }] }] },
    { name: "Qto_BeamBaseQuantities", kind: "qto", from_type: true, props: [{ name: "Length", value: 12, unit: "m", from_type: true },
      { name: "NetVolume", value: 0.6123456, unit: "m³", from_type: true }] },
  ],
  size_m: [0.4, 12, 1],
};

test("values read as people say them, lengths in millimetres", () => {
  assert.equal(props.shown(true), "Yes");
  assert.equal(props.shown(false), "No");
  assert.equal(props.shown(null), "—");
  assert.equal(props.shown(""), "—");
  assert.equal(props.shown(12.0000004), "12");
  assert.equal(props.shown(0.6123456, "m³"), "0.6123 m³");
  assert.equal(props.shown(0.1025, "m"), "102.5 mm");
  assert.equal(props.shown(["a", 2]), "a, 2");
  assert.equal(props.classWords("IfcDistributionSystem"), "Distribution system");
});

test("the element first, then its type, materials, classification, groups, documents, then each set", () => {
  const s = props.sections(girder);
  assert.deepEqual(s.map((x) => x.title), ["Element", "Type · PG 1000x400", "Materials", "Classification", "Systems and groups",
    "Documents", "Model data", "Pset_BeamCommon", "Qto_BeamBaseQuantities"]);
  assert.deepEqual(s[0].rows.map((r) => [r.name, r.value]), [
    ["Class", "IfcBeam"], ["Name", "Transfer plate girder"], ["Tag", "TB-L02-01"], ["Predefined type", "BEAM"],
    ["Object type", "Plate girder"], ["GlobalId", "1eVHoPtl1IhAbbhivqVqb0"], ["Storey", "Level 02"],
    ["File", "Northbank-Structure.ifc"], ["Size", "400 × 12000 × 1000 mm"]]);
  assert.deepEqual(s[0].rows.find((r) => r.name === "Storey").link, storey);
  assert.deepEqual(s[2].rows, [{ name: "Material", value: "Steel S355", fromType: undefined, raw: "Steel S355", facet: "material",
    edit: { kind: "material" } }]);
  assert.equal(s[3].rows[0].value, "Ss_20_10_75_35 Steel beams");
  assert.equal(s[4].rows[0].name, "Building system");
  assert.equal(s[5].rows[0].href, "https://example.com/s201.pdf");
  const common = s[7].rows;
  assert.deepEqual(common.map((r) => [r.name, r.value]), [["LoadBearing", "Yes"], ["Span", "12000 mm"], ["Reference", "PG1000"],
    ["Service temperature", "10 °C to 20 °C (set point 18 °C)"], ["Connection", "End plate"], ["Connection › Torque", "210"]]);
  assert.equal(common[2].fromType, true);
  assert.equal(s[8].fromType, true);
  assert.deepEqual(s[8].rows.map((r) => r.value), ["12000 mm", "0.6123 m³"]);
});

test("a row the filters can use carries its facet key and the server's value", () => {
  const rows = props.sections(girder).flatMap((x) => x.rows);
  const by = (n) => rows.find((r) => r.name === n);
  assert.deepEqual([by("Class").facet, by("Class").raw], ["class", "IfcBeam"]);
  assert.deepEqual([by("Tag").facet, by("Tag").raw], ["attr:Tag", "TB-L02-01"]);
  assert.deepEqual([by("Level").facet, by("Level").raw], ["pset:Model data/Level", "Level 02"]);
  assert.deepEqual([by("Span").facet, by("Span").raw], ["pset:Pset_BeamCommon/Span", 12.0000004]);
  assert.deepEqual([by("Connection › Torque").facet, by("Connection › Torque").raw], ["pset:Pset_BeamCommon/Connection/Torque", 210]);
  assert.deepEqual([by("Length").facet, by("Length").raw], ["qto:Qto_BeamBaseQuantities/Length", 12]);
  assert.deepEqual([by("Ss_20_10_75_35") ?? by("Uniclass 2015")].map((r) => [r.facet, r.raw]), [["classif:Uniclass 2015", "Ss_20_10_75_35"]]);
  assert.equal(by("Service temperature").facet, undefined, "a range is not one value to match");
  assert.equal(by("GlobalId").facet, undefined);
});

test("an object with nothing but geometry shows what it is, where and its size", () => {
  const s = props.sections({ ...girder, attributes: [{ name: "Name", value: "Duct" }], type: null, materials: [], classifications: [],
    groups: [], documents: [], sets: [] });
  assert.deepEqual(s.map((x) => x.title), ["Element"]);
});

test("the filter keeps matching rows, or a whole set whose name matches", () => {
  const s = props.sections(girder);
  assert.deepEqual(props.filtered(s, "  ").length, 9);
  assert.deepEqual(props.filtered(s, "steel b").map((x) => [x.title, x.rows.map((r) => r.name)]), [["Classification", ["Uniclass 2015"]]]);
  assert.deepEqual(props.filtered(s, "WEBOPEN").map((x) => x.title), ["Model data"]);
  assert.deepEqual(props.filtered(s, "qto").map((x) => x.rows.length), [2]);
  assert.deepEqual(props.filtered(s, "nothing like it"), []);
});

test("a row's pencil changes what the element says of its own, never its type's values or its quantities", () => {
  const s = props.sections(girder);
  const edit = (title, name) => s.find((x) => x.title.startsWith(title)).rows.find((r) => r.name === name)?.edit;
  assert.deepEqual(edit("Element", "Name"), { kind: "attribute", name: "Name" });
  assert.deepEqual(edit("Element", "Predefined type"), { kind: "attribute", name: "PredefinedType" });
  assert.deepEqual(edit("Element", "Storey"), { kind: "container" });
  assert.equal(edit("Element", "Class"), undefined);
  assert.deepEqual(edit("Type", "Name"), { kind: "type" });
  assert.deepEqual(edit("Materials", "Material"), { kind: "material" });
  assert.deepEqual(edit("Pset_BeamCommon", "Span"), { kind: "property", pset: "Pset_BeamCommon", name: "Span" });
  assert.equal(edit("Pset_BeamCommon", "Reference"), undefined, "given by its type");
  assert.equal(edit("Pset_BeamCommon", "Service temperature"), undefined, "a range");
  assert.equal(edit("Pset_BeamCommon", "Connection › Torque"), undefined, "a part");
  assert.equal(edit("Qto_BeamBaseQuantities", "Length"), undefined, "quantities follow the body");
});

test("a change is what the server takes: typed text, a number kept a number, yes and no, a choice", () => {
  assert.deepEqual(props.changeFor({ kind: "attribute", name: "Tag" }, " TB-02 "), { kind: "attribute", name: "Tag", value: "TB-02" });
  assert.deepEqual(props.changeFor({ kind: "attribute", name: "Description" }, ""), { kind: "attribute", name: "Description", value: null });
  const span = { kind: "property", pset: "Pset_BeamCommon", name: "Span" };
  assert.deepEqual(props.changeFor(span, "12.5", 12), { kind: "property", pset: "Pset_BeamCommon", name: "Span", value: 12.5 });
  assert.equal(props.changeFor({ ...span, name: "LoadBearing" }, "no", true).value, false);
  assert.deepEqual(props.changeFor({ kind: "material" }, "42"), { kind: "material", material: 42 });
  assert.deepEqual(props.changeFor({ kind: "type" }, "3EaJ"), { kind: "type", type: "3EaJ" });
  const choices = { types: [{ global_id: "t1", name: "PG 1000x400" }], containers: [{ global_id: "s2", name: "Level 02" }],
    materials: [{ id: 7, name: "Steel S355" }], predefined: ["BEAM", "JOIST"] };
  assert.deepEqual(props.editOptions({ kind: "type" }, choices), [{ value: "t1", label: "PG 1000x400" }]);
  assert.deepEqual(props.editOptions({ kind: "material" }, choices), [{ value: "7", label: "Steel S355" }]);
  assert.deepEqual(props.editOptions({ kind: "attribute", name: "PredefinedType" }, choices).map((o) => o.value), ["BEAM", "JOIST"]);
  assert.equal(props.editOptions({ kind: "attribute", name: "Tag" }, choices), null);
});
