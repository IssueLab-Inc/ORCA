// web-ifc loads its WebAssembly at runtime; serve it from /wasm/ so dev and build both find it.
import { cpSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const out = join(root, "public", "wasm");
mkdirSync(out, { recursive: true });
for (const f of ["web-ifc.wasm", "web-ifc-mt.wasm"]) {
  try { cpSync(join(root, "node_modules", "web-ifc", f), join(out, f)); } catch { /* mt build is optional */ }
}
