import { Fragment, useState } from "react";
import type { ElementProperties } from "./api";

/** The selected element's properties (docs/panels.md, "Properties"): its type, material, size and attributes, then each
 * property set and quantity set as the model has them (properties.py), with a filter and click to copy. */

export type Row = { name: string; value: string };
export type Section = { title: string; rows: Row[] };

/** A value as people read it: numbers to four decimals at most, yes and no, lists joined, a unit after. */
export function shown(v: unknown, unit = ""): string {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "boolean") return v ? "Yes" : "No";
  if (typeof v === "number") return `${Number.isInteger(v) ? v : Number(v.toFixed(4))}${unit ? ` ${unit}` : ""}`;
  if (Array.isArray(v)) return v.map((x) => shown(x)).join(", ");
  return String(v);
}

/** "PredefinedType" → "Predefined type". */
const words = (name: string) => name.replace(/([a-z])([A-Z])/g, "$1 $2").replace(/ ([A-Z])(?=[a-z])/g, (_, c: string) => ` ${c.toLowerCase()}`);

/** The panel's sections, in order: the element itself (type, material, size, the attributes the card doesn't show
 * already), then each property set, then each quantity set. Empty ones are left out. */
export function sections(p: ElementProperties): Section[] {
  const element: Row[] = [
    ...(p.type ? [{ name: "Type", value: [p.type.name, p.type.ifc_class.replace(/^Ifc/, "")].filter(Boolean).join(" · ") }] : []),
    ...(p.materials.length ? [{ name: p.materials.length > 1 ? "Materials" : "Material", value: p.materials.join(", ") }] : []),
    ...(p.size_m ? [{ name: "Size", value: `${p.size_m.map((v) => Math.round(v * 1000)).join(" × ")} mm` }] : []),
    ...Object.keys(p.attributes).filter((k) => k !== "Name" && k !== "Tag").map((k) => ({ name: words(k), value: shown(p.attributes[k]) })),
  ];
  return [
    { title: "Element", rows: element },
    ...Object.keys(p.psets).map((title) => ({ title, rows: Object.keys(p.psets[title]).map((k) => ({ name: k, value: shown(p.psets[title][k]) })) })),
    ...Object.keys(p.quantities).map((title) => ({ title, rows: Object.keys(p.quantities[title]).map((k) => {
      const q = p.quantities[title][k];
      return { name: k, value: shown(q.value, q.unit) };
    }) })),
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

export function PropertySets({ data, loading }: { data: ElementProperties | null; loading: boolean }) {
  const [filter, setFilter] = useState("");
  const [copied, setCopied] = useState<string | null>(null);
  if (!data) return <p className="hint">{loading ? "Reading its properties…" : "No properties to show."}</p>;
  const list = filtered(sections(data), filter);
  // The panel may be in a window of its own: copy with that window's clipboard.
  const copy = (e: React.MouseEvent<HTMLElement>, text: string, key: string) => {
    const nav = e.currentTarget.ownerDocument.defaultView?.navigator ?? navigator;
    void nav.clipboard?.writeText(text).then(() => { setCopied(key); window.setTimeout(() => setCopied((k) => (k === key ? null : k)), 1200); })
      .catch(() => undefined);
  };
  return (
    <div className="psets">
      <input className="pset-filter" type="search" placeholder="Filter properties" aria-label="Filter properties" value={filter}
        onChange={(e) => setFilter(e.target.value)} />
      {list.map((s) => (
        <details key={s.title} open>
          <summary>{s.title}<span className="why"> · {s.rows.length}</span></summary>
          <dl className="kv">
            {s.rows.map((r) => {
              const key = `${s.title}/${r.name}`;
              return <Fragment key={key}><dt>{r.name}</dt><dd>
                <button type="button" className="pset-value" title="Click to copy" onClick={(e) => copy(e, r.value, key)}>
                  {copied === key ? "Copied" : r.value}</button></dd></Fragment>;
            })}
          </dl>
        </details>
      ))}
      {!list.length && <p className="hint">{filter ? `Nothing matches “${filter}”.` : "The model gives this element no properties."}</p>}
    </div>
  );
}
