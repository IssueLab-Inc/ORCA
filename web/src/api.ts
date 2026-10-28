export interface Hit { other: string; other_class: string; kind: string; distance_m: number }
export interface Verdict { passed: boolean; hits: Hit[]; min_clearance_m: number | null; checked_against: number }
export interface Piece { global_id: string; verts: number[]; faces: number[] }
export interface Option {
  title: string; moved: string[]; delta_m: number[]; rationale: string; also_needs: string;
  min_clearance_m: number | null;
  kind: FixKind; split_m: number[] | null; preview: Piece[] | null; before: Piece[] | null;
  trim?: TrimCut | null;
  /** A trim inside one model: tidies a joint for the model's author, not a coordination fix. */
  cleanup?: boolean;
  checked_against?: number;
}
export interface Attempt {
  title: string; delta_m: number[]; passed: boolean; reason: string; kind: FixKind; split_m: number[] | null;
  trim?: TrimCut | null;
  hit_ids?: string[];  // what it hit, worst first
}
/** A candidate in place while the agent checks it: a move's elements and delta, or an offset's new pieces. */
export interface Trial { index: number; kind: FixKind; moved: string[]; delta_m: number[]; pieces: Piece[] | null }
/** move: shift the run; offset: split and raise or lower the middle; trim: cut one end back to butt the other element. */
export type FixKind = "move" | "offset" | "trim";
export interface TrimCut { end: "start" | "end"; by_m: number }
export interface Proposal { understanding: string; options: Option[]; attempts: Attempt[]; advice?: string }
/** Revision-pinned context proposals are accepted by server-held ID, as a complete arrangement. */
export interface ContextObjective { element_a: string; element_b: string; report_id?: string; clash_id?: string }
export interface ContextHit { element: string; other: string; kind: string; distance_m: number }
export interface ContextChecks {
  geometry: { passed: boolean; target_resolved: boolean; hits: ContextHit[]; existing_conflicts: ContextHit[]; min_clearance_m: number | null };
  integrity: { passed: boolean; errors: string[]; warnings: string[] };
}
export interface ContextEdit {
  kind: FixKind; element: string; reason: string; label: string; moved: string[]; pieces: string[];
  before: Piece[]; preview: Piece[]; delta_m?: number[]; split_m?: number[]; end?: "start" | "end"; by_m?: number;
}
export interface ContextProposal {
  id: string; scene_revision: number; objective: ContextObjective; title: string; edits: ContextEdit[];
  checks: ContextChecks; review_conditions: { id: string; message: string }[]; passed: boolean;
}
export interface ContextResult {
  type: "context_result"; proposals: ContextProposal[]; message: string; seconds: number; trials: number; model_calls: number;
  blockers?: string[];
}
export type ContextEvent =
  | { type: "context_progress"; phase: "inspecting" | "thinking" | "checking" | "blocked"; message: string }
  | ContextResult
  | { type: "error"; detail: string };
export interface ContextApplied {
  files: number[]; pieces: string[][]; edits: ContextEdit[];
  resolved_pairs: { element_a: string; element_b: string }[]; checks: ContextChecks;
}
/** Progress from the agent while it works (server: agent.resolve), then the result. */
export type AgentEvent =
  | { type: "thinking"; round: number }
  | { type: "reasoning"; round: number; text: string }  // a summary of what Muse Spark is working out, as it thinks
  | { type: "ideas"; round: number; seconds: number; understanding: string; count: number }
  | { type: "checking"; index: number; title: string; kind: string }
  | ({ type: "trial" } & Trial)
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

/** Bulk triage (server: triage.py): one verdict per report clash, by rule or by the triage model. */
export type TriageKind = "real_clash" | "by_design" | "non_physical" | "modelling_error" | "unknown";
export interface TriageVerdict {
  verdict: TriageKind; severity?: "high" | "medium" | "low" | "none"; responsible?: string; action?: string;
  understanding?: string; fix_hint?: string; confidence?: number; source: "rule" | "model"; seconds?: number; error?: string;
  /** What settled a "not a clash" verdict without the model (or overrode it): non_physical, touch, same_element,
   *  no_overlap (Sightline's measure) or reviewed (marked in this browser). */
  basis?: "non_physical" | "touch" | "same_element" | "no_overlap" | "reviewed";
  /** The triage model's own reading, when a settled fact overrode it. */
  model_reading?: string;
  /** What the triage model wrote while working it out (Muse Spark Open streams it). */
  reasoning?: string;
}
export interface TriageModel { model: string; open_weights: boolean; images?: boolean; note?: string }
export type TriageEvent =
  | ({ type: "start"; total: number } & TriageModel)
  | ({ type: "clash"; id: string } & TriageVerdict)
  | { type: "reasoning"; id: string; text: string }
  | { type: "done"; summary: Record<string, number>; seconds: number; error?: string }
  | { type: "ping" };
export interface TriageState extends Partial<TriageModel> {
  results: Record<string, TriageVerdict>; done: boolean; started?: boolean; total?: number; seconds?: number | null;
  error?: string | null;
}

/** The owner's settings (server: owner.py), sent with every call; the server ignores them for anyone but the owner. */
export type Effort = "minimal" | "low" | "medium" | "high";
export interface OwnerSettings { effort?: Effort; triage_effort?: Effort; no_caps?: boolean }
let ownerSettings: OwnerSettings | null = null;
export function setOwnerSettings(s: OwnerSettings | null) { ownerSettings = s; }
const settingsHeader = (): Record<string, string> => (ownerSettings ? { "X-Sightline-Settings": JSON.stringify(ownerSettings) } : {});
const jsonHeaders = () => ({ "Content-Type": "application/json", ...settingsHeader() });

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`/api${path}`, { headers: jsonHeaders(), ...init });
  if (!r.ok) throw new ApiError((await r.json().catch(() => null))?.detail ?? `Request failed (${r.status})`, r.status);
  return r.json() as Promise<T>;
}

export class ApiError extends Error {
  constructor(message: string, public status: number) { super(message); }
}

/** A plan: several fixes chosen together and checked as a whole (server: plans.py). */
export interface PlanItem {
  key: string; element_a: string; element_b: string; label: string; clash_ids: string[]; in_report: boolean;
  distance_m: number | null; understanding: string; option: Option | null; alternatives: Option[]; tried: number; error: string;
}
export interface PlanCheck {
  passed: boolean; items: Record<string, { passed: boolean; reason: string; min_clearance_m: number | null }>;
  conflicts: { a: string; b: string; detail: string }[];
}
export interface Plan {
  kind: "batch" | "root_cause"; title: string; root_cause: string; strategy: string; hub: RootCause | null;
  items: PlanItem[]; check: PlanCheck; seconds: number; advice: string;
}
/** Many clashes of the same kind (server: plans.patterns), and what Muse Spark makes of each. */
export interface Pattern {
  id: string; classes: string[]; files: string[]; cross_discipline: boolean; clashes: number; pairs: number;
  levels: string[]; min_mm: number; max_mm: number; constant: boolean; clash_ids: string[]; examples: string[];
}
export interface PatternVerdict { verdict: "by_design" | "modelling_error" | "real_problem"; cause: string; action: string; rule: string }
export interface RootCausePartner {
  global_id: string; ifc_class: string; name: string; source: string; storey: string | null;
  distance_m: number; clash_ids: string[]; in_report: boolean;
}
export interface RootCause {
  hub: { global_id: string; ifc_class: string; name: string; storey: string | null; source: string };
  partners: RootCausePartner[]; cross_discipline: number; clash_ids: string[]; not_in_report: number;
}
export type PlanEvent =
  | { type: "plan_items"; items: PlanItem[]; skipped: string[] }
  | { type: "item"; key: string; status: "thinking" | "checking" | "done"; attempt?: string; passed?: boolean; ok?: boolean; title?: string }
  | { type: "thinking"; what: string }
  | { type: "root_cause"; root_cause: string; strategy: string; reason: string }
  | { type: "checking_plan"; retry?: string[] }
  | ({ type: "plan" } & Plan)
  | { type: "error"; detail: string };

/** What the chat streams while it works (server: chat.py). */
export type ChatEvent =
  | { type: "session"; id: string }
  | { type: "thinking" }
  | { type: "tool"; name: string; args: Record<string, unknown> }
  | { type: "tool_result"; name: string; summary: string }
  | { type: "ui"; action: "select_clash"; clash_id: string }
  | { type: "ui"; action: "set_view"; mode?: string; section_box?: boolean }
  | { type: "agent"; event: AgentEvent }
  | { type: "context_event"; event: ContextEvent }
  | ({ type: "proposal"; clash_id: string; element_a: string; element_b: string } & Proposal)
  | { type: "plan_started"; kind: "batch" | "root_cause" }
  | { type: "plan_event"; event: PlanEvent }
  | ({ type: "plan" } & Plan)
  | { type: "message"; text: string }
  | { type: "error"; detail: string }
  | { type: "done" };

/** Coordination reports (server: document.py). */
export type Team = "Structure" | "MEP" | "Architecture" | "Site";
export interface ModelTeam { file: string; guess: Team; elements: number }
/** A fix shown in the report: what it changes, and the view of the clash as it is and with the fix. */
export interface Evidence {
  status: "proposed" | "accepted"; title: string; kind: FixKind; edit: string; clearance: string; clearance_m: number | null;
  rationale: string; also_needs: string; advice?: string; moved: string[]; before_img?: string; after_img?: string;
}
/** A team's review of one clash, recorded in the app. */
export interface Signoff { team: Team; name: string; decision: "approve" | "reject"; note: string; at: string }
export type DocEvent =
  | { type: "progress"; step: "explaining" | "summarising" | "rendering" | "bcf"; done?: number; total?: number }
  | { type: "ready"; url: string; name: string; bytes: number }
  | { type: "error"; message: string };

/** POST and read newline-delimited JSON events until the stream ends. */
async function ndjson<T>(path: string, body: unknown, onEvent: (e: T) => boolean | void, signal?: AbortSignal) {
  const r = await fetch(`/api${path}`, { method: "POST", headers: jsonHeaders(), body: JSON.stringify(body), signal });
  if (!r.ok || !r.body) throw new Error((await r.json().catch(() => null))?.detail ?? `Request failed (${r.status})`);
  const reader = r.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    for (;;) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done });
      let nl: number;
      while ((nl = buffer.indexOf("\n")) >= 0) {
        const line = buffer.slice(0, nl).trim();
        buffer = buffer.slice(nl + 1);
        if (signal?.aborted) return;
        if (line && onEvent(JSON.parse(line) as T) === true) return;
      }
      if (done) return;
    }
  } finally { await reader.cancel().catch(() => undefined); reader.releaseLock(); }
}

export const api = {
  contextStream: async (sceneId: string, objective: ContextObjective, onEvent: (e: ContextEvent) => void) => {
    let finished = false;
    await ndjson<ContextEvent>(`/scenes/${sceneId}/context/stream`, objective, (e) => {
      onEvent(e); finished = e.type === "context_result" || e.type === "error"; return finished;
    });
    if (!finished) throw new Error("The server stopped before the wider search finished. Regenerate for the original objective.");
  },
  applyContext: (sceneId: string, proposalId: string, acknowledgedConditions: string[]) =>
    call<ContextApplied>(`/scenes/${sceneId}/context/apply`, { method: "POST",
      body: JSON.stringify({ proposal_id: proposalId, acknowledged_conditions: acknowledgedConditions }) }),
  owner: () => call<{ available: boolean; owner: boolean }>("/owner"),
  unlock: (token: string) => call<{ owner: boolean }>("/owner/unlock", { method: "POST", body: JSON.stringify({ token }) }),
  lock: () => call<{ owner: boolean }>("/owner/lock", { method: "POST" }),
  teams: (reportId: string, sceneId: string | null) =>
    call<{ teams: Team[]; models: ModelTeam[] }>(`/reports/${reportId}/teams${sceneId ? `?scene_id=${sceneId}` : ""}`),
  document: (reportId: string, body: { scene_id: string | null; scope: "combined" | "team" | "model"; teams: Record<string, Team>;
                                      bcf: boolean; evidence: Record<string, Evidence>; reviews: Record<string, Signoff[]>;
                                      marks: Record<string, string>; triage: Record<string, Omit<TriageVerdict, "reasoning">> }, onEvent: (e: DocEvent) => void) =>
    ndjson<DocEvent>(`/reports/${reportId}/document/stream`, body, (e) => { onEvent(e); return e.type !== "progress"; }),
  triage: (reportId: string, sceneId: string | null) =>
    call<TriageState>(`/reports/${reportId}/triage${sceneId ? `?scene_id=${sceneId}` : ""}`),
  /** Triage every clash in the report (or follow the run already going), event by event. */
  triageStream: (reportId: string, sceneId: string | null, onEvent: (e: TriageEvent) => void, rerun = false) => {
    const q = new URLSearchParams({ ...(rerun ? { rerun: "true" } : {}), ...(sceneId ? { scene_id: sceneId } : {}) }).toString();
    return ndjson<TriageEvent>(`/reports/${reportId}/triage/stream${q ? `?${q}` : ""}`, {}, (e) => { onEvent(e); return e.type === "done"; });
  },
  patterns: (reportId: string, sceneId: string, fixed: string[]) =>
    call<Pattern[]>(`/reports/${reportId}/patterns/${sceneId}?fixed=${encodeURIComponent(fixed.join(","))}`),
  triagePatterns: (reportId: string, sceneId: string, fixed: string[]) =>
    call<Record<string, PatternVerdict>>(`/reports/${reportId}/patterns/${sceneId}/triage`, { method: "POST", body: JSON.stringify({ fixed }) }),
  rootCauses: (reportId: string, sceneId: string, fixed: string[]) =>
    call<RootCause[]>(`/reports/${reportId}/root_causes/${sceneId}?fixed=${encodeURIComponent(fixed.join(","))}`),
  /** Build a plan (clash_ids: fix these together; hub: fix the root cause around it). Resolves with the plan. */
  planStream: async (sceneId: string, body: { report_id: string; clash_ids?: string[]; hub?: string; fixed: string[] },
                     onEvent: (e: PlanEvent) => void): Promise<Plan> => {
    let plan: Plan | null = null;
    await ndjson<PlanEvent>(`/scenes/${sceneId}/plan/stream`, body, (e) => {
      if (e.type === "error") throw new Error(e.detail);
      if (e.type === "plan") { plan = e; return true; }
      onEvent(e);
    });
    if (!plan) throw new Error("The server stopped before the plan was ready. Try again.");
    return plan;
  },
  applyPlan: (sceneId: string, options: Option[]) =>
    call<{ files: number[]; pieces: string[][] }>(`/scenes/${sceneId}/plan/apply`, { method: "POST", body: JSON.stringify({ options }) }),
  chat: (body: { message: string; session_id: string | null; scene_id: string | null; report_id: string | null;
                 clash_id: string | null; fixed: string[] }, onEvent: (e: ChatEvent) => void, signal?: AbortSignal) =>
    ndjson<ChatEvent>("/chat", body, (e) => { onEvent(e); return e.type === "done"; }, signal),
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
      method: "POST", headers: jsonHeaders(), body: JSON.stringify({ element_a, element_b, ...from }),
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
  accept: (id: string, o: Option) => (o.kind === "trim" && o.trim
    ? call<{ files: number[]; pieces?: string[] }>(`/scenes/${id}/trim/apply`, { method: "POST", body: JSON.stringify({ element: o.moved[0], end: o.trim.end, by_m: o.trim.by_m }) })
    : o.kind === "offset"
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
  /** A spoken message (16 kHz WAV) to text, with Muse Voice Transcribe; biased to the open report's clash names. */
  transcribe: async (wav: Blob, reportId: string | null) => {
    const form = new FormData();
    form.append("audio", wav, "voice.wav");
    if (reportId) form.append("report_id", reportId);
    const r = await fetch("/api/transcribe", { method: "POST", body: form, headers: settingsHeader() });
    if (!r.ok) throw new Error((await r.json().catch(() => null))?.detail ?? `Transcription failed (${r.status})`);
    return r.json() as Promise<{ transcript: string; duration_ms: number | null }>;
  },
  imageUrl: (reportId: string, clashId: string, index: number) => `/api/reports/${reportId}/clashes/${clashId}/images/${index}`,
  match: (reportId: string, sceneId: string) => call<Matches>(`/reports/${reportId}/match/${sceneId}`),
  measure: (reportId: string, clashId: string, sceneId: string) => call<Measure>(`/reports/${reportId}/clashes/${clashId}/measure/${sceneId}`),
};
