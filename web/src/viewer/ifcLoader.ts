// Loads an IFC into ONE BatchedMesh: one draw call, but every element keeps its own transform, colour and visibility.
// That is what makes "preview option 2" a single matrix update. The parse (web-ifc, creased normals, placements from
// the origin: viewer/ifcParse.ts) runs in a worker (viewer/ifcWorker.ts), so the page never stops while a big model is
// read; only the batches are built here. See-through elements (a robot's safety zone, mesh guards, glazing) go in a
// second batch drawn after the solid one without writing depth, so what is inside them still shows.
import * as THREE from "three";
import type { IfcAPI } from "web-ifc";
import { CIRCLE_SEGMENTS, type ParsedModel } from "./ifcParse";
import { ROOM } from "./patch";

export { CIRCLE_SEGMENTS };

export interface LoadedElement {
  globalId: string;
  expressId: number;
  instanceId: number;
  /** The batch it is drawn in: the model's solid `mesh`, or its see-through `glass`. */
  mesh: THREE.BatchedMesh;
  baseColor: THREE.Color;
  /** 1 for solid elements; the IFC style's opacity for see-through ones. */
  baseAlpha: number;
  baseMatrix: THREE.Matrix4;
}

export interface LoadedModel {
  mesh: THREE.BatchedMesh;
  glass: THREE.BatchedMesh | null;
  byGlobalId: Map<string, LoadedElement>;
  byInstance: Map<number, LoadedElement>;
  glassByInstance: Map<number, LoadedElement>;
  stats: { elements: number; triangles: number; parseMs: number };
  /** The IFC plan point [x, y] (metres) its elements were placed from (viewer/origin.ts). */
  origin: [number, number];
}

// ---------------------------------------------------------------- the worker

/** How long the worker stays after its last parse: a federation's files follow each other; then its memory goes back
 * (web-ifc's WebAssembly heap only grows, to over a gigabyte for a 204 MB model). */
const IDLE_MS = 15_000;
type Reply = { ready?: true; id?: number; model?: ParsedModel; error?: string };
let worker: { w: Worker; ready: Promise<boolean> } | null = null;
let noWorker = false;   // it would not start (an old browser, a blocked script): every parse is on the page
let idle = 0;
let serial = 0;
const waiting = new Map<number, { resolve: (m: ParsedModel) => void; reject: (e: Error) => void }>();

/** The worker, started if need be; `ready` says whether its script runs (it says so first). */
function startWorker() {
  if (worker || noWorker) return worker;
  let w: Worker;
  try {
    w = new Worker(new URL("./ifcWorker.ts", import.meta.url), { type: "module" });
  } catch { noWorker = true; return null; }
  let started: (ok: boolean) => void = () => undefined;
  const ready = new Promise<boolean>((resolve) => { started = resolve; });
  w.onmessage = (e: MessageEvent<Reply>) => {
    if (e.data.ready) { started(true); return; }
    const job = e.data.id != null ? waiting.get(e.data.id) : undefined;
    if (!job) return;
    waiting.delete(e.data.id!);
    if (e.data.model) job.resolve(e.data.model); else job.reject(new Error(e.data.error ?? "The model could not be read."));
    if (!waiting.size) { clearTimeout(idle); idle = window.setTimeout(stopWorker, IDLE_MS); }
  };
  // Before it said it was ready, the script never ran: parse on the page from now on. After, the worker died with the
  // files it had (out of memory): those fail, the next parse starts a new one.
  w.onerror = (e) => {
    e.preventDefault();
    started(false);
    stopWorker();
    for (const job of waiting.values()) job.reject(new Error("The model reader stopped (out of memory?). Open fewer or smaller models."));
    waiting.clear();
  };
  worker = { w, ready };
  ready.then((ok) => { if (!ok) noWorker = true; });
  return worker;
}

function stopWorker() {
  clearTimeout(idle);
  worker?.w.terminate();
  worker = null;
}

/** web-ifc on the page, for when no worker starts: loaded only then. */
let pageApi: Promise<IfcAPI> | null = null;
async function parseHere(bytes: Uint8Array, origin: [number, number] | null): Promise<ParsedModel> {
  const [{ IfcAPI: Api }, parse] = await Promise.all([import("web-ifc"), import("./ifcParse")]);
  pageApi ??= (async () => { const ifc = new Api(); ifc.SetWasmPath("/wasm/"); await ifc.Init(); return ifc; })();
  return parse.parseIfc(await pageApi, bytes, origin);
}

/** Parse one IFC off the page's thread (on it when no worker starts). The bytes are handed to the worker, not copied:
 * the caller's array is empty after (a view onto part of a buffer is copied first). */
export async function parseIfc(bytes: Uint8Array, origin: [number, number] | null = null): Promise<ParsedModel> {
  const started = startWorker();
  if (!started || !(await started.ready) || worker !== started) return parseHere(bytes, origin);
  clearTimeout(idle);
  const whole = bytes.byteOffset === 0 && bytes.byteLength === bytes.buffer.byteLength ? bytes : bytes.slice();
  return new Promise<ParsedModel>((resolve, reject) => {
    const id = ++serial;
    waiting.set(id, { resolve, reject });
    started.w.postMessage({ id, bytes: whole, origin }, [whole.buffer]);
  });
}

// ---------------------------------------------------------------- the batches

/** The batches for a parsed model: solid and see-through elements, each element one geometry and one instance. */
export function buildModel(p: ParsedModel): LoadedModel {
  const alpha = (e: number) => p.colors[e * 4 + 3];
  const byGlobalId = new Map<string, LoadedElement>();
  const batch = (list: number[], byInstance: Map<number, LoadedElement>) => {
    let vertexCount = 0;
    let indexCount = 0;
    for (const e of list) { vertexCount += p.vertexCount[e]; indexCount += p.indexCount[e]; }
    const material = new THREE.MeshStandardMaterial({ metalness: 0, roughness: 0.85, side: THREE.DoubleSide });
    // Room for the pieces a kept fix adds (offset and route pieces, bends), so accepting one patches the batch in place
    // (viewer/patch.ts) instead of regrowing it the first time.
    const mesh = new THREE.BatchedMesh(list.length + ROOM.instances, vertexCount + ROOM.vertices, indexCount + ROOM.indices, material);
    for (const e of list) {
      const v0 = p.vertexStart[e] * 3, v1 = v0 + p.vertexCount[e] * 3, i0 = p.indexStart[e], i1 = i0 + p.indexCount[e];
      const geo = new THREE.BufferGeometry();   // views onto the parsed arrays: the batch copies them in
      geo.setAttribute("position", new THREE.BufferAttribute(p.position.subarray(v0, v1), 3));
      geo.setAttribute("normal", new THREE.BufferAttribute(p.normal.subarray(v0, v1), 3));
      geo.setIndex(new THREE.BufferAttribute(p.index.subarray(i0, i1), 1));
      const instanceId = mesh.addInstance(mesh.addGeometry(geo));
      const baseColor = new THREE.Color(p.colors[e * 4], p.colors[e * 4 + 1], p.colors[e * 4 + 2]);
      mesh.setColorAt(instanceId, new THREE.Vector4(baseColor.r, baseColor.g, baseColor.b, alpha(e)));
      const globalId = p.globalIds[e];
      const el = { globalId, expressId: p.expressIds[e], instanceId, mesh, baseColor, baseAlpha: alpha(e), baseMatrix: new THREE.Matrix4() };
      byGlobalId.set(globalId, el);
      byInstance.set(instanceId, el);
    }
    return { mesh, triangles: indexCount / 3 };
  };
  const SEE_THROUGH = 0.99;
  const all = Array.from({ length: p.expressIds.length }, (_, e) => e);
  const byInstance = new Map<number, LoadedElement>();
  const glassByInstance = new Map<number, LoadedElement>();
  const solid = batch(all.filter((e) => alpha(e) >= SEE_THROUGH), byInstance);
  const seeThrough = all.filter((e) => alpha(e) < SEE_THROUGH);
  const glass = seeThrough.length ? batch(seeThrough, glassByInstance) : null;
  return {
    mesh: solid.mesh, glass: glass?.mesh ?? null, byGlobalId, byInstance, glassByInstance,
    stats: { elements: all.length, triangles: solid.triangles + (glass?.triangles ?? 0), parseMs: 0 },
    origin: p.origin,
  };
}

/** Parse one IFC (off the page's thread) and build its batches. `origin` (IFC plan metres): the point to place its
 * elements from, so a federation shares one; null picks it from this file's elements (`origin.pickOrigin`: zero near
 * zero). The bytes are handed over: the caller's array is empty after. */
export async function loadIfc(bytes: Uint8Array, origin: [number, number] | null = null): Promise<LoadedModel> {
  const t0 = performance.now();
  const model = buildModel(await parseIfc(bytes, origin));
  model.stats.parseMs = Math.round(performance.now() - t0);
  return model;
}
