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
import { alignDistance, EDIT_TOOLS, faceRef, OFFER, pointDistance, signedMm, SNAP_WORDS, toolForKey, toolState, type EditToolId } from "./viewer/edit";
import type { FacePick, Viewer } from "./viewer/Viewer";

const ICON: Record<EditToolId, LucideIcon> = { push_pull: PushPullIcon, align: AlignIcon, move: MoveIcon, void: VoidIcon,
  cut_by: CutByIcon, split: SplitIcon, remove_section: RemoveSectionIcon, clip: ClipIcon, delete: DeleteIcon };
/** The tools this build makes; the rest say so in the palette. */
export const READY: ReadonlySet<EditToolId> = new Set<EditToolId>(["push_pull", "align", "move", "void", "cut_by", "split", "remove_section", "clip", "delete"]);

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
  /** A hand edit Muse or an agent checked: shown here as if it were checked on this page, with Keep. */
  incoming?: { check: EditCheck; n: number } | null;
  /** The element and face chosen (for chat: "this face"), with the pick on it. */
  onFace?: (f: { element: string; face: string | null; pick?: { point: number[]; normal: number[] } } | null) => void;
}>(function EditTool({ viewer, sceneId, busy, coarse, clash, journal, csvUrl, clashLabel, showLog, onKept, onUndo, onRedo,
  onUndoTo, onShow, onError, onClose, incoming, onFace }, ref) {
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
  /** A face kept across a change of tool (a face the last tool could not take: "Align it"), with a target and an op
   * to check at once ("Clip it flush"). */
  const carry = useRef<{ face: Face; pick: FacePick; target?: Face | null; targetPick?: FacePick | null; then?: EditOp } | null>(null);
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
  useEffect(() => {
    const c = carry.current;
    carry.current = null;
    reset();
    if (c) {
      setFace(c.face); setPick(c.pick); setHow(c.face.allows.includes("push_pull") ? "stretch" : "move");
      if (c.target && c.targetPick) { setTarget(c.target); setTargetPick(c.targetPick); }
      if (c.then) void run(c.then);
    }
  }, [tool, sceneId]);
  useEffect(() => { onFace?.(face ? { element: face.element, face: face.name, pick: pick ? { point: pick.point, normal: pick.normal } : undefined } : null); }, [face, pick]);
  // Muse's (or an agent's) check: its tool, its face, its result and its preview, as if checked here.
  const shown = useRef(0);
  useEffect(() => {
    if (!incoming || shown.current === incoming.n) return;
    const wanted = (EDIT_TOOLS.find((t) => t.id === incoming.check.op.op)?.id ?? tool) as EditToolId;
    if (wanted !== tool) { setTool(wanted); return; }   // the reset runs first, then this again
    shown.current = incoming.n;
    const c = incoming.check, f = c.face as Face | null | undefined;
    if (f) { setFace(f); setPick({ globalId: f.element, point: f.point as [number, number, number], normal: f.normal as [number, number, number] }); }
    setCheck(c);
    const o = c.op as Record<string, unknown>;   // its numbers in the boxes, as if typed here
    if (typeof o.by_m === "number" && c.op.op === "push_pull") setBy(o.by_m);
    if (typeof o.gap_m === "number") setGap(o.gap_m);
    if (Array.isArray(o.delta_m) && c.op.op === "move") setDelta(o.delta_m as [number, number, number]);
    const v = viewer();
    if (v && c.preview?.length) {
      v.showOption({ kind: "edit", moved: c.targets ?? [], deltaM: [0, 0, 0], pieces: c.preview, before: c.before ?? null, worldMeshes: true },
        "after", c.blocked ? "#b8352a" : c.clashes ? "#d98a00" : "#1f9d3a");
    }
  }, [incoming?.n, tool]);

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
        onStart: () => { ++ask.current; setCheck(null); setChecking(false); v.preview([]); },   // a check's drawing goes once
        onMove: (m) => { setBy(m); v.pushPreview(face.element, pick.point, face.normal, m); },
        onEnd: (m) => { if (Math.abs(m) >= 0.0005) void run(pushOp(m)); } });
    } else v.setEditDrag(null);
    return () => v.setEditDrag(null);
  }, [tool, face, pick]);

  const own = () => faceRef(face!, pick ?? { point: face!.point, normal: face!.normal });
  /** The face aimed at: by id, or by the pick on it when only a pick places it. */
  const toFace = (t: Face, tp: FacePick) => {
    if (t.id.startsWith("point:")) return { element: t.element, point: tp.point, snap: t.id.slice(6) };   // a corner or an edge
    const r = faceRef(t, tp);
    return typeof r === "string" ? { element: t.element, face: r } : { element: t.element, ...r };
  };
  const pushOp = (m: number): EditOp => ({ op: "push_pull", element: face!.element, face: own(), by_m: m });
  const alignOp = (t = target!, tp = targetPick!, g = gap, h = how): EditOp => ({ op: "align", element: face!.element, face: own(),
    gap_m: g, how: h, to: toFace(t, tp) });
  const moveOp = (d: number[]): EditOp => ({ op: "move", element: element!, delta_m: d });
  const voidOp = (at = pick!.point): EditOp => ({ op: "void", element: face!.element, face: own(), at, shape: voidShape,
    ...(voidShape === "round" ? { diameter_m: voidSize[0] } : { width_m: voidSize[0], height_m: voidSize[1] }),
    ...(recess != null ? { depth_m: recess } : {}) });
  const cutOp = (c = cutter, g = gap): EditOp => ({ op: "cut_by", element: element!, cutter: c!.globalId, gap_m: g });
  const clipOp = (t = target!, tp = targetPick!, g = gap): EditOp => ({ op: "clip", element: face!.element, gap_m: g, to: toFace(t, tp) });

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

  async function choose(p: FacePick, as: "face" | "target", then?: (f: Face) => void) {
    if (!sceneId) return;
    const n = ++ask.current;
    try {
      const f = await api.editFace(sceneId, p.globalId, p.point, p.normal) as Face;
      if (n !== ask.current) return;
      if (as === "target") {
        if (tool === "clip") {
          setTarget(f); setTargetPick(p);
          if (face) void run(clipOp(f, p));
          return;
        }
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
      // A face this tool cannot take is still chosen: the panel says why and offers the tools it does take.
      setFace(f); setPick(p); setBy(0); setCheck(null);
      setHow(f.allows.includes("push_pull") ? "stretch" : "move");
      then?.(f);
    } catch (e) { if (n === ask.current) onError((e as Error).message); }
  }

  /** Align to that face: at once a preview from the two picks (a stretch or a move), then the server's check. */
  function runAlign(t: Face, tp: FacePick, g = gap, h = how) {
    if (!face || !pick) return;
    const v = viewer(), d = t.id.startsWith("point:") ? pointDistance(pick.point, face.normal, tp.point, g)
      : alignDistance(pick.point, face.normal, tp.point, t.normal, g);
    if (v && d != null) {
      v.preview([]);
      if (h === "stretch" && face.allows.includes("push_pull")) v.pushPreview(face.element, pick.point, face.normal, d);
      else { v.pushPreview(face.element, pick.point, face.normal, null); v.preview([{ globalIds: [face.element], deltaM: face.normal.map((x) => x * d) as [number, number, number] }]); }
    }
    return run(alignOp(t, tp, g, h));
  }

  /** Change tool, keeping the face chosen (and the target, and an op to check at once). */
  function offer(t: EditToolId, then?: EditOp) {
    if (face && pick) carry.current = { face, pick, target, targetPick, then };
    setTool(t);
  }

  /** A snapped corner, edge midpoint or edge point of another element as the align target. */
  function pointTarget(globalId: string, s: { point: [number, number, number]; kind: string }) {
    if (!face || !pick) return;
    const t: Face = { element: globalId, id: `point:${s.kind}`, kind: "other", name: `the ${SNAP_WORDS[s.kind] ?? "point"}`, normal: face.normal,
      point: s.point, size_m: null, allows: [], why_not: null };
    const tp: FacePick = { globalId, point: s.point, normal: face.normal as [number, number, number] };
    setTarget(t); setTargetPick(tp);
    void runAlign(t, tp);
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
      const at = v.snapPoint(ev)?.point ?? p.point;   // a split or a section's end: snapped like a measure
      if (tool === "delete") { void choose(p, "face", (f) => void run({ op: "delete", element: f.element })); return; }
      if (tool === "split") { void choose(p, "face", (f) => void run({ op: "split", element: f.element, at })); return; }
      if (tool === "remove_section") {
        if (from && face && p.globalId === face.element) { const a = from; setFrom(null); void run({ op: "remove_section", element: face.element, from: a, to: at }); }
        else void choose(p, "face", () => { setFrom(at); });
        return;
      }
      if ((tool === "align" || tool === "cut_by" || tool === "clip") && face && toolState(tool, face, READY).ok && p.globalId !== face.element) {
        const sn = tool === "align" ? v.snapPoint(ev) : null;   // a corner or an edge: its point is the target
        if (sn && (sn.kind === "end" || sn.kind === "mid" || sn.kind === "edge")) { pointTarget(p.globalId, sn); return; }
        void choose(p, "target"); return;
      }
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
    if (face && !toolState(tool, face, READY).ok) return `${act} another face, or use one of these`;
    if (tool === "align") return !face ? `${act} the face to move` : !target ? `${act} the face to align it to` : null;
    if (tool === "move") return !element ? `${act} the element to move` : from ? `${act} where it goes` : `Type the move, or ${act.toLowerCase()} where it comes from, then where it goes`;
    if (tool === "push_pull") return !face ? `${act} a face to push or pull` : !check && !checking ? (coarse ? "Type how far" : "Drag the face (Shift: by the mm), or type how far") : null;
    if (tool === "void") return !face ? `${act} the face to cut the opening in` : `It goes where you ${act.toLowerCase()}ed; ${act.toLowerCase()} elsewhere on the face to move it`;
    if (tool === "cut_by") return !face ? `${act} the element to cut` : !cutter ? `${act} the element whose shape cuts it` : null;
    if (tool === "split") return check ? `${act} elsewhere on it to split it there instead` : `${act} the element where it splits`;
    if (tool === "remove_section") return !face || (!from && !check) ? `${act} where the section starts` : from ? `${act} where it ends` : null;
    if (tool === "clip") return !face ? `${act} the end to clip` : !target ? `${act} the face to clip it to (any angle)` : null;
    if (tool === "delete") return !face ? `${act} the element to delete` : null;
    return EDIT_TOOLS.find((t) => t.id === tool)!.hint;
  })();
  const status = check ? checkStatus(check) : null;
  const can = face ? toolState(tool, face, READY) : null;
  const refused = can && !can.ok ? can.why : null;
  /** What the face does take, when this tool cannot: its face tools, then a move. */
  const offers = refused && face ? [...EDIT_TOOLS.filter((t) => t.needs === "face" && READY.has(t.id) && face.allows.includes(t.id)).map((t) => t.id),
    ...(READY.has("move") ? ["move" as EditToolId] : [])] : [];
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
        {face && refused && (
          <div className="edit-offer" role="status">
            <p>{refused}{face.why_not ? `: ${face.why_not}` : ""}.</p>
            {offers.length > 0 && <div className="edit-offer-tools">{offers.map((t) => {
              const Icon = ICON[t];
              return <button key={t} type="button" className="ebtn btn small" onClick={() => offer(t)}><Icon size={14} aria-hidden /> {OFFER[t]}</button>;
            })}</div>}
          </div>)}
        {tool === "push_pull" && face && !refused && (
          <form className="edit-row-in" onSubmit={(e) => { e.preventDefault(); if (by) void run(pushOp(by)); }}>
            <label>{by >= 0 ? "Out" : "In"} <input type="number" step={5} value={mmIn(by)} aria-label="How far, mm (out is +)"
              onChange={(e) => { const m = Number(e.target.value) / 1000; setBy(m); setCheck(null); viewer()?.preview([]);
                if (pick) viewer()?.pushPreview(face.element, pick.point, face.normal, m); }} /> mm</label>
            <button type="submit" className="btn small" disabled={!by || checking}>Check</button>
          </form>)}
        {tool === "align" && face && target && !refused && (
          <div className="edit-row-in">
            <span className="edit-target">{target.id.startsWith("point:") ? "through " : ""}<b>{target.name}</b>{target.label ? <> of {target.label}</> : null}</span>
            <label>Gap <input type="number" step={5} min={0} value={mmIn(gap)} aria-label="Gap, mm"
              onChange={(e) => setGap(Number(e.target.value) / 1000)} onBlur={() => target && targetPick && void runAlign(target, targetPick)}
              onKeyDown={(e) => { if (e.key === "Enter" && target && targetPick) void runAlign(target, targetPick); }} /> mm</label>
            <div className="seg" role="group" aria-label="How">
              {(["stretch", "move"] as const).map((h) => (
                <button key={h} type="button" className={how === h ? "on" : ""} disabled={h === "stretch" && !face.allows.includes("push_pull")}
                  onClick={() => { setHow(h); if (target && targetPick) void runAlign(target, targetPick, gap, h); }}>{h === "stretch" ? "Stretch to it" : "Move to it"}</button>))}
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
        {tool === "void" && face && pick && !refused && (
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
        {tool === "clip" && face && target && !refused && (
          <form className="edit-row-in" onSubmit={(e) => { e.preventDefault(); void run(clipOp()); }}>
            <span className="edit-target">to the <b>{target.name}</b>{target.label ? <> of {target.label}</> : null}</span>
            <label>Gap <input type="number" step={5} min={0} value={mmIn(gap)} aria-label="Gap, mm"
              onChange={(e) => { setGap(Number(e.target.value) / 1000); setCheck(null); }} /> mm</label>
            <button type="submit" className="btn small" disabled={checking}>Check</button>
          </form>)}
        {(checking || check) && (
          <div className={`edit-status ${status?.tone ?? ""}`} role="status">
            {checking ? <><CheckingIcon size={15} aria-hidden /> Checking against the model…</> : status && <span>{status.text}</span>}
          </div>)}
        {check && !check.blocked && check.summary && <p className="edit-summary">{check.summary}</p>}
        {check?.warnings.map((w, i) => <p key={i} className="edit-warn">{w.text}{w.review ? <span className="chip">review: {w.review}</span> : null}</p>)}
        {check?.offer?.op === "clip" && !check.blocked && READY.has("clip") && (
          <div className="edit-offer-tools"><button type="button" className="ebtn btn small" onClick={() => offer("clip", check.offer!)}
            data-tip="Clip its end to that face, so it is flush all along"><ClipIcon size={14} aria-hidden /> Clip it flush</button></div>)}
        {check && !check.blocked && (
          <div className="edit-actions">
            <button type="button" className={`ebtn btn ${check.clashes ? "danger" : "primary"}`} disabled={keeping || checking} onClick={() => void keep()}
              data-tip={check.clashes ? "Keep it anyway: it is not verified, and its clashes join the list" : "Keep it in the model (checked again first)"}>
              {tool === "delete" ? <DeleteIcon size={15} aria-hidden /> : <KeepIcon size={15} aria-hidden />}
              {" "}{keeping ? "Keeping…" : check.clashes ? `Keep with ${check.clashes} clash${check.clashes === 1 ? "" : "es"}` : tool === "delete" ? "Delete it" : "Keep"}</button>
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

});

function sameNormal(a: number[] | undefined, b: number[] | undefined): boolean {
  return !!a && !!b && a[0] * b[0] + a[1] * b[1] + a[2] * b[2] > 0.99;
}
