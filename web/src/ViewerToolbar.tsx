import { Box, Camera, Compass, Crop, Layers, LocateFixed, Maximize, Radar, Ruler, ScanEye, Shapes, SlidersHorizontal, Target, Waypoints } from "lucide-react";
import { IconButton, Popover } from "./ui";
import type { Preset, ViewMode } from "./viewer/Viewer";

const MODES = [
  { id: "shaded", icon: Box, label: "Shaded: every element in its own colour", key: "V" },
  { id: "xray", icon: ScanEye, label: "X-ray: see the clash through the building", key: "X" },
  { id: "context", icon: Radar, label: "Context: only what is within 2.5 m", key: "C" },
  { id: "isolate", icon: Target, label: "Isolate: only the clashing elements", key: "I" },
] as const;
const VIEWS: { id: Preset; label: string; key: string }[] = [
  { id: "top", label: "Top", key: "1" }, { id: "front", label: "Front", key: "2" },
  { id: "right", label: "Right", key: "3" }, { id: "iso", label: "Isometric", key: "4" },
];

export interface ToolbarState {
  mode: ViewMode;
  edges: boolean;
  section: boolean;
  measure: boolean;
  /** The connection highlight: pointing at an element (or tapping it) lights what it is linked to. */
  links: boolean;
  hiddenModels: number[];
}

/** The viewer's tools as a vertical icon rail: modes, then tools, then camera. Every icon has a tooltip. On a phone
 * (`compact`) a touch screen shows no tooltips, so the same tools sit in one labelled Tools menu (a sheet from the
 * bottom), beside Go to the clash and Fit, the two people reach for most. */
export function ViewerToolbar({ compact = false, state, models, hasFocus, onMode, onToggle, onView, onFit, onFocus, onModel, onShot }: {
  compact?: boolean; state: ToolbarState; models: string[]; hasFocus: boolean;
  onMode: (m: ViewMode) => void; onToggle: (k: "edges" | "section" | "measure" | "links") => void; onView: (p: Preset) => void;
  onFit: () => void; onFocus: () => void; onModel: (i: number, visible: boolean) => void; onShot: () => void;
}) {
  const stop = (e: React.SyntheticEvent) => e.stopPropagation();
  if (compact) return (
    <nav className="rail compact" aria-label="Viewer tools" onClick={stop} onDoubleClick={stop} onPointerDown={stop}>
      <Popover icon={SlidersHorizontal} label="View tools" text="Tools" tip="bottom">
        {(close) => (<>
          <p className="pop-title">Show</p>
          <div className="tool-modes" role="group" aria-label="View mode">
            {MODES.map((m) => (
              <button key={m.id} type="button" className={state.mode === m.id ? "on" : ""} aria-pressed={state.mode === m.id}
                onClick={() => { onMode(m.id); close(); }}>
                <m.icon size={18} strokeWidth={1.8} aria-hidden /><b>{m.label.split(":")[0]}</b><small>{m.label.split(": ")[1]}</small></button>))}
          </div>
          <p className="pop-title">Tools</p>
          <button type="button" className={`pop-item ${state.section ? "on" : ""}`} aria-pressed={state.section} disabled={!hasFocus && !state.section}
            onClick={() => { onToggle("section"); close(); }}><Crop size={16} aria-hidden /> Section box around the clash{state.section && <b className="tick">✓</b>}</button>
          <button type="button" className={`pop-item ${state.edges ? "on" : ""}`} aria-pressed={state.edges}
            onClick={() => { onToggle("edges"); close(); }}><Shapes size={16} aria-hidden /> Outline the pair through walls{state.edges && <b className="tick">✓</b>}</button>
          <button type="button" className={`pop-item ${state.measure ? "on" : ""}`} aria-pressed={state.measure}
            onClick={() => { onToggle("measure"); close(); }}><Ruler size={16} aria-hidden /> Measure between two points{state.measure && <b className="tick">✓</b>}</button>
          <button type="button" className={`pop-item ${state.links ? "on" : ""}`} aria-pressed={state.links}
            onClick={() => { onToggle("links"); close(); }}><Waypoints size={16} aria-hidden /> Show connections: tap an element{state.links && <b className="tick">✓</b>}</button>
          <button type="button" className="pop-item" onClick={() => { onShot(); close(); }}><Camera size={16} aria-hidden /> Save a screenshot</button>
          <p className="pop-title">Camera</p>
          <div className="tool-views" role="group" aria-label="Standard views">
            {VIEWS.map((v) => <button key={v.id} type="button" className="btn small" onClick={() => { onView(v.id); close(); }}>{v.label}</button>)}
          </div>
          {models.length > 0 && <>
            <p className="pop-title">Models shown</p>
            {models.map((name, i) => (
              <label key={name} className="pop-item check">
                <input type="checkbox" checked={!state.hiddenModels.includes(i)} onChange={(e) => onModel(i, e.target.checked)} /> {name}
              </label>))}
          </>}
        </>)}
      </Popover>
      <button type="button" className="btn rail-btn" disabled={!hasFocus} onClick={onFocus}><LocateFixed size={16} aria-hidden /> Go to clash</button>
      <button type="button" className="btn rail-btn" aria-label="Fit the whole model" onClick={onFit}><Maximize size={16} aria-hidden /></button>
    </nav>
  );
  return (
    <nav className="rail" aria-label="Viewer tools" onClick={stop} onDoubleClick={stop} onPointerDown={stop}>
      <div className="rail-group" role="group" aria-label="View mode">
        {MODES.map((m) => <IconButton key={m.id} icon={m.icon} label={m.label} shortcut={m.key} active={state.mode === m.id} onClick={() => onMode(m.id)} />)}
      </div>
      <div className="rail-group" role="group" aria-label="Tools">
        <IconButton icon={Crop} label="Section box around the clash" shortcut="S" active={state.section} disabled={!hasFocus && !state.section} onClick={() => onToggle("section")} />
        <IconButton icon={Shapes} label="Outline the pair through walls" shortcut="E" active={state.edges} onClick={() => onToggle("edges")} />
        <IconButton icon={Ruler} label="Measure between two points" shortcut="M" active={state.measure} onClick={() => onToggle("measure")} />
        <IconButton icon={Waypoints} label="Connections: point at an element to light what it is joined to (or hold Alt / Option); Shift for the whole run" shortcut="L" active={state.links} onClick={() => onToggle("links")} />
      </div>
      <div className="rail-group" role="group" aria-label="Camera">
        <IconButton icon={LocateFixed} label="Go to the clash" shortcut="F" disabled={!hasFocus} onClick={onFocus} />
        <IconButton icon={Maximize} label="Fit the whole model" shortcut="H" onClick={onFit} />
        <Popover icon={Compass} label="Standard views" shortcut="1-4">
          {(close) => VIEWS.map((v) => (
            <button key={v.id} role="menuitem" className="pop-item" onClick={() => { onView(v.id); close(); }}>
              <span>{v.label}</span><kbd>{v.key}</kbd></button>))}
        </Popover>
        {models.length > 0 && (
          <Popover icon={Layers} label="Show or hide models">
            {() => models.map((name, i) => (
              <label key={name} className="pop-item check">
                <input type="checkbox" checked={!state.hiddenModels.includes(i)} onChange={(e) => onModel(i, e.target.checked)} /> {name}
              </label>))}
          </Popover>
        )}
        <IconButton icon={Camera} label="Save a screenshot" onClick={onShot} />
      </div>
    </nav>
  );
}
