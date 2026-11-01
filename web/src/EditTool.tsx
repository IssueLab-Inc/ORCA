// The Edit tool (docs/manual-edits.md): edit the model by hand. Pick a tool, click a face (or an element), drag it or
// type how far, and ORCA checks the edit on the server before anything is kept: what it clears, what it would hit,
// the nearest gap, who must review it. Keep it, or keep it with the clashes it makes when that is what you mean. Every
// kept edit goes in the edit log (EditPanel), tied to the clash on screen and to any fix it amends.
import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import { ChevronDown, ChevronUp, X } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { api, type EditCheck, type EditFace, type EditKept, type EditOp, type Journal, type JournalEntry } from "./api";
import { AlignIcon, CheckingIcon, ClipIcon, CutByIcon, DeleteIcon, EditIcon, KeepIcon, LogIcon, MoveIcon, PushPullIcon,
  RemoveSectionIcon, SplitIcon, VoidIcon } from "./editIcons";
import { EditPanel } from "./EditPanel";
import { EDIT_TOOLS, signedMm, toolForKey, toolState, type EditToolId } from "./viewer/edit";
import type { FacePick, Viewer } from "./viewer/Viewer";

const ICON: Record<EditToolId, LucideIcon> = { push_pull: PushPullIcon, align: AlignIcon, move: MoveIcon, void: VoidIcon,
  cut_by: CutByIcon, split: SplitIcon, remove_section: RemoveSectionIcon, clip: ClipIcon, delete: DeleteIcon };
/** The tools this build makes; the rest say so in the palette. */
export const READY: ReadonlySet<EditToolId> = new Set<EditToolId>(["push_pull", "align", "move", "void", "cut_by"]);

export interface EditToolHandle {
  /** A click on the stage while the tool is on. */ click(ev: MouseEvent): void;
  /** The pointer over the stage: light the face under it. */ hover(ev: MouseEvent | null): void;
  /** A key while the tool is on; true when the tool took it. */ key(key: string): boolean;
  /** Esc: one step back (a preview, a target, the face); false when there is nothing left to step back from. */ escape(): boolean;
}

type Face = EditFace & { label?: string };
const mmIn = (m: number) => Math.round(m * 1000);
const metres = (m: number) => `${m.toFixed(3)} m`;

/** What the check found, in one line, with its tone. */
export function checkStatus(c: EditCheck): { tone: "ok" | "warn" | "bad"; text: string } {
  if (c.blocked) return { tone: "bad", text: c.blocked.charAt(0).toUpperCase() + c.blocked.slice(1) };
  const near = c.min_clearance_m != null ? ` · nearest ${mmIn(c.min_clearance_m).toLocaleString()} mm` : "";
  const cleared = c.cleared?.length ? ` · clears ${c.cleared.length} clash${c.cleared.length === 1 ? "" : "es"}` : "";
  if (c.clashes) {
    const hits = [...(c.new ?? []), ...(c.worse ?? [])].filter((h) => h.kind === "collision");
    const first = hits[0];
    return { tone: "warn", text: `Makes ${c.clashes} clash${c.clashes === 1 ? "" : "es"}${first ? `: ${first.name} ${signedMm(first.distance_m)}` : ""}${hits.length > 1 ? ` and ${hits.length - 1} more` : ""}` };
  }
  return { tone: "ok", text: `Clear${near}${cleared}${c.close ? ` · ${c.close} closer than the clearance` : ""}` };
}

export const EditTool = forwardRef<EditToolHandle, {
  viewer: () => Viewer | null; sceneId: string | null; busy: boolean; coarse: boolean;
  /** The clash on screen: a kept edit is tied to it. */ clash: { id: string | null; pair: string[] | null } | null;
  journal: Journal | null; csvUrl: string | null; clashLabel: (id: string) => string | null; showLog: boolean;
  onKept: (kept: EditKept) => Promise<void>; onUndo: () => void; onRedo: () => void; onUndoTo: (e: JournalEntry) => void;
  onShow: (e: JournalEntry) => void; onError: (message: string) => void; onClose: () => void;
}>(function EditTool({ viewer, sceneId, busy, coarse, clash, journal, csvUrl, clashLabel, showLog, onKept, onUndo, onRedo,
  onUndoTo, onShow, onError, onClose }, ref) {
  const [tool, setTool] = useState<EditToolId>("push_pull");
  const [folded, setFolded] = useState(false);
  const [face, setFace] = useState<Face | null>(null);
  const [pick, setPick] = useState<FacePick | null>(null);
  const [target, setTarget] = useState<Face | null>(null);
  const [targetPick, setTargetPick] = useState<FacePick | null>(null);
  const [hover, setHover] = useState<FacePick | null>(null);
  const [by, setBy] = useState(0);
  const [gap, setGap] = useState(0);
  const [how, setHow] = useState<"stretch" | "move">("stretch");
  const [delta, setDelta] = useState<[number, number, number]>([0, 0, 0]);
  const [from, setFrom] = useState<number[] | null>(null);
  const [voidShape, setVoidShape] = useState<"rect" | "round">("rect");
  const [voidSize, setVoidSize] = useState<[number, number]>([0.3, 0.3]);   // width and height, or the diameter first
  const [recess, setRecess] = useState<number | null>(null);                 // null: through; else the recess's depth
  const [cutter, setCutter] = useState<{ globalId: string; label: string } | null>(null);
  const [check, setCheck] = useState<EditCheck | null>(null);
  const [checking, setChecking] = useState(false);
  const [keeping, setKeeping] = useState(false);
  const [settled, setSettled] = useState(0);
  const ask = useRef(0), frame = useRef(0);
  const act = coarse ? "Tap" : "Click";
  const element = face?.element ?? pick?.globalId ?? null;

  /** Back to picking (the tool stays): previews and highlights go. */
  function reset(keepTool = true) {
    ++ask.current;
    const v = viewer();
    if (v && face && pick) v.pushPreview(face.element, pick.point, face.normal, null);
    v?.preview([]);
    setFace(null); setPick(null); setTarget(null); setTargetPick(null); setBy(0); setGap(tool === "cut_by" ? 0.02 : 0); setDelta([0, 0, 0]); setFrom(null);
    setCutter(null);
    setCheck(null); setChecking(false);
    if (!keepTool) setTool("push_pull");
  }
  useEffect(() => () => { const v = viewer(); v?.showEditFaces([]); v?.setEditDrag(null); v?.preview([]); }, []);
  useEffect(() => { reset(); }, [tool, sceneId]);

  // The faces lit: the one to edit (with its arrow), the target, and the one under the pointer.
  useEffect(() => {
    const v = viewer();
    if (!v) return;
    const lit: Parameters<Viewer["showEditFaces"]>[0] = [];
    if (face && pick) lit.push({ globalId: face.element, point: pick.point, normal: pick.normal, tone: "chosen", arrow: tool === "push_pull" && face.allows.includes("push_pull") && !check });
    if (target && targetPick) lit.push({ globalId: target.element, point: targetPick.point, normal: targetPick.normal, tone: "target" });
    if (hover && !(face && hover.globalId === face.element && sameNormal(hover.normal, pick?.normal))) lit.push({ ...hover, tone: "hover" });
    v.showEditFaces(lit);
  }, [face, pick, target, targetPick, hover, check, tool]);

  // Dragging the chosen face pushes or pulls it, live; letting go checks it.
  useEffect(() => {
    const v = viewer();
    if (!v) return;
    if (tool === "push_pull" && face && pick && face.allows.includes("push_pull")) {
      v.setEditDrag({ globalId: face.element, point: pick.point, normal: face.normal,
        onMove: (m) => { setCheck(null); v.preview([]); setBy(m); v.pushPreview(face.element, pick.point, face.normal, m); },
        onEnd: (m) => { if (Math.abs(m) >= 0.0005) void run(pushOp(m)); } });
    } else v.setEditDrag(null);
    return () => v.setEditDrag(null);
  }, [tool, face, pick]);

  const pushOp = (m: number): EditOp => ({ op: "push_pull", element: face!.element, face: face!.id, by_m: m });
  const alignOp = (g = gap, h = how): EditOp => ({ op: "align", element: face!.element, face: face!.id, gap_m: g, how: h,
    to: { element: target!.element, face: target!.kind === "other" ? undefined : target!.id,
      ...(target!.kind === "other" && targetPick ? { point: targetPick.point, normal: targetPick.normal } : {}) } });
  const moveOp = (d: number[]): EditOp => ({ op: "move", element: element!, delta_m: d });
  const voidOp = (at = pick!.point): EditOp => ({ op: "void", element: face!.element, face: face!.id, at, shape: voidShape,
    ...(voidShape === "round" ? { diameter_m: voidSize[0] } : { width_m: voidSize[0], height_m: voidSize[1] }),
    ...(recess != null ? { depth_m: recess } : {}) });
  const cutOp = (c = cutter, g = gap): EditOp => ({ op: "cut_by", element: element!, cutter: c!.globalId, gap_m: g });

  async function run(op: EditOp) {
    if (!sceneId) return;
    const n = ++ask.current;
    setChecking(true); setCheck(null);
    try {
      const r = await api.editCheck(sceneId, op);
      if (n !== ask.current) return;
      setCheck(r);
      const v = viewer();
      if (v && face && pick) v.pushPreview(face.element, pick.point, face.normal, null);
      if (v && r.preview?.length) {
        v.showOption({ kind: "edit", moved: r.targets ?? [], deltaM: [0, 0, 0], pieces: r.preview, before: r.before ?? null,
          worldMeshes: true }, "after", r.blocked ? "#b8352a" : r.clashes ? "#d98a00" : "#1f9d3a");
      } else v?.preview([]);
    } catch (e) { if (n === ask.current) onError((e as Error).message); } finally { if (n === ask.current) setChecking(false); }
  }

  async function keep() {
    if (!check || !sceneId || check.blocked || keeping) return;
    setKeeping(true);
    try {
      const kept = await api.editApply(sceneId, check.op, check.key, check.clashes, clash);
      viewer()?.preview([]);
      await onKept(kept);
      setSettled(Date.now());
      reset();
    } catch (e) { onError((e as Error).message); } finally { setKeeping(false); }
  }

  async function choose(p: FacePick, as: "face" | "target") {
    if (!sceneId) return;
    const n = ++ask.current;
    try {
      const f = await api.editFace(sceneId, p.globalId, p.point, p.normal) as Face;
      if (n !== ask.current) return;
      if (as === "target") {
        if (tool === "cut_by") {
          const c = { globalId: f.element, label: f.label ?? "the element" };
          setCutter(c); setTarget(f); setTargetPick(p);
          if (element) void run(cutOp(c));
          return;
        }
        setTarget(f); setTargetPick(p);
        if (face) void runAlign(f, p);
        return;
      }
      const need = EDIT_TOOLS.find((t) => t.id === tool)!.needs === "face" ? tool : null;
      if (as === "face" && need && !f.allows.includes(need)) {
        onError(`Its ${f.name} cannot be ${need === "push_pull" ? "pushed or pulled" : need === "align" ? "aligned" : "used for that"}${f.why_not ? `: ${f.why_not}` : ""}.`);
        return;
      }
      setFace(f); setPick(p); setBy(0); setCheck(null);
      setHow(f.allows.includes("push_pull") ? "stretch" : "move");
    } catch (e) { if (n === ask.current) onError((e as Error).message); }
  }

  function runAlign(t: Face, tp: FacePick) {
    if (!face) return;
    return run({ op: "align", element: face.element, face: face.id, gap_m: gap, how,
      to: t.kind === "other" ? { element: t.element, point: tp.point, normal: tp.normal } : { element: t.element, face: t.id } });
  }

  useImperativeHandle(ref, () => ({
    click(ev) {
      const v = viewer();
      if (!v || !sceneId || busy || keeping) return;
      if (tool === "move" && element) {   // two points: where from, then where to
        const s = v.snapPoint(ev);
        if (!s) return;
        if (!from) { setFrom(s.point); return; }
        const d = s.point.map((x, i) => Math.round((x - from[i]) * 1000) / 1000) as [number, number, number];
        setDelta(d); setFrom(null);
        void run(moveOp(d));
        return;
      }
      const p = v.pickFace(ev);
      if (!p) return;
      if ((tool === "align" || tool === "cut_by") && face && p.globalId !== face.element) { void choose(p, "target"); return; }
      if (tool === "void" && face && p.globalId === face.element && sameNormal(p.normal, pick?.normal)) {
        setPick(p); setCheck(null); viewer()?.preview([]);   // the same face: the opening goes where it was clicked
        return;
      }
      if (face && p.globalId === face.element && sameNormal(p.normal, pick?.normal)) return;   // the same face: drag it
      void choose(p, "face");
    },
    hover(ev) {
      if (!ev) { setHover(null); return; }
      cancelAnimationFrame(frame.current);
      frame.current = requestAnimationFrame(() => setHover(viewer()?.pickFace(ev) ?? null));
    },
    key(k) {
      if (k === "delete" || k === "backspace") { if (READY.has("delete")) setTool("delete"); return READY.has("delete"); }
      const t = toolForKey(k);
      if (!t || t === tool) return false;
      setTool(t);
      return true;
    },
    escape() {
      if (checking || check || by || delta.some((x) => x) || from) {
        ++ask.current;
        const v = viewer();
        if (v && face && pick) v.pushPreview(face.element, pick.point, face.normal, null);
        v?.preview([]);
        setCheck(null); setChecking(false); setBy(0); setDelta([0, 0, 0]); setFrom(null);
        return true;
      }
      if (target) { setTarget(null); setTargetPick(null); return true; }
      if (face || pick) { setFace(null); setPick(null); return true; }
      return false;
    },
  }), [tool, face, pick, target, element, from, check, checking, by, delta, sceneId, busy, keeping, gap, how, voidShape, voidSize, recess, cutter]);

  const hint = (() => {
    if (tool === "align") return !face ? `${act} the face to move` : !target ? `${act} the face to align it to` : null;
    if (tool === "move") return !element ? `${act} the element to move` : from ? `${act} where it goes` : `Type the move, or ${act.toLowerCase()} where it comes from, then where it goes`;
    if (tool === "push_pull") return !face ? `${act} a face to push or pull` : !check && !checking ? (coarse ? "Type how far" : "Drag the face (Shift: by the mm), or type how far") : null;
    if (tool === "void") return !face ? `${act} the face to cut the opening in` : `It goes where you ${act.toLowerCase()}ed; ${act.toLowerCase()} elsewhere on the face to move it`;
    if (tool === "cut_by") return !face ? `${act} the element to cut` : !cutter ? `${act} the element whose shape cuts it` : null;
    return EDIT_TOOLS.find((t) => t.id === tool)!.hint;
  })();
  const status = check ? checkStatus(check) : null;
  const stop = (e: React.SyntheticEvent) => e.stopPropagation();
  const Tool = ICON[tool];

  return (
    <section className={`edit-panel ${folded ? "folded" : ""}`} aria-label="Edit the model" onClick={stop} onDoubleClick={stop} onPointerDown={stop} onPointerMove={stop}>
      <header>
        <EditIcon size={16} aria-hidden className={settled ? "play" : ""} key={settled} />
        <b>Edit</b><span className="why">{EDIT_TOOLS.find((t) => t.id === tool)!.label}</span>
        <button type="button" className="ibtn" aria-label={folded ? "Show the tool" : "Fold the panel"} data-tip={folded ? "Show" : "Fold"} data-tip-side="bottom"
          onClick={() => setFolded((f) => !f)}>{folded ? <ChevronDown size={14} aria-hidden /> : <ChevronUp size={14} aria-hidden />}</button>
        <button type="button" className="ibtn" aria-label="Stop editing" data-tip="Stop editing (P)" data-tip-side="bottom" onClick={onClose}><X size={14} aria-hidden /></button>
      </header>
      {!folded && <>
        <div className="edit-palette" role="toolbar" aria-label="Edit tools">
          {EDIT_TOOLS.map((t) => {
            const Icon = ICON[t.id], state = toolState(t.id, face, READY);
            return (
              <button key={t.id} type="button" className={`ebtn ibtn ${tool === t.id ? "on" : ""}`} aria-pressed={tool === t.id} aria-label={t.label}
                disabled={!READY.has(t.id)} onClick={() => setTool(t.id)}
                data-tip={`${t.label}  ·  ${t.key.toUpperCase()}${state.why && READY.has(t.id) ? `\n${state.why}` : !READY.has(t.id) ? " · soon" : ""}`} data-tip-side="bottom">
                <Icon size={19} aria-hidden /></button>);
          })}
        </div>
        {hint && <p className="hint">{hint}</p>}
        {face && <div className="edit-face">
          <Tool size={14} aria-hidden /><span><b>{face.name}</b>{face.label ? <> of {face.label}</> : null}
            {face.size_m != null && face.kind !== "edge" ? <span className="why mono"> · {metres(face.size_m)}</span> : null}</span></div>}
        {tool === "push_pull" && face && (
          <form className="edit-row-in" onSubmit={(e) => { e.preventDefault(); if (by) void run(pushOp(by)); }}>
            <label>{by >= 0 ? "Out" : "In"} <input type="number" step={5} value={mmIn(by)} aria-label="How far, mm (out is +)"
              onChange={(e) => { const m = Number(e.target.value) / 1000; setBy(m); setCheck(null); viewer()?.preview([]);
                if (pick) viewer()?.pushPreview(face.element, pick.point, face.normal, m); }} /> mm</label>
            <button type="submit" className="btn small" disabled={!by || checking}>Check</button>
          </form>)}
        {tool === "align" && face && target && (
          <div className="edit-row-in">
            <span className="edit-target"><b>{target.name}</b>{target.label ? <> of {target.label}</> : null}</span>
            <label>Gap <input type="number" step={5} min={0} value={mmIn(gap)} aria-label="Gap, mm"
              onChange={(e) => setGap(Number(e.target.value) / 1000)} onBlur={() => target && targetPick && void runAlign(target, targetPick)}
              onKeyDown={(e) => { if (e.key === "Enter" && target && targetPick) void runAlign(target, targetPick); }} /> mm</label>
            <div className="seg" role="group" aria-label="How">
              {(["stretch", "move"] as const).map((h) => (
                <button key={h} type="button" className={how === h ? "on" : ""} disabled={h === "stretch" && !face.allows.includes("push_pull")}
                  onClick={() => { setHow(h); if (target && targetPick) void run(alignOpWith(h)); }}>{h === "stretch" ? "Stretch to it" : "Move to it"}</button>))}
            </div>
          </div>)}
        {tool === "move" && element && (
          <form className="edit-row-in" onSubmit={(e) => { e.preventDefault(); if (delta.some((x) => x)) void run(moveOp(delta)); }}>
            {(["x", "y", "z"] as const).map((axis, i) => (
              <label key={axis}>{axis === "x" ? "East" : axis === "y" ? "North" : "Up"} <input type="number" step={10} value={mmIn(delta[i])} aria-label={`Move ${axis}, mm`}
                onChange={(e) => { const d = [...delta] as [number, number, number]; d[i] = Number(e.target.value) / 1000; setDelta(d); setCheck(null);
                  viewer()?.preview([{ globalIds: [element], deltaM: d }]); }} /></label>))}
            <button type="submit" className="btn small" disabled={!delta.some((x) => x) || checking}>Check</button>
          </form>)}
        {tool === "void" && face && pick && (
          <form className="edit-row-in" onSubmit={(e) => { e.preventDefault(); void run(voidOp()); }}>
            <div className="seg" role="group" aria-label="Shape">
              {(["rect", "round"] as const).map((sh) => <button key={sh} type="button" className={voidShape === sh ? "on" : ""}
                onClick={() => { setVoidShape(sh); setCheck(null); }}>{sh === "rect" ? "Rectangle" : "Round"}</button>)}
            </div>
            <label>{voidShape === "round" ? "Ø" : "W"} <input type="number" step={10} min={5} value={mmIn(voidSize[0])} aria-label={voidShape === "round" ? "Diameter, mm" : "Width, mm"}
              onChange={(e) => { setVoidSize([Number(e.target.value) / 1000, voidSize[1]]); setCheck(null); }} /></label>
            {voidShape === "rect" && <label>H <input type="number" step={10} min={5} value={mmIn(voidSize[1])} aria-label="Height, mm"
              onChange={(e) => { setVoidSize([voidSize[0], Number(e.target.value) / 1000]); setCheck(null); }} /></label>}
            <label className="check-in"><input type="checkbox" checked={recess == null} onChange={(e) => { setRecess(e.target.checked ? null : 0.05); setCheck(null); }} /> Through</label>
            {recess != null && <label>Depth <input type="number" step={5} min={1} value={mmIn(recess)} aria-label="Recess depth, mm"
              onChange={(e) => { setRecess(Number(e.target.value) / 1000); setCheck(null); }} /></label>}
            <button type="submit" className="btn small" disabled={checking}>Check</button>
          </form>)}
        {tool === "cut_by" && face && (
          <form className="edit-row-in" onSubmit={(e) => { e.preventDefault(); if (cutter) void run(cutOp()); }}>
            {cutter && <span className="edit-target">cut round <b>{cutter.label}</b></span>}
            <label>Gap <input type="number" step={5} min={0} value={mmIn(gap)} aria-label="Gap all round, mm"
              onChange={(e) => { setGap(Number(e.target.value) / 1000); setCheck(null); }} /> mm</label>
            <button type="submit" className="btn small" disabled={!cutter || checking}>Check</button>
          </form>)}
        {(checking || check) && (
          <div className={`edit-status ${status?.tone ?? ""}`} role="status">
            {checking ? <><CheckingIcon size={15} aria-hidden /> Checking against the model…</> : status && <span>{status.text}</span>}
          </div>)}
        {check && !check.blocked && check.summary && <p className="edit-summary">{check.summary}</p>}
        {check?.warnings.map((w, i) => <p key={i} className="edit-warn">{w.text}{w.review ? <span className="chip">review: {w.review}</span> : null}</p>)}
        {check && !check.blocked && (
          <div className="edit-actions">
            <button type="button" className={`ebtn btn ${check.clashes ? "danger" : "primary"}`} disabled={keeping || checking} onClick={() => void keep()}
              data-tip={check.clashes ? "Keep it anyway: it is not verified, and its clashes join the list" : "Keep it in the model (checked again first)"}>
              <KeepIcon size={15} aria-hidden /> {keeping ? "Keeping…" : check.clashes ? `Keep with ${check.clashes} clash${check.clashes === 1 ? "" : "es"}` : "Keep"}</button>
            <button type="button" className="btn small ghost" onClick={() => { const v = viewer(); v?.preview([]); setCheck(null); }}>Cancel</button>
          </div>)}
        {showLog && (journal?.entries.length ?? 0) > 0 && (
          <details className="edit-log">
            <summary><LogIcon size={14} aria-hidden /> Edits · {journal!.entries.filter((e) => e.state === "kept").length}</summary>
            <EditPanel journal={journal} busy={busy} csvUrl={csvUrl} clashLabel={clashLabel} onUndo={onUndo} onRedo={onRedo} onUndoTo={onUndoTo} onShow={onShow} />
          </details>)}
      </>}
    </section>
  );

  function alignOpWith(h: "stretch" | "move"): EditOp { return alignOp(gap, h); }
});

function sameNormal(a: number[] | undefined, b: number[] | undefined): boolean {
  return !!a && !!b && a[0] * b[0] + a[1] * b[1] + a[2] * b[2] > 0.99;
}
