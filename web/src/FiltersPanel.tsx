import { useMemo, useState } from "react";
import { ArrowDown, ArrowUp, Check, EyeOff, Focus, LocateFixed, Palette, Plus, Radar, Rows3, Trash2, X } from "lucide-react";
import type { CheckDefaults, DetectTest } from "./api";
import { checkTest, roomsLine, shownCounts, sideCounts, type CheckKind, type Side } from "./checks";
import {
  actedOn, complete, count, describe, ELEMENT, found, nameFor, newId, nextColour, PALETTE, ruleColour, sets, shownValue, valueColours, valueCounts,
  withBy, OTHER,
  type Action, type Condition, type FilterState, type Op, type Prepared, type Rule, type Value,
} from "./filters";

/** The Filters panel (docs/filters.md): the list of filters, several on at once (the top one wins where two colour the
 * same element), and the editor for one. What it finds comes from the server's index (`api.facets`); what it does is
 * drawn in every view by the viewer (`Viewer.setRules`). The editor's filter shows live in the model as it is built. */

/** The editor's scope rows: models, classes and floors, each a condition on its own facet. */
const SCOPE: { key: string; label: string }[] = [
  { key: "file", label: "Models" }, { key: "class", label: "Classes" }, { key: "storey", label: "Floors" },
];
const SCOPED = new Set(SCOPE.map((s) => s.key));
const ACTIONS: { id: Action; label: string; icon: typeof Palette; tip: string }[] = [
  { id: "colour", label: "Colour", icon: Palette, tip: "Colour what it finds" },
  { id: "byValue", label: "By value", icon: Rows3, tip: "Colour what it finds, a colour for each value of a property" },
  { id: "hide", label: "Hide", icon: EyeOff, tip: "Hide what it finds" },
  { id: "isolate", label: "Isolate", icon: Focus, tip: "Show only what it finds" },
];
const OPS: Record<"text" | "number" | "bool", { op: Op; label: string }[]> = {
  text: [{ op: "is", label: "is" }, { op: "isNot", label: "is not" }, { op: "contains", label: "contains" },
    { op: "has", label: "has any value" }, { op: "missing", label: "has none" }],
  number: [{ op: "is", label: "is" }, { op: "between", label: "between" }, { op: "lt", label: "less than" },
    { op: "gt", label: "more than" }, { op: "has", label: "has any value" }, { op: "missing", label: "has none" }],
  bool: [{ op: "is", label: "is" }, { op: "has", label: "has any value" }, { op: "missing", label: "has none" }],
};
const SHOWN_MAX = 300;
/** What happens to what no filter colours or isolates (docs/filters.md, "The rest"). */
const REST: { id: "show" | "grey" | "hide"; label: string; tip: string }[] = [
  { id: "show", label: "Show", tip: "What no filter colours or isolates stays as it is" },
  { id: "grey", label: "Grey", tip: "What no filter colours turns grey" },
  { id: "hide", label: "Hide", tip: "Only what the filters colour or isolate stays: everything else is hidden" },
];
const restOf = (s: FilterState) => (s.hideRest ? "hide" : s.greyRest ? "grey" : "show");

export interface FiltersPanelProps {
  index: Prepared | null; loading: boolean;
  state: FilterState; onState: (s: FilterState) => void;
  /** The filter being edited (shown live), or null. */
  draft: Rule | null; onDraft: (r: Rule | null) => void;
  /** Drawing views: show what the filters leave (default) or the whole model (docs/filters.md, "Drawings"). */
  drawingsWhole?: boolean; onDrawingsWhole?: (whole: boolean) => void;
  /** Frame these elements in the views. */
  onZoom?: (ids: string[]) => void;
  /** Why the index did not arrive, and asking for it again. */
  error?: string | null; onRetry?: () => void;
  /** Checks on filters (docs/filters.md, "Checks"): the defaults a check takes, whether one can run now, and running
   * one (its clashes replace the open list). */
  check?: { defaults: CheckDefaults | null; busy: boolean; onCheck: (t: DetectTest) => void };
}

/** A blank filter for the editor. */
export const blankRule = (when: Condition[] = [], action: Action = "colour"): Rule =>
  ({ id: newId(), name: "", on: true, when, action });

export function FiltersPanel({ index: p, loading, state, onState, draft, onDraft, drawingsWhole, onDrawingsWhole, onZoom, error, onRetry, check }: FiltersPanelProps) {
  if (!p && error) return (
    <div className="fpanel"><p className="hint">Could not read what the models say: {error}</p>
      {onRetry && <button type="button" className="btn small" onClick={onRetry}>Try again</button>}</div>);
  if (!p) return <div className="fpanel"><p className="hint">{loading ? "Reading what the models say…" : "Open models to filter them."}</p></div>;
  if (draft) return <div className="fpanel"><Editor p={p} draft={draft} onDraft={onDraft} state={state} onState={onState} /></div>;
  const rules = state.rules;
  const set = (rules: Rule[]) => onState({ ...state, rules });
  const move = (i: number, by: number) => {
    const next = rules.slice(), [r] = next.splice(i, 1);
    next.splice(Math.max(0, Math.min(next.length, i + by)), 0, r);
    set(next);
  };
  return (
    <div className="fpanel">
      <div className="fpanel-head">
        <button type="button" className="btn small" onClick={() => onDraft(blankRule())}><Plus size={14} aria-hidden /> New filter</button>
        <QuickColour p={p} onPick={(facet) => set([{ ...blankRule([], "byValue"), by: { facet }, name: `By ${describe(facet).name}` }, ...rules])} />
      </div>
      {rules.length > 0 && <div className="fpanel-switches">
        <label className="check"><input type="checkbox" checked={state.colours} onChange={(e) => onState({ ...state, colours: e.target.checked })} /> Show colours</label>
        <div className="frest"><span className="flabel">The rest</span>
          <div className="fact frest-seg" role="radiogroup" aria-label="The rest">
            {REST.map((r) => { const on = restOf(state) === r.id; return (
              <button key={r.id} type="button" role="radio" aria-checked={on} className={`seg${on ? " on" : ""}`} data-tip={r.tip}
                onClick={() => onState({ ...state, greyRest: r.id === "grey", hideRest: r.id === "hide" })}>{r.label}</button>); })}
          </div>
        </div>
        {onDrawingsWhole && <label className="check" data-tip="Plans, sections and elevations ignore the filters">
          <input type="checkbox" checked={!!drawingsWhole} onChange={(e) => onDrawingsWhole(e.target.checked)} /> Drawings show the whole model</label>}
      </div>}
      {!rules.length && <p className="hint">Find elements by model, class, floor or anything the model says about them, then
        colour, hide or isolate them. Start with <b>New filter</b>, a <b>Colour by</b> property, or a value in Properties.</p>}
      <ul className="filter-list">
        {rules.map((r, i) => (
          <li key={r.id} className={`frule${r.on ? "" : " off"}`}>
            <div className="frule-row">
              <input type="checkbox" checked={r.on} aria-label={`${r.name} on`} onChange={(e) => set(rules.map((x) => x.id === r.id ? { ...x, on: e.target.checked } : x))} />
              <ActionMark rule={r} at={i} />
              <button type="button" className="frule-name" onClick={() => onDraft({ ...r, when: r.when.map((c) => ({ ...c })) })}>
                {r.name || nameFor(r.when, r.by?.facet)}{r.invert ? " (inverted)" : ""}</button>
              <small className="why">{count(p, r)}</small>
              <span className="frule-tools">
                <button type="button" className="ibtn" disabled={i === 0} aria-label="Up" data-tip="Up: wins over those below" onClick={() => move(i, -1)}><ArrowUp size={14} aria-hidden /></button>
                <button type="button" className="ibtn" disabled={i === rules.length - 1} aria-label="Down" data-tip="Down" onClick={() => move(i, 1)}><ArrowDown size={14} aria-hidden /></button>
                {onZoom && <button type="button" className="ibtn" aria-label="Zoom to them" data-tip="Zoom to them" onClick={() => onZoom(actedOn(p, r))}><LocateFixed size={14} aria-hidden /></button>}
                {check && <HitButton p={p} rule={r} check={check} />}
                <button type="button" className="ibtn" aria-label="Delete" data-tip="Delete" onClick={() => set(rules.filter((x) => x.id !== r.id))}><Trash2 size={14} aria-hidden /></button>
              </span>
            </div>
            {r.action === "byValue" && r.on && state.colours && <Legend p={p} rule={r} />}
          </li>
        ))}
      </ul>
      {rules.length > 0 && <button type="button" className="btn small ghost" onClick={() => set([])}>Clear all</button>}
      {check && rules.length > 0 && <CheckClashes p={p} state={state} check={check} />}
    </div>
  );
}

type CheckProps = NonNullable<FiltersPanelProps["check"]>;
/** Check clashes' choice for what the filters show together (never a filter's id: those are generated). */
const SHOWN = "__shown";

/** Why a filter cannot be a check's side now, or null when it can. */
function cannot(p: Prepared, r: Rule, check: CheckProps): string | null {
  if (!check.defaults) return "Reading the models…";
  if (check.busy) return "Wait for the check that is running";
  const { n, rooms } = sideCounts(p, r);
  if (!n) return r.action === "byValue" ? "It colours nothing to check" : "It finds nothing to check";
  if (n === rooms) return "It finds only rooms, which have no solid body to clash";
  if (actedOn(p, r).length >= p.n) return "It finds everything: Check the open models instead";
  return null;
}

/** Why what the filters show cannot be a check's side now, or null when it can. */
function cannotShown(p: Prepared, state: FilterState, check: CheckProps): string | null {
  if (!check.defaults) return "Reading the models…";
  if (check.busy) return "Wait for the check that is running";
  const { n, rooms, all } = shownCounts(p, state);
  if (!n || n === rooms) return "The filters show nothing to check";
  if (n >= all) return "The filters hide nothing: Check the open models instead";
  return null;
}

/** A filter's row tool: what it finds against everything, in one click. */
function HitButton({ p, rule, check }: { p: Prepared; rule: Rule; check: CheckProps }) {
  const why = cannot(p, rule, check);
  return <button type="button" className="ibtn" aria-label="What do these hit?" disabled={!!why}
    data-tip={why ?? "What do these hit? Check them against everything the full check covers"}
    onClick={() => check.defaults && check.onCheck(checkTest(rule, "everything", "hard", null, check.defaults))}><Radar size={14} aria-hidden /></button>;
}

/** A check of one filter, or of what the filters show together, against everything, itself, what the filters show or
 * another filter: hard clashes deeper than a tolerance, or elements closer than a clearance. */
function CheckClashes({ p, state, check }: { p: Prepared; state: FilterState; check: CheckProps }) {
  const rules = state.rules;
  const [aId, setA] = useState(rules[0].id);
  const [bId, setB] = useState<string>("everything");
  const [kind, setKind] = useState<CheckKind>("hard");
  const [mm, setMm] = useState("");
  const a: Rule | "shown" = aId === SHOWN ? "shown" : rules.find((r) => r.id === aId) ?? rules[0];
  const others = rules.filter((r) => a === "shown" || r.id !== a.id);
  const b: Side = bId === "everything" || bId === "itself" ? bId : bId === SHOWN && a !== "shown" ? "shown"
    : others.find((r) => r.id === bId) ?? "everything";
  const d = check.defaults;
  const fallback = d ? Math.round((kind === "hard" ? d.tolerance_m : d.clearance_m) * 1000) : null;
  const typed = mm.trim() === "" || !Number.isFinite(Number(mm)) ? null : Number(mm);
  const why = (a === "shown" ? cannotShown(p, state, check) : cannot(p, a, check))
    ?? (b === "shown" ? cannotShown(p, state, check) : null)
    ?? (typeof b === "object" && sideCounts(p, b).n === sideCounts(p, b).rooms ? `${b.name || "Side B"} finds nothing to check` : null)
    ?? (kind === "clearance" && typed !== null && typed <= 0 ? "A clearance is more than 0 mm" : null);
  // The same numbers as the filter list (rooms included); the rooms a check cannot test are said under the choices.
  const nameOf = (r: Rule) => r.name || nameFor(r.when.filter(complete));
  const label = (r: Rule) => `${nameOf(r)} (${count(p, r)})`;
  const shown = shownCounts(p, state);
  const shownLabel = `What the filters show (${shown.n})`;
  const roomsOf = (s: Side) => (s === "shown" ? { name: "What the filters show", rooms: shown.rooms }
    : typeof s === "object" ? { name: nameOf(s), rooms: sideCounts(p, s).rooms } : { name: "", rooms: 0 });
  const rooms = roomsLine(b === "shown" || typeof b === "object" ? [roomsOf(a), roomsOf(b)] : [roomsOf(a)]);
  return (
    <details className="fcheck">
      <summary><Radar size={14} aria-hidden /> Check clashes</summary>
      <div className="fcheck-body">
      <div className="fgrid">
        <span className="flabel">Check</span>
        <div className="fcontrol"><select className="fselect" aria-label="Side A" value={a === "shown" ? SHOWN : a.id} onChange={(e) => setA(e.target.value)}>
          <option value={SHOWN}>{shownLabel}</option>
          {rules.map((r) => <option key={r.id} value={r.id}>{label(r)}</option>)}</select></div>
        <span className="flabel">Against</span>
        <div className="fcontrol"><select className="fselect" aria-label="Side B" value={typeof b === "object" ? b.id : b === "shown" ? SHOWN : b}
          onChange={(e) => setB(e.target.value)} data-tip={b === "everything" ? "Everything the full check covers: a site model is context, left out" : undefined}>
          <option value="everything">Everything</option>
          <option value="itself">Itself: these against each other</option>
          {a !== "shown" && <option value={SHOWN}>{shownLabel}</option>}
          {others.map((r) => <option key={r.id} value={r.id}>{label(r)}</option>)}</select></div>
        <span className="flabel">Find</span>
        <div className="fcontrol">
          <select className="fselect" aria-label="Kind" value={kind} onChange={(e) => { setKind(e.target.value as CheckKind); setMm(""); }}>
            <option value="hard">Hard clashes</option>
            <option value="clearance">Elements too close</option>
          </select>
        </div>
        <span className="flabel">{kind === "hard" ? "Deeper than" : "Closer than"}</span>
        <div className="fcontrol">
          <input className="fnum" type="number" min={0} aria-label="Millimetres" placeholder={fallback === null ? "" : String(fallback)} value={mm}
            onChange={(e) => setMm(e.target.value)} /> mm
        </div>
      </div>
      {rooms && <p className="fcheck-why">{rooms}</p>}
      <button type="button" className="btn primary fcheck-go" disabled={!!why}
        onClick={() => d && check.onCheck(checkTest(a, b, kind, typed, d, state))}><Radar size={15} aria-hidden /> Check clashes</button>
      {why && <p className="fcheck-why" role="status">{why}</p>}
      <p className="hint small">The clashes replace the open list; Detect again repeats this check.</p>
      </div>
    </details>
  );
}

/** A rule's mark in the list: its colour, or its action's icon. */
function ActionMark({ rule, at }: { rule: Rule; at: number }) {
  if (rule.action === "colour") return <i className="fswatch" style={{ background: ruleColour(rule, at) }} aria-hidden />;
  const a = ACTIONS.find((x) => x.id === rule.action)!;
  const Icon = a.icon;
  return <span className="faction" data-tip={a.label}><Icon size={14} aria-hidden /></span>;
}

/** A colour-by-value filter's colours, as a key under it. */
function Legend({ p, rule }: { p: Prepared; rule: Rule }) {
  const facet = rule.by ? p.byKey.get(rule.by.facet) : undefined;
  if (!facet) return null;
  const within = found(p, rule), off = new Set(rule.by?.off ?? []), colours = valueColours(rule, facet, within);
  const values = valueCounts(p, facet.key, within).filter((v) => !off.has(String(v.value)));
  return (
    <div className="flegend">
      {values.slice(0, 12).map((v) => (
        <span key={String(v.value)}><i className="fswatch" style={{ background: colours.get(String(v.value)) }} aria-hidden />
          {shownValue(v.value, facet.unit)} <small className="why">{v.count}</small></span>))}
      {values.length > 12 && <span className="why">and {values.length - 12} more</span>}
    </div>
  );
}

/** One click to colour everything by a property: the facets with a handful of values that most elements have. */
function QuickColour({ p, onPick }: { p: Prepared; onPick: (facet: string) => void }) {
  const options = useMemo(() => p.index.facets
    .filter((f) => f.values.length >= 2 && f.values.length <= 24 && f.kind !== "number")
    .map((f) => ({ f, n: new Set(f.items.flat()).size }))
    .filter(({ n }) => n >= Math.min(20, p.n / 10))
    .sort((x, y) => y.n - x.n).slice(0, 16), [p]);
  if (!options.length) return null;
  return (
    <select className="fselect" value="" aria-label="Colour by" onChange={(e) => { if (e.target.value) onPick(e.target.value); }}>
      <option value="">Colour by…</option>
      {options.map(({ f }) => { const d = describe(f.key); return <option key={f.key} value={f.key}>{d.set === ELEMENT ? d.name : `${d.name} (${d.set})`}</option>; })}
    </select>
  );
}

// ---------------------------------------------------------------- the editor

function Editor({ p, draft, onDraft, state, onState }: { p: Prepared; draft: Rule; onDraft: (r: Rule | null) => void;
  state: FilterState; onState: (s: FilterState) => void }) {
  const isNew = !state.rules.some((r) => r.id === draft.id);
  const set = (patch: Partial<Rule>) => onDraft({ ...draft, ...patch });
  const scope = (key: string) => draft.when.find((c) => c.facet === key)?.values ?? [];
  const setScope = (key: string, values: Value[]) => set({
    when: values.length
      ? (draft.when.some((c) => c.facet === key) ? draft.when.map((c) => c.facet === key ? { ...c, op: "is" as Op, values } : c)
        : [...draft.when, { facet: key, op: "is" as Op, values }])
      : draft.when.filter((c) => c.facet !== key),
  });
  // Counts among what the other conditions find, so each list says how many it would leave.
  const without = (i: number | string) => found(p, { when: draft.when.filter((c, k) => (typeof i === "number" ? k !== i : c.facet !== i)) });
  const props = draft.when.map((c, i) => ({ c, i })).filter(({ c }) => !SCOPED.has(c.facet));
  const setCond = (i: number, c: Condition) => set({ when: draft.when.map((x, k) => (k === i ? c : x)) });
  const hits = found(p, draft).size;
  const save = () => {
    const kept = withBy(draft);
    const rule = { ...kept, name: kept.name.trim() || nameFor(kept.when.filter(complete), kept.action === "byValue" ? kept.by?.facet : undefined),
      ...(draft.action === "colour" && !draft.colour ? { colour: nextColour(state.rules, draft.id) } : {}) };
    onState({ ...state, rules: isNew ? [rule, ...state.rules] : state.rules.map((r) => (r.id === rule.id ? rule : r)) });
    onDraft(null);
  };
  // A By value filter takes the last condition's property until one is picked: shown, saved and previewed alike.
  const byFacet = withBy(draft).by?.facet;
  return (
    <div className="feditor">
      <div className="feditor-head">
        <b>{isNew ? "New filter" : "Edit filter"}</b>
        <button type="button" className="ibtn" aria-label="Cancel" data-tip="Cancel" onClick={() => onDraft(null)}><X size={15} aria-hidden /></button>
      </div>
      <input className="fname-input" type="text" placeholder={nameFor(draft.when.filter(complete), draft.action === "byValue" ? byFacet : undefined)}
        aria-label="Name" value={draft.name} onChange={(e) => set({ name: e.target.value })} />
      <div className="fgrid">
        {SCOPE.map((s) => p.byKey.has(s.key) && (
          <Row key={s.key} label={s.label}>
            <Pick options={valueCounts(p, s.key, without(s.key))} chosen={scope(s.key)} onChange={(v) => setScope(s.key, v)} />
          </Row>))}
        {props.map(({ c, i }) => (
          <PropertyCondition key={`${i}:${c.facet}`} p={p} c={c} within={without(i)} onChange={(next) => setCond(i, next)}
            onRemove={() => set({ when: draft.when.filter((_, k) => k !== i) })} />
        ))}
      </div>
      <button type="button" className="btn small ghost" onClick={() => set({ when: [...draft.when, { facet: "", op: "is", values: [] }] })}>
        <Plus size={14} aria-hidden /> Property condition</button>
      <div className="fact" role="radiogroup" aria-label="What to do">
        {ACTIONS.map((a) => { const Icon = a.icon; return (
          <button key={a.id} type="button" role="radio" aria-checked={draft.action === a.id} className={`seg${draft.action === a.id ? " on" : ""}`}
            data-tip={a.tip} onClick={() => set({ action: a.id, ...(a.id === "byValue" && !draft.by && byFacet ? { by: { facet: byFacet } } : {}) })}>
            <Icon size={14} aria-hidden /> {a.label}</button>); })}
      </div>
      {draft.action === "colour" && <Swatches value={draft.colour ?? nextColour(state.rules, draft.id)}
        onChange={(colour) => set({ colour })} />}
      {draft.action === "byValue" && <ByValue p={p} draft={withBy(draft)} facet={byFacet} onChange={set} />}
      <label className="check"><input type="checkbox" checked={!!draft.invert} onChange={(e) => set({ invert: e.target.checked })} />
        Invert: everything it does not find</label>
      <p className="fcount"><b>{hits}</b> {hits === 1 ? "element" : "elements"}{draft.when.filter(complete).length === 0 && !draft.invert ? " (everything)" : ""}</p>
      <div className="feditor-foot">
        <button type="button" className="btn small" onClick={save}><Check size={14} aria-hidden /> {isNew ? "Add filter" : "Save"}</button>
        <button type="button" className="btn small ghost" onClick={() => onDraft(null)}>Cancel</button>
        {!isNew && <button type="button" className="btn small ghost danger" onClick={() => { onState({ ...state, rules: state.rules.filter((r) => r.id !== draft.id) }); onDraft(null); }}>
          <Trash2 size={14} aria-hidden /> Delete</button>}
      </div>
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return <><span className="flabel">{label}</span><div className="fcontrol">{children}</div></>;
}

/** A condition on any property: its set, the property, how to compare, and the values or bounds. */
function PropertyCondition({ p, c, within, onChange, onRemove }: { p: Prepared; c: Condition; within: Set<number>;
  onChange: (c: Condition) => void; onRemove: () => void }) {
  const groups = useMemo(() => sets(p), [p]);
  // The set comes from the chosen property; only a condition with none yet keeps the set picked for it.
  const chosenSet = c.facet ? describe(c.facet).set : "";
  const [picked, setSetName] = useState(chosenSet);
  const setName = chosenSet || picked;
  const inSet = groups.find((g) => g.set === setName)?.facets ?? [];
  const facet = c.facet ? p.byKey.get(c.facet) : undefined;
  const kind = facet?.kind ?? "text";
  const metres = facet?.unit === "m";
  const toInput = (v: number | undefined) => (v === undefined ? "" : String(metres ? Number((v * 1000).toFixed(1)) : v));
  const fromInput = (s: string) => (s.trim() === "" || !Number.isFinite(Number(s)) ? undefined : metres ? Number(s) / 1000 : Number(s));
  return (<>
    <span className="flabel">Property set</span>
    <div className="fcontrol fcond-head">
      <select className="fselect" value={setName} aria-label="Property set" onChange={(e) => { setSetName(e.target.value); onChange({ facet: "", op: "is", values: [] }); }}>
        <option value="">Choose…</option>
        {groups.map((g) => <option key={g.set} value={g.set}>{g.set}</option>)}
      </select>
      <button type="button" className="ibtn" aria-label="Remove this condition" data-tip="Remove" onClick={onRemove}><X size={14} aria-hidden /></button>
    </div>
    <span className="flabel">Property</span>
    <div className="fcontrol">
      <select className="fselect" value={c.facet} aria-label="Property" disabled={!inSet.length}
        onChange={(e) => onChange({ facet: e.target.value, op: "is", values: [] })}>
        <option value="">Choose…</option>
        {inSet.map((f) => <option key={f.key} value={f.key}>{describe(f.key).name}</option>)}
      </select>
    </div>
    {facet && <>
      <span className="flabel">Value</span>
      <div className="fcontrol fvalue">
        <select className="fselect fop" value={c.op} aria-label="Compare" onChange={(e) => onChange({ facet: c.facet, op: e.target.value as Op, values: c.values })}>
          {OPS[kind].map((o) => <option key={o.op} value={o.op}>{o.label}</option>)}
        </select>
        {(c.op === "is" || c.op === "isNot") && <Pick options={valueCounts(p, c.facet, within)} chosen={c.values ?? []} unit={facet.unit}
          onChange={(values) => onChange({ ...c, values })} />}
        {c.op === "contains" && <input className="ftext" type="text" aria-label="Contains" value={String(c.values?.[0] ?? "")}
          onChange={(e) => onChange({ ...c, values: e.target.value ? [e.target.value] : [] })} />}
        {(c.op === "between" || c.op === "gt") && <input className="fnum" type="number" aria-label="From" placeholder="from" value={toInput(c.min)}
          onChange={(e) => onChange({ ...c, min: fromInput(e.target.value) })} />}
        {(c.op === "between" || c.op === "lt") && <input className="fnum" type="number" aria-label="To" placeholder="to" value={toInput(c.max)}
          onChange={(e) => onChange({ ...c, max: fromInput(e.target.value) })} />}
        {(c.op === "between" || c.op === "lt" || c.op === "gt") && facet.unit && <span className="why">{metres ? "mm" : facet.unit}</span>}
      </div>
    </>}
  </>);
}

/** Several values from a list, with counts and a search when the list is long. */
function Pick({ options, chosen, onChange, unit }: { options: { value: Value; count: number }[]; chosen: Value[];
  onChange: (values: Value[]) => void; unit?: string }) {
  const [q, setQ] = useState("");
  const has = (v: Value) => chosen.some((x) => String(x) === String(v));
  const shown = q ? options.filter((o) => shownValue(o.value, unit).toLowerCase().includes(q.toLowerCase())) : options;
  const label = chosen.length === 0 ? "Choose…" : chosen.length <= 2 ? chosen.map((v) => shownValue(v, unit)).join(", ") : `${chosen.length} chosen`;
  return (
    <details className="pick">
      <summary><span>{label}</span></summary>
      <div className="pick-list">
        {options.length > 10 && <input className="pick-search" type="search" placeholder="Search" aria-label="Search values" value={q}
          onChange={(e) => setQ(e.target.value)} />}
        {chosen.length > 0 && <button type="button" className="pick-clear" onClick={() => onChange([])}>Clear</button>}
        {shown.slice(0, SHOWN_MAX).map((o) => (
          <label key={String(o.value)} className="pick-item">
            <input type="checkbox" checked={has(o.value)} onChange={(e) => onChange(e.target.checked ? [...chosen, o.value]
              : chosen.filter((x) => String(x) !== String(o.value)))} />
            <span>{shownValue(o.value, unit)}</span><small className="why">{o.count}</small>
          </label>))}
        {shown.length > SHOWN_MAX && <p className="hint">{shown.length - SHOWN_MAX} more: search to narrow them.</p>}
        {!options.length && <p className="hint">Nothing here among what the rest finds.</p>}
      </div>
    </details>
  );
}

function Swatches({ value, onChange }: { value: string; onChange: (c: string) => void }) {
  return (
    <div className="fswatches" role="radiogroup" aria-label="Colour">
      {PALETTE.map((c) => <button key={c} type="button" role="radio" aria-checked={c === value} aria-label={c}
        className={`fswatch big${c === value ? " on" : ""}`} style={{ background: c }} onClick={() => onChange(c)} />)}
      <input type="color" aria-label="Any colour" value={value} onChange={(e) => onChange(e.target.value)} />
    </div>
  );
}

/** Colour by value: which property, and a row per value with a tick, its count and its colour (the reference's
 * "Filter | Items | Color" table). */
function ByValue({ p, draft, facet: key, onChange }: { p: Prepared; draft: Rule; facet?: string; onChange: (patch: Partial<Rule>) => void }) {
  const groups = useMemo(() => sets(p), [p]);
  const facet = key ? p.byKey.get(key) : undefined;
  const within = found(p, draft);
  const off = new Set(draft.by?.off ?? []);
  const colours = facet ? valueColours(draft, facet, within) : new Map<string, string>();
  const by = draft.by ?? { facet: key ?? "" };
  return (<div className="fbyvalue">
    <label className="fbyvalue-pick">Colour by
      <select className="fselect" value={key ?? ""} aria-label="Colour by" onChange={(e) => onChange({ by: { facet: e.target.value } })}>
        <option value="">Choose a property…</option>
        {groups.map((g) => <optgroup key={g.set} label={g.set}>
          {g.facets.map((f) => <option key={f.key} value={f.key}>{describe(f.key).name}</option>)}</optgroup>)}
      </select>
    </label>
    {facet && <table className="ftable">
      <thead><tr><th><input type="checkbox" aria-label="All" checked={!off.size}
        onChange={(e) => onChange({ by: { ...by, facet: facet.key, off: e.target.checked ? [] : facet.values.map(String) } })} /></th>
        <th>Value</th><th>Items</th><th>Colour</th></tr></thead>
      <tbody>
        {valueCounts(p, facet.key, within).slice(0, SHOWN_MAX).map((v) => {
          const k = String(v.value), colour = colours.get(k) ?? OTHER;
          return (<tr key={k} className={off.has(k) ? "off" : ""}>
            <td><input type="checkbox" aria-label={`Colour ${k}`} checked={!off.has(k)}
              onChange={(e) => onChange({ by: { ...by, facet: facet.key, off: e.target.checked ? [...off].filter((x) => x !== k) : [...off, k] } })} /></td>
            <td>{shownValue(v.value, facet.unit)}</td><td className="why">{v.count}</td>
            <td><input type="color" aria-label={`Colour for ${k}`} value={colour}
              onChange={(e) => onChange({ by: { ...by, facet: facet.key, colours: { ...(by.colours ?? {}), [k]: e.target.value } } })} /></td>
          </tr>);
        })}
      </tbody>
    </table>}
  </div>);
}
