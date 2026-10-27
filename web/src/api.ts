export interface Hit { other: string; other_class: string; kind: string; distance_m: number }
export interface Verdict { passed: boolean; hits: Hit[]; min_clearance_m: number | null; checked_against: number }
export interface Piece { global_id: string; verts: number[]; faces: number[] }
export interface Option {
  title: string; moved: string[]; delta_m: number[]; rationale: string; also_needs: string;
  min_clearance_m: number | null;
  kind: "move" | "offset"; split_m: number[] | null; preview: Piece[] | null; before: Piece[] | null;
}
export interface Attempt { title: string; delta_m: number[]; passed: boolean; reason: string; kind: "move" | "offset"; split_m: number[] | null }
export interface Proposal { understanding: string; options: Option[]; attempts: Attempt[] }
/** Progress from the agent while it works (server: agent.resolve), then the result. */
export type AgentEvent =
  | { type: "thinking"; round: number }
  | { type: "ideas"; round: number; seconds: number; understanding: string; count: number }
  | { type: "checking"; index: number; title: string; kind: string }
  | ({ type: "attempt"; index: number } & Attempt)
  | ({ type: "result" } & Proposal)
  | { type: "error"; detail: string };

/** One side of a clash as the Navisworks report describes it. */
export interface ReportElement {
  global_id: string | null; ifc_class: string | null; name: string; level: string | null; file: string | null;
  system: string | null; description: string | null; part_of: string | null;
}
export interface ReportClash {
  id: string; name: string; guid: string | null; test: string; test_type: string | null; tolerance_m: number | null;
  status: string | null; distance_m: number | null; point: number[] | null; grid: string | null;
  a: ReportElement; b: ReportElement; images: string[]; source: string;
}
export interface Report { id: string; title: string; sources: string[]; clashes: ReportClash[] }
/** Per clash id: the model elements each side matched, and how. */
export type Matches = Record<string, { a: string | null; b: string | null; how: (string | null)[]; show?: (string | null)[] }>;
export interface Measure { matched: boolean; physical: boolean | null; distance_m: number | null }

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`/api${path}`, { headers: { "Content-Type": "application/json" }, ...init });
  if (!r.ok) throw new Error((await r.json().catch(() => null))?.detail ?? `Request failed (${r.status})`);
  return r.json() as Promise<T>;
}

/** What the chat streams while it works (server: chat.py). */
export type ChatEvent =
  | { type: "session"; id: string }
  | { type: "thinking" }
  | { type: "tool"; name: string; args: Record<string, unknown> }
  | { type: "tool_result"; name: string; summary: string }
  | { type: "ui"; action: "select_clash"; clash_id: string }
  | { type: "ui"; action: "set_view"; mode?: string; section_box?: boolean }
  | { type: "agent"; event: AgentEvent }
  | ({ type: "proposal"; clash_id: string; element_a: string; element_b: string } & Proposal)
  | { type: "message"; text: string }
  | { type: "error"; detail: string }
  | { type: "done" };

/** POST and read newline-delimited JSON events until the stream ends. */
async function ndjson<T>(path: string, body: unknown, onEvent: (e: T) => boolean | void) {
  const r = await fetch(`/api${path}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!r.ok || !r.body) throw new Error((await r.json().catch(() => null))?.detail ?? `Request failed (${r.status})`);
  const reader = r.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done });
    let nl: number;
    while ((nl = buffer.indexOf("\n")) >= 0) {
      const line = buffer.slice(0, nl).trim();
      buffer = buffer.slice(nl + 1);
      if (line && onEvent(JSON.parse(line) as T) === true) { reader.cancel(); return; }
    }
    if (done) return;
  }
}

export const api = {
  chat: (body: { message: string; session_id: string | null; scene_id: string | null; report_id: string | null;
                 clash_id: string | null; fixed: string[] }, onEvent: (e: ChatEvent) => void) =>
    ndjson<ChatEvent>("/chat", body, (e) => { onEvent(e); return e.type === "done"; }),
  samples: () => call<string[]>("/samples"),
  open: (samples: string[]) => call<{ id: string; files: string[] }>("/scenes", { method: "POST", body: JSON.stringify({ samples }) }),
  file: async (id: string, index: number) => new Uint8Array(await (await fetch(`/api/scenes/${id}/files/${index}`, { cache: "no-store" })).arrayBuffer()),
  verify: (id: string, moved: string[], delta_m: number[]) =>
    call<Verdict>(`/scenes/${id}/verify`, { method: "POST", body: JSON.stringify({ moved, delta_m }) }),
  propose: (id: string, element_a: string, element_b: string, from?: { report_id: string; clash_id: string }) =>
    call<Proposal>(`/scenes/${id}/propose`, { method: "POST", body: JSON.stringify({ element_a, element_b, ...from }) }),
  /** Propose fixes, hearing each step as it happens. Resolves with the final proposal. */
  proposeStream: async (id: string, element_a: string, element_b: string, from: { report_id: string; clash_id: string } | undefined,
                        onEvent: (e: AgentEvent) => void): Promise<Proposal> => {
    const r = await fetch(`/api/scenes/${id}/propose/stream`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ element_a, element_b, ...from }),
    });
    if (!r.ok || !r.body) throw new Error((await r.json().catch(() => null))?.detail ?? `Request failed (${r.status})`);
    const reader = r.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    for (;;) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done });
      let nl: number;
      while ((nl = buffer.indexOf("\n")) >= 0) {
        const line = buffer.slice(0, nl).trim();
        buffer = buffer.slice(nl + 1);
        if (!line) continue;
        const e = JSON.parse(line) as AgentEvent;
        if (e.type === "error") throw new Error(e.detail);
        if (e.type === "result") return e;
        onEvent(e);
      }
      if (done) throw new Error("The server stopped before Sightline finished. Try again.");
    }
  },
  exportUrl: (id: string) => `/api/scenes/${id}/export`,
  element: (id: string, globalId: string) => call<Record<string, unknown>>(`/scenes/${id}/elements/${encodeURIComponent(globalId)}`),
  /** Keep a fix in the server's model; returns the indexes of the files that changed. */
  accept: (id: string, o: Option) => (o.kind === "offset"
    ? call<{ files: number[]; pieces?: string[] }>(`/scenes/${id}/offset/apply`, { method: "POST", body: JSON.stringify({ element: o.moved[0], split_m: o.split_m, dz_m: o.delta_m[2] }) })
    : call<{ files: number[]; pieces?: string[] }>(`/scenes/${id}/apply`, { method: "POST", body: JSON.stringify({ moved: o.moved, delta_m: o.delta_m }) })),

  reportSamples: () => call<string[]>("/reports/samples"),
  openReport: (sample: string) => call<Report>("/reports", { method: "POST", body: JSON.stringify({ sample }) }),
  /** XML report(s) plus their images; folder uploads keep relative paths so the XML's image links resolve. */
  uploadReport: async (files: File[]) => {
    const form = new FormData();
    for (const f of files) form.append("files", f, f.webkitRelativePath || f.name);
    const r = await fetch("/api/reports/upload", { method: "POST", body: form });
    if (!r.ok) throw new Error((await r.json().catch(() => null))?.detail ?? `Upload failed (${r.status})`);
    return r.json() as Promise<Report>;
  },
  imageUrl: (reportId: string, clashId: string, index: number) => `/api/reports/${reportId}/clashes/${clashId}/images/${index}`,
  match: (reportId: string, sceneId: string) => call<Matches>(`/reports/${reportId}/match/${sceneId}`),
  measure: (reportId: string, clashId: string, sceneId: string) => call<Measure>(`/reports/${reportId}/clashes/${clashId}/measure/${sceneId}`),
};
