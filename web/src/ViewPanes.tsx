import { FlipHorizontal2, LocateFixed, Maximize, Maximize2, Minimize2, Pin, PinOff, SlidersHorizontal } from "lucide-react";
import { useState } from "react";
import { Popover } from "./ui";
import type { Pane, Viewer } from "./viewer/Viewer";
import { COMPASS_NAME, level3, planPreset, planRange, storeyHeight, type Compass, type DrawingSpec, type PlanPreset,
  type SectionSpec } from "./viewer/views";

const COMPASSES: Compass[] = ["north", "south", "east", "west"];
const PRESETS: { id: PlanPreset; label: string; hint: string }[] = [
  { id: "floor", label: "Floor plan", hint: "cut +1.200, down to the floor" },
  { id: "ceiling", label: "Ceiling void", hint: "beams, girders and the services between them, no floor" },
  { id: "storey", label: "Whole storey", hint: "cut just under the next level" },
];

/** Each pane's header over the viewer (docs/views.md, "Interaction"): what it shows, its view range or depth and crop,
 * pin, go to the clash, fit and maximise; the lines between panes to drag; and the clash chip, in the 3D pane. */
export function ViewPanes({ viewer, chip, offset, compact = false }: { viewer: Viewer | null; chip: React.ReactNode; offset: number; compact?: boolean }) {
  if (!viewer || !viewer.models.length) return null;
  const panes = viewer.visiblePanes();
  const single = panes.length === 1 && panes[0].spec.kind === "3d";
  const stop = (e: React.SyntheticEvent) => e.stopPropagation();
  if (single) return chip ? <div className="pane-head solo" style={{ left: offset, top: compact ? 56 : 12 }} onClick={stop} onPointerDown={stop} onDoubleClick={stop}>{chip}</div> : null;
  return (<>
    {panes.map((pane) => {
      const i = viewer.panes.indexOf(pane);
      return (
        <div key={i} className={`pane-head of-${pane.spec.kind}`} style={{ left: pane.rect.x + (pane.rect.x < 4 ? offset : 8), top: pane.rect.y + 8,
          maxWidth: Math.max(pane.rect.w - (pane.rect.x < 4 ? offset : 8) - 16, 120) }}
          onClick={stop} onPointerDown={stop} onDoubleClick={stop}>
          {pane.spec.kind === "3d" ? <><b className="pane-name">3D</b>{chip}</> : <DrawingHead viewer={viewer} pane={pane} i={i} />}
          {viewer.panes.length > 1 && (
            <button className="ibtn" aria-label={viewer.maximisedPane === i ? "Back to the layout" : "Maximise this view"}
              data-tip={viewer.maximisedPane === i ? "Back to the layout" : "Maximise this view"} data-tip-side="bottom"
              onClick={() => viewer.maximise(viewer.maximisedPane === i ? null : i)}>
              {viewer.maximisedPane === i ? <Minimize2 size={14} aria-hidden /> : <Maximize2 size={14} aria-hidden />}</button>)}
        </div>);
    })}
    {viewer.maximisedPane == null && viewer.panes.length > 1 && <Splitters viewer={viewer} />}
  </>);
}

function DrawingHead({ viewer, pane, i }: { viewer: Viewer; pane: Pane; i: number }) {
  const spec = pane.spec as DrawingSpec;
  const value = spec.kind === "plan" ? `plan:${spec.level}` : spec.kind === "section" ? "section" : `elevation:${spec.facing}`;
  const pick = (v: string) => {
    const [kind, arg] = v.split(":");
    if (kind === "plan") viewer.setPaneSpec(i, spec.kind === "plan" ? { ...spec, level: Number(arg) } : { kind: "plan", level: Number(arg), cut: 1.2, bottom: 0 });
    else if (kind === "section") viewer.setPaneSpec(i, { kind: "section", origin: [0, 0], angle: 0, flip: false, far: null, crop: null, ...(spec.kind === "section" ? spec : {}) });
    else viewer.setPaneSpec(i, { kind: "elevation", facing: arg as Compass, far: spec.kind === "elevation" ? spec.far : null });
  };
  return (<>
    <select className="pane-pick" value={value} onChange={(e) => pick(e.target.value)} aria-label="What this view shows">
      <optgroup label="Plans">{viewer.levels.map((l, k) => <option key={k} value={`plan:${k}`}>{l.name} · Plan</option>)}</optgroup>
      <optgroup label="Section"><option value="section">Section A–A</option></optgroup>
      <optgroup label="Elevations">{COMPASSES.map((c) => <option key={c} value={`elevation:${c}`}>{COMPASS_NAME[c]} elevation</option>)}</optgroup>
    </select>
    <Popover icon={SlidersHorizontal} label="View range, depth and crop" text={rangeText(spec)} tip="bottom">
      {() => <RangeMenu viewer={viewer} spec={spec} i={i} />}
    </Popover>
    <button className="ibtn" aria-label={pane.pinned ? "Unpin: follow the clashes I pick" : "Pin: keep this view when I pick a clash"}
      data-tip={pane.pinned ? "Pinned: a clash I pick leaves it alone" : "Pin: keep this view when I pick a clash"} data-tip-side="bottom"
      aria-pressed={pane.pinned} onClick={() => viewer.setPinned(i, !pane.pinned)}>
      {pane.pinned ? <Pin size={14} aria-hidden /> : <PinOff size={14} aria-hidden />}</button>
    <button className="ibtn" aria-label="Go to the clash" data-tip="Go to the clash" data-tip-side="bottom" onClick={() => viewer.paneToClash(i)}><LocateFixed size={14} aria-hidden /></button>
    <button className="ibtn" aria-label="Fit the whole model" data-tip="Fit the whole model" data-tip-side="bottom" onClick={() => viewer.fitPane(i)}><Maximize size={14} aria-hidden /></button>
  </>);
}

/** The range in a word or two (the title block says the rest). */
function rangeText(spec: DrawingSpec): string {
  if (spec.kind === "plan") return `cut ${level3(spec.cut)}`;
  return spec.far == null ? "depth: all" : `depth ${spec.far.toFixed(1)} m`;
}

/** A number in metres, typed to the millimetre; Enter or leaving the field sets it. */
function Metres({ label, value, onSet, step = 0.05 }: { label: string; value: number; onSet: (v: number) => void; step?: number }) {
  const [text, setText] = useState<string | null>(null);
  const commit = () => { const v = Number(text); if (text != null && Number.isFinite(v)) onSet(v); setText(null); };
  return (
    <label className="range-field"><span>{label}</span>
      <input type="number" step={step} value={text ?? value.toFixed(3)} aria-label={`${label}, metres`}
        onChange={(e) => setText(e.target.value)} onBlur={commit} onKeyDown={(e) => { if (e.key === "Enter") commit(); }} />
      <small>m</small></label>
  );
}

function RangeMenu({ viewer, spec, i }: { viewer: Viewer; spec: DrawingSpec; i: number }) {
  const set = (s: DrawingSpec) => viewer.setPaneSpec(i, s);
  if (spec.kind === "plan") {
    const h = storeyHeight(viewer.levels, spec.level);
    const { level } = planRange(viewer.levels, spec);
    return (<>
      <p className="pop-title">{level.name} · view range</p>
      <div className="range-presets">
        {PRESETS.map((p) => {
          const r = planPreset(viewer.levels, spec.level, p.id);
          return <button key={p.id} className="btn small" disabled={!r} data-tip={r ? p.hint : "Needs a level above"} data-tip-side="bottom"
            onClick={() => r && set({ ...spec, ...r })}>{p.label}</button>;
        })}
        <button className="btn small" data-tip="Its level and a cut through the clash picked" data-tip-side="bottom"
          onClick={() => viewer.paneToClash(i)}>Through the clash</button>
      </div>
      <Metres label="Cut plane" value={spec.cut} onSet={(cut) => set({ ...spec, cut: Math.max(cut, (spec.bottom ?? -1e9) + 0.01) })} />
      <input className="range-slider" type="range" min={0} max={h} step={0.01} value={spec.cut} aria-label="Cut plane height"
        onChange={(e) => set({ ...spec, cut: Math.max(Number(e.target.value), (spec.bottom ?? -1e9) + 0.01) })} />
      <label className="pop-item check"><input type="checkbox" checked={spec.bottom != null}
        onChange={(e) => set({ ...spec, bottom: e.target.checked ? Math.min(0, spec.cut - 0.01) : null })} /> Bottom (what is below is left out)</label>
      {spec.bottom != null && <Metres label="Bottom" value={spec.bottom} onSet={(bottom) => set({ ...spec, bottom: Math.min(bottom, spec.cut - 0.01) })} />}
      <p className="hint">Heights above {level.name} ({level3(level.elevation_m)}). Only the cut plane cuts: the bottom just leaves out what is below.</p>
    </>);
  }
  if (spec.kind === "section") {
    const crop = spec.crop;
    const setCrop = (k: keyof NonNullable<SectionSpec["crop"]>, v: number) => crop && set({ ...spec, crop: { ...crop, [k]: v } });
    return (<>
      <p className="pop-title">Section A–A · depth and crop</p>
      <div className="range-presets">
        <button className="btn small" onClick={() => set({ ...spec, flip: !spec.flip })}><FlipHorizontal2 size={13} aria-hidden /> Look the other way</button>
        <button className="btn small" onClick={() => viewer.paneToClash(i)}>Through the clash</button>
      </div>
      <label className="pop-item check"><input type="checkbox" checked={spec.far != null}
        onChange={(e) => set({ ...spec, far: e.target.checked ? 2 : null })} /> Far clip (leave out what lies further)</label>
      {spec.far != null && <Metres label="Far clip" value={spec.far} onSet={(far) => set({ ...spec, far: Math.max(far, 0.01) })} />}
      <label className="pop-item check"><input type="checkbox" checked={!!crop}
        onChange={(e) => set({ ...spec, crop: e.target.checked ? viewer.defaultCrop() : null })} /> Crop</label>
      {crop && <>
        <Metres label="Left" value={crop.left} onSet={(v) => setCrop("left", Math.max(v, 0))} />
        <Metres label="Right" value={crop.right} onSet={(v) => setCrop("right", Math.max(v, 0))} />
        <Metres label="Bottom" value={crop.bottom} onSet={(v) => setCrop("bottom", Math.min(v, crop.top - 0.01))} />
        <Metres label="Top" value={crop.top} onSet={(v) => setCrop("top", Math.max(v, crop.bottom + 0.01))} />
      </>}
      <p className="hint">Only the section line cuts; the far clip and the crop just bound what is drawn.</p>
    </>);
  }
  return (<>
    <p className="pop-title">{COMPASS_NAME[spec.facing]} elevation · depth</p>
    <label className="pop-item check"><input type="checkbox" checked={spec.far != null}
      onChange={(e) => set({ ...spec, far: e.target.checked ? 6 : null })} /> Far clip from the façade</label>
    {spec.far != null && <Metres label="Far clip" value={spec.far} onSet={(far) => set({ ...spec, far: Math.max(far, 0.01) })} />}
  </>);
}

/** The lines between panes: drag to give one view more room. */
function Splitters({ viewer }: { viewer: Viewer }) {
  const host = viewer.renderer.domElement.parentElement;
  if (!host) return null;
  const W = host.clientWidth, H = host.clientHeight, s = viewer.splitShares;
  const drag = (axis: "x" | "y") => (e: React.PointerEvent) => {
    e.stopPropagation();
    const r = host.getBoundingClientRect();
    const move = (m: PointerEvent) => viewer.setSplit(axis === "x" ? (m.clientX - r.left) / r.width : s.x, axis === "y" ? (m.clientY - r.top) / r.height : s.y);
    const up = () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };
  return (<>
    <div className="pane-split x" style={{ left: W * s.x - 3 }} onPointerDown={drag("x")} onClick={(e) => e.stopPropagation()} aria-hidden />
    {viewer.layout === "quad" && <div className="pane-split y" style={{ top: H * s.y - 3 }} onPointerDown={drag("y")} onClick={(e) => e.stopPropagation()} aria-hidden />}
  </>);
}
