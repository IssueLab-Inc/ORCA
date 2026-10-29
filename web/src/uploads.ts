// Uploading your own models (server: app.upload_models_stream; docs/uploads.md): the size check before anything is
// sent, and the words for each stage while a big model goes up and opens.
import type { UploadEvent } from "./api";

const mb = (bytes: number) => (bytes / 1e6 >= 10 ? Math.round(bytes / 1e6).toLocaleString() : (bytes / 1e6).toFixed(1));

/** Why these files cannot be uploaded (too many, too big together, not a model), or null. `maxMb` is the server's cap
 * (GET /api/models), counted on the files as they are, before packing. */
export function uploadRefusal(files: { name: string; size: number }[], maxMb: number | null, maxFiles = 8): string | null {
  if (!files.length) return "Choose at least one IFC or STEP file.";
  if (files.length > maxFiles) return `Choose up to ${maxFiles} model files at once.`;
  const bad = files.find((f) => !/\.(ifc|step|stp)$/i.test(f.name));
  if (bad) return `${bad.name} is not an IFC or STEP file (.ifc, .step, .stp).`;
  const total = files.reduce((n, f) => n + f.size, 0);
  if (maxMb && total > maxMb * 2 ** 20) return `These files are ${mb(total)} MB together: the limit here is ${maxMb} MB.`;
  return null;
}

/** The busy line for an upload event, or null to keep the last one (a heartbeat). */
export function uploadStatus(e: UploadEvent, step: boolean): string | null {
  switch (e.type) {
    case "packing": return `Packing ${e.name} for the upload…`;
    case "upload": {
      const { loaded, total } = e as { loaded: number; total: number };
      return total ? `Uploading ${Math.floor((loaded / total) * 100)}% (${mb(loaded)} of ${mb(total)} MB)…` : "Uploading…";
    }
    case "received": return step ? "Received: converting the STEP…" : `Received ${mb((e as { bytes: number }).bytes)} MB: reading the models…`;
    case "reading": return "Reading the STEP file…";
    case "classifying": return `Muse is naming ${(e as { parts?: number }).parts ?? ""} STEP parts…`;
    case "meshing": return "Converting the STEP parts…";
    case "opening": return "Reading the models…";
    case "boxes": {
      const { done, total } = e as { done: number; total: number };
      return `Measuring elements: ${done.toLocaleString()} of ${total.toLocaleString()}…`;
    }
    default: return null;
  }
}

/** Which opened files the page already holds: an uploaded IFC is parsed from the visitor's own file, not downloaded
 * again; a STEP comes back converted. `step` maps a file index to its STEP name (server: Workspace.step_files). */
export function localFile(files: File[], names: string[], step: Record<string, string> | undefined, index: number): File | null {
  if (step && String(index) in step) return null;
  const name = names[index];
  return files.find((f) => f.name === name && /\.ifc$/i.test(f.name)) ?? null;
}
