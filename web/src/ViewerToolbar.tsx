import { Box, Camera, Compass, Crop, Layers, LocateFixed, Maximize, Radar, Ruler, ScanEye, Shapes, Target } from "lucide-react";
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
  hiddenModels: number[];
}

/** The viewer's tools as a vertical icon rail: modes, then tools, then camera. Every icon has a tooltip. */
export function ViewerToolbar({ state, models, hasFocus, onMode, onToggle, onView, onFit, onFocus, onModel, onShot }: {
  state: ToolbarState; models: string[]; hasFocus: boolean;
  onMode: (m: ViewMode) => void; onToggle: (k: "edges" | "section" | "measure") => void; onView: (p: Preset) => void;
  onFit: () => void; onFocus: () => void; onModel: (i: number, visible: boolean) => void; onShot: () => void;
}) {
  const stop = (e: React.SyntheticEvent) => e.stopPropagation();
  return (
    <nav className="rail" aria-label="Viewer tools" onClick={stop} onDoubleClick={stop} onPointerDown={stop}>
      <div className="rail-group" role="group" aria-label="View mode">
        {MODES.map((m) => <IconButton key={m.id} icon={m.icon} label={m.label} shortcut={m.key} active={state.mode === m.id} onClick={() => onMode(m.id)} />)}
      </div>
      <div className="rail-group" role="group" aria-label="Tools">
        <IconButton icon={Crop} label="Section box around the clash" shortcut="S" active={state.section} disabled={!hasFocus && !state.section} onClick={() => onToggle("section")} />
        <IconButton icon={Shapes} label="Outline the pair through walls" shortcut="E" active={state.edges} onClick={() => onToggle("edges")} />
        <IconButton icon={Ruler} label="Measure between two points" shortcut="M" active={state.measure} onClick={() => onToggle("measure")} />
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
