import assert from "node:assert/strict";
import test from "node:test";
import * as THREE from "three";
import { compiled, originModule } from "./app-host.mjs";

/** The IFC parse runs in a worker (docs/architecture/13-3d-viewer.md, "Loading": a 204 MB model held the page for
 * about six seconds) and hands back a few long arrays; the page builds the batches from them. Here with a stand-in for
 * web-ifc: one triangle, placed by matrices in web-ifc's Y-up frame. */

const three = import.meta.resolve("three");
await originModule();
const origin = await compiled("../src/viewer/origin.ts", { three });
const normals = await compiled("../src/viewer/normals.ts", { three });
const { parseIfc, buffers } = await import(await compiled("../src/viewer/ifcParse.ts", { three, "./normals": normals, "./origin": origin }));
const { buildModel } = await import(await compiled("../src/viewer/ifcLoader.ts", { three,
  "./ifcParse": await compiled("../src/viewer/ifcParse.ts", { three, "./normals": normals, "./origin": origin }),
  "./patch": `data:text/javascript,export const ROOM={instances:4,vertices:64,indices:192};` }));

// A triangle in its own coordinates, interleaved x, y, z, nx, ny, nz as web-ifc gives it.
const TRIANGLE = new Float32Array([0, 0, 0, 0, 0, 1, 1, 0, 0, 0, 0, 1, 0, 1, 0, 0, 0, 1]);
const at = (x, y, z) => new THREE.Matrix4().makeTranslation(x, y, z).toArray();

function fakeIfc(elements) {
  let closed = 0;
  return {
    closed: () => closed,
    OpenModel: () => 7,
    CloseModel: () => { closed++; },
    StreamAllMeshes(_, each) {
      for (const e of elements) each({ expressID: e.id, geometries: { size: () => e.placed.length, get: (i) => e.placed[i] } });
    },
    GetGeometry: () => ({ GetVertexData: () => 0, GetVertexDataSize: () => 0, GetIndexData: () => 0, GetIndexDataSize: () => 0, delete() {} }),
    GetVertexArray: () => TRIANGLE,
    GetIndexArray: () => new Uint32Array([0, 1, 2]),
    GetLine: (_, id) => ({ GlobalId: { value: `gid-${id}` } }),
  };
}

const placed = (matrix, color = { x: 0.5, y: 0.25, z: 1, w: 1 }) => ({ geometryExpressID: 99, flatTransformation: matrix, color });
// Two elements 418 km out (Snowdon Towers' survey coordinates; web-ifc's z is −IFC y): a wall placed once, a window
// placed twice (two pieces of one element) and see-through.
const ELEMENTS = [
  { id: 11, placed: [placed(at(417615, 3, -78710))] },
  { id: 12, placed: [placed(at(417616, 3, -78710), { x: 0.2, y: 0.4, z: 0.6, w: 0.3 }), placed(at(417617, 4, -78710))] },
];

test("a parse packs every element's placed triangles into a few arrays, drawn from the federation's origin", () => {
  const ifc = fakeIfc(ELEMENTS);
  const p = parseIfc(ifc, new Uint8Array(1), null);
  assert.deepEqual(p.origin, [417616, 78710], "the median placement, to the metre");
  assert.deepEqual([...p.expressIds], [11, 12]);
  assert.deepEqual(p.globalIds, ["gid-11", "gid-12"]);
  assert.deepEqual([...p.vertexCount], [3, 6], "the window's two placements are one element");
  assert.deepEqual([...p.indexStart], [0, 3]);
  assert.deepEqual([...p.index.subarray(3)], [0, 1, 2, 3, 4, 5], "the second piece's triangle numbered after the first's");
  // Placed relative to the origin in double precision: small numbers, exact, though the placements are 418 km out.
  assert.deepEqual([...p.position.subarray(0, 9)], [-1, 3, 0, 0, 3, 0, -1, 4, 0]);
  assert.deepEqual([...p.position.subarray(18, 21)], [1, 4, 0], "the window's second piece, 1 m along and 1 m up");
  assert.deepEqual([...p.normal.subarray(0, 3)], [0, 0, 1]);
  assert.deepEqual([...p.colors.subarray(4, 8)].map((c) => +c.toFixed(2)), [0.2, 0.4, 0.6, 0.3], "an element's first placement's style");
  assert.equal(ifc.closed(), 1, "web-ifc's model closed");
  assert.equal(buffers(p).length, 9, "every array handed over, not copied");
  const second = parseIfc(fakeIfc(ELEMENTS), new Uint8Array(1), [417000, 78000]);
  assert.deepEqual([...second.position.subarray(0, 3)], [615, 3, -710], "a given origin (the federation's) is used as it is");
});

test("the page builds the batches from the parse: solid and see-through elements, their colours and GlobalIds", () => {
  const m = buildModel(parseIfc(fakeIfc(ELEMENTS), new Uint8Array(1), null));
  assert.equal(m.byGlobalId.size, 2);
  assert.equal(m.byGlobalId.get("gid-11").mesh, m.mesh, "solid");
  assert.equal(m.byGlobalId.get("gid-12").mesh, m.glass, "alpha 0.3: drawn see-through");
  assert.equal(m.byGlobalId.get("gid-12").baseAlpha.toFixed(2), "0.30");
  assert.deepEqual(m.stats, { elements: 2, triangles: 3, parseMs: 0 });
  assert.deepEqual(m.origin, [417616, 78710]);
  const box = new THREE.Box3();
  m.mesh.getBoundingBoxAt(m.byGlobalId.get("gid-11").instanceId, box);
  assert.deepEqual(box.min.toArray(), [-1, 3, 0], "its triangle where the parse put it");
});

test("a parse that fails still closes web-ifc's model", () => {
  const ifc = fakeIfc(ELEMENTS);
  ifc.StreamAllMeshes = () => { throw new Error("broken file"); };
  assert.throws(() => parseIfc(ifc, new Uint8Array(1), null), /broken file/);
  assert.equal(ifc.closed(), 1);
});
