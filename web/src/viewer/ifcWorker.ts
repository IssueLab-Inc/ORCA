// The IFC parse, off the page's thread (docs/architecture/13-3d-viewer.md, "Loading"): a 204 MB model held the page
// for about six seconds. One request at a time, in the order sent: { id, bytes, origin } in, { id, model } (its buffers
// handed over, not copied) or { id, error } out. viewer/ifcLoader.ts starts it, and ends it when it has been idle a
// while, which gives web-ifc's memory back (a WebAssembly heap only grows).
import { IfcAPI } from "web-ifc";
import { buffers, parseIfc } from "./ifcParse";

type Request = { id: number; bytes: Uint8Array; origin: [number, number] | null };
// The worker's own scope (the project's types are the page's: no WebWorker lib beside the DOM one).
const scope = self as unknown as {
  onmessage: ((e: MessageEvent<Request>) => void) | null;
  postMessage(message: unknown, transfer?: Transferable[]): void;
};

let api: Promise<IfcAPI> | null = null;
const ready = () => (api ??= (async () => {
  const ifc = new IfcAPI();
  ifc.SetWasmPath("/wasm/");
  await ifc.Init();
  return ifc;
})());

scope.postMessage({ ready: true });   // the script runs: the page can hand its files over
scope.onmessage = async (e) => {
  const { id, bytes, origin } = e.data;
  try {
    const model = parseIfc(await ready(), bytes, origin);
    scope.postMessage({ id, model }, buffers(model));
  } catch (err) {
    scope.postMessage({ id, error: (err as Error)?.message ?? String(err) });
  }
};
