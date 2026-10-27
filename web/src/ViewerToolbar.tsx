import type { Preset, ViewMode } from "./viewer/Viewer";

const MODES: { id: ViewMode; label: string; key: string; hint: string }[] = [
  { id: "shaded", label: "Shaded", key: "", hint: "Every element in its own colour; the pair in red and green" },
  { id: "xray", label: "X-ray", key: "X", hint: "Everything else see-through, so a clash inside the building shows" },
  { id: "context", label: "Context", key: "C", hint: "Only elements within 2.5 m of the pair, see-through" },
  { id: "isolate", label: "Isolate", key: "I", hint: "Only the pair" },
];
const VIEWS: { id: Preset; label: string; key: string }[] = [
  { id: "top", label: "Top", key: "1" }, { id: "front", label: "Front", key: "2" },
  { id: "right", label: "Right", key: "3" }, { id: "iso", label: "Iso", key: "4" },
];

export interface ToolbarState {
  mode: ViewMode;
  edges: boolean;
  section: boolean;
  measure: boolean;
  hiddenModels: number[];
}

export function ViewerToolbar({ state, models, hasFocus, onMode, onToggle, onView, onFit, onFocus, onModel, onShot }: {
  state: ToolbarState; models: string[]; hasFocus: boolean;
  onMode: (m: ViewMode) => void; onToggle: (k: "edges" | "section" | "measure") => void; onView: (p: Preset) => void;
  onFit: () => void; onFocus: () => void; onModel: (i: number, visible: boolean) => void; onShot: () => void;
}) {
  const stop = (e: React.SyntheticEvent) => e.stopPropagation();
  return (
    <div className="vtool" onClick={stop} onDoubleClick={stop} onPointerDown={stop}>
      <div className="seg" role="group" aria-label="View mode">
        {MODES.map((m) => (
          <button key={m.id} className={state.mode === m.id ? "on" : ""} onClick={() => onMode(m.id)}
            title={`${m.hint}${m.key ? ` (${m.key})` : ""}`} aria-pressed={state.mode === m.id}>{m.label}</button>
        ))}
      </div>
      <div className="seg" role="group" aria-label="Tools">
        <button className={state.section ? "on" : ""} onClick={() => onToggle("section")} disabled={!hasFocus && !state.section}
          title="Section box around the clash (S)" aria-pressed={state.section}>Section</button>
        <button className={state.edges ? "on" : ""} onClick={() => onToggle("edges")}
          title="Outline the pair through other elements (E)" aria-pressed={state.edges}>Edges</button>
        <button className={state.measure ? "on" : ""} onClick={() => onToggle("measure")}
          title="Measure: click two points (M)" aria-pressed={state.measure}>Measure</button>
      </div>
      <div className="seg" role="group" aria-label="Camera">
        <button onClick={onFocus} disabled={!hasFocus} title="Go to the clash (F)">Clash</button>
        <button onClick={onFit} title="Fit the whole model (H)">Fit</button>
        {VIEWS.map((v) => <button key={v.id} onClick={() => onView(v.id)} title={`${v.label} view (${v.key})`}>{v.label}</button>)}
      </div>
      {models.length > 0 && (
        <details className="models vmodels">
          <summary>Models</summary>
          <div className="menu">
            {models.map((name, i) => (
              <label key={name} className="check">
                <input type="checkbox" checked={!state.hiddenModels.includes(i)} onChange={(e) => onModel(i, e.target.checked)} /> {name}
              </label>
            ))}
          </div>
        </details>
      )}
      <button className="btn ghost-btn" onClick={onShot} title="Download a PNG of this view">Screenshot</button>
    </div>
  );
}
