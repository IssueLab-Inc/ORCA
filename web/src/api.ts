import type { Action, Condition, FacetIndex, Rule } from "./filters";
import type { Graph } from "./links";
import type { ElementMesh } from "./viewer/patch";
import type { Datums } from "./viewer/views";
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
  /** The clash it was verified for (A, B) and what else it had to clear: keeping it tries it again against these. */
  pair?: string[] | null;
  others?: string[];
}
export interface FixEdit { summary?: string; key?: string; [param: string]: unknown }
export interface Attempt {
  title: string; delta_m: number[]; passed: boolean; reason: string; kind: FixKind; split_m: number[] | null;
  trim?: TrimCut | null;
  hit_ids?: string[];  // what it hit, worst first
  edit?: FixEdit | null;
  where?: number[][];  // where the worst hits are, world metres
  model?: string;      // whose idea it was ("Muse Spark", "Muse Wonder")
  seconds?: number;    // the geometry check's seconds (the stream's attempt events; none for an idea refused before any geometry)
  checked?: number;    // how many elements a passing fix was tested against
}
/** A candidate in place while the agent checks it: a move's elements and delta, or an offset's new pieces. */
export interface Trial { index: number; kind: FixKind; moved: string[]; delta_m: number[]; pieces: Piece[] | null; summary?: string }
/** move: shift the run; offset: split and raise or lower the middle; trim: cut one end back to butt the other element;
 * route: a detour of several steps; resize: a flatter section past the obstacle; penetration: an opening through it. */
/** A kept fix: the files it changed, a split run's pieces, and how to patch the page's model (Patch). A penetration whose
 * host the requirements lock comes back `cut: false`, with who cuts it. */
/** A kept fix: `pieces`, its split run (the original first); `groups`, every run it split (a combined fix's several). */
export type Kept = { files: number[]; pieces?: string[]; groups?: string[][]; cut?: boolean; blocked_by?: string } & Patch;
export type FixKind = "move" | "offset" | "trim" | "route" | "resize" | "penetration" | "seat" | "combined";
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
/** One value the model gives (properties.py): lengths, areas, volumes and masses in SI with their unit, others as
 * authored with theirs; `from_type` when the object's type gives it. Kinds other than a single value say so: an
 * enumerated or list value is a list, a bounded one {lower, upper, set_point}, a table has `table`, a complex
 * property nests `rows`, a reference names what it points at. */
export interface PropRow {
  name: string; value: unknown; unit?: string; from_type?: boolean;
  kind?: "enumerated" | "list" | "bounded" | "table" | "reference" | "complex" | string;
  rows?: PropRow[]; of?: string;
  table?: { defining: unknown[]; defined: unknown[]; defining_unit: string | null; defined_unit: string | null; expression: string | null };
}
/** A property set, quantity set or a material's own set. */
export interface PropSet { name: string; kind: "pset" | "qto"; props: PropRow[]; from_type?: boolean; material?: string }
/** An object one points at (a breadcrumb, a container): enough to read its own properties (`file` picks the model). */
export interface ObjectRef { global_id: string | null; ifc_class: string; name: string; file: number }
export interface MaterialUse {
  usage: "single" | "layers" | "profiles" | "constituents" | "list" | string; name: string; from_type: boolean;
  items: { material: string | null; name?: string; thickness_m?: number; fraction?: number; profile?: string; category?: string }[];
  total_m?: number; sets: PropSet[];
}
/** One change to what the model says about an element (property_edits.plan). */
export type PropertyChange =
  | { kind: "attribute"; name: string; value: string | null }
  | { kind: "property"; pset: string; name: string; value: string | number | boolean | null }
  | { kind: "type"; type: string } | { kind: "material"; material: number } | { kind: "container"; container: string }
  | { kind: "classification"; reference: number; remove?: boolean };
/** What an element's properties can be set to from its own model (property_edits.choices). */
export interface PropertyChoices {
  attributes: string[]; predefined: string[];
  types: { global_id: string; name: string; ifc_class: string }[]; type: string | null;
  materials: { id: number; name: string }[]; material: number | null; material_fixed: string | null;
  containers: { global_id: string; name: string; ifc_class: string }[]; container: string | null;
  classifications: { id: number; identification: string | null; name: string | null; system: string | null; on: boolean }[];
}
export interface PropertyEdited { entry: JournalEntry | null; properties: ElementProperties; revision_before: number; revision: number }
/** Everything the model says about one object (properties.py): every attribute, its type, every set (the type's
 * marked), materials, classifications, groups, documents, where it sits and the path up to the project; size in
 * metres (IFC axes), none for a storey or a building. */
export interface ElementProperties {
  global_id: string; ifc_class: string; name: string | null; source: string; file: number; size_m: number[] | null;
  attributes: PropRow[];
  type: { global_id: string | null; ifc_class: string; name: string | null; attributes: PropRow[] } | null;
  storey: ObjectRef | null; container: ObjectRef | null; path: ObjectRef[];
  materials: MaterialUse[];
  classifications: { system: string | null; identification: string | null; name: string | null; location: string | null }[];
  groups: { global_id: string | null; ifc_class: string; name: string }[];
  documents: { identification: string | null; name: string | null; location: string | null }[];
  sets: PropSet[];
}
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
  removed?: string[];               // elements the request took out (a delete, undo of what a fix made)
}

/** Who kept an edit: by hand on the page, Muse in chat or voice, an MCP agent, an accepted fix, a plan, a wider fix. */
export type EditSource = "you" | "muse" | "agent" | "fix" | "plan" | "wider";
/** One kept edit in the scene's edit log (server: journal.py, docs/manual-edits.md). */
export interface JournalEntry {
  id: string; seq: number; when: string; source: EditSource; kind: string; title: string; summary: string;
  actor: string | null; elements: string[]; created: string[]; removed: string[]; names: Record<string, string>;
  files: number[]; revision: number; clashes: { id: string | null; pair: string[] }[]; follows: string[];
  check: { verified?: boolean; cleared?: unknown[]; new?: { kind?: string }[]; worse?: { kind?: string }[]; accepted_clashes?: number;
    min_clearance_m?: number | null; open_joints?: { element: string; name: string }[] } | null;
  warnings: { rule: string; text: string; review: string | null }[]; status: { clash: string | null; resolved: boolean;
    depth_m: number | null } | null; state: "kept" | "undone"; has_picture: boolean; params: Record<string, unknown>;
}
export interface Journal { entries: JournalEntry[]; can_undo: boolean; can_redo: boolean; undo: string | null; redo: string | null }
/** A face of an element as the server reads a pick (faces.py): its kind, its name in words, what it allows. */
export interface EditFace {
  element: string; id: string; kind: "cap" | "side" | "radial" | "flank" | "edge" | "plane" | "clip" | "other"; name: string;
  normal: number[]; point: number[]; size_m: number | null; allows: string[]; why_not: string | null;
}
/** A hand edit, as the server takes it from the page, chat, voice and MCP (manual.py). */
export type EditOp = { op: string; element: string } & Record<string, unknown>;
export interface EditHit { other: string; other_class: string; kind: string; distance_m: number; name: string }
/** What checking a hand edit found (manual.check): refused (`blocked`), or what it clears and hits, and its preview. */
export interface EditCheck {
  op: EditOp; passed: boolean; blocked: string | null; clashes: number; warnings: JournalEntry["warnings"];
  summary?: string; face?: EditFace | null; key?: string; revision?: number; targets?: string[]; close?: number;
  new?: EditHit[]; worse?: EditHit[]; cleared?: { other: string; name: string; was_m: number }[];
  min_clearance_m?: number | null; checked_against?: number; changed?: string[]; created?: string[]; removed?: string[];
  open_ends?: string[]; preview?: Piece[] | null; before?: Piece[] | null;
  /** A follow-up the check suggests, in a few words: an align that meets the other face at one edge offers to clip it
   * flush; a move carrying its joined parts that cannot keep its joints offers to move it on its own. */
  offer?: EditOp | null; offer_words?: string;
  /** The joints it leaves open (an edit changes the face or element picked only, unless `carry` takes joined parts
   * along): kept only when said. */
  joints?: { element: string; name: string }[];
}
export type EditKept = { entry: JournalEntry | null; files: number[]; changed: string[]; created: string[]; removed: string[];
  pieces: string[]; check: EditCheck } & Patch;
/** Undo or redo: the entry, and how to patch the page (what came back in `changed`, what went in `removed`). */
export type Stepped = { entry: JournalEntry; files: number[]; can_undo: boolean; can_redo: boolean;
  undo: string | null; redo: string | null;
  /** Each clash of the entry measured again after the step: what the page marks fixed or opens again. */
  clash_states?: { clash: string | null; pair: string[]; resolved: boolean; depth_m: number | null }[] } & Patch;
/** Progress from the agent while it works (server: agent.resolve), then the result. */
export type AgentEvent = (
  | { type: "thinking"; round: number }
  | { type: "reasoning"; round: number; text: string }  // a summary of what Muse Spark is working out, as it thinks
  | { type: "ideas"; round: number; seconds: number; understanding: string; count: number; candidates?: { title: string; kind: string }[] }
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
  /** A clash ORCA found: the kept checks that found it, check key → its test there (docs/detection.md, "Kept checks"). */
  checks?: Record<string, string>;
}
/** Muse titling a report's clashes (server: titles.py). */
export type TitleEvent =
  | { type: "start"; total: number; missing: number; model: string; report_id?: string }   // the list the run titles
  | { type: "titles"; items: Record<string, string> }
  | { type: "batch_error"; detail: string }
  | { type: "ping" }
  | { type: "done"; titled: number; seconds: number; error?: string };
export interface Report {
  id: string; title: string; sources: string[]; clashes: ReportClash[]; origin?: "navisworks" | "sightline";
  requirements_id?: string | null;  // a detected run: the requirements it ran under (null: the defaults)
  /** ORCA's checks (server: checks.Register.union): the scene, which list this is (a later one has a higher serial),
   * and the checks it holds. */
  scene_id?: string; serial?: number; checks?: CheckSummary[];
}

/** ORCA detection (server: detect.py; design in docs/detection.md). */
/** A filter as a check's side (docs/filters.md, "Checks"): what it finds, and colouring by value, only what it colours. */
export interface SideFilter { when: Condition[]; invert: boolean; by?: { facet: string; off: string[] } }
/** What the page's filters show together, as a check's side (server: detect.Selection.view, facets.shown). */
export interface CheckView { filters: (SideFilter & { action: Action })[]; hide_rest: boolean; colours: boolean }
export interface DetectSelection { files: string[]; teams: string[]; classes: string[]; exclude_classes: string[]; systems: string[]; ids: string[];
  /** A side found by a filter, or by what the filters show (docs/filters.md, "Checks"). */
  filter?: SideFilter | null; view?: CheckView | null }
/** What a check on filters takes when it says nothing else (server: Workspace.check_defaults); `everything`: what its
 * Everything takes, the models the full check covers (a site model left out). */
export interface CheckDefaults { tolerance_m: number; clearance_m: number; rules: Record<string, boolean>; min_size_m: number;
  everything?: DetectSelection }
/** One of the user's filters as the page shares it with chat and an agent link (server: PageFilter). */
export interface SharedFilter { id: string; name: string; when: Condition[]; invert: boolean; on: boolean; origin?: string | null;
  action?: Action; by?: { facet: string; off: string[] } | null }
/** How the page's filters show together (server: FilterView). */
export interface FilterView { hide_rest: boolean; colours: boolean }
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
export interface Detection { coverage: DetectCoverage[]; diff: DetectDiff; elements: number; seconds: number; requirements?: RequirementsInfo | null;
  /** The tests as run when they were chosen (a check on filters), for Detect again; null: the defaults. */
  tests?: DetectTest[] | null }
/** A kept check: its latest run (server: checks.Check.summary). `key` "models" is the check of the open models; any
 * other is one check on filters. `stale`: a fix was kept after it ran. */
export interface CheckSummary extends Detection {
  key: string; name: string; title: string; revision: number; stale: boolean; ran_at: number; clashes: number;
}
/** The scene's kept checks and the report listing their clashes (null: none kept). */
export interface ChecksInfo { report_id: string | null; checks: CheckSummary[] }
export interface DetectSetup {
  tests: DetectTest[]; teams: Record<string, string>; elements: number; rules: Record<string, string>;
  file_elements?: Record<string, number>;  // physical elements per model file
  requirements?: RequirementsInfo | null;  // the tests are what these requirements compile to
  check?: CheckDefaults;                   // what a check on filters takes by default
}
export type DetectEvent =
  | { type: "phase"; text: string }
  | { type: "start"; elements: number; tests: { id: string; name: string; kind: string }[] }
  | { type: "test"; index: number; id: string; name: string; candidates: number }
  | { type: "test_done"; index: number; coverage: DetectCoverage }
  | { type: "check"; key: string; name: string; index: number; of: number }   // Run all again: the next check
  | ({ type: "done"; report: Report; offset: number[] | null; check: string | null; ran: string[]; checks: CheckSummary[] }
     & Omit<Detection, "diff"> & { diff: DetectDiff | null })
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
  | ({ type: "start"; total: number; asking?: number; scope?: string | null;
       queued?: boolean;          // waits for the run under way, then reads what it leaves
       following?: string | null  // the run under way is over an earlier list of the same checks: only unchanged clashes
     } & TriageModel)
  | { type: "asking"; asking: number | null }   // a queued run starts: how many it asks about
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
  /** ORCA's checks: how many clashes the model has not read (readings follow their clashes from list to list). */
  unread?: number; scope?: string | null;
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
  /** A building or a machine (server: domains.py); absent: as the models were opened (all STEP: a machine). */
  domain?: Domain;
  /** IFC classes fixed in place: a fix never moves them to make room. Absent: the domain's (`Inventory.stays`). */
  stays?: string[];
}
export type Domain = "construction" | "machines";
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
/** A demo among the samples (server: demos.listing): its default files, the start button's words and its tour. */
export interface Demo {
  id: string; name: string; label: string; kind: Domain; files: string[]; context: string[]; tour: string | null;
}
export interface Inventory {
  files: { file: string; team: string; elements: number; classes: Record<string, number> }[];
  classes: Record<string, number>; systems: Record<string, number>; storeys: Record<string, number>;
  step_groups: Record<string, number>; groups: ReqGroup[];
  /** The domain the default groups were made for, and its classes fixed in place by default. */
  domain?: Domain; stays?: string[];
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

/** A scene or report the server no longer holds (a restart, or let go to make room), from the 404's X-Sightline-Gone
 *  header: the page offers to open them again rather than show each call's error. */
export interface Gone { kind: "scene" | "report"; id: string; detail?: string }  // detail: the server's words
let goneHandler: ((g: Gone) => void) | null = null;
export function setGoneHandler(fn: ((g: Gone) => void) | null) { goneHandler = fn; }
export function goneOf(r: Pick<Response, "status" | "headers">): Gone | null {
  const m = r.status === 404 ? /^(scene|report):(\w+)$/.exec(r.headers.get("X-Sightline-Gone") ?? "") : null;
  return m ? { kind: m[1] as Gone["kind"], id: m[2] } : null;
}

/** fetch, registering the requirements again and retrying once when the server has forgotten them, and telling the
 *  page when a scene or report is gone. */
async function send(url: string, init: RequestInit = {}): Promise<Response> {
  const r = await fetch(url, init);
  const gone = goneOf(r);
  if (gone && goneHandler) goneHandler({ ...gone, detail: (await r.clone().json().catch(() => null))?.detail });
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

/** How long to wait before asking again after a gateway failure (milliseconds), once per wait. */
export const GATEWAY_WAITS = [1500, 4000];

/** A read the server makes once and keeps (a report's patterns reading), asked again after a gateway failure: a 502,
 * 503 or 504, or no answer at all. Those come from the edge in front of the server, not from it (Oct 31: a patterns
 * reading's 502 never reached the server). Asking again never charges twice: the server keeps the reading, and a
 * caller who comes while it is being made waits for it. */
async function callAgain<T>(path: string, init: RequestInit): Promise<T> {
  for (let i = 0; ; i++) {
    try { return await call<T>(path, init); }
    catch (e) {
      const gateway = e instanceof ApiError ? [502, 503, 504].includes(e.status) : e instanceof TypeError;
      if (!gateway || i >= GATEWAY_WAITS.length) throw e;
      await new Promise((r) => setTimeout(r, GATEWAY_WAITS[i]));
    }
  }
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
  | { type: "item"; key: string; status: "thinking" | "checking" | "done"; attempt?: string; passed?: boolean; ok?: boolean; title?: string;
      seconds?: number; checked?: number; reason?: string }
  | { type: "thinking"; what: string }
  | { type: "root_cause"; root_cause: string; strategy: string; reason: string }
  | { type: "checking_plan"; retry?: string[] }
  | ({ type: "plan" } & Plan)
  | { type: "error"; detail: string };

/** What the chat streams while it works (server: chat.py). */
export type ChatEvent =
  | { type: "session"; id: string }
  /** The page's own, before the request: what the person asked (typed or spoken), so Workings can draw the turn. */
  | { type: "asked"; text: string; voice?: boolean }
  | { type: "thinking" }
  | { type: "tool"; name: string; args: Record<string, unknown> }
  | { type: "tool_result"; name: string; summary: string }
  | { type: "ui"; action: "select_clash"; clash_id: string }
  /** A hand edit Muse (or an agent) checked: the page previews it in the Edit tool, with its own Keep. */
  | { type: "ui"; action: "edit_preview"; check: EditCheck }
  /** A hand edit kept on the person's word (chat, voice) or by an agent: patch the model, read the log again. */
  | { type: "ui"; action: "edit_kept"; kept: EditKept }
  | { type: "ui"; action: "edit_stepped"; step: Stepped }
  | { type: "ui"; action: "show_it_built"; clash_id: string }   // draw the chosen or kept fix (docs/show-it-built.md)
  | { type: "ui"; action: "set_view"; mode?: string; section_box?: boolean }
  /** Chat's or an agent's filters (docs/filters.md): replace its own (the user's paused), or clear them. */
  | { type: "ui"; action: "filters"; mode: "replace" | "clear"; filters?: Rule[]; grey_rest?: boolean; hide_rest?: boolean }
  | { type: "ui"; action: "open_report"; report_id: string; detection: Detection; check?: string | null; checks?: CheckSummary[] }
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
/** A team, named by the user (the report dialog); ORCA only guesses a first name per model (`ModelTeam.guess`). */
export type Team = string;
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
export interface SceneInfo extends OpenedScene, ChecksInfo {}
/** This browser's last session, kept so a reload or a closed tab can resume it while the server still holds it. */
export interface SavedSession {
  scene_id: string; report_id: string | null; files: string[]; fixes: Record<string, string>;
  link: AgentLink | null; clock_offset?: number; saved_at: number;
  check?: string | null;   // the kept check the list showed (null: all of them)
}
export interface LinkContext { scene_id: string | null; report_id: string | null; clash_id: string | null; fixed: string[];
  filters?: SharedFilter[]; filter_view?: FilterView; check?: string | null }
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
  models: () => call<{ triage: TriageModel; escalation?: EscalationInfo; built_views?: boolean; labels?: Partial<Record<"proposal" | "escalation" | "triage" | "image" | "voice", string>>;
    triage_workers?: number; model_upload_max_mb?: number; model_upload_max_files?: number }>("/models"),
  /** Every physical element's class and name (GlobalId → [class, name]): a built view's cutaway costs, its caption. */
  classes: (sceneId: string) => call<Record<string, [string, string]>>(`/scenes/${sceneId}/classes`),
  /** Levels, grid axes and each element's storey (docs/views.md, "Datums from the server"). */
  datums: (sceneId: string) => call<Datums>(`/scenes/${sceneId}/datums`),
  /** The filters' index (docs/filters.md): each facet's values and, per value, the elements that have it. */
  facets: (sceneId: string) => call<FacetIndex>(`/scenes/${sceneId}/facets`),
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
                                      marks: Record<string, string>; triage: Record<string, Omit<TriageVerdict, "reasoning">>;
                                      check?: string | null }, onEvent: (e: DocEvent) => void) =>
    ndjson<DocEvent>(`/reports/${reportId}/document/stream`, body, (e) => { onEvent(e); return e.type !== "progress"; }),
  triage: (reportId: string, sceneId: string | null) =>
    call<TriageState>(`/reports/${reportId}/triage${sceneId ? `?scene_id=${sceneId}` : ""}`),
  /** Triage every clash in the report (or follow the run already going), event by event. */
  /** `scope`: a kept check's key, to read only its clashes no reading holds for (ORCA's checks). */
  triageStream: (reportId: string, sceneId: string | null, onEvent: (e: TriageEvent) => void, rerun = false, scope: string | null = null) => {
    const q = new URLSearchParams({ ...(rerun ? { rerun: "true" } : {}), ...(sceneId ? { scene_id: sceneId } : {}),
      ...(scope ? { scope } : {}) }).toString();
    return ndjson<TriageEvent>(`/reports/${reportId}/triage/stream${q ? `?${q}` : ""}`, {}, (e) => { onEvent(e); return e.type === "done"; });
  },
  patterns: (reportId: string, sceneId: string, fixed: string[]) =>
    call<Pattern[]>(`/reports/${reportId}/patterns/${sceneId}?fixed=${encodeURIComponent(fixed.join(","))}`),
  triagePatterns: (reportId: string, sceneId: string, fixed: string[]) =>
    callAgain<Record<string, PatternVerdict>>(`/reports/${reportId}/patterns/${sceneId}/triage`, { method: "POST", body: JSON.stringify({ fixed }) }),
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
  applyPlan: (sceneId: string, options: Option[], clashIds: (string | null)[] = []) =>
    call<{ files: number[]; pieces: string[][]; groups?: string[][][]; not_cut?: { index: number; blocked_by: string }[] } & Patch>(`/scenes/${sceneId}/plan/apply`, { method: "POST", body: JSON.stringify({ options, clash_ids: clashIds }) }),
  chat: (body: { message: string; session_id: string | null; scene_id: string | null; report_id: string | null;
                 clash_id: string | null; fixed: string[]; filters?: SharedFilter[]; filter_view?: FilterView; check?: string | null;
                 selected?: { element: string; face: string | null; pick?: { point: number[]; normal: number[] } } | null },
         onEvent: (e: ChatEvent) => void, signal?: AbortSignal) =>
    ndjson<ChatEvent>("/chat", body, (e) => { onEvent(e); return e.type === "done"; }, signal),
  /** The sample models, and the demos among them (server: demos.py). */
  samples: () => call<{ files: string[]; demos: Demo[] }>("/samples"),
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
                        onEvent: (e: AgentEvent) => void, escalate = false, notes = ""): Promise<Proposal> => {
    const r = await send(`/api/scenes/${id}/propose/stream`, {
      method: "POST", headers: jsonHeaders(),
      body: JSON.stringify({ element_a, element_b, ...from, ...(escalate ? { escalate } : {}), ...(notes ? { notes } : {}) }),
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
  /** Everything the model says about one element, for the Properties panel (properties.py). */
  properties: (id: string, globalId: string, file?: number) =>
    call<ElementProperties>(`/scenes/${id}/elements/${encodeURIComponent(globalId)}/properties${file === undefined ? "" : `?file=${file}`}`),
  /** What an element's properties can be set to from its own model (property_edits.choices). */
  propertyChoices: (id: string, globalId: string) =>
    call<PropertyChoices>(`/scenes/${id}/elements/${encodeURIComponent(globalId)}/property-choices`),
  /** Change one thing the model says about an element, not its shape (property_edits.edit): kept in the edit log. */
  editProperty: (id: string, globalId: string, change: PropertyChange) =>
    call<PropertyEdited>(`/scenes/${id}/elements/${encodeURIComponent(globalId)}/properties`,
      { method: "POST", body: JSON.stringify({ change }) }),
  /** What is linked to what in the open models (joints, assemblies, hosts, what rests on what, contacts from the last
   *  check): the connection highlight's graph (docs/connections.md). */
  connections: (id: string) => call<Graph>(`/scenes/${id}/connections`),
  /** Keep a fix in the server's model; returns the indexes of the files that changed. One endpoint keeps every kind
   *  from the option itself (its meshes are not needed there): the server tries it again against the clash it names
   *  (`pair`: the option's own, else the clash on screen) and answers 409 with why when it no longer passes. A
   *  penetration whose host the requirements lock comes back `cut: false`: only its provision for void was written. */
  accept: (id: string, o: Option, pair: string[] | null, clashId: string | null = null) =>
    call<Kept>(`/scenes/${id}/fix/apply`, { method: "POST",
      body: JSON.stringify({ option: { ...o, pair: o.pair ?? pair, preview: null, before: null }, clash_id: clashId }) }),
  /** The face of an element under a pick (IFC axes): its name, and what the Edit tool can do with it. */
  editFace: (id: string, element: string, point: number[], normal: number[]) =>
    call<EditFace>(`/scenes/${id}/edit/face`, { method: "POST", body: JSON.stringify({ element, point, normal }) }),
  elementFaces: (id: string, element: string) => call<{ element: string; faces: EditFace[] }>(`/scenes/${id}/elements/${encodeURIComponent(element)}/faces`),
  /** Try a hand edit without keeping it: what it clears and hits, its warnings, its preview; `blocked` says why not. */
  editCheck: (id: string, op: EditOp) => call<EditCheck>(`/scenes/${id}/edit/check`, { method: "POST", body: JSON.stringify({ op }) }),
  /** Keep a hand edit: checked again on the server (409 when it would make more clashes than accepted, or changed). */
  editApply: (id: string, op: EditOp, key: string | undefined, acceptClashes: number, clash: { id: string | null; pair: string[] | null } | null,
    acceptJoints = 0) =>
    call<EditKept>(`/scenes/${id}/edit/apply`, { method: "POST", body: JSON.stringify({ op, key: key ?? null, accept_clashes: acceptClashes,
      accept_joints: acceptJoints, clash_id: clash?.id ?? null, pair: clash?.pair ?? null }) }),
  /** The scene's edit log: every kept edit, oldest first, and whether undo and redo can go now. */
  journal: (id: string) => call<Journal>(`/scenes/${id}/edits`),
  journalCsvUrl: (id: string) => `/api/scenes/${id}/edits?format=csv`,
  /** A picture of a kept edit, for the report's "After the edits". */
  editPicture: (id: string, entry: string, png: string) =>
    call<{ ok: boolean }>(`/scenes/${id}/edits/${encodeURIComponent(entry)}/picture`, { method: "POST", body: JSON.stringify({ png }) }),
  /** Undo (or redo) the newest edit; `entry` names the one meant (409 when it is not next in line). */
  undo: (id: string, entry?: string) => call<Stepped>(`/scenes/${id}/edits/undo`, { method: "POST", body: JSON.stringify({ entry: entry ?? null }) }),
  redo: (id: string, entry?: string) => call<Stepped>(`/scenes/${id}/edits/redo`, { method: "POST", body: JSON.stringify({ entry: entry ?? null }) }),

  detectTests: (sceneId: string) => call<DetectSetup>(`/scenes/${sceneId}/detect/tests`),
  /** ORCA's own detection; resolves with the "done" event (the report and its coverage). `again`: run a kept check
   * again by its key, or every kept check (`all`). */
  detect: async (sceneId: string, tests: DetectTest[] | null, onEvent: (e: DetectEvent) => void,
                 again: { check?: string; all?: boolean; after_edit?: string } = {}) => {
    let done: Extract<DetectEvent, { type: "done" }> | null = null;
    await ndjson<DetectEvent>(`/scenes/${sceneId}/detect/stream`, { tests, ...again }, (e) => {
      onEvent(e);
      if (e.type === "error") throw new Error(e.detail);
      if (e.type === "done") { done = e; return true; }
    });
    if (!done) throw new Error("Detection stopped before it finished.");
    return done as Extract<DetectEvent, { type: "done" }>;
  },
  report: (reportId: string) => call<Report>(`/reports/${reportId}`),
  /** The scene's kept checks (docs/detection.md, "Kept checks"); a list the server let go is made again. */
  checks: (sceneId: string) => call<ChecksInfo>(`/scenes/${sceneId}/checks`),
  /** Drop a check on filters: the list of what is left (report null when nothing is). */
  removeCheck: (sceneId: string, key: string) =>
    call<{ report: Report | null; checks: CheckSummary[] }>(`/scenes/${sceneId}/checks/${encodeURIComponent(key)}`, { method: "DELETE" }),
  /** Muse titles the report's clashes; one run per report is shared, so this may join one already going. */
  /** `sceneId`: the open models, whose domain (a building or a machine cell) the titles are written for. */
  titles: (reportId: string, onEvent: (e: TitleEvent) => void, sceneId?: string | null) =>
    ndjson<TitleEvent>(`/reports/${reportId}/titles/stream${sceneId ? `?scene_id=${sceneId}` : ""}`, {}, (e) => { onEvent(e); return e.type === "done"; }),
  /** A view of a clash ORCA found (A, B or C), captured in the browser for the fix agent, triage and the PDF. */
  saveView: async (reportId: string, clashId: string, label: string, png: Blob) => {
    const form = new FormData();
    form.append("label", label);
    form.append("image", png, `${label}.png`);
    const r = await send(`/api/reports/${reportId}/clashes/${clashId}/images`, { method: "POST", body: form });
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
  transcribe: async (wav: Blob, reportId: string | null, sceneId: string | null = null) => {
    const form = new FormData();
    form.append("audio", wav, "voice.wav");
    if (reportId) form.append("report_id", reportId);
    if (sceneId) form.append("scene_id", sceneId);
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
