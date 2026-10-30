import type { ElementMesh } from "./viewer/patch";
export interface Hit { other: string; other_class: string; kind: string; distance_m: number }
export interface Verdict {
  passed: boolean; hits: Hit[]; min_clearance_m: number | null; checked_against: number;
  /** Why a move fails without a hit: it would pull a joint apart (connections.plan_move) or leave what stood on
   *  something standing on nothing (verify.keep_supports). */
  reason?: string | null;
  /** A move's new placements: what was asked to move and what it takes along. */
  placements?: Record<string, number[]>;
  /** The segments a move stretches so its joints hold, as they would be. */
  preview?: Piece[] | null;
  /** What a move carried and stretched (`summary`), or, when it was refused before it was tried, the joints it would
   *  pull apart (`refused_at`). */
  joints?: { refused_at?: string[]; summary?: string };
}
export interface Piece { global_id: string; verts: number[]; faces: number[] }
export interface Option {
  title: string; moved: string[]; delta_m: number[]; rationale: string; also_needs: string;
  min_clearance_m: number | null;
  kind: FixKind; split_m: number[] | null; preview: Piece[] | null; before: Piece[] | null;
  trim?: TrimCut | null;
  /** A trim inside one model: tidies a joint for the model's author, not a coordination fix. */
  cleanup?: boolean;
  checked_against?: number;
  /** The coordination requirements it meets, in plain words (server: requirements.meets). */
  meets?: string[];
  /** The newer kinds' parameters (route steps, a resize, a penetration), with the edit in a few words. */
  edit?: FixEdit | null;
  /** Who must review it before it is built ("structure", "services"), when geometry alone cannot say it works. */
  review?: string | null;
  /** Who proposed it, as people read it ("Muse Spark", "Muse Wonder"). */
  model?: string;
}
export interface FixEdit { summary?: string; key?: string; [param: string]: unknown }
export interface Attempt {
  title: string; delta_m: number[]; passed: boolean; reason: string; kind: FixKind; split_m: number[] | null;
  trim?: TrimCut | null;
  hit_ids?: string[];  // what it hit, worst first
  edit?: FixEdit | null;
  where?: number[][];  // where the worst hits are, world metres
  model?: string;      // whose idea it was ("Muse Spark", "Muse Wonder")
}
/** A candidate in place while the agent checks it: a move's elements and delta, or an offset's new pieces. */
export interface Trial { index: number; kind: FixKind; moved: string[]; delta_m: number[]; pieces: Piece[] | null; summary?: string }
/** move: shift the run; offset: split and raise or lower the middle; trim: cut one end back to butt the other element;
 * route: a detour of several steps; resize: a flatter section past the obstacle; penetration: an opening through it. */
/** A kept fix: the files it changed, a split run's pieces, and how to patch the page's model (Patch). A penetration whose
 * host the requirements lock comes back `cut: false`, with who cuts it. */
/** A kept fix: `pieces`, its split run (the original first); `groups`, every run it split (a combined fix's several). */
export type Kept = { files: number[]; pieces?: string[]; groups?: string[][]; cut?: boolean; blocked_by?: string } & Patch;
export type FixKind = "move" | "offset" | "trim" | "route" | "resize" | "penetration" | "combined";
export interface TrimCut { end: "start" | "end"; by_m: number }
/** Under requirements that allow no edit: Muse Spark's best idea for the designer, never tried or applied. */
export interface Recommendation {
  title: string; kind: FixKind; element: string; delta_m: number[]; split_m: number[] | null; rationale: string;
  also_needs: string; blocked_by: string; others: string[]; edit?: FixEdit | null;
}
export interface Proposal {
  understanding: string; options: Option[]; attempts: Attempt[]; advice?: string;
  recommendation?: Recommendation | null; requirements?: string | null;
  clearance_m?: number;  // the clearance every option had to keep (25 mm, or what the requirements ask)
  model?: string;        // the model that ran these rounds ("Muse Spark", "Muse Wonder")
  usage?: Usage | null;  // its tokens, and what they cost for a model billed per token
  /** A second try on a larger model (docs/escalation.md): the first try's options and ideas are carried in. */
  escalated?: boolean;
}
export interface Usage { model: string; calls: number; input_tokens: number; output_tokens: number; reasoning_tokens: number; usd: number }
/** Show it built (server: built.make): Muse Image's restyle of a fix's view, checked against the model. */
export interface BuiltResult {
  status: "done" | "failed"; key?: string; image_url?: string; lines_url?: string; why?: string;
  gate?: { f: number; tile: number }; verdicts?: { verdict: string; differences: { kind: string; what: string; where: string; size: string }[] }[];
  tried?: number; seconds?: number; cached?: boolean;
  judge?: string;   // who checked it: "Muse Wonder", or "Muse Spark" (the lighter check, when Wonder's budget was spent)
}
export type BuiltEvent =
  | { type: "drawing"; round: number; pictures: number; shared?: boolean }
  | { type: "gate"; round: number; picture: number; f?: number; tile?: number; passed: boolean; error?: string }
  | { type: "judging"; round: number; picture: number }
  | { type: "judged"; round: number; picture: number; verdicts: string[] }
  | { type: "retry"; why: string }
  | ({ type: "result" } & BuiltResult)
  | { type: "error"; detail: string };
/** Whether a clash Muse Spark could not fix may go to a larger model for a second try (server: escalation_info). */
export interface EscalationInfo { model: string; label: string; mode: "off" | "button" | "auto"; available: boolean }
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
export interface ContextApplied extends Patch {
  files: number[]; pieces: string[][]; edits: ContextEdit[];
  resolved_pairs: { element_a: string; element_b: string }[]; checks: ContextChecks;
}
/** What a kept fix sends back so the page can update its model in place instead of reloading the files it changed
 * (server: Workspace.patch). A page whose model is not at `revision_before`, or that gets no meshes, reloads. */
export interface Patch {
  scene_id?: string; revision_before?: number; revision?: number; meshes?: ElementMesh[] | null;
  history?: [number, number[]][];   // (revision, files it changed): a page that missed an edit reloads those
}
/** Progress from the agent while it works (server: agent.resolve), then the result. */
export type AgentEvent = (
  | { type: "thinking"; round: number }
  | { type: "reasoning"; round: number; text: string }  // a summary of what Muse Spark is working out, as it thinks
  | { type: "ideas"; round: number; seconds: number; understanding: string; count: number }
  | { type: "checking"; index: number; title: string; kind: string }
  | ({ type: "trial" } & Trial)
  | ({ type: "attempt"; index: number } & Attempt)
  | ({ type: "result" } & Proposal)
  // A second try starts, on this model; with the first try as it stands (null: none to read).
  | { type: "escalating"; model: string; first: boolean; first_try?: { understanding: string; advice?: string; attempts: Attempt[]; options?: Option[] } | null }
  | { type: "note"; text: string }
  | { type: "error"; detail: string }) & { model?: string };   // a second try names its model on every event

/** One side of a clash as the Navisworks report describes it. */
export interface ReportElement {
  global_id: string | null; ifc_class: string | null; name: string; level: string | null; file: string | null;
  system: string | null; description: string | null; part_of: string | null;
}
export interface ReportClash {
  id: string; name: string; guid: string | null; test: string; test_type: string | null; tolerance_m: number | null;
  status: string | null; distance_m: number | null; point: number[] | null; grid: string | null;
  a: ReportElement; b: ReportElement; images: string[]; source: string;
  /** #N, unique across the report; Muse's title (null until titled); the source tool's own label ("Clash39"). */
  number: number; title: string | null; ref: string | null;
}
/** Muse titling a report's clashes (server: titles.py). */
export type TitleEvent =
  | { type: "start"; total: number; missing: number; model: string }
  | { type: "titles"; items: Record<string, string> }
  | { type: "batch_error"; detail: string }
  | { type: "ping" }
  | { type: "done"; titled: number; seconds: number; error?: string };
export interface Report { id: string; title: string; sources: string[]; clashes: ReportClash[]; origin?: "navisworks" | "sightline" }

/** ORCA detection (server: detect.py; design in docs/detection.md). */
export interface DetectSelection { files: string[]; teams: string[]; classes: string[]; exclude_classes: string[]; systems: string[]; ids: string[] }
export interface DetectTest {
  id: string; name: string; a: DetectSelection; b: DetectSelection | null; kind: "hard" | "clearance" | "duplicate";
  tolerance_m: number; clearance_m: number; rules: Record<string, boolean>; enabled: boolean; min_size_m?: number;
}
export interface DetectCoverage {
  test: string; name: string; kind: string; elements_a: number; elements_b: number; candidate_pairs: number; clashes: number;
  touching: number; excluded: Record<string, number>; partial: boolean; seconds: number;
}
export interface DetectGone { id: string; test: string; a: string; b: string }
export interface DetectDiff { new: string[]; resolved: DetectGone[]; no_longer_checked: DetectGone[]; first: boolean }
/** What a result was checked against (server: Workspace.requirements_info). */
export interface RequirementsInfo { id: string; name: string; version: number; label: string; level: number; strictness: Strictness }
export interface Detection { coverage: DetectCoverage[]; diff: DetectDiff; elements: number; seconds: number; requirements?: RequirementsInfo | null }
export interface DetectSetup {
  tests: DetectTest[]; teams: Record<string, string>; elements: number; rules: Record<string, string>;
  file_elements?: Record<string, number>;  // physical elements per model file
  requirements?: RequirementsInfo | null;  // the tests are what these requirements compile to
}
export type DetectEvent =
  | { type: "phase"; text: string }
  | { type: "start"; elements: number; tests: { id: string; name: string; kind: string }[] }
  | { type: "test"; index: number; id: string; name: string; candidates: number }
  | { type: "test_done"; index: number; coverage: DetectCoverage }
  | ({ type: "done"; report: Report; offset: number[] } & Detection)
  | { type: "error"; detail: string };
/** Per clash id: the model elements each side matched, and how. */
export type Matches = Record<string, { a: string | null; b: string | null; how: (string | null)[]; show?: (string | null)[] }>;
export interface Measure { matched: boolean; physical: boolean | null; distance_m: number | null }

/** Bulk triage (server: triage.py): one verdict per report clash, by rule or by the triage model. */
export type TriageKind = "real_clash" | "by_design" | "non_physical" | "modelling_error" | "unknown";
export interface TriageVerdict {
  verdict: TriageKind; severity?: "high" | "medium" | "low" | "none"; responsible?: string; action?: string;
  understanding?: string; fix_hint?: string; confidence?: number; source: "rule" | "model"; seconds?: number; error?: string;
  /** What settled a "not a clash" verdict without the model (or overrode it): non_physical, touch, same_element,
   *  no_overlap (ORCA's measure) or reviewed (marked in this browser). */
  basis?: "non_physical" | "touch" | "same_element" | "no_overlap" | "reviewed" | "requirement" | "strictness";
  /** A requirements rule that settled it (index in by_design); Muse's audit disputing that rule. */
  rule?: number; audit?: "disputed"; audit_note?: string;
  /** Strictness kept a low-confidence "by design" for a person: what the model said. */
  model_verdict?: TriageKind;
  /** The triage model's own reading, when a settled fact overrode it. */
  model_reading?: string;
  /** What the triage model wrote while working it out (Muse Spark Open streams it). */
  reasoning?: string;
  /** Alike clashes are read once (server: triage.alike_groups): the group's size, and on the others the clash read. */
  alike?: number; alike_of?: string;
}
export interface TriageModel { model: string; open_weights: boolean; images?: boolean; note?: string; requirements?: RequirementsInfo | null }
/** Muse Spark's check of a by-design rule on the clashes it set aside (server: triage.audit_rules). */
export interface RuleAudit { answer: "consistent" | "looks_real" | "unsure"; note: string; rule: string; samples: string[]; settled: string[] }
export type TriageEvent =
  | ({ type: "start"; total: number } & TriageModel)
  | ({ type: "clash"; id: string } & TriageVerdict)
  | { type: "reasoning"; id: string; text: string }
  | { type: "audit"; rules: Record<string, RuleAudit> }
  | { type: "done"; summary: Record<string, number>; seconds: number; error?: string }
  | { type: "ping" };
export interface TriageState extends Partial<TriageModel> {
  results: Record<string, TriageVerdict>; done: boolean; started?: boolean; total?: number; seconds?: number | null;
  error?: string | null;
  audit?: Record<string, RuleAudit>;
  /** The last run was under other requirements (another level, strictness or guidance): run again to apply these. */
  stale?: boolean;
}

/** Coordination requirements (server: requirements.py; docs/requirements.md). */
export type Strictness = "lenient" | "relaxed" | "balanced" | "strict" | "exacting";
export type GroupRole = "structure" | "services" | "architecture" | "equipment" | "site" | "other";
export type ReqSource = "orca" | "user" | "level" | "triage";
export interface ReqGroup {
  id: string; name: string; role: GroupRole; teams: string[]; classes: string[]; exclude_classes: string[];
  systems: string[]; files: string[]; source: ReqSource;
}
export interface ReqCheck {
  a: string; b: string | null; check: "hard" | "clearance" | "off"; clearance_mm: number | null; tolerance_mm: number | null;
  reason: string; source: ReqSource;
}
export interface ReqMover { group: string; edits: "any" | "move" | "none"; max_move_mm: number | null; trims: boolean }
export interface ReqByDesign { a_classes: string[]; b_classes: string[]; reason: string; source: ReqSource }
/** Whether a group may take openings for services (server: requirements.PenRule); wins over Muse's reading. */
export interface ReqPenRule {
  group: string; rule: "allowed" | "review" | "never"; max_mm: number | null; reviewer: string | null; reason: string;
  source: "user" | "orca";
  kind?: string | null; kind_name?: string;   // only for one kind of host in the group (from Muse's reading of it)
}
export interface Requirements {
  format: "orca-requirements/1"; name: string; version: number; level: number; strictness: Strictness;
  groups: ReqGroup[]; checks: ReqCheck[]; duplicates: boolean; rules: Record<string, boolean>;
  who_moves: ReqMover[]; by_design: ReqByDesign[]; guidance: { triage: string; fixes: string }; notes: string;
  penetrations?: ReqPenRule[];
}
/** The numbers a level and strictness resolve to (server: requirements.resolve). */
export interface ReqParams {
  level: number; level_name: string; strictness: Strictness; strictness_name: string; tolerance_mm: number;
  min_size_mm: number; service_clearance_mm: number; clearance_x: number; fix_clearance_mm: number;
  max_move_mm: number | null; trims: "yes" | "cleanup" | "no"; edits: "any" | "move" | "none";
  lean: "by_design" | "real_clash" | null; dispute_below: number | null;
}
export interface ReqLevel { level: number; name: string; meaning: string; hints: string[]; tolerance_mm: number; min_size_mm: number; service_clearance_mm: number; edits: string }
export interface ReqStep { id: Strictness; name: string; meaning: string; fix_clearance_mm: number; max_move_mm: number | null; trims: string; lean: string | null }
export interface ReqScale { levels: ReqLevel[]; strictness: ReqStep[]; format: string }
export interface Inventory {
  files: { file: string; team: string; elements: number; classes: Record<string, number> }[];
  classes: Record<string, number>; systems: Record<string, number>; storeys: Record<string, number>;
  step_groups: Record<string, number>; groups: ReqGroup[];
}
export interface Registered { id: string; doc: Requirements; params: ReqParams; label: string; model_key: string }
export interface ReqPreview { clashes: number; baseline: number; seconds: number; tests: { name: string; kind: string; clashes: number }[]; params: ReqParams }

/** The owner's settings (server: owner.py), sent with every call; the server ignores them for anyone but the owner. */
export type Effort = "minimal" | "low" | "medium" | "high";
/** The owner's own settings (this browser): absent fields follow the settings for everyone. */
/** An opened set of models: the scene id, the file names, and which came from STEP (index → STEP name). */
export interface OpenedScene { id: string; files: string[]; step?: Record<string, string>; revision?: number }
/** How an upload is going (server: app.upload_models_stream): packing here, sending, then the server opening it. */
export type UploadEvent =
  | { type: "packing"; done: number; total: number; name: string }
  | { type: "upload"; loaded: number; total: number }
  | { type: "received"; bytes: number }
  | { type: "opening"; files: number }
  | { type: "boxes"; done: number; total: number }
  | { type: "tick" }
  | { type: string; [k: string]: unknown };   // the STEP conversion's own events

/** A file gzipped for the upload (the server unpacks `.gz` parts), or the file itself when the browser cannot or it is
 * small. */
async function pack(file: File): Promise<Blob> {
  if (typeof CompressionStream === "undefined" || file.size < 1 << 20) return file;
  return new Response(file.stream().pipeThrough(new CompressionStream("gzip"))).blob();
}
export type EscalationMode = "off" | "button" | "auto";
export interface OwnerSettings {
  effort?: Effort; triage_effort?: Effort; no_caps?: boolean; open_weights?: boolean;
  escalation?: EscalationMode; escalation_effort?: Effort; built_views?: boolean;
}
/** The settings for everyone (server: settings.py); null fields take the environment's default. */
export interface EveryoneSettings {
  open_weights: boolean | null; effort: Effort | null; triage_effort: Effort | null;
  escalation: EscalationMode | null; escalation_effort: Effort | null; built_views: boolean | null;
}
export interface SettingsState {
  everyone: EveryoneSettings;
  defaults: { open_weights: boolean; effort: Effort | null; triage_effort: Effort | null; escalation: EscalationMode;
    escalation_effort: Effort | null; built_views: boolean };
  host: boolean;  // an open-weights host key is configured
}
let ownerSettings: OwnerSettings | null = null;
export function setOwnerSettings(s: OwnerSettings | null) { ownerSettings = s; }
/** The coordination requirements in use: their id goes with every call; the file is registered again when the server
 *  no longer knows the id (a restart answers 409 "requirements_unknown"). */
let requirementsId: string | null = null;
let requirementsDoc: Requirements | null = null;
export function setRequirements(id: string | null, doc: Requirements | null) { requirementsId = id; requirementsDoc = id ? doc : null; }
export const requirementsInUse = () => requirementsId;
const settingsHeader = (): Record<string, string> => ({
  ...(ownerSettings ? { "X-Sightline-Settings": JSON.stringify(ownerSettings) } : {}),
  ...(requirementsId ? { "X-Sightline-Requirements": requirementsId } : {}),
});
const jsonHeaders = () => ({ "Content-Type": "application/json", ...settingsHeader() });

/** Register the requirements in use again (the server forgot their id: a restart); true when it took them. */
async function reRegister(): Promise<boolean> {
  if (!requirementsId || !requirementsDoc) return false;
  const again = await fetch("/api/requirements", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(requirementsDoc) });
  if (!again.ok) return false;
  requirementsId = ((await again.json()) as Registered).id;
  return true;
}

/** fetch, registering the requirements again and retrying once when the server has forgotten them. */
async function send(url: string, init: RequestInit = {}): Promise<Response> {
  const r = await fetch(url, init);
  if (r.status !== 409 || !requirementsId || !requirementsDoc) return r;
  const detail = (await r.clone().json().catch(() => null))?.detail;
  if (detail !== "requirements_unknown" || !(await reRegister())) return r;
  return fetch(url, { ...init, headers: { ...(init.headers as Record<string, string> | undefined), "X-Sightline-Requirements": requirementsId! } });
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await send(`/api${path}`, { headers: jsonHeaders(), ...init });
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
  others?: string[];  // more elements the same movable element runs into: one fix clears them all
  recommended?: boolean;  // the requirements allow no edit here: a recommendation, no second try
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
  /** Client only: no longer a root cause (its clashes were resolved); kept in its place so the list does not jump. */
  done?: boolean;
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
  | { type: "ui"; action: "show_it_built"; clash_id: string }   // draw the chosen or kept fix (docs/show-it-built.md)
  | { type: "ui"; action: "set_view"; mode?: string; section_box?: boolean }
  | { type: "ui"; action: "open_report"; report_id: string; detection: Detection }
  | { type: "detect_event"; event: DetectEvent }
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
  /** recommended: the requirements allowed no edit; Muse Spark's recommendation for the designer. */
  status: "proposed" | "accepted" | "recommended"; meets?: string[]; blocked_by?: string; title: string; kind: FixKind | "context"; edit: string; clearance: string; clearance_m: number | null;
  rationale: string; also_needs: string; advice?: string; moved: string[]; before_img?: string; after_img?: string;
  /** Who must review the fix before it is built ("structure", "services"). */
  review?: string;
  /** Show it built: the fix's checked picture (`/api/built/<key>.jpg`), or why none kept to the model. */
  built_img?: string; built_note?: string;
}
/** A team's review of one clash, recorded in the app. */
export interface Signoff { team: Team; name: string; decision: "approve" | "reject"; note: string; at: string }
export type DocEvent =
  | { type: "progress"; step: "drawing" | "explaining" | "summarising" | "rendering" | "bcf"; done?: number; total?: number }
  | { type: "ready"; url: string; name: string; bytes: number }
  | { type: "error"; message: string };

/** POST and read newline-delimited JSON events until the stream ends. */
async function ndjson<T>(path: string, body: unknown, onEvent: (e: T) => boolean | void, signal?: AbortSignal, method = "POST") {
  const r = await send(`/api${path}`, method === "GET" ? { headers: jsonHeaders(), signal }
    : { method, headers: jsonHeaders(), body: JSON.stringify(body), signal });
  if (!r.ok || !r.body) throw new ApiError((await r.json().catch(() => null))?.detail ?? `Request failed (${r.status})`, r.status);
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

/** An agent link (server: agents.py): an MCP client holding the token works on this session; the page follows it. */
export interface AgentLink {
  token: string; mcp_url: string; id: string; calls: number; browser: boolean; last_call: { tool: string; at: number } | null;
  expires_at: number; max_expires_at: number;  // seconds: 12 h after its last use, never past the 24 h cap
  server_time: number;  // the server's clock when this was sent, to count time left on any visitor's clock
  clock_offset?: number;  // set by the page: server clock minus this browser's, in seconds
}
/** What a page needs to reopen a scene it had open (server: Workspace.scene_info). */
export interface SceneInfo extends OpenedScene { detection: (Detection & { report_id: string }) | null }
/** This browser's last session, kept so a reload or a closed tab can resume it while the server still holds it. */
export interface SavedSession {
  scene_id: string; report_id: string | null; files: string[]; fixes: Record<string, string>;
  link: AgentLink | null; clock_offset?: number; saved_at: number;
}
export interface LinkContext { scene_id: string | null; report_id: string | null; clash_id: string | null; fixed: string[] }
/** What the agent does, for the page to follow: its calls, requests for pictures, and the chat's ui events. */
export type LinkEvent =
  | { type: "hello"; stream: string; calls: number; last_call: AgentLink["last_call"]; expires_at: number; max_expires_at: number; server_time: number }
  | { type: "heartbeat" } | { type: "revoked" }
  | { type: "agent_call"; tool: string; args: Record<string, unknown>; expires_at: number }
  | { type: "agent_result"; tool: string; summary: string }
  | { type: "capture_request"; id: string; what: "view" | "clash"; report_id?: string; clash_id?: string; a?: string; b?: string }
  | { type: "ui"; action: "open_models"; names: string[] }
  | ({ type: "ui"; action: "applied"; files: number[]; pieces: string[][]; pairs: [string, string][]; titles: string[]; clash_ids: string[] } & Patch)
  | { type: "ui"; action: "follow_triage" }
  | ChatEvent;

export const api = {
  createLink: (ctx: LinkContext) => call<AgentLink>("/links", { method: "POST", body: JSON.stringify(ctx) }),
  /** A link's state; `applied`: the fixes its agent applied (clash id → title), for a page that resumes later. */
  linkState: (token: string) => call<Omit<AgentLink, "token" | "mcp_url"> & { applied: Record<string, string> }>(`/links/${encodeURIComponent(token)}`),
  sceneInfo: (sceneId: string) => call<SceneInfo>(`/scenes/${sceneId}`),
  linkContext: (token: string, ctx: LinkContext) =>
    call<unknown>(`/links/${encodeURIComponent(token)}/context`, { method: "PUT", body: JSON.stringify(ctx) }),
  /** The page is closing: a beacon, which the browser still sends while it unloads. */
  leaveLink: (token: string, stream: string) => navigator.sendBeacon?.(`/api/links/${encodeURIComponent(token)}/leave/${stream}`),
  revokeLink: (token: string) => call<{ revoked: boolean }>(`/links/${encodeURIComponent(token)}`, { method: "DELETE" }),
  /** Follow the link until the server ends the stream (a few minutes) or `signal` aborts; the caller reconnects. */
  linkEvents: (token: string, onEvent: (e: LinkEvent) => void, signal?: AbortSignal) =>
    ndjson<LinkEvent>(`/links/${encodeURIComponent(token)}/events`, null, (e) => { onEvent(e); }, signal, "GET"),
  linkCapture: (token: string, id: string, png: Blob | null) =>
    fetch(`/api/links/${encodeURIComponent(token)}/captures/${id}`, { method: "POST", body: png ?? new Blob([]) }),
  contextStream: async (sceneId: string, objective: ContextObjective, onEvent: (e: ContextEvent) => void, signal?: AbortSignal) => {
    let finished = false;
    try {
      await ndjson<ContextEvent>(`/scenes/${sceneId}/context/stream`, objective, (e) => {
        onEvent(e); finished = e.type === "context_result" || e.type === "error"; return finished;
      }, signal);
    } catch (e) { if (!signal?.aborted) throw e; }
    if (signal?.aborted) return;
    if (!finished) throw new Error("The server stopped before the wider search finished. Regenerate for the original objective.");
  },
  applyContext: (sceneId: string, proposalId: string, acknowledgedConditions: string[]) =>
    call<ContextApplied>(`/scenes/${sceneId}/context/apply`, { method: "POST",
      body: JSON.stringify({ proposal_id: proposalId, acknowledged_conditions: acknowledgedConditions }) }),
  owner: () => call<{ available: boolean; owner: boolean }>("/owner"),
  unlock: (token: string) => call<{ owner: boolean }>("/owner/unlock", { method: "POST", body: JSON.stringify({ token }) }),
  lock: () => call<{ owner: boolean }>("/owner/lock", { method: "POST" }),
  settings: () => call<SettingsState>("/settings"),
  /** Which model this browser's titles and triage would use now (the owner's choice, else the setting for everyone). */
  models: () => call<{ triage: TriageModel; escalation?: EscalationInfo; built_views?: boolean; model_upload_max_mb?: number; model_upload_max_files?: number }>("/models"),
  /** Every physical element's class and name (GlobalId → [class, name]): a built view's cutaway costs, its caption. */
  classes: (sceneId: string) => call<Record<string, [string, string]>>(`/scenes/${sceneId}/classes`),
  /** Show it built: the passes of one view (Viewer.captureBuilt) → a checked restyle, or why not. */
  built: async (sceneId: string, passes: { look: string; ids: string; normals: string }, fixKind: string,
                onEvent: (e: BuiltEvent) => void, signal?: AbortSignal): Promise<BuiltResult> => {
    let out: BuiltResult | null = null;
    await ndjson<BuiltEvent>(`/scenes/${sceneId}/built/stream`, { ...passes, fix_kind: fixKind }, (e) => {
      if (e.type === "error") throw new ApiError(e.detail, 500);
      if (e.type === "result") { out = e; return true; }
      onEvent(e);
    }, signal);
    if (!out) throw new ApiError("The server stopped before the picture was checked. Try again.", 500);
    return out;
  },
  saveSettings: (changes: Partial<EveryoneSettings>) => call<SettingsState>("/settings", { method: "PUT", body: JSON.stringify(changes) }),
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
    call<{ files: number[]; pieces: string[][]; groups?: string[][][]; not_cut?: { index: number; blocked_by: string }[] } & Patch>(`/scenes/${sceneId}/plan/apply`, { method: "POST", body: JSON.stringify({ options }) }),
  chat: (body: { message: string; session_id: string | null; scene_id: string | null; report_id: string | null;
                 clash_id: string | null; fixed: string[] }, onEvent: (e: ChatEvent) => void, signal?: AbortSignal) =>
    ndjson<ChatEvent>("/chat", body, (e) => { onEvent(e); return e.type === "done"; }, signal),
  samples: () => call<string[]>("/samples"),
  /** Open sample models (a STEP sample is converted to IFC on the server). `step`: file index → its STEP name. */
  open: (samples: string[]) => call<OpenedScene>("/scenes", { method: "POST", body: JSON.stringify({ samples }) }),
  /** Open your own IFC or STEP files (capped per visitor and in size). */
  uploadModels: async (files: File[]) => {
    const form = new FormData();
    for (const f of files) form.append("files", f, f.name);
    const r = await send("/api/models/upload", { method: "POST", body: form, headers: settingsHeader() });
    if (!r.ok) throw new ApiError((await r.json().catch(() => null))?.detail ?? `Upload failed (${r.status})`, r.status);
    return r.json() as Promise<OpenedScene>;
  },
  /** Upload your own models with progress (UploadEvent): each file gzipped here first when the browser can (IFC text
   * packs 5-10x), sent with XMLHttpRequest for upload progress, then the server's opening streamed back. */
  uploadModelsStream: async (files: File[], onEvent: (e: UploadEvent) => void): Promise<OpenedScene> => {
    const form = new FormData();
    for (const [i, f] of files.entries()) {
      onEvent({ type: "packing", done: i, total: files.length, name: f.name });
      const packed = await pack(f);
      form.append("files", packed, packed === f ? f.name : `${f.name}.gz`);
    }
    // Sent again once, as `send` does, when the server has forgotten the requirements' id (a restart).
    const post = (retry: boolean) => new Promise<OpenedScene>((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", "/api/models/upload/stream");
      for (const [k, v] of Object.entries(settingsHeader())) xhr.setRequestHeader(k, v);
      let seen = 0, opened: OpenedScene | null = null, failed: Error | null = null;
      const read = () => {
        const text = xhr.responseText;
        for (let nl = text.indexOf("\n", seen); nl >= 0; nl = text.indexOf("\n", seen)) {
          const line = text.slice(seen, nl);
          seen = nl + 1;
          if (!line.trim()) continue;
          const e = JSON.parse(line) as UploadEvent;
          if (e.type === "done") {
            const d = e as unknown as OpenedScene;
            opened = { id: d.id, files: d.files, step: d.step, revision: d.revision };
          } else if (e.type === "error") {
            const x = e as unknown as { status: number; detail: string };
            failed = new ApiError(x.detail, x.status);
          } else onEvent(e);
        }
      };
      xhr.upload.onprogress = (e) => onEvent({ type: "upload", loaded: e.loaded, total: e.total });
      xhr.onprogress = () => { if (xhr.status === 200) read(); };
      xhr.onload = () => {
        if (xhr.status !== 200) {
          let detail = `Upload failed (${xhr.status})`;
          try { detail = JSON.parse(xhr.responseText).detail ?? detail; } catch { /* not JSON */ }
          if (retry && xhr.status === 409 && detail === "requirements_unknown") {
            reRegister().then((ok) => (ok ? post(false) : Promise.reject(new ApiError(detail, 409)))).then(resolve, reject);
            return;
          }
          reject(new ApiError(detail, xhr.status));
          return;
        }
        read();
        if (failed) reject(failed);
        else if (opened) resolve(opened);
        else reject(new Error("The server stopped before the models opened. Try again."));
      };
      xhr.onerror = () => reject(new Error("The upload stopped: the connection dropped."));
      xhr.send(form);
    });
    return post(true);
  },
  file: async (id: string, index: number) => {
    const r = await fetch(`/api/scenes/${id}/files/${index}`, { cache: "no-store" });
    if (!r.ok) throw new ApiError(`Model download failed (${r.status})`, r.status);
    return new Uint8Array(await r.arrayBuffer());
  },
  /** A move checked without keeping it; `obstacles` (what it must clear): what it stands on is kept, as a proposal's. */
  verify: (id: string, moved: string[], delta_m: number[], obstacles: string[] = []) =>
    call<Verdict>(`/scenes/${id}/verify`, { method: "POST", body: JSON.stringify({ moved, delta_m, obstacles }) }),
  propose: (id: string, element_a: string, element_b: string, from?: { report_id: string; clash_id: string }) =>
    call<Proposal>(`/scenes/${id}/propose`, { method: "POST", body: JSON.stringify({ element_a, element_b, ...from }) }),
  /** Propose fixes, hearing each step as it happens. Resolves with the final proposal. `escalate`: a second, longer try
   * on the larger model, reading the last try at this pair (docs/escalation.md). */
  proposeStream: async (id: string, element_a: string, element_b: string, from: { report_id: string; clash_id: string } | undefined,
                        onEvent: (e: AgentEvent) => void, escalate = false): Promise<Proposal> => {
    const r = await send(`/api/scenes/${id}/propose/stream`, {
      method: "POST", headers: jsonHeaders(), body: JSON.stringify({ element_a, element_b, ...from, ...(escalate ? { escalate } : {}) }),
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
      if (done) throw new Error("The server stopped before ORCA finished. Try again.");
    }
  },
  exportUrl: (id: string) => `/api/scenes/${id}/export`,
  element: (id: string, globalId: string) => call<Record<string, unknown>>(`/scenes/${id}/elements/${encodeURIComponent(globalId)}`),
  /** Keep a fix in the server's model; returns the indexes of the files that changed. */
  accept: (id: string, o: Option) => (o.kind === "trim" && o.trim
    ? call<Kept>(`/scenes/${id}/trim/apply`, { method: "POST", body: JSON.stringify({ element: o.moved[0], end: o.trim.end, by_m: o.trim.by_m }) })
    : o.kind === "offset"
    ? call<Kept>(`/scenes/${id}/offset/apply`, { method: "POST", body: JSON.stringify({ element: o.moved[0], split_m: o.split_m, dz_m: o.delta_m[2] }) })
    : o.kind === "move" && !o.edit
    ? call<Kept>(`/scenes/${id}/apply`, { method: "POST", body: JSON.stringify({ moved: o.moved, delta_m: o.delta_m }) })
    // Every other kind: one endpoint keeps it from the option itself (its meshes are not needed there). A move that
    // takes parts along or stretches segments goes there too, so the server refuses it if its plan has changed. A
    // penetration whose host the requirements lock comes back `cut: false`: only its provision for void was written.
    : call<Kept>(`/scenes/${id}/fix/apply`, { method: "POST", body: JSON.stringify({ option: { ...o, preview: null, before: null } }) })),

  detectTests: (sceneId: string) => call<DetectSetup>(`/scenes/${sceneId}/detect/tests`),
  /** ORCA's own detection; resolves with the "done" event (the report and its coverage). */
  detect: async (sceneId: string, tests: DetectTest[] | null, onEvent: (e: DetectEvent) => void) => {
    let done: Extract<DetectEvent, { type: "done" }> | null = null;
    await ndjson<DetectEvent>(`/scenes/${sceneId}/detect/stream`, { tests }, (e) => {
      onEvent(e);
      if (e.type === "error") throw new Error(e.detail);
      if (e.type === "done") { done = e; return true; }
    });
    if (!done) throw new Error("Detection stopped before it finished.");
    return done as Extract<DetectEvent, { type: "done" }>;
  },
  report: (reportId: string) => call<Report>(`/reports/${reportId}`),
  /** Muse titles the report's clashes; one run per report is shared, so this may join one already going. */
  titles: (reportId: string, onEvent: (e: TitleEvent) => void) =>
    ndjson<TitleEvent>(`/reports/${reportId}/titles/stream`, {}, (e) => { onEvent(e); return e.type === "done"; }),
  /** A view of a clash ORCA found (A, B or C), captured in the browser for the fix agent, triage and the PDF. */
  saveView: async (reportId: string, clashId: string, label: string, png: Blob) => {
    const form = new FormData();
    form.append("label", label);
    form.append("image", png, `${label}.png`);
    const r = await fetch(`/api/reports/${reportId}/clashes/${clashId}/images`, { method: "POST", body: form });
    if (!r.ok) throw new Error((await r.json().catch(() => null))?.detail ?? `Saving the view failed (${r.status})`);
    return (await r.json()).images as string[];
  },
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
    const r = await send("/api/transcribe", { method: "POST", body: form, headers: settingsHeader() });
    if (!r.ok) throw new Error((await r.json().catch(() => null))?.detail ?? `Transcription failed (${r.status})`);
    return r.json() as Promise<{ transcript: string; duration_ms: number | null }>;
  },
  imageUrl: (reportId: string, clashId: string, index: number) => `/api/reports/${reportId}/clashes/${clashId}/images/${index}`,
  match: (reportId: string, sceneId: string) => call<Matches>(`/reports/${reportId}/match/${sceneId}`),
  measure: (reportId: string, clashId: string, sceneId: string) => call<Measure>(`/reports/${reportId}/clashes/${clashId}/measure/${sceneId}`),

  requirementsScale: () => call<ReqScale>("/requirements/scale"),
  /** Register a requirements file: its id (sent with every call once set), the file as ORCA reads it, its numbers. */
  registerRequirements: (doc: Requirements) => call<Registered>("/requirements", { method: "POST", body: JSON.stringify(doc) }),
  /** A starting point from the open models (what ORCA checks without requirements) and what they contain. */
  requirementsDefault: (sceneId: string) => call<Registered & { inventory: Inventory }>(`/scenes/${sceneId}/requirements/default`),
  /** Muse Spark drafts requirements for the open models (one model call: counts as a proposal). */
  suggestRequirements: (sceneId: string, level: number, strictness: Strictness, name: string) =>
    call<Registered & { summary: string; inventory: Inventory }>(`/scenes/${sceneId}/requirements/suggest`,
      { method: "POST", body: JSON.stringify({ level, strictness, name }) }),
  /** How many clashes a file would find in the open models, and how many ORCA's defaults find. */
  previewRequirements: (sceneId: string, doc: Requirements) =>
    call<ReqPreview>(`/scenes/${sceneId}/requirements/preview`, { method: "POST", body: JSON.stringify(doc) }),
};
