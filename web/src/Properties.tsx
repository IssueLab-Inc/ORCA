import { Fragment, useState } from "react";
import { ChevronsDownUp, ChevronsUpDown, Copy, Focus, ListFilter, Palette } from "lucide-react";
import type { ElementProperties, ObjectRef, PropRow } from "./api";
import { IconButton } from "./ui";

/** The selected object's properties (docs/panels.md, "Properties"): what it is and where it sits, its type, materials,
 * classifications, groups and documents, then each property set and quantity set as the model has them
 * (properties.py), with a filter and click to copy. A row the filters can use carries its facet key (docs/filters.md):
 * `class`, `type`, `material`, `storey`, `file`, `attr:<Name>`, `pset:<Set>/<Prop>`, `qto:<Set>/<Name>`,
 * `classif:<System>`, `group:<IfcClass>`. */

export type Row = {
  name: string; value: string;
  /** The value as the server gives it (SI numbers, text, yes/no): what a filter matches. */
  raw?: string | number | boolean;
  facet?: string; fromType?: boolean;
  /** An object the row points at (the storey, the container): the panel can open its own properties. */
  link?: ObjectRef;
  href?: string;
};
export type Section = { title: string; rows: Row[]; fromType?: boolean };

/** A number as people read it: four decimals at most. */
const num = (v: number) => `${Number.isInteger(v) ? v : Number(v.toFixed(4))}`;

/** A value as people read it: numbers to four decimals at most, lengths in millimetres, yes and no, lists joined, a
 * unit after. */
export function shown(v: unknown, unit = ""): string {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "boolean") return v ? "Yes" : "No";
  if (typeof v === "number") return unit === "m" ? `${Number((v * 1000).toFixed(1))} mm` : `${num(v)}${unit ? ` ${unit}` : ""}`;
  if (Array.isArray(v)) return v.length ? v.map((x) => shown(x, unit)).join(", ") : "—";
  return String(v);
}

/** "PredefinedType" → "Predefined type". */
export const words = (name: string) => name.replace(/([a-z])([A-Z])/g, "$1 $2").replace(/ ([A-Z])(?=[a-z])/g, (_, c: string) => ` ${c.toLowerCase()}`);

/** "IfcDistributionSystem" → "Distribution system". */
export const classWords = (cls: string) => {
  const w = words(cls.replace(/^Ifc/, ""));
  return w.charAt(0).toUpperCase() + w.slice(1);
};

/** What a filter can match a value by: text, a number or yes/no; nothing for lists, ranges and tables. */
const matchable = (v: unknown): v is string | number | boolean =>
  typeof v === "string" ? v !== "" : typeof v === "number" || typeof v === "boolean";

/** One value of any kind as a row (a complex property's parts become rows of their own, after it). */
function valueRows(p: PropRow, facet: string | undefined, fromType: boolean | undefined, prefix = ""): Row[] {
  const name = prefix ? `${prefix} › ${p.name}` : p.name;
  const from = fromType || p.from_type || undefined;
  if (p.kind === "complex") {
    const head: Row[] = p.value ? [{ name, value: String(p.value), fromType: from }] : [];
    return [...head, ...(p.rows ?? []).flatMap((r) => valueRows(r, facet ? `${facet}/${r.name}` : undefined, from, name))];
  }
  let value: string;
  if (p.kind === "bounded") {
    const b = (p.value ?? {}) as { lower?: number; upper?: number; set_point?: number };
    const lo = b.lower !== undefined ? shown(b.lower, p.unit) : null, hi = b.upper !== undefined ? shown(b.upper, p.unit) : null;
    value = lo && hi ? `${lo} to ${hi}` : lo ? `at least ${lo}` : hi ? `at most ${hi}` : "—";
    if (b.set_point !== undefined) value += ` (set point ${shown(b.set_point, p.unit)})`;
  } else if (p.kind === "table" && p.table) {
    const t = p.table;
    value = t.defining.map((d, i) => `${shown(d, t.defining_unit ?? "")} → ${shown(t.defined[i], t.defined_unit ?? "")}`).join("; ") || "—";
  } else {
    value = shown(p.value, p.unit);
  }
  const row: Row = { name, value, fromType: from };
  if (facet && matchable(p.value) && p.kind !== "table" && p.kind !== "bounded") { row.facet = facet; row.raw = p.value; }
  return [row];
}

const href = (s: string | null | undefined) => (s && /^https?:\/\//i.test(s) ? s : undefined);

/** The panel's sections, in order: the object itself (class, name, every attribute, GlobalId, where it sits, file,
 * size), its type, materials, classification, systems and groups, documents, then each property and quantity set and
 * each material's own sets. Empty ones are left out. */
export function sections(p: ElementProperties): Section[] {
  const attr = (a: PropRow) => valueRows(a, `attr:${a.name}`, undefined).map((r) => ({ ...r, name: words(r.name) }));
  const element: Row[] = [
    { name: "Class", value: p.ifc_class, raw: p.ifc_class, facet: "class" },
    ...p.attributes.flatMap(attr),
    ...(p.global_id ? [{ name: "GlobalId", value: p.global_id }] : []),
    ...(p.storey ? [{ name: "Storey", value: p.storey.name, raw: p.storey.name, facet: "storey", link: p.storey }] : []),
    ...(p.container && p.container.global_id !== p.storey?.global_id
      ? [{ name: classWords(p.container.ifc_class), value: p.container.name, link: p.container }] : []),
    { name: "File", value: p.source, raw: p.source, facet: "file" },
    ...(p.size_m ? [{ name: "Size", value: `${p.size_m.map((v) => Math.round(v * 1000)).join(" × ")} mm` }] : []),
  ];
  const type: Row[] = p.type ? [
    { name: "Class", value: p.type.ifc_class },
    ...(p.type.name ? [{ name: "Name", value: p.type.name, raw: p.type.name, facet: "type" }] : []),
    ...p.type.attributes.filter((a) => a.name !== "Name").map((a) => ({ name: words(a.name), value: shown(a.value, a.unit) })),
  ] : [];
  const materials: Row[] = p.materials.flatMap((m) => {
    const from = m.from_type || undefined;
    const item = (i: (typeof m.items)[number], n: number): Row => {
      const parts = [i.material, i.profile, i.thickness_m !== undefined ? shown(i.thickness_m, "m") : null,
        i.fraction !== undefined ? `${num(i.fraction * 100)} %` : null, i.category].filter(Boolean);
      const label = m.usage === "layers" ? `Layer ${n + 1}${i.name ? ` · ${i.name}` : ""}`
        : m.usage === "single" ? "Material" : i.name || (m.usage === "profiles" ? "Profile" : "Material");
      return { name: label, value: parts.join(" · ") || "—", fromType: from, ...(i.material ? { raw: i.material, facet: "material" } : {}) };
    };
    const head: Row[] = m.usage === "single" ? [] : [{ name: classWords(m.usage), value: m.name, fromType: from }];
    const total: Row[] = m.total_m !== undefined ? [{ name: "Total thickness", value: shown(m.total_m, "m"), fromType: from }] : [];
    return [...head, ...m.items.map(item), ...total];
  });
  const classification: Row[] = p.classifications.map((c) => ({
    name: c.system ?? "Classification", value: [c.identification, c.name].filter(Boolean).join(" ") || "—",
    ...(c.identification || c.name ? { raw: (c.identification ?? c.name)!, facet: `classif:${c.system ?? ""}` } : {}),
    href: href(c.location),
  }));
  const groups: Row[] = p.groups.map((g) => ({ name: classWords(g.ifc_class), value: g.name, raw: g.name, facet: `group:${g.ifc_class}` }));
  const documents: Row[] = p.documents.map((d) => ({ name: d.identification ?? "Document", value: d.name ?? d.location ?? "—", href: href(d.location) }));
  const sets: Section[] = p.sets.map((s) => ({
    title: s.name, fromType: s.from_type || undefined,
    rows: s.props.flatMap((r) => valueRows(r, `${s.kind}:${s.name}/${r.name}`, s.from_type)),
  }));
  const materialSets: Section[] = p.materials.flatMap((m) => m.sets.map((s) => ({
    title: `${s.material ?? m.name} · ${s.name}`, fromType: m.from_type || undefined,
    rows: s.props.flatMap((r) => valueRows(r, undefined, m.from_type)),
  })));
  return [
    { title: "Element", rows: element },
    { title: p.type?.name ? `Type · ${p.type.name}` : "Type", rows: type },
    { title: "Materials", rows: materials },
    { title: "Classification", rows: classification },
    { title: "Systems and groups", rows: groups },
    { title: "Documents", rows: documents },
    ...sets,
    ...materialSets,
  ].filter((s) => s.rows.length);
}

/** Only what has `filter` in its name or value (any case); a section whose title matches keeps every row. */
export function filtered(list: Section[], filter: string): Section[] {
  const f = filter.trim().toLowerCase();
  if (!f) return list;
  return list.map((s) => s.title.toLowerCase().includes(f) ? s
    : { ...s, rows: s.rows.filter((r) => r.name.toLowerCase().includes(f) || r.value.toLowerCase().includes(f)) })
    .filter((s) => s.rows.length);
}

/** What a value's row offers when the filters' index knows its facet: filter by it, colour by it, isolate all with it. */
export interface RowActions {
  facets: Set<string>;
  onFilter: (row: Row) => void;
  onColourBy: (row: Row) => void;
  onIsolate: (row: Row) => void;
}

export function PropertySets({ data, loading, rows: acts, onOpen }: { data: ElementProperties | null; loading: boolean;
  rows?: RowActions; onOpen?: (ref: ObjectRef) => void }) {
  const [filter, setFilter] = useState("");
  const [copied, setCopied] = useState<string | null>(null);
  const [closed, setClosed] = useState<Set<string>>(new Set());
  if (!data) return <p className="hint">{loading ? "Reading its properties…" : "No properties to show."}</p>;
  const all = sections(data);
  const list = filtered(all, filter);
  // The panel may be in a window of its own: copy with that window's clipboard.
  const copy = (e: React.MouseEvent<HTMLElement>, text: string, key: string) => {
    const nav = e.currentTarget.ownerDocument.defaultView?.navigator ?? navigator;
    void nav.clipboard?.writeText(text).then(() => { setCopied(key); window.setTimeout(() => setCopied((k) => (k === key ? null : k)), 1200); })
      .catch(() => undefined);
  };
  const folded = all.length > 0 && all.every((s) => closed.has(s.title));
  return (
    <div className="psets">
      <div className="pset-tools">
        <input className="pset-filter" type="search" placeholder="Filter properties" aria-label="Filter properties" value={filter}
          onChange={(e) => setFilter(e.target.value)} />
        <IconButton icon={folded ? ChevronsUpDown : ChevronsDownUp} label={folded ? "Expand all" : "Collapse all"} tip="left" size={15}
          onClick={() => setClosed(folded ? new Set() : new Set(all.map((s) => s.title)))} />
      </div>
      {list.map((s) => (
        <details key={s.title} open={!!filter || !closed.has(s.title)}
          onToggle={(e) => { const open = e.currentTarget.open; if (filter) return;
            setClosed((c) => { const n = new Set(c); if (open) n.delete(s.title); else n.add(s.title); return n; }); }}>
          <summary>{s.title}{s.fromType && <span className="from-type">Type</span>}<span className="why"> · {s.rows.length}</span></summary>
          <dl className="kv">
            {s.rows.map((r, i) => {
              const key = `${s.title}/${r.name}/${i}`;
              const usable = !!acts && !!r.facet && acts.facets.has(r.facet) && r.raw !== undefined;
              return <Fragment key={key}><dt>{r.name}{r.fromType && !s.fromType && <span className="from-type" data-tip="Given by its type">Type</span>}</dt>
                <dd className="prow">
                  {r.link && onOpen ? <button type="button" className="pset-link" onClick={() => onOpen(r.link!)} data-tip="Its own properties">{r.value}</button>
                    : r.href ? <a href={r.href} target="_blank" rel="noreferrer">{r.value}</a>
                    : <button type="button" className="pset-value" title="Click to copy" onClick={(e) => copy(e, r.value, key)}>
                      {copied === key ? "Copied" : r.value}</button>}
                  <span className="prow-tools">
                    <button type="button" className="ibtn" aria-label={`Copy ${r.name}`} data-tip="Copy" onClick={(e) => copy(e, r.value, key)}><Copy size={13} aria-hidden /></button>
                    {usable && <>
                      <button type="button" className="ibtn" aria-label={`Filter by ${r.name} = ${r.value}`} data-tip="Filter by this value" onClick={() => acts!.onFilter(r)}><ListFilter size={13} aria-hidden /></button>
                      <button type="button" className="ibtn" aria-label={`Colour by ${r.name}`} data-tip={`Colour by ${r.name}`} onClick={() => acts!.onColourBy(r)}><Palette size={13} aria-hidden /></button>
                      <button type="button" className="ibtn" aria-label={`Isolate all with ${r.name} = ${r.value}`} data-tip="Isolate all with this value" onClick={() => acts!.onIsolate(r)}><Focus size={13} aria-hidden /></button>
                    </>}
                  </span>
                </dd></Fragment>;
            })}
          </dl>
        </details>
      ))}
      {!list.length && <p className="hint">{filter ? `Nothing matches “${filter}”.` : "The model gives this element no properties."}</p>}
    </div>
  );
}
