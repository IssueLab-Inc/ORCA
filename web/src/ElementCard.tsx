import { useState } from "react";
import { ArrowLeft, Box, ChevronRight, Ellipsis, EyeOff, Focus, ListFilter, LocateFixed, Waypoints, X } from "lucide-react";
import type { ElementProperties, ObjectRef } from "./api";
import { LINK_COLOURS, LINK_ORDER, LINK_WORDS, type LinkKind } from "./links";
import { classWords, PropertySets, type PropEditor, type RowActions } from "./Properties";
import { IconButton, Popover } from "./ui";

/** The selected element's card (docs/panels.md, "Properties"): what it is, where it sits (breadcrumbs up to the
 * project, each opening that object's own properties), what to do with it (icon buttons), what it is linked to, then
 * everything its model says (Properties.tsx). The dock's Properties panel and the card over the model (classic layout,
 * tablets, phones) both show it. */

type LinkEntry = { global_id: string; name: string | null; ifc_class: string };

export interface CardActions {
  onClose?: () => void;
  /** Select a linked element and go to it. */
  onPick: (gid: string) => void;
  onShowLinks: () => void;
  onSide: (side: "a" | "b") => void;
  canB: boolean;
  onZoom: () => void; onHide: () => void; onIsolate: () => void; onSection: () => void;
  onHideClass: () => void; onIsolateClass: () => void; onFilterClass: () => void;
  /** A storey's own: isolate, hide or filter by everything on it. */
  onLevel: (name: string, how: "isolate" | "hide" | "filter") => void;
  /** Read another object's properties (a breadcrumb, the storey row). */
  load: (ref: ObjectRef) => Promise<ElementProperties>;
  /** What a value's row offers (filter by it, colour by it, isolate all with it): only for the element itself. */
  rows?: RowActions;
  /** Change what the model says about the element (its pencil rows): only for the element itself. */
  editor?: PropEditor;
}

export function ElementCard({ gid, info, props, loading, actions: act, fold = false }: {
  gid: string; info: Record<string, unknown> | null; props: ElementProperties | null; loading: boolean;
  actions: CardActions;
  /** The card over the model folds everything the model says under "All properties". */
  fold?: boolean;
}) {
  const [parent, setParent] = useState<{ ref: ObjectRef; data: ElementProperties | null; loading: boolean } | null>(null);
  const open = (ref: ObjectRef) => {
    if (!ref.global_id) return;
    if (ref.global_id === gid) { setParent(null); return; }
    setParent({ ref, data: null, loading: true });
    act.load(ref).then((data) => setParent((p) => (p?.ref.global_id === ref.global_id ? { ...p, data, loading: false } : p)))
      .catch(() => setParent((p) => (p?.ref.global_id === ref.global_id ? { ...p, loading: false } : p)));
  };
  const cls = String(props?.ifc_class ?? info?.ifc_class ?? "");
  const name = String(props?.name ?? info?.name ?? "") || classWords(cls || "IfcElement");
  const typeName = props?.type?.name;
  const path = props?.path ?? [];
  const shown = parent ? parent.data : props;
  const shownClass = parent ? parent.ref.ifc_class : cls;
  const isStorey = parent?.ref.ifc_class === "IfcBuildingStorey";
  const sets = <PropertySets data={shown} loading={parent ? parent.loading : loading} rows={parent ? undefined : act.rows} onOpen={open}
    editor={parent ? undefined : act.editor} />;
  return (
    <div className="ecard">
      <div className="ecard-head">
        {parent && <IconButton icon={ArrowLeft} label={`Back to ${name}`} onClick={() => setParent(null)} tip="bottom" size={16} />}
        <div className="ecard-title">
          <b>{parent ? parent.ref.name : name}</b>
          <span className="why">{classWords(shownClass || "IfcElement")}{!parent && typeName ? ` · ${typeName}` : ""}</span>
        </div>
        {act.onClose && <IconButton icon={X} label="Close" onClick={act.onClose} tip="left" size={15} className="ecard-close" />}
      </div>
      {path.length > 0 && (
        <nav className="crumbs" aria-label="Where it sits">
          {path.map((c, i) => (
            <span key={`${c.global_id}-${i}`} className="crumb-step">
              <button type="button" className={`crumb${parent?.ref.global_id === c.global_id ? " on" : ""}`} aria-current={parent?.ref.global_id === c.global_id || undefined}
                onClick={() => open(c)} data-tip={`${classWords(c.ifc_class)}: its own properties`} data-tip-side="bottom">{c.name}</button>
              {i < path.length - 1 && <ChevronRight size={12} aria-hidden />}
            </span>))}
        </nav>)}
      {!parent && (
        <div className="ecard-bar" role="toolbar" aria-label="What to do with it">
          <button type="button" className="side-btn" onClick={() => act.onSide("a")} data-tip="Set as A: one side of a pair to check" data-tip-side="bottom">
            <i className="sw red" aria-hidden />A</button>
          <button type="button" className="side-btn" disabled={!act.canB} onClick={() => act.onSide("b")}
            data-tip={act.canB ? "Set as B: the other side of the pair" : "Set A first"} data-tip-side="bottom"><i className="sw green" aria-hidden />B</button>
          <span className="ecard-sep" aria-hidden />
          <IconButton icon={LocateFixed} label="Zoom to it" shortcut="F" onClick={act.onZoom} tip="bottom" size={16} />
          <IconButton icon={EyeOff} label="Hide it for now" onClick={act.onHide} tip="bottom" size={16} />
          <IconButton icon={Focus} label="Isolate it for now" onClick={act.onIsolate} tip="bottom" size={16} />
          <IconButton icon={Box} label="Section box round it" onClick={act.onSection} tip="bottom" size={16} />
          {hasLinks(info) && <IconButton icon={Waypoints} label="Light up what it is linked to" onClick={act.onShowLinks} tip="bottom" size={16} />}
          {cls && <Popover icon={Ellipsis} label={`More: every ${classWords(cls)}`} tip="bottom">
            {(close) => (<>
              <p className="pop-title">Every {classWords(cls)}</p>
              <button type="button" className="pop-item" onClick={() => { act.onHideClass(); close(); }}><EyeOff size={15} aria-hidden /> Hide them for now</button>
              <button type="button" className="pop-item" onClick={() => { act.onIsolateClass(); close(); }}><Focus size={15} aria-hidden /> Isolate them for now</button>
              <button type="button" className="pop-item" onClick={() => { act.onFilterClass(); close(); }}><ListFilter size={15} aria-hidden /> Filter by this class…</button>
            </>)}
          </Popover>}
        </div>)}
      {isStorey && parent && (
        <div className="ecard-bar" role="toolbar" aria-label="This level">
          <IconButton icon={Focus} label="Isolate this level for now" onClick={() => act.onLevel(parent.ref.name, "isolate")} tip="bottom" size={16} />
          <IconButton icon={EyeOff} label="Hide this level for now" onClick={() => act.onLevel(parent.ref.name, "hide")} tip="bottom" size={16} />
          <IconButton icon={ListFilter} label="Filter by this level…" onClick={() => act.onLevel(parent.ref.name, "filter")} tip="bottom" size={16} />
        </div>)}
      {!parent && <Links info={info} onPick={act.onPick} onShow={act.onShowLinks} />}
      {fold ? <details className="all-props"><summary>All properties</summary>{sets}</details> : sets}
    </div>
  );
}

const hasLinks = (info: Record<string, unknown> | null) =>
  LINK_ORDER.some((k) => ((info?.links as Partial<Record<LinkKind, LinkEntry[]>> | undefined)?.[k]?.length ?? 0) > 0);

/** What the element is linked to, by kind (docs/connections.md), with its system and assembly. */
export function Links({ info, onPick, onShow }: { info: Record<string, unknown> | null; onPick: (gid: string) => void; onShow: () => void }) {
  const links = (info?.links ?? {}) as Partial<Record<LinkKind, LinkEntry[]>>;
  const kinds = LINK_ORDER.filter((k) => links[k]?.length);
  const systems = (info?.systems ?? []) as string[];
  const partOf = info?.part_of as { name: string; parts: number } | null | undefined;
  if (!info || (!kinds.length && !systems.length && !partOf)) return null;
  return (
    <div className="links">
      {kinds.map((k) => (
        <div key={k} className="link-kind">
          <span className="link-head"><i className="sw" style={{ background: LINK_COLOURS[k] }} />{LINK_WORDS[k]} · {links[k]!.length}</span>
          <ul>
            {links[k]!.slice(0, 6).map((l) => (
              <li key={l.global_id}><button type="button" className="link" onClick={() => onPick(l.global_id)}
                data-tip={`${l.ifc_class.replace(/^Ifc/, "")}: select and go to it`}>{l.name || l.ifc_class.replace(/^Ifc/, "")}</button></li>))}
            {links[k]!.length > 6 && <li className="hint">and {links[k]!.length - 6} more</li>}
          </ul>
        </div>))}
      {partOf && <p className="hint">Part of {partOf.name} ({partOf.parts} parts)</p>}
      {systems.length > 0 && <p className="hint">System: {systems.join(", ")}</p>}
      {kinds.length > 0 && <button type="button" className="btn small" onClick={onShow}><Waypoints size={14} aria-hidden /> Light them up</button>}
    </div>
  );
}
