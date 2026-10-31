import { toCreasedNormals } from "three/examples/jsm/utils/BufferGeometryUtils.js";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { loadIfc, type LoadedElement, type LoadedModel } from "./ifcLoader";
import { patchModel, ROOM, type ElementMesh } from "./patch";
import { ViewCube } from "./cube";
import { CAP_LAYER, CUT, DrawingStyle, DrawingView, farBehind, PAPER, targets, toIfc } from "./drawing";
import { annotate, type Handle } from "./annotate";
import type { RuleView } from "../filters";
import { candidatesOf, clipSegment, cutSegments, measureText, mergeRuns, pickSnap, type Candidates, type Measurement, type Segment,
  type SnapKind } from "./measure";
import { CameraHistory, defaultKinds, facingFor, levelsOrModel, paneRects, planThrough, sectionFrame, sectionThrough, shownBy,
  viewTitle, type Datums, type DrawingSpec, type Filters, type Layout, type Level, type Pose, type Rect, type Temporary, type ViewSpec, type DrawingsShow } from "./views";

const RED = new THREE.Color("#d0342c");
const GREEN = new THREE.Color("#1f9d3a");
const PURPLE = new THREE.Color("#8e44ad");  // one element on both sides: a port and its own valve, two parts of a door
const GREY = new THREE.Color("#b9c2cc");
const GHOST = new THREE.Color("#9aa7b4");

// The server works in IFC axes (metres, Z up); web-ifc and three.js are Y up.
export function serverDeltaToViewer([dx, dy, dz]: number[]): THREE.Vector3 {
  return new THREE.Vector3(dx, dz, -dy);
}
export const serverPointToViewer = serverDeltaToViewer;

type Found = { model: LoadedModel; el: LoadedElement };
/** A model's batches: its solid mesh, and its see-through one when it has see-through elements. */
const batches = (m: LoadedModel): THREE.BatchedMesh[] => (m.glass ? [m.mesh, m.glass] : [m.mesh]);
const disposeBatches = (m: LoadedModel) => { for (const batch of batches(m)) batch.dispose(); };
/** Triangles from the server: flat xyz (metres, IFC Z up) and indices. */
export type Mesh = { verts: number[]; faces: number[]; global_id?: string };
/** The connection highlight draws at most this many elements, outlining the first LINK_EDGES of each kind. */
const LINK_MAX = 150, LINK_EDGES = 40;
/** A fix's piece as Show it built frames it: its element (a kept piece), the element its run came from and its part
 * (a combined fix's: "moved", "end" or "middle"). */
export type BuiltPiece = Mesh & { global_id?: string; origin?: string; part?: string };
/** Show it built's passes (Viewer.captureBuilt): PNG data URLs of one square view, and what the cutaway took away. */
export interface BuiltPasses {
  look: string; ids: string; normals: string; side: number;
  cut: string[];        // elements taken away for the view (GlobalIds)
  sectioned: string[];  // slabs, roofs or ceilings the section cuts at instead
  shown: number;        // the share of the fix the view shows
}
/** A fix to preview: a move, or any other kind's pieces as world meshes. `before`: what it changes, as it is now. */
export type OptionShape = { kind: string; moved: string[]; deltaM: number[]; pieces: Mesh[] | null; before: Mesh[] | null; worldMeshes?: boolean };

/**
 * How the model is drawn around the elements in focus (a clash pair, plus pieces an accepted fix added):
 * - shaded: every element in its own colour, focus in red/green
 * - xray: everything else see-through, so a clash inside a building is visible from outside
 * - context: only elements near the focus, see-through; the rest hidden (images B of the clash recipe)
 * - isolate: only the focus
 */
export type ViewMode = "shaded" | "xray" | "context" | "isolate";
export type Preset = "top" | "front" | "right" | "iso";
/** How the 3D view draws what is solid (docs/views.md, "Visual styles"), apart from the mode round the focus:
 * - shaded: lit, each element in its own colour
 * - consistent: unlit, own colours
 * - xray: everything see-through (with nothing in focus too), the pair and the selection solid
 * - edges, hidden: Shaded with dark outlines, and paper with lines (the drawing views' passes in 3D) */
export type VisualStyle = "shaded" | "consistent" | "edges" | "hidden" | "xray";
export type Projection = "perspective" | "orthographic";
/** The element selected by a single click: blue in every view, a colour no other role uses. */
export const SELECTED = "#2f8fdf";

/** Side A (red), side B (green), or both at once (purple): the model has one element where the report has two. */
export type Side = "a" | "b" | "ab";

export interface Focus {
  a: string | null;
  b: string | null;
  group?: Record<string, Side>;  // more elements drawn as part of side A or B
}

/** A picked point on the model: the element and where on it (three.js world coordinates). */
export interface Pick { globalId: string; point: THREE.Vector3 }

/** One pane of the layout: its view, its element over the canvas, where it sits (stage CSS pixels), and whether a
 * clash may move it. A drawing pane has its DrawingView. */
export interface Pane { spec: ViewSpec; el: HTMLDivElement; rect: Rect; pinned: boolean; view: DrawingView | null;
  /** Its own number, kept while it lives (a measurement taken in it refers to it). */
  key: number;
  /** What its annotation layer was last drawn for, and the marks on it a user can drag. */
  annotated?: string; handles?: Handle[]; composed?: string }

/** Classes that stay where they are (the server's FIXED_CLASSES): a clash's section runs along the other side. */
const FIXED = /^Ifc(Beam|Column|Slab|Wall|WallStandardCase|Footing|Member|Plate)$/;

export class Viewer {
  readonly renderer: THREE.WebGLRenderer;
  readonly scene = new THREE.Scene();
  readonly camera = new THREE.PerspectiveCamera(45, 1, 0.05, 5000);
  readonly controls: OrbitControls;
  /** One batched mesh per federated file (structure, MEP, architecture…). */
  models: LoadedModel[] = [];
  names: string[] = [];
  mode: ViewMode = "shaded";
  style: VisualStyle = "shaded";
  projection: Projection = "perspective";
  /** The orthographic camera follows the perspective one (same view, size from its distance), so the controls,
   * framing and captures keep working on one camera. */
  readonly ortho = new THREE.OrthographicCamera(-1, 1, 1, -1, 0.01, 5000);
  /** With a focus in Shaded, the rest in grey (today's look) or in its own colours. */
  greyContext = true;
  /** Called when something the page shows about the views changes (history, temporary hides, projection…). */
  onChange: (() => void) | null = null;
  /** The 3D view's element over the canvas: its controls, the view cube and its labels live here. */
  readonly pane3d: HTMLDivElement;

  private raycaster = new THREE.Raycaster();
  private resize = new ResizeObserver(() => this.fit());
  private solid = new THREE.MeshStandardMaterial({ metalness: 0, roughness: 0.85, side: THREE.DoubleSide });
  private ghost = new THREE.MeshStandardMaterial({ metalness: 0, roughness: 1, side: THREE.DoubleSide, transparent: true,
    opacity: 0.12, depthWrite: false });
  /** See-through elements (safety zones, mesh guards): per-element opacity from the IFC style, drawn without depth. */
  private glass = new THREE.MeshStandardMaterial({ metalness: 0, roughness: 0.85, side: THREE.DoubleSide, transparent: true,
    depthWrite: false });
  private clipping: THREE.Plane[] = [];
  private focus: Focus = { a: null, b: null };
  /** Elements in focus are drawn as their own meshes over shared GPU buffers, so any mode can keep them solid. */
  private focusLayer = new THREE.Group();
  private focusMeshes = new Map<string, THREE.Mesh>();
  private focusGeometry = new Map<string, THREE.BufferGeometry>();
  private focusMaterials = { a: this.focusMaterial(RED), b: this.focusMaterial(GREEN), ab: this.focusMaterial(PURPLE) };
  /** The same for a see-through element in focus (a zone): tinted, still see-through. */
  private focusGlass = { a: this.focusMaterial(RED, 0.35), b: this.focusMaterial(GREEN, 0.35), ab: this.focusMaterial(PURPLE, 0.35) };
  /** Outlines of the focus elements drawn through everything, so a clash buried in a wall or slab still shows. */
  private edgeMaterials = {
    a: new THREE.LineBasicMaterial({ color: "#ff5a5a", depthTest: false, transparent: true, opacity: 0.9 }),
    b: new THREE.LineBasicMaterial({ color: "#5dff8a", depthTest: false, transparent: true, opacity: 0.9 }),
    ab: new THREE.LineBasicMaterial({ color: "#d39bff", depthTest: false, transparent: true, opacity: 0.9 }),
  };
  private edges = new Map<string, THREE.LineSegments>();
  private edgeGeometry = new Map<string, THREE.EdgesGeometry>();
  showEdges = true;
  /** Elements a candidate fix ran into, while the agent shows its work. */
  private hitLayer = new THREE.Group();
  /** The connection highlight: linked elements lit by kind (setLinks), over the model, never in captured pictures. */
  private linkLayer = new THREE.Group();
  private linkMaterials = new Map<string, { mesh: THREE.MeshStandardMaterial; edges: THREE.LineBasicMaterial }>();
  private hitMaterial = new THREE.MeshStandardMaterial({ color: "#e040fb", emissive: "#5c0a6b", roughness: 0.5,
    side: THREE.DoubleSide, transparent: true, opacity: 0.9 });
  private hitEdges = new THREE.LineBasicMaterial({ color: "#f48fff", depthTest: false, transparent: true, opacity: 0.95 });
  /** Called when the user moves the camera (drag, wheel, touch) or clicks the model: the agent hands over the view. */
  onUserCamera: (() => void) | null = null;
  /** New pieces of a previewed edit and ghosts of what it replaces, until the preview changes. */
  private overlay = new THREE.Group();
  private hidden = new Set<string>();       // replaced by a previewed edit
  private hiddenModels = new Set<number>();
  private moved = new Map<string, THREE.Matrix4>();  // previewed moves: GlobalId → offset matrix
  private marker = new THREE.Group();
  private markerLabel: HTMLDivElement;
  private sectionBox: THREE.Box3 | null = null;
  private sectionHelper: THREE.Box3Helper | null = null;
  private flight: { from: [THREE.Vector3, THREE.Vector3]; to: [THREE.Vector3, THREE.Vector3]; t0: number; ms: number } | null = null;
  /** Unlit own colours (Consistent colours), and everything see-through with its own colours (X-ray, nothing in focus). */
  private consistent = new THREE.MeshBasicMaterial({ side: THREE.DoubleSide });
  private xrayAll = new THREE.MeshStandardMaterial({ metalness: 0, roughness: 1, side: THREE.DoubleSide, transparent: true,
    opacity: 0.22, depthWrite: false });
  /** The selected element, drawn over the model in blue with an outline through everything. */
  private selection: string | null = null;
  private selectionLayer = new THREE.Group();
  private selectionMaterial = new THREE.MeshStandardMaterial({ color: SELECTED, emissive: new THREE.Color(SELECTED).multiplyScalar(0.3),
    roughness: 0.5, transparent: true, opacity: 0.75, polygonOffset: true, polygonOffsetFactor: -1, polygonOffsetUnits: -1,
    side: THREE.DoubleSide });
  private selectionEdges = new THREE.LineBasicMaterial({ color: "#7cc0ff", depthTest: false, transparent: true, opacity: 0.95 });
  /** Element facts the filters read (IFC class, storey), visibility filters and the temporary hide / isolate. */
  private info = new Map<string, { cls?: string; level?: string }>();
  private filters: Filters = { classes: [], levels: [] };
  private temp: Temporary = { hidden: [], isolated: null };
  /** The filters' rules (docs/filters.md): what they hide, the only ones they show, their colours (filters.ts). */
  private rules: RuleView | null = null;
  private paints = new Map<string, THREE.Color>();
  private scratch = new THREE.Vector4();
  private linkGroups: { color: string; ids: string[] }[] = [];
  /** While a picture is taken: the user's style, filters, hides and selection are lifted (they never reach a picture). */
  private lifted = false;
  private history = new CameraHistory();
  private homePose: Pose | null = null;
  private cube: ViewCube;
  /** Grips on the section box's faces, to drag one in or out. */
  private grips = new THREE.Group();
  private grip: { axis: "x" | "y" | "z"; side: "min" | "max"; box: THREE.Box3; x: number; y: number; perPx: THREE.Vector2; ppm: number } | null = null;
  private swallowClick = false;
  /** The layout (docs/views.md, "Views and layouts"): panes, the split between them, a pane maximised. */
  layout: Layout = "single";
  panes: Pane[] = [];
  private split = { x: 0.5, y: 0.5 };
  private maximised: number | null = null;
  /** Drawing views hide what Context / Isolate hide (true), or show the whole model (false, the default). */
  /** What the drawing views show: what the filters leave, what the 3D view shows, or the whole model. */
  drawings: DrawingsShow = "filtered";
  /** Levels (sorted) and grids from the server, and a counter every change to what is drawn bumps. */
  datums: Datums | null = null;
  levels: Level[] = [];
  private version = 0;
  private drawVis: { el: LoadedElement; v3d: boolean; vDraw: boolean }[] = [];
  /** The drawing style's materials and passes (fills, stencil caps, linework), shared by every drawing. */
  private drawStyle = new DrawingStyle();
  /** The 3D view's targets for Shaded with edges and Hidden line. */
  private styled: [THREE.WebGLRenderTarget, THREE.WebGLRenderTarget] | null = null;

  constructor(private host: HTMLElement) {
    this.renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.localClippingEnabled = true;
    host.appendChild(this.renderer.domElement);
    // The graphics card can take the context away (short of memory, a driver reset). three.js takes it back when the
    // browser restores it; every pane is then drawn again, and meanwhile the stage says what happened.
    this.renderer.domElement.addEventListener("webglcontextlost", () => this.contextLost(true));
    this.renderer.domElement.addEventListener("webglcontextrestored", () => this.contextLost(false));
    this.pane3d = document.createElement("div");
    this.pane3d.className = "view-pane view-3d";
    this.pane3d.hidden = true;   // until models are open: the start page and the project's own page sit there
    host.appendChild(this.pane3d);
    this.controls = new OrbitControls(this.camera, this.pane3d);
    this.controls.enableDamping = true;
    this.controls.zoomToCursor = true;  // the wheel zooms to what is under the pointer, not the orbit centre
    this.controls.addEventListener("start", () => { this.flight = null; this.onUserCamera?.(); });
    // Before the controls see the press: a section box grip takes it, else orbiting turns about what is under it.
    this.pane3d.addEventListener("pointerdown", (e) => this.press(e), { capture: true });
    this.pane3d.addEventListener("pointermove", (e) => { if (this.spin) this.spinMove(e); else this.dragGrip(e); });
    this.pane3d.addEventListener("pointerup", (e) => this.release(e));
    this.pane3d.addEventListener("pointercancel", (e) => this.release(e));
    this.pane3d.addEventListener("click", (e) => { if (this.swallowClick) { this.swallowClick = false; e.stopPropagation(); } }, { capture: true });
    this.controls.autoRotateSpeed = 0.6;
    this.cube = new ViewCube((dir) => this.lookFrom(dir), (dx, dy) => this.turn(dx, dy), () => this.home());
    this.pane3d.appendChild(this.cube.el);
    this.panes = [{ spec: { kind: "3d" }, el: this.pane3d, rect: { x: 0, y: 0, w: 1, h: 1 }, pinned: false, view: null, key: 0 }];
    this.scene.background = new THREE.Color("#dfe6ee");
    this.scene.add(new THREE.HemisphereLight(0xffffff, 0x8899aa, 1.6));
    const sun = new THREE.DirectionalLight(0xffffff, 1.4);
    sun.position.set(30, 60, 20);
    this.scene.add(sun);
    this.scene.add(this.focusLayer, this.overlay, this.hitLayer, this.linkLayer, this.selectionLayer, this.marker, this.grips);
    for (const m of [this.solid, this.ghost, this.glass, this.hitMaterial, this.consistent, this.xrayAll, this.selectionMaterial]) m.clippingPlanes = this.clipping;
    // Shaded with edges and Hidden line draw through the drawings' materials: the section box cuts them too (a drawing
    // view empties `clipping` while it draws, so it never does there).
    const st = this.drawStyle;
    for (const m of [...st.fills, st.glass, ...Object.values(st.side), st.selected, st.normals]) m.clippingPlanes = this.clipping;
    this.buildGrips();
    this.camera.layers.enable(1);
    this.ortho.layers.enable(1);
    this.marker.layers.set(1);
    this.markerLabel = this.label("marker-label");
    this.measureCanvas = document.createElement("canvas");
    this.measureCanvas.className = "measure-layer";
    host.appendChild(this.measureCanvas);
    this.buildMarker();
    this.resize.observe(host);
    this.fit();
    this.renderer.setAnimationLoop(() => this.frameTick());
  }

  // ---------------------------------------------------------------- models

  async load(files: Uint8Array[], names: string[] = [], isCurrent: () => boolean = () => true,
    onDrawn?: (count: number, elements: number) => void) {
    // Parse the entire replacement off-screen. A failed or superseded load leaves the usable scene intact.
    const staged: LoadedModel[] = [];
    try {
      for (const bytes of files) {
        staged.push(await loadIfc(bytes));
        if (!isCurrent()) { for (const m of staged) disposeBatches(m); return; }
        if (onDrawn) {
          onDrawn(staged.length, staged.reduce((n, m) => n + m.stats.elements, 0));
          // Parsing a file holds the thread: let the page paint the count before the next one starts.
          await new Promise((resolve) => setTimeout(resolve, 0));
          if (!isCurrent()) { for (const m of staged) disposeBatches(m); return; }
        }
      }
    } catch (e) { for (const m of staged) disposeBatches(m); throw e; }
    if (!isCurrent()) { for (const m of staged) disposeBatches(m); return; }
    this.preview([]);
    this.clearFocusCache();
    for (const m of this.models) { this.scene.remove(...batches(m)); disposeBatches(m); }
    this.models = staged.map((m) => this.adopt(m));
    this.pane3d.hidden = !this.models.length;
    for (const pane of this.panes) pane.el.hidden = !this.models.length;
    this.sceneChanged();
    this.names = names;
    this.hiddenModels.clear();
    this.lastClash = null;
    this.measures = []; this.draft = null; this.hover = null; this.measureStamp++;   // they were on the other models
    this.configureViews(true);
    this.applyMode();
    this.fitAll(false);
    this.history.clear();   // after the fit: Back never flies to the camera of the models before
    return {
      elements: this.models.reduce((n, m) => n + m.stats.elements, 0),
      triangles: this.models.reduce((n, m) => n + m.stats.triangles, 0),
      parseMs: this.models.reduce((n, m) => n + m.stats.parseMs, 0),
    };
  }

  /** Swap one federated file for a new version of it (after an edit was accepted on the server). */
  async replace(index: number, bytes: Uint8Array, isCurrent: () => boolean = () => true) {
    const old = this.models[index];
    const loaded = await loadIfc(bytes);
    // IFC parsing yields; a scene replaced during that work must never receive the old file.
    if (!isCurrent()) { disposeBatches(loaded); return; }
    const m = this.adopt(loaded);
    if (old) { this.scene.remove(...batches(old)); disposeBatches(old); }
    this.models[index] = m;
    this.sceneChanged();
    this.clearFocusCache();
    this.applyMode();
  }

  /** Swap a kept fix's changed and new elements into the models in place (viewer/patch.ts), instead of reloading the
   * files it changed. `origin` maps a new piece to the element it was split from, for its colour when it has none.
   * False when it cannot (a mesh for a file that is not loaded, or a batch refused it): reload the files then. */
  patch(meshes: ElementMesh[], origin: Map<string, string> = new Map()): boolean {
    const byFile = new Map<number, ElementMesh[]>();
    for (const m of meshes) {
      if (m.file == null || !this.models[m.file]) return false;
      byFile.set(m.file, [...(byFile.get(m.file) ?? []), m]);
    }
    try {
      for (const [index, list] of byFile) {
        const model = this.models[index];
        patchModel(model, list, () => {
          const glass = new THREE.BatchedMesh(ROOM.instances, ROOM.vertices, ROOM.indices, this.glass);
          this.scene.add(glass);
          return glass;
        }, (gid) => {
          const from = model.byGlobalId.get(origin.get(gid) ?? "");
          return from ? { color: from.baseColor, alpha: from.baseAlpha } : null;
        });
      }
    } catch (e) {
      console.warn("Patching the model failed; reloading the files instead.", e);
      return false;
    }
    this.sceneChanged();
    this.clearFocusCache();  // focus geometry shares the batches' buffers, which may have moved or grown
    this.applyMode();
    return true;
  }

  /** The models changed (loaded, replaced, patched): what is measured over them is measured again. */
  private sceneChanged() { this.sceneSize = 0; this.boxCache = null; this.countsCache = null; this.snapCache.clear(); }
  private boxCache: THREE.Box3 | null = null;
  private countsCache: ReturnType<Viewer["infoCounts"]> | null = null;

  /** The diagonal of everything loaded, metres (cached until the models change). */
  private sceneSize = 0;
  private sceneDiag(): number {
    if (!this.sceneSize) {
      const box = new THREE.Box3();
      for (const m of this.models) for (const b of batches(m)) { b.computeBoundingBox(); if (b.boundingBox) box.union(b.boundingBox); }
      this.sceneSize = box.isEmpty() ? 100 : Math.max(box.getSize(new THREE.Vector3()).length(), 1e-3);
    }
    return this.sceneSize;
  }

  /** A length tuned on buildings (`metres`), never more than `share` of the whole scene: a 100 mm machine part
   * gets millimetres where a building gets half a metre, and buildings keep exactly what they had. */
  private reach(metres: number, share: number): number {
    return Math.min(metres, this.sceneDiag() * share);
  }

  setModelVisible(index: number, visible: boolean) {
    if (visible) this.hiddenModels.delete(index); else this.hiddenModels.add(index);
    this.boxCache = null;
    this.applyMode();
  }

  private adopt(m: LoadedModel): LoadedModel {
    m.mesh.layers.enable(CAP_LAYER.rest);   // a drawing's cut fills what this batch's solids cross
    m.mesh.material = this.solid;
    if (m.glass) m.glass.material = this.glass;
    this.scene.add(...batches(m));
    return m;
  }

  private find(globalId: string): Found | null {
    for (const model of this.models) {
      const el = model.byGlobalId.get(globalId);
      if (el) return { model, el };
    }
    return null;
  }

  has(globalId: string) { return !!this.find(globalId); }

  // ---------------------------------------------------------------- focus and view modes

  /** Elements in focus (red A, green B, plus their groups); the view mode decides how the rest is drawn. */
  setFocus(focus: Focus) {
    this.focus = { ...focus, group: { ...(focus.group ?? {}) } };
    this.applyMode();
  }

  setMode(mode: ViewMode) {
    this.mode = mode;
    this.applyMode();
  }

  private focusSide(gid: string): Side | undefined {
    const g = this.focus.group?.[gid];
    const inA = gid === this.focus.a || g === "a" || g === "ab";
    const inB = gid === this.focus.b || g === "b" || g === "ab";
    return inA && inB ? "ab" : inA ? "a" : inB ? "b" : undefined;
  }

  private focusIds(): string[] {
    return [this.focus.a, this.focus.b, ...Object.keys(this.focus.group ?? {})].filter((g): g is string => !!g);
  }

  /** What the mode works round: the clash pair (and its group), or, for Context and Isolate with no pair, the selected
   * element (isolate one element without making it side A). */
  private aroundIds(focus: string[]): string[] {
    if (focus.length || this.lifted) return focus;
    return this.selection && (this.mode === "context" || this.mode === "isolate") && this.has(this.selection) ? [this.selection] : [];
  }

  /** Re-draw everything for the current mode, style, focus, moves, filters and hidden elements. */
  private applyMode() {
    this.version++;
    this.drawVis = [];
    const ids = this.focusIds().filter((g) => !this.hidden.has(g));
    const around = this.aroundIds(ids);
    const hasFocus = around.length > 0;
    const near = this.mode === "context" && hasFocus ? this.nearFocus(around) : null;
    const keep = new Set(around);
    const ghostly = hasFocus && (this.mode === "xray" || this.mode === "context");
    const style = this.lifted ? "shaded" : this.style;
    const ghostAll = !ghostly && style === "xray";   // X-ray as a style: everything see-through, in its own colours
    const shown = this.lifted ? null : this.filterTest();
    const solid = style === "consistent" ? this.consistent : this.solid;
    // The filters' colours, and grey for the rest when asked; never in a captured picture.
    const paint = this.lifted ? null : this.rules?.paint ?? null;
    const greyRest = !!paint && !!this.rules?.greyRest;
    this.models.forEach((model, mi) => {
      model.mesh.visible = !this.hiddenModels.has(mi);
      model.mesh.material = ghostly ? this.ghost : ghostAll ? this.xrayAll : solid;
      if (model.glass) {
        model.glass.visible = model.mesh.visible;
        model.glass.material = ghostly ? this.ghost : this.glass;
      }
      for (const el of model.byGlobalId.values()) {
        const inFocus = !!this.focusSide(el.globalId);
        const raw = !inFocus && !this.hidden.has(el.globalId);  // focus elements are drawn by the focus layer
        const base = raw && shown ? shown(el.globalId) : raw;
        let visible = base;
        if (visible && hasFocus && this.mode === "isolate") visible = keep.has(el.globalId);
        if (visible && near) visible = near.has(el.globalId);
        const vDraw = this.drawings === "follow" ? visible : this.drawings === "whole" ? raw : base;
        if (visible !== vDraw && this.panes.length > 1) this.drawVis.push({ el, v3d: visible, vDraw });
        el.mesh.setVisibleAt(el.instanceId, visible);
        const p = paint?.get(el.globalId);
        const c = p ? this.paintColour(p) : ghostly ? GHOST
          : (hasFocus && this.mode === "shaded" && this.greyContext) || greyRest ? GREY : el.baseColor;
        el.mesh.setColorAt(el.instanceId, this.scratch.set(c.r, c.g, c.b, ghostly ? 1 : el.baseAlpha));
        el.mesh.setMatrixAt(el.instanceId, this.matrixOf(el));
      }
    });
    this.drawFocus(ids);
    this.drawSelection();
    if (this.linkGroups.length) this.drawLinks();
  }

  /** The filters' and temporary hides' test for an element, or null when none is on: the temporary hide and isolate,
   * the quick class and level checkboxes, then the filters' rules (docs/filters.md, "What wins"). */
  private filterTest(): ((gid: string) => boolean) | null {
    const f = this.filters, t = this.temp, r = this.rules;
    const ruled = !!(r?.hide?.size || r?.only);
    if (!f.classes.length && !f.levels.length && !t.hidden.length && !t.isolated && !ruled) return null;
    const classes = new Set(f.classes), levels = new Set(f.levels), hidden = new Set(t.hidden);
    const isolated = t.isolated ? new Set(t.isolated) : null;
    return (gid) => {
      const i = this.info.get(gid);
      if (!shownBy(gid, i?.cls, i?.level, f, t, classes, levels, hidden, isolated)) return false;
      if (r?.hide?.has(gid)) return false;
      return !r?.only || r.only.has(gid);
    };
  }

  /** Whether the filters and the temporary hide leave an element on screen (its model shown too). */
  isShown(gid: string): boolean {
    const f = this.find(gid);
    if (!f || this.hiddenModels.has(this.models.indexOf(f.model))) return false;
    return this.lifted ? true : this.filterTest()?.(gid) ?? true;
  }

  /** The filters' rules (filters.ts `evaluate`): hidden, the only ones shown, colours. Null: none. */
  setRules(v: RuleView | null) {
    this.rules = v && (v.hide?.size || v.only || v.paint?.size) ? v : null;
    this.applyMode();
    this.onChange?.();
  }

  private paintColour(hex: string): THREE.Color {
    let c = this.paints.get(hex);
    if (!c) { c = new THREE.Color(hex); this.paints.set(hex, c); }
    return c;
  }

  // ---------------------------------------------------------------- style, selection, visibility

  setStyle(style: VisualStyle) { this.style = style; this.applyMode(); this.onChange?.(); }

  setGreyContext(on: boolean) { this.greyContext = on; this.applyMode(); }

  /** Element facts for the filters: IFC class and storey name, by GlobalId. */
  setInfo(classes: Record<string, string> | null, storeys: Record<string, string> | null) {
    if (classes) this.infoClasses = classes;
    if (storeys) this.infoStoreys = storeys;
    this.info = new Map();
    for (const [g, c] of Object.entries(this.infoClasses)) this.info.set(g, { cls: c });
    for (const [g, l] of Object.entries(this.infoStoreys)) this.info.set(g, { ...this.info.get(g), level: l });
    this.countsCache = null;
    this.applyMode();
  }
  private infoClasses: Record<string, string> = {};
  private infoStoreys: Record<string, string> = {};

  /** Classes and levels hidden (viewing only). */
  setFilters(f: Filters) { this.filters = { classes: [...f.classes], levels: [...f.levels] }; this.applyMode(); }

  /** Hide elements for now, or isolate them (null: none isolated). */
  setTemporary(t: Temporary) {
    this.temp = { hidden: [...t.hidden], isolated: t.isolated ? [...t.isolated] : null };
    this.applyMode();
    this.onChange?.();
  }
  get temporary(): Temporary { return this.temp; }

  /** The element picked by a single click (null: none). Draws it in blue; Context and Isolate work round it when
   * there is no clash pair. */
  setSelection(gid: string | null) {
    if (gid === this.selection) return;
    this.selection = gid;
    if (this.mode === "context" || this.mode === "isolate") this.applyMode(); else this.drawSelection();
  }

  private drawSelection() {
    this.version++;
    this.selectionLayer.clear();
    const gid = this.selection;
    const f = gid && !this.lifted ? this.find(gid) : null;
    if (!f || this.hidden.has(gid!) || this.hiddenModels.has(this.models.indexOf(f.model)) || !this.isShown(gid!)) return;
    const mesh = new THREE.Mesh(this.geometryOf(f), this.selectionMaterial);
    const line = new THREE.LineSegments(this.edgeGeometryOf(gid!, f), this.selectionEdges);
    for (const o of [mesh, line]) {
      o.matrixAutoUpdate = false;
      o.matrix.copy(this.matrixOf(f.el));
      o.frustumCulled = false;
      o.renderOrder = 8;
    }
    line.layers.set(1);   // the outline through everything is the 3D view's; a drawing shows the blue shape
    this.selectionLayer.add(mesh, line);
  }

  /** Every element's class and storey known to the filters, with counts (for the Visibility menu). */
  infoCounts(): { classes: [string, number][]; levels: [string, number][] } {
    if (this.countsCache) return this.countsCache;
    const classes = new Map<string, number>(), levels = new Map<string, number>();
    for (const m of this.models) for (const g of m.byGlobalId.keys()) {
      const i = this.info.get(g);
      if (i?.cls) classes.set(i.cls, (classes.get(i.cls) ?? 0) + 1);
      if (i?.level) levels.set(i.level, (levels.get(i.level) ?? 0) + 1);
    }
    return this.countsCache = { classes: [...classes].sort((a, b) => b[1] - a[1]), levels: [...levels] };
  }

  /** Elements of a class among the loaded ones (to hide or isolate a class). */
  ofClass(cls: string): string[] {
    const out: string[] = [];
    for (const m of this.models) for (const g of m.byGlobalId.keys()) if (this.info.get(g)?.cls === cls) out.push(g);
    return out;
  }

  private matrixOf(el: LoadedElement): THREE.Matrix4 {
    const offset = this.moved.get(el.globalId);
    return offset ? el.baseMatrix.clone().premultiply(offset) : el.baseMatrix;
  }

  private drawFocus(ids: string[]) {
    this.focusLayer.clear();
    for (const gid of ids) {
      const f = this.find(gid);
      const side = this.focusSide(gid);
      if (!f || !side || this.hiddenModels.has(this.models.indexOf(f.model))) continue;
      const material = (f.el.baseAlpha < 1 ? this.focusGlass : this.focusMaterials)[side];
      let mesh = this.focusMeshes.get(gid);
      if (!mesh) {
        mesh = new THREE.Mesh(this.geometryOf(f), material);
        mesh.matrixAutoUpdate = false;
        mesh.frustumCulled = false;
        mesh.userData.globalId = gid;
        this.focusMeshes.set(gid, mesh);
      }
      mesh.material = material;
      mesh.userData.side = side;
      mesh.layers.set(0);
      if (f.el.baseAlpha >= 1) mesh.layers.enable(CAP_LAYER[side]);
      mesh.matrix.copy(this.matrixOf(f.el));
      this.focusLayer.add(mesh);
      if (this.showEdges) {
        const line = this.edgesOf(gid, f, side);
        line.matrix.copy(mesh.matrix);
        this.focusLayer.add(line);
      }
    }
  }

  /** One element's triangles as a view over its model's batched buffers: no copy, already on the GPU. */
  private geometryOf({ model, el }: Found): THREE.BufferGeometry {
    const key = `${this.models.indexOf(model)}:${el.globalId}`;
    let g = this.focusGeometry.get(key);
    if (!g) {
      const src = el.mesh.geometry;
      const range = el.mesh.getGeometryRangeAt(el.mesh.getGeometryIdAt(el.instanceId))!;
      g = new THREE.BufferGeometry();
      g.setAttribute("position", src.getAttribute("position"));
      g.setAttribute("normal", src.getAttribute("normal"));
      g.setIndex(src.getIndex());
      g.setDrawRange(range.start, range.count);
      this.focusGeometry.set(key, g);
    }
    return g;
  }

  private edgesOf(gid: string, f: Found, side: Side): THREE.LineSegments {
    let line = this.edges.get(gid);
    if (!line) {
      line = new THREE.LineSegments(this.edgeGeometryOf(gid, f), this.edgeMaterials[side]);
      line.matrixAutoUpdate = false;
      line.frustumCulled = false;
      line.renderOrder = 9;
      line.layers.set(1);   // through everything: the 3D view's way to show a buried pair
      this.edges.set(gid, line);
    }
    line.material = this.edgeMaterials[side];
    return line;
  }

  private edgeGeometryOf(gid: string, f: Found): THREE.EdgesGeometry {
    let edges = this.edgeGeometry.get(gid);
    if (!edges) {
      // EdgesGeometry needs a geometry of its own: copy just this element's triangles out of the batch.
      const src = this.geometryOf(f);
      const index = src.getIndex()!;
      const pos = src.getAttribute("position");
      const { start, count } = src.drawRange;
      const tri = new Float32Array(count * 3);
      for (let i = 0; i < count; i++) {
        const v = index.getX(start + i);
        tri[i * 3] = pos.getX(v); tri[i * 3 + 1] = pos.getY(v); tri[i * 3 + 2] = pos.getZ(v);
      }
      const g = new THREE.BufferGeometry();
      g.setAttribute("position", new THREE.BufferAttribute(tri, 3));
      edges = new THREE.EdgesGeometry(g, 25);
      g.dispose();
      this.edgeGeometry.set(gid, edges);
    }
    return edges;
  }

  /** Light up what a candidate fix ran into (magenta, outlined through everything); [] clears it. */
  setHits(ids: string[]) {
    this.version++;
    this.hitLayer.clear();
    for (const gid of ids) {
      const f = this.find(gid);
      if (!f || this.hiddenModels.has(this.models.indexOf(f.model))) continue;
      const mesh = new THREE.Mesh(this.geometryOf(f), this.hitMaterial);
      const line = new THREE.LineSegments(this.edgeGeometryOf(gid, f), this.hitEdges);
      line.layers.set(1);
      for (const o of [mesh, line]) {
        o.matrixAutoUpdate = false;
        o.matrix.copy(this.matrixOf(f.el));
        o.frustumCulled = false;
        o.renderOrder = 8;
      }
      this.hitLayer.add(mesh, line);
    }
  }

  /** Light elements by group, each group in its colour (an element's connections by kind). At most LINK_MAX are
   *  drawn, and outlines only for the first LINK_EDGES of each group: a slab can support hundreds of things. */
  setLinks(groups: { color: string; ids: string[] }[]) {
    this.linkGroups = groups;
    this.drawLinks();
  }

  /** The lit links, leaving out what the filters or a temporary hide take off screen. */
  private drawLinks() {
    this.version++;
    this.linkLayer.clear();
    const shown = this.lifted ? null : this.filterTest();
    for (const group of this.linkGroups) {
      const mats = this.linkMats(group.color);
      group.ids.slice(0, LINK_MAX).forEach((gid, k) => {
        const f = this.find(gid);
        if (!f || this.hidden.has(gid) || this.hiddenModels.has(this.models.indexOf(f.model)) || (shown && !shown(gid))) return;
        const parts: THREE.Object3D[] = [new THREE.Mesh(this.geometryOf(f), mats.mesh)];
        if (k < LINK_EDGES) { const l = new THREE.LineSegments(this.edgeGeometryOf(gid, f), mats.edges); l.layers.set(1); parts.push(l); }
        for (const o of parts) {
          o.matrixAutoUpdate = false;
          o.matrix.copy(this.matrixOf(f.el));
          o.frustumCulled = false;
          o.renderOrder = 7;
        }
        this.linkLayer.add(...parts);
      });
    }
  }

  private linkMats(color: string) {
    let mats = this.linkMaterials.get(color);
    if (!mats) {
      mats = {
        mesh: new THREE.MeshStandardMaterial({ color, emissive: new THREE.Color(color).multiplyScalar(0.35), roughness: 0.5,
          transparent: true, opacity: 0.85, polygonOffset: true, polygonOffsetFactor: -1, polygonOffsetUnits: -1,
          clippingPlanes: this.clipping }),
        edges: new THREE.LineBasicMaterial({ color, depthTest: false, transparent: true, opacity: 0.9 }),
      };
      this.linkMaterials.set(color, mats);
    }
    return mats;
  }

  /** A slow turn around the current target, while the agent thinks. */
  /** Turn the view slowly round the clash while ORCA works on it (the pilot): the view first glides sideways to put the
   * clash in the middle, keeping its angle and distance, so the turn is round the clash, not wherever the camera's
   * target was left. */
  orbit(on: boolean) {
    if (on && !this.controls.autoRotate) {
      const c = this.clashCentre(), t = this.controls.target;
      if (c && c.distanceTo(t) > this.reach(0.01, 0.001)) this.flyTo(this.camera.position.clone().add(c.clone().sub(t)), c, true, false);
    }
    this.controls.autoRotate = on;
  }

  /** While ORCA works on a clash (a proposal, a plan, a wider fix), a drag with nothing selected orbits round it. */
  setOrbitClash(on: boolean) { this.orbitClash = on; }
  private orbitClash = false;

  /** The middle of the clash on screen: where its pair meets, else the focus (a plan's or a wider fix's elements). */
  private clashCentre(): THREE.Vector3 | null {
    if (this.lastClash) return this.lastClash.zone.getCenter(new THREE.Vector3());
    const ids = this.focusIds();
    const box = ids.length ? this.boxOf(ids) : null;
    return box && !box.isEmpty() ? box.getCenter(new THREE.Vector3()) : null;
  }

  setEdges(on: boolean) { this.showEdges = on; this.applyMode(); }

  private clearFocusCache() {
    this.setHits([]);
    this.linkLayer.clear();   // its meshes share the batches' buffers too
    for (const g of this.edgeGeometry.values()) g.dispose();
    this.edgeGeometry.clear();
    this.edges.clear();
    // Not disposed: these geometries share their model's buffers, and disposing would free them.
    this.focusGeometry.clear();
    this.focusMeshes.clear();
  }

  private focusMaterial(color: THREE.Color, opacity = 1) {
    const m = new THREE.MeshStandardMaterial({ color, metalness: 0, roughness: 0.6, side: THREE.DoubleSide,
      ...(opacity < 1 ? { transparent: true, opacity, depthWrite: false } : {}) });
    m.clippingPlanes = this.clipping;
    return m;
  }

  /** Elements whose box comes within `margin` metres of the focus elements' boxes. */
  private nearFocus(ids: string[], margin = this.reach(2.5, 0.25)): Set<string> {
    const box = this.boxOf(ids);
    const out = new Set<string>();
    if (box.isEmpty()) return out;
    box.expandByScalar(margin);
    const tmp = new THREE.Box3();
    for (const model of this.models) {
      for (const el of model.byGlobalId.values()) {
        this.instanceBox(el, tmp);
        if (tmp.intersectsBox(box)) out.add(el.globalId);
      }
    }
    return out;
  }

  private instanceBox(el: LoadedElement, target: THREE.Box3) {
    el.mesh.getBoundingBoxAt(el.mesh.getGeometryIdAt(el.instanceId), target);
    return target.applyMatrix4(this.matrixOf(el));
  }

  boxOf(ids: string[]): THREE.Box3 {
    const box = new THREE.Box3();
    const tmp = new THREE.Box3();
    for (const gid of ids) {
      const f = this.find(gid);
      if (f) box.union(this.instanceBox(f.el, tmp));
    }
    return box;
  }

  // ---------------------------------------------------------------- previews of fixes

  /** Preview moves without touching the model: GlobalIds + server delta (metres, Z up). Clears any edit preview. */
  preview(moves: { globalIds: string[]; deltaM: number[] }[]) {
    this.clearOverlay();
    this.moved.clear();
    for (const m of moves) {
      const t = new THREE.Matrix4().makeTranslation(serverDeltaToViewer(m.deltaM));
      for (const gid of m.globalIds) this.moved.set(gid, t);
    }
    this.applyMode();
  }

  /** Show a proposed fix three ways: "after" (the fix in place of what it changes), "before" (the model as it is)
   * or "both" (the fix, with what it replaces as an orange ghost). Shapes are server triangles (metres, Z up). */
  showOption(opt: OptionShape, mode: "before" | "after" | "both", color: THREE.ColorRepresentation) {
    this.showOptions([{ ...opt, color }], mode);
  }

  /** Several fixes at once (a plan), each in its own colour. */
  showOptions(opts: (OptionShape & { color: THREE.ColorRepresentation })[], mode: "before" | "after" | "both") {
    this.clearOverlay();
    this.moved.clear();
    if (mode !== "before") {
      for (const opt of opts) {
        if ((opt.worldMeshes || opt.kind !== "move") && opt.pieces) {  // already positioned world meshes replace sources; never translate them twice
          for (const gid of opt.moved) this.hidden.add(gid);
          const solid = () => new THREE.MeshStandardMaterial({ color: opt.color, roughness: 0.6, side: THREE.DoubleSide, clippingPlanes: this.clipping });
          if (opt.kind === "penetration") {  // the provision for void solid, the wall or slab with its hole see-through round it
            this.addMeshes(opt.pieces.slice(0, 1), solid());
            this.addMeshes(opt.pieces.slice(1), new THREE.MeshStandardMaterial({ color: opt.color, roughness: 0.6, transparent: true,
              opacity: 0.3, depthWrite: false, side: THREE.DoubleSide, clippingPlanes: this.clipping }));
          } else {
            this.addMeshes(opt.pieces, solid());
          }
        } else {
          const t = new THREE.Matrix4().makeTranslation(serverDeltaToViewer(opt.deltaM));
          for (const gid of opt.moved) this.moved.set(gid, t);
          if (opt.pieces?.length) {   // a move that keeps its joints: the segments it stretches, as they would be
            for (const p of opt.pieces) if (p.global_id) this.hidden.add(p.global_id);
            this.addMeshes(opt.pieces, new THREE.MeshStandardMaterial({ color: opt.color, roughness: 0.6,
              side: THREE.DoubleSide, clippingPlanes: this.clipping }));
          }
        }
        if (mode === "both" && opt.before) {
          this.addMeshes(opt.before, new THREE.MeshBasicMaterial({ color: "#e67e22", transparent: true, opacity: 0.35,
            depthWrite: false, side: THREE.DoubleSide, clippingPlanes: this.clipping }));
        }
      }
    }
    this.applyMode();
  }

  private addMeshes(meshes: Mesh[], material: THREE.Material) {
    const capped = !material.transparent;   // a fix's solid pieces are cut like the model; ghosts are not
    for (const p of meshes) {
      const pos = new Float32Array(p.verts.length);
      for (let i = 0; i < p.verts.length; i += 3) {
        pos[i] = p.verts[i]; pos[i + 1] = p.verts[i + 2]; pos[i + 2] = -p.verts[i + 1]; // IFC Z up → three.js Y up
      }
      const g = new THREE.BufferGeometry();
      g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
      g.setIndex(p.faces);
      g.computeVertexNormals();
      const mesh = new THREE.Mesh(g, material);
      if (capped) mesh.layers.enable(CAP_LAYER.preview);
      this.overlay.add(mesh);
    }
  }

  private clearOverlay() {
    this.hidden.clear();
    for (const child of [...this.overlay.children]) {
      const mesh = child as THREE.Mesh;
      mesh.geometry.dispose();
      (mesh.material as THREE.Material).dispose();
      this.overlay.remove(mesh);
    }
  }

  // ---------------------------------------------------------------- camera

  /** Fly to a clash. Frames the zone where the two elements meet (their overlap, or the gap between them for a
   * clearance clash) with a margin, not the two whole elements: a 16 m run crossing a beam frames the crossing.
   * With no geometry here for an element (spaces and ports are not loaded), the report's clash point is enough. */
  focusClash(ids: string[], point: THREE.Vector3 | null, label = "", fly = true) {
    const boxes = ids.map((g) => this.boxOf([g])).filter((b) => !b.isEmpty());
    let zone: THREE.Box3 | null = null;
    if (boxes.length === 2) zone = meetingZone(boxes[0], boxes[1]);
    else if (boxes.length === 1 && point) zone = new THREE.Box3().setFromCenterAndSize(point, new THREE.Vector3().setScalar(this.reach(1, 0.2))).intersect(boxes[0]);
    if ((!zone || zone.isEmpty()) && point) zone = new THREE.Box3().setFromCenterAndSize(point, new THREE.Vector3().setScalar(this.reach(0.6, 0.15)));
    if (!zone || zone.isEmpty()) return false;
    this.setMarker(point ?? zone.getCenter(new THREE.Vector3()), label);
    if (fly) {
      this.flyToZone(zone, boxes.reduce((u, b) => u.union(b), zone.clone()));
      this.clashViews(ids, zone, point);
    } else this.lastClash = { ids, zone: zone.clone(), point: point?.clone() ?? null };
    return true;
  }

  /** Frame what a fix changes: the offset pieces given, and where each moved element now meets its partner
   * (`pairs`: [moved, partner]). Not the whole moved element: raising a 16 m run frames the crossing. */
  frameFix(meshes: Mesh[], pairs: [string, string][]) {
    const zone = meshBox(meshes);
    const union = zone.clone();
    for (const [moved, partner] of pairs) {
      const a = this.boxOf([moved]), b = this.boxOf([partner]);
      if (a.isEmpty() || b.isEmpty()) continue;
      zone.union(meetingZone(a, b));
      union.union(a).union(b);
    }
    if (zone.isEmpty()) return false;
    this.flyToZone(zone, union.union(zone));
    return true;
  }

  /** Fly to a zone with a margin that grows with it and with the elements around it (`union`), never too far out. */
  private flyToZone(zone: THREE.Box3, union: THREE.Box3) {
    const [position, target] = this.zoneCamera(zone, union);
    this.flyTo(position, target);
  }

  /** Where the camera goes to frame a zone (see flyToZone): [position, target]. */
  private zoneCamera(zone: THREE.Box3, union: THREE.Box3): [THREE.Vector3, THREE.Vector3] {
    const zoneDiag = zone.getSize(new THREE.Vector3()).length();
    const unionDiag = union.getSize(new THREE.Vector3()).length();
    // Half a metre at least around a building clash; for small parts, a share of the parts themselves.
    const least = Math.min(0.5, Math.max(0.25 * unionDiag, 2 * zoneDiag), this.reach(0.5, 0.15));
    const margin = Math.min(Math.max(0.35 * zoneDiag, 0.1 * unionDiag, least), Math.max((unionDiag - zoneDiag) / (2 * Math.sqrt(3)), least));
    const framed = zone.clone().expandByScalar(margin);
    const centre = framed.getCenter(new THREE.Vector3());
    const r = framed.getSize(new THREE.Vector3()).length() / 2;
    const vFov = THREE.MathUtils.degToRad(this.camera.fov);
    const hFov = 2 * Math.atan(Math.tan(vFov / 2) * this.camera.aspect);
    const dist = Math.max((r / Math.sin(Math.min(vFov, hFov) / 2)) * 1.1, 2 * r + least);
    return [centre.clone().add(this.viewDirection().multiplyScalar(dist)), centre];
  }

  /** The three pictures of a clash ORCA found, taken the way the Navisworks export takes them (CLAUDE.md, "Images
   * sent to the model"): A the pair alone and see-through, framed on where they meet; B the pair solid in its grey
   * context within 2.5 m; C the pair alone from a quarter turn round. Red A and green B, so the colour reading that
   * crops Navisworks pictures works on these too. The view is put back as it was. Null when either element has no
   * geometry here. */
  captureClash(a: string, b: string, side = 768): { A: string; B: string; C: string } | null {
    if (this.lost) return null;   // asked again later: never black pictures on the server
    return this.posed(a, b, (shot, turn) => {
      const A = shot("isolate", true, side), B = shot("context", false, side);
      turn();
      return { A, B, C: shot("isolate", true, side) };
    });
  }

  /** A small picture of a clash for the list (view A's recipe, as a JPEG), taken off screen like `captureClash`. */
  thumbClash(a: string, b: string, side = 192): string | null {
    if (this.lost) return null;
    return this.posed(a, b, (shot) => shot("isolate", true, side, "image/jpeg"));
  }

  /** Show it built (docs/show-it-built.md): the fix rendered four ways from one camera, for Muse Image to restyle and
   * the server to check, taken in one task with the user's view put back.
   * - A cutaway the viewer picks: of 12 directions, the one that shows at least 85% of the fix having taken away the
   *   least (ceilings, lights, grilles, furniture, slabs and glazing cost 1, walls 2, services, structure and machine
   *   parts 6; never the pair or what the fix passes through). A slab, roof or ceiling taken away above the fix becomes
   *   the section's top, one below its bottom. Zones (style alpha under 0.2) are never drawn.
   * - `fix`: a verified option (its pieces drawn in their elements' colours, the originals hidden) or, `applied`, a
   *   fix already in the model (its pieces only frame it).
   * - Passes, all the same square: the look (true colours), ids (index + 1 per element in 24 bits, no light, no
   *   antialiasing) and view-space normals. Null when there is nothing to frame. */
  captureBuilt(fix: { kind: string; moved: string[]; deltaM: number[]; pieces: BuiltPiece[] | null; applied: boolean },
    pair: [string, string], classOf: (gid: string) => string | undefined, radius = 3, side = 1024): BuiltPasses | null {
    if (this.lost) return null;
    const version = this.version;   // everything is put back: the drawings need not redraw
    try { return this.fullCanvas(() => this.builtPasses(fix, pair, classOf, radius, side)); } finally { this.version = version; this.drawFrame(); }
  }

  private builtPasses(fix: { kind: string; moved: string[]; deltaM: number[]; pieces: BuiltPiece[] | null; applied: boolean },
    pair: [string, string], classOf: (gid: string) => string | undefined, radius: number, side: number): BuiltPasses | null {
    // What the fix changes, to frame: a split run's new middle (not its long shortened ends); a penetration's provision
    // for void (the opening); a combined fix's new middles and the moved runs' parts near the clash.
    const pa = this.boxOf([pair[0]]), pb = this.boxOf([pair[1]]);
    const near = !pa.isEmpty() && !pb.isEmpty() ? meetingZone(pa, pb).expandByScalar(this.reach(1.5, 0.3)) : null;
    const combinedChanged = (pieces: BuiltPiece[]) => {
      const picked = pieces.filter((p) => p.part === "middle" || (p.part === "moved" && (!near || meshBox([p]).intersectsBox(near))));
      return picked.length ? picked : pieces;
    };
    const changed = (fix.kind === "offset" || fix.kind === "route" || fix.kind === "resize") && fix.pieces ? fix.pieces.slice(1, -1)
      : fix.kind === "penetration" && fix.pieces ? fix.pieces.slice(0, 1)
      : fix.kind === "combined" && fix.pieces ? combinedChanged(fix.pieces) : fix.pieces ?? [];
    const renderer = this.renderer, scene = this.scene, camera = this.camera;
    const saved = { position: camera.position.clone(), target: this.controls.target.clone(), mode: this.mode, focus: this.focus,
      flight: this.flight, marker: this.marker.visible, overlay: this.overlay.visible, hidden: new Set(this.hidden),
      moved: new Map(this.moved), section: this.sectionBox?.clone() ?? null, background: scene.background, hits: this.hitLayer.visible,
      links: this.linkLayer.visible, clear: renderer.getClearColor(new THREE.Color()), clearAlpha: renderer.getClearAlpha() };
    const temp = new THREE.Group();
    const trash: { dispose(): void }[] = [];   // render targets and materials made here, freed however it ends
    const all = this.models.flatMap((m) => [...m.byGlobalId.values()]);
    const legend = new Map<string, number>(all.map((el, i) => [el.globalId, i + 1]));
    const idColor = (k: number) => new THREE.Vector4((k & 255) / 255, ((k >> 8) & 255) / 255, ((k >> 16) & 255) / 255, 1);
    let cut = new Set<string>();
    const zonesAndCut = () => {
      // Zones, what the cutaway took, and what is not physical ("" from classOf: a space, a provision for void).
      for (const el of all) {
        if (el.baseAlpha < 0.2 || cut.has(el.globalId) || classOf(el.globalId) === "") el.mesh.setVisibleAt(el.instanceId, false);
      }
    };
    const shaded = () => { this.mode = "shaded"; this.applyMode(); zonesAndCut(); };
    try {
      this.flight = null; this.marker.visible = false; this.overlay.visible = false; this.hitLayer.visible = false;
      this.linkLayer.visible = false; this.grips.visible = false; this.lifted = true;
      this.focus = { a: null, b: null, group: {} };
      // The fix in place: a proposed option's pieces as their own meshes in their elements' colours (a move translates
      // its run), the originals hidden; an applied fix is the model itself.
      const pieceMeshes: THREE.Mesh[] = [];
      this.hidden = new Set(); this.moved = new Map();   // the model as it is, whatever preview is on screen
      if (!fix.applied) {
        const first = this.find(fix.moved[0]);
        const draw = (p: BuiltPiece, i: number) => {
          // Its own element's colour, else its run's (a combined fix's new pieces), else the first moved element's.
          const own = p.global_id ? this.find(p.global_id) : null;
          const origin = p.origin ? this.find(p.origin) : null;
          const colour = (own ?? origin ?? first)?.el.baseColor ?? GREY;
          const pos = new Float32Array(p.verts.length);
          for (let i = 0; i < p.verts.length; i += 3) { pos[i] = p.verts[i]; pos[i + 1] = p.verts[i + 2]; pos[i + 2] = -p.verts[i + 1]; }
          const welded = new THREE.BufferGeometry();
          welded.setAttribute("position", new THREE.BufferAttribute(pos, 3));
          welded.setIndex(p.faces);
          // Sharp edges stay sharp (a wall with a hole, a box): normals averaged across them shade a flat face in
          // streaks, which Muse Image draws as facets and the judges rightly reject.
          const g = toCreasedNormals(welded, Math.PI / 6);
          welded.dispose();
          const mesh = new THREE.Mesh(g, new THREE.MeshStandardMaterial({ color: colour, metalness: 0, roughness: 0.85,
            side: THREE.DoubleSide, clippingPlanes: this.clipping }));
          mesh.userData.piece = true;
          // A penetration's provision for void frames the view but is not drawn: it would fill the opening.
          if (fix.kind === "penetration" && i === 0) mesh.visible = false;
          pieceMeshes.push(mesh); temp.add(mesh);
        };
        if (fix.pieces && fix.kind !== "move") {
          for (const g of fix.moved) this.hidden.add(g);
          fix.pieces.forEach(draw);
        } else if (fix.kind === "move") {
          const t = new THREE.Matrix4().makeTranslation(serverDeltaToViewer(fix.deltaM));
          for (const g of fix.moved) this.moved.set(g, t);
          for (const p of fix.pieces ?? []) if (p.global_id) this.hidden.add(p.global_id);   // its stretched segments
          (fix.pieces ?? []).forEach(draw);
        }
      }
      scene.add(temp);
      shaded();
      // What the fix is, to frame and to see: its changed pieces, or (a move, an applied fix) its elements as they are.
      const fixObjects = (): THREE.Object3D[] => {
        if (!fix.applied && pieceMeshes.length && fix.kind !== "move") {
          const keep = new Set(changed);
          return pieceMeshes.filter((_, i) => keep.has(fix.pieces![i]));
        }
        const ids = fix.applied && changed.length ? changed.map((p) => p.global_id).filter((g): g is string => !!g) : fix.moved;
        let found = ids.map((g) => this.find(g)).filter((f): f is Found => !!f);
        // Kept pieces whose ids the page doesn't know (a trial's): the elements the fix changed, as they now are.
        if (!found.length) found = fix.moved.map((g) => this.find(g)).filter((f): f is Found => !!f);
        const els = found.map((f) => {
          const m = new THREE.Mesh(this.geometryOf(f));
          m.matrixAutoUpdate = false; m.matrix.copy(this.matrixOf(f.el)); m.frustumCulled = false;
          return m;
        });
        return fix.applied ? els : [...els, ...pieceMeshes];   // a move: what it takes along and what it stretches
      };
      const zone = changed.length ? meshBox(changed) : this.boxOf(fix.moved);
      if (!pa.isEmpty() && !pb.isEmpty()) zone.union(meetingZone(pa, pb));
      if (zone.isEmpty()) return null;
      const union = zone.clone().expandByScalar(this.reach(0.75, 0.2));
      const box = zone.clone().expandByScalar(this.reach(radius, 0.4));
      this.setSection(true, 0, box);
      if (this.sectionHelper) this.sectionHelper.visible = false;
      const keep = new Set(pair);
      const tmp = new THREE.Box3(), inner = (changed.length ? meshBox(changed) : zone.clone()).expandByScalar(0.01);
      for (const el of all) if (this.instanceBox(el, tmp).intersectsBox(inner)) keep.add(el.globalId);
      for (const g of fix.moved) keep.add(g);
      const aim = (dir: THREE.Vector3) => {
        const [position, target] = this.zoneCameraFrom(zone, union, dir);
        camera.position.copy(position); this.controls.target.copy(target); this.controls.update(); this.adjustClipRange();
      };
      const small = new THREE.WebGLRenderTarget(256, 256, { samples: 0 });
      const white = new THREE.MeshBasicMaterial({ color: 0xffffff, side: THREE.DoubleSide, polygonOffset: true,
        polygonOffsetFactor: -2, polygonOffsetUnits: -8, clippingPlanes: this.clipping });
      const idsMaterial = new THREE.MeshBasicMaterial({ color: 0xffffff, side: THREE.DoubleSide, clippingPlanes: this.clipping });
      trash.push(small, white, idsMaterial);
      const read = (rt: THREE.WebGLRenderTarget) => {
        const buf = new Uint8Array(rt.width * rt.height * 4);
        renderer.readRenderTargetPixels(rt, 0, 0, rt.width, rt.height, buf);
        return buf;
      };
      const draw = (rt: THREE.WebGLRenderTarget, material: THREE.Material | null, bg: THREE.Color | null, clear = true,
        root: THREE.Object3D = scene) => {
        scene.overrideMaterial = material;
        scene.background = clear ? bg : null;   // a colour background clears the depth buffer too
        renderer.setRenderTarget(rt);
        if (clear) { renderer.setClearColor(bg ?? new THREE.Color(1, 1, 1), 1); renderer.clear(); }
        const auto = renderer.autoClear;
        renderer.autoClear = false;
        renderer.render(root, camera);
        renderer.autoClear = auto;
        renderer.setRenderTarget(null);
        scene.overrideMaterial = null;
      };
      // Ids: every batch drawn unlit with its instances' colours set to their ids; each proposed piece its own id after
      // the model's elements. (An override material would draw the pieces white.)
      const colourIds = () => {
        for (const el of all) el.mesh.setColorAt(el.instanceId, idColor(legend.get(el.globalId)!));
        for (const m of this.models) { m.mesh.material = idsMaterial; if (m.glass) m.glass.material = idsMaterial; }
        pieceMeshes.forEach((m, i) => { m.userData.saved = m.material; m.material = new THREE.MeshBasicMaterial({
          color: new THREE.Color().setRGB(...(idColor(all.length + 1 + i).toArray().slice(0, 3) as [number, number, number])),
          side: THREE.DoubleSide, clippingPlanes: this.clipping }); });
      };
      const uncolourIds = () => { pieceMeshes.forEach((m) => { (m.material as THREE.Material).dispose(); m.material = m.userData.saved; }); shaded(); };
      /** How much of the fix this view shows, and which elements hide the rest (pixels each). */
      const measure = () => {
        const objects = fixObjects();
        const solo = new THREE.Group();
        for (const o of objects) { const c = o.parent ? o.clone() : o; c.visible = true; solo.add(c); }
        solo.traverse((o) => { if ((o as THREE.Mesh).isMesh) (o as THREE.Mesh).material = white; });
        scene.add(solo);
        const visibleModels = this.models.map((m) => [m.mesh.visible, m.glass?.visible ?? false] as const);
        for (const m of this.models) { m.mesh.visible = false; if (m.glass) m.glass.visible = false; }
        temp.visible = false;
        draw(small, null, new THREE.Color(0, 0, 0), true, solo);
        const alone = read(small);
        this.models.forEach((m, i) => { m.mesh.visible = visibleModels[i][0]; if (m.glass) m.glass.visible = visibleModels[i][1]; });
        temp.visible = true; solo.visible = false;
        colourIds();
        draw(small, null, new THREE.Color(0, 0, 0));
        uncolourIds();
        solo.visible = true;
        const ids = read(small);
        draw(small, null, null, false, solo);
        const seen = read(small);
        scene.remove(solo);
        let n = 0, shown = 0;
        const hiders = new Map<string, number>();
        const gidOf = new Map<number, string>(all.map((el, i) => [i + 1, el.globalId]));
        for (let i = 0; i < alone.length; i += 4) {
          if (alone[i] < 128) continue;
          n++;
          if (seen[i] > 128 && seen[i + 1] > 128 && seen[i + 2] > 128) { shown++; continue; }
          const g = gidOf.get(ids[i] | (ids[i + 1] << 8) | (ids[i + 2] << 16));
          if (g) hiders.set(g, (hiders.get(g) ?? 0) + 1);
        }
        return { shown: n ? shown / n : 0, hiders };
      };
      const CHEAP = /^Ifc(Covering|LightFixture|AirTerminal|Furniture|FurnishingElement|Slab|Roof|Plate|Window|Door|Space|Railing|SanitaryTerminal)$/;
      const cost = (g: string) => { const c = classOf(g) ?? ""; return CHEAP.test(c) ? 1 : c === "IfcWall" || c === "IfcCurtainWall" ? 2 : 6; };
      const dirs: THREE.Vector3[] = [];
      for (const y of [0.8, 0.3, -0.5]) for (const [x, z] of [[1, 1], [1, -1], [-1, 1], [-1, -1]]) dirs.push(new THREE.Vector3(x, y, z));
      const views: { dir: THREE.Vector3; shown: number; cut: string[]; score: number }[] = [];
      for (const dir of dirs) {
        aim(dir);
        cut = new Set(); shaded();
        let spent = 0;
        let m = measure();
        while (m.shown < 0.85 && cut.size < 12) {
          const next = [...m.hiders.entries()].filter(([g]) => !keep.has(g)).map(([g, px]) => ({ g, px, c: cost(g) }))
            .sort((x, y) => y.px / y.c - x.px / x.c)[0];
          if (!next || (next.c > 2 && m.shown >= 0.7)) break;
          cut.add(next.g); spent += next.c; shaded();
          m = measure();
        }
        views.push({ dir, shown: m.shown, cut: [...cut], score: spent + 10 * (1 - m.shown) + (m.shown < 0.6 ? 100 : 0) + (dir.y < 0 ? 1 : 0) });
      }
      const best = views.reduce((bi, v, i) => (v.score < views[bi].score - 1e-6 ? i : bi), 0);
      cut = new Set(views[best].cut);
      // A slab, roof or ceiling taken away above the fix becomes the section's top (its underside), one below its bottom.
      const section = box.clone(), centre = zone.getCenter(new THREE.Vector3());
      const sectioned: string[] = [];
      for (const g of [...cut]) {
        if (!/^Ifc(Slab|Roof|Covering)$/.test(classOf(g) ?? "")) continue;
        const f = this.find(g);
        if (!f) continue;
        const eb = this.instanceBox(f.el, new THREE.Box3());
        if (eb.min.y > centre.y) section.max.y = Math.min(section.max.y, eb.min.y - 0.002);
        else if (eb.max.y < centre.y) section.min.y = Math.max(section.min.y, eb.max.y + 0.002);
        else continue;
        cut.delete(g); sectioned.push(g);
      }
      this.setSection(true, 0, section);
      if (this.sectionHelper) this.sectionHelper.visible = false;
      scene.background = saved.background;
      shaded();
      aim(views[best].dir);
      // The passes: one square crop of the canvas's own view, so all three line up exactly.
      const size = renderer.getDrawingBufferSize(new THREE.Vector2());
      const s = Math.min(size.x, size.y), out = Math.min(side, s);
      const look = this.png(out, "image/png");
      const rt = new THREE.WebGLRenderTarget(size.x, size.y, { samples: 0 });
      trash.push(rt);
      const crop = (buf: Uint8Array) => {
        const full = document.createElement("canvas");
        full.width = size.x; full.height = size.y;
        const img = new ImageData(size.x, size.y);
        for (let y = 0; y < size.y; y++) img.data.set(buf.subarray((size.y - 1 - y) * size.x * 4, (size.y - y) * size.x * 4), y * size.x * 4);
        full.getContext("2d")!.putImageData(img, 0, 0);
        const c = document.createElement("canvas");
        c.width = c.height = out;
        const ctx = c.getContext("2d")!;
        ctx.imageSmoothingEnabled = false;   // ids must stay exact
        ctx.drawImage(full, (size.x - s) / 2, (size.y - s) / 2, s, s, 0, 0, out, out);
        return c.toDataURL("image/png");
      };
      colourIds();
      draw(rt, null, new THREE.Color(0, 0, 0));
      const ids = crop(read(rt));
      uncolourIds();
      const normalsMaterial = new THREE.MeshNormalMaterial({ side: THREE.DoubleSide, clippingPlanes: this.clipping });
      trash.push(normalsMaterial);
      draw(rt, normalsMaterial, new THREE.Color(0, 0, 0));
      const normals = crop(read(rt));
      return { look, ids, normals, side: out, cut: [...cut], sectioned, shown: views[best].shown };
    } finally {
      scene.remove(temp);
      temp.traverse((o) => { const m = o as THREE.Mesh; if (m.isMesh) { m.geometry.dispose(); (m.material as THREE.Material).dispose(); } });
      renderer.setRenderTarget(null);
      for (const t of trash) t.dispose();
      renderer.setClearColor(saved.clear, saved.clearAlpha);
      scene.overrideMaterial = null;
      scene.background = saved.background;
      this.hidden = saved.hidden; this.moved = saved.moved;
      this.overlay.visible = saved.overlay; this.hitLayer.visible = saved.hits; this.linkLayer.visible = saved.links;
      this.lifted = false;
      this.focus = saved.focus;
      if (saved.section) { this.setSection(true, 0, saved.section); } else this.setSection(false);
      this.mode = saved.mode; this.applyMode();
      camera.position.copy(saved.position); this.controls.target.copy(saved.target);
      this.flight = saved.flight; this.marker.visible = saved.marker;
      this.controls.update(); this.adjustClipRange();
    }
  }

  /** `zoneCamera` from a given direction (zoneCamera keeps the user's angle). */
  private zoneCameraFrom(zone: THREE.Box3, union: THREE.Box3, dir: THREE.Vector3): [THREE.Vector3, THREE.Vector3] {
    const zoneDiag = zone.getSize(new THREE.Vector3()).length(), unionDiag = union.getSize(new THREE.Vector3()).length();
    const least = Math.min(0.5, Math.max(0.25 * unionDiag, 2 * zoneDiag), this.reach(0.5, 0.15));
    const margin = Math.min(Math.max(0.35 * zoneDiag, 0.1 * unionDiag, least), Math.max((unionDiag - zoneDiag) / (2 * Math.sqrt(3)), least));
    const framed = zone.clone().expandByScalar(margin);
    const centre = framed.getCenter(new THREE.Vector3());
    const r = framed.getSize(new THREE.Vector3()).length() / 2;
    const vFov = THREE.MathUtils.degToRad(this.camera.fov), hFov = 2 * Math.atan(Math.tan(vFov / 2) * this.camera.aspect);
    const dist = Math.max((r / Math.sin(Math.min(vFov, hFov) / 2)) * 1.1, 2 * r + least);
    return [centre.clone().add(dir.clone().normalize().multiplyScalar(dist)), centre];
  }

  /** Point the camera at where `a` and `b` meet and let `take` render shots, then put everything back. It all happens
   * in one task, so nothing on screen changes. */
  private posed<T>(a: string, b: string, take: (shot: (mode: ViewMode, seeThrough: boolean, side: number, type?: string) => string,
    turn: () => void) => T): T | null {
    // Draw the user's view again before the browser paints: the canvas keeps its last frame (preserveDrawingBuffer),
    // and a shot taken after this frame's own render would otherwise show until the next one (thumbnails flashing).
    const version = this.version;   // everything is put back: the drawings need not redraw (a thumbnail every 60 ms)
    try { return this.fullCanvas(() => this.posedShots(a, b, take)); } finally { this.version = version; this.drawFrame(); }
  }

  private posedShots<T>(a: string, b: string, take: (shot: (mode: ViewMode, seeThrough: boolean, side: number, type?: string) => string,
    turn: () => void) => T): T | null {
    const boxA = this.boxOf([a]), boxB = this.boxOf([b]);
    if (boxA.isEmpty() || boxB.isEmpty()) return null;
    const zone = meetingZone(boxA, boxB);
    if (zone.isEmpty()) return null;
    const saved = { position: this.camera.position.clone(), target: this.controls.target.clone(), mode: this.mode,
      focus: this.focus, flight: this.flight, marker: this.marker.visible, links: this.linkLayer.visible };
    const pair = Object.values(this.focusMaterials);
    const shot = (mode: ViewMode, seeThrough: boolean, side: number, type?: string) => {
      for (const m of pair) { m.transparent = seeThrough; m.opacity = seeThrough ? 0.6 : 1; m.depthWrite = !seeThrough; m.needsUpdate = true; }
      this.setMode(mode);
      this.controls.update();
      this.adjustClipRange();
      return this.png(side, type);
    };
    try {
      this.flight = null;
      this.marker.visible = false;
      this.linkLayer.visible = false;   // the connection highlight is the viewer's, never the pictures'
      this.grips.visible = false;
      this.lifted = true;               // nor the user's style, filters, hides or selection
      this.setFocus({ a, b });
      const [position, target] = this.zoneCamera(zone, boxA.clone().union(boxB));
      this.camera.position.copy(position);
      this.controls.target.copy(target);
      return take(shot, () => this.camera.position.copy(position.clone().sub(target)
        .applyAxisAngle(new THREE.Vector3(0, 1, 0), Math.PI / 2).add(target)));
    } finally {
      for (const m of pair) { m.transparent = false; m.opacity = 1; m.depthWrite = true; m.needsUpdate = true; }
      this.lifted = false;
      this.placeGrips();
      this.focus = saved.focus;
      this.setMode(saved.mode);
      this.camera.position.copy(saved.position);
      this.controls.target.copy(saved.target);
      this.flight = saved.flight;
      this.marker.visible = saved.marker;
      this.linkLayer.visible = saved.links;
      this.controls.update();
      this.adjustClipRange();
    }
  }

  /** Keep the user's angle when it is a reasonable one; otherwise a high iso view. */
  private viewDirection(): THREE.Vector3 {
    const d = this.camera.position.clone().sub(this.controls.target).normalize();
    if (!isFinite(d.x) || d.y < 0.15 || d.y > 0.97) return new THREE.Vector3(1, 0.8, 1).normalize();
    return d;
  }

  frame(globalIds: string[]) {
    const box = this.boxOf(globalIds);
    if (!box.isEmpty()) this.flyToBox(box, 1.4);
  }

  /** Frame elements in every view (docs/filters.md, "Zoom"): the 3D camera flies to them, and each drawing view that is
   * not pinned pans and zooms to them, keeping its level, section line and facing. */
  frameEverywhere(globalIds: string[]) {
    const box = this.boxOf(globalIds);
    if (box.isEmpty()) return;
    this.flyToBox(box, 1.4);
    for (const pane of this.panes) if (pane.view && !pane.pinned) pane.view.frame(box, pane.rect, 0.08);
    this.onChange?.();
  }

  /** Frame server triangles (metres, Z up): the part of the model a fix changes. */
  frameMeshes(meshes: Mesh[], tight = 1.4) {
    const box = meshBox(meshes);
    if (!box.isEmpty()) this.flyToBox(box, tight);
  }

  fitAll(animate = true) {
    const box = new THREE.Box3();
    this.models.forEach((m, i) => {
      if (this.hiddenModels.has(i)) return;
      for (const b of batches(m)) { b.computeBoundingBox(); box.union(b.boundingBox!); }
    });
    if (!box.isEmpty()) this.flyToBox(box, 1.1, undefined, animate);
  }

  /** Standard views around the current target (or the section box, if one is on). */
  view(preset: Preset) {
    const target = this.controls.target.clone();
    const dist = Math.max(this.camera.position.distanceTo(target), this.reach(2, 0.8));
    const dirs: Record<Preset, THREE.Vector3> = {
      top: new THREE.Vector3(0, 1, 0.0001), front: new THREE.Vector3(0, 0, 1), right: new THREE.Vector3(1, 0, 0),
      iso: new THREE.Vector3(1, 0.8, 1),
    };
    this.flyTo(target.clone().add(dirs[preset].normalize().multiplyScalar(dist)), target);
  }

  private flyToBox(box: THREE.Box3, tight: number, dir?: THREE.Vector3, animate = true) {
    const centre = box.getCenter(new THREE.Vector3());
    const size = Math.max(box.getSize(new THREE.Vector3()).length(), this.reach(1.5, 0.5));
    const d = (dir ?? this.viewDirection()).normalize();
    this.flyTo(centre.clone().add(d.multiplyScalar(size * tight)), centre, animate);
  }

  /** Fly the camera there. A jump goes on the history (back / forward) unless `record` is false. */
  flyTo(position: THREE.Vector3, target: THREE.Vector3, animate = true, record = true) {
    if (record && this.models.length) { this.history.push(this.pose()); this.onChange?.(); }
    if (!animate || window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) {
      this.camera.position.copy(position);
      this.controls.target.copy(target);
      this.flight = null;
      return;
    }
    this.flight = { from: [this.camera.position.clone(), this.controls.target.clone()], to: [position, target],
      t0: performance.now(), ms: 650 };
  }

  // ---------------------------------------------------------------- projection, history, home, view cube

  /** The camera the 3D view draws and picks with. */
  activeCamera(): THREE.Camera { return this.projection === "orthographic" ? this.ortho : this.camera; }

  setProjection(p: Projection) { this.projection = p; this.onChange?.(); }

  /** The orthographic camera as the perspective one sees: the same direction, its frame the size of the view at the
   * target, set back far enough that nothing in front of the model is cut. */
  private syncOrtho(aspect: number) {
    const target = this.controls.target, dist = this.camera.position.distanceTo(target);
    const h = 2 * dist * Math.tan(THREE.MathUtils.degToRad(this.camera.fov) / 2), w = h * aspect;
    const dir = this.camera.position.clone().sub(target).normalize();
    const back = Math.max(dist, this.sceneDiag() * 1.5);
    this.ortho.position.copy(target).addScaledVector(dir, back);
    this.ortho.quaternion.copy(this.camera.quaternion);
    Object.assign(this.ortho, { left: -w / 2, right: w / 2, top: h / 2, bottom: -h / 2, near: 0.001, far: back + this.sceneDiag() * 2 });
    this.ortho.updateProjectionMatrix();
    this.ortho.updateMatrixWorld();
  }

  pose(): Pose {
    return { position: this.camera.position.toArray() as Pose["position"], target: this.controls.target.toArray() as Pose["target"] };
  }

  /** Fly to a saved pose. */
  applyPose(p: Pose, animate = true) {
    this.flyTo(new THREE.Vector3(...p.position), new THREE.Vector3(...p.target), animate);
  }

  back() { const p = this.history.goBack(this.pose()); if (p) this.flyTo(new THREE.Vector3(...p.position), new THREE.Vector3(...p.target), true, false); this.onChange?.(); }
  forward() { const p = this.history.goForward(this.pose()); if (p) this.flyTo(new THREE.Vector3(...p.position), new THREE.Vector3(...p.target), true, false); this.onChange?.(); }
  get canBack() { return this.history.canBack; }
  get canForward() { return this.history.canForward; }

  /** Home: a pose set by the user (per project, kept by the page), else the whole model. */
  setHome(p: Pose | null) { this.homePose = p; this.onChange?.(); }
  get homeView(): Pose | null { return this.homePose; }
  home() { if (this.homePose) this.applyPose(this.homePose); else this.fitAll(); }

  /** Look from a direction (three axes; a view cube face, edge or corner) round the current target. */
  lookFrom(dir: THREE.Vector3) {
    const d = dir.clone().normalize();
    if (Math.abs(d.y) > 0.999) d.set(0, Math.sign(d.y), 0.0001).normalize();   // straight down or up: keep north up
    const target = this.controls.target.clone();
    const dist = Math.max(this.camera.position.distanceTo(target), this.reach(2, 0.8));
    this.onUserCamera?.();
    this.flyTo(target.clone().addScaledVector(d, dist), target);
  }

  /** Orbit by a drag on the view cube (pixels). */
  private turn(dx: number, dy: number) {
    this.flight = null;
    this.onUserCamera?.();
    const target = this.controls.target, offset = this.camera.position.clone().sub(target);
    const sph = new THREE.Spherical().setFromVector3(offset);
    sph.theta -= dx * 0.01;
    sph.phi = THREE.MathUtils.clamp(sph.phi - dy * 0.01, 0.01, Math.PI - 0.01);
    this.camera.position.copy(target).add(new THREE.Vector3().setFromSpherical(sph));
    this.camera.lookAt(target);
  }

  /** What a drag in the 3D view orbits round (docs/views.md, "Navigate like a CAD tool"): the selected element, else the
   * clash while ORCA works on it; null: the point under the pointer. */
  private pivotFor(): THREE.Vector3 | null {
    if (this.selection && this.has(this.selection)) {
      const b = this.boxOf([this.selection]);
      if (!b.isEmpty()) return b.getCenter(new THREE.Vector3());
    }
    return this.orbitClash ? this.clashCentre() : null;
  }

  /** A drag that orbits round a pivot of its own (the selection, the clash): the controls do not turn for it. */
  private spin: { id: number; x: number; y: number; pivot: THREE.Vector3 } | null = null;

  private spinMove(e: PointerEvent) {
    const s = this.spin!;
    if (e.pointerId !== s.id) return;
    this.orbitAround(s.pivot, e.clientX - s.x, e.clientY - s.y);
    s.x = e.clientX; s.y = e.clientY;
  }

  /** Turn the camera and its target together round `pivot`, as the controls turn round their target: a drag across
   * (`dx` pixels) turns round the vertical, a drag up or down (`dy`) tilts, never past straight up or down. The pivot
   * stays where it is on screen, so nothing jumps. */
  orbitAround(pivot: THREE.Vector3, dx: number, dy: number) {
    const cam = this.camera, t = this.controls.target, up = new THREE.Vector3(0, 1, 0);
    const k = (2 * Math.PI * this.controls.rotateSpeed) / Math.max(this.pane3d.clientHeight, 1);
    const yaw = new THREE.Quaternion().setFromAxisAngle(up, -dx * k);
    const offset = cam.position.clone().sub(t).applyQuaternion(yaw);
    const phi = offset.angleTo(up), next = THREE.MathUtils.clamp(phi - dy * k, 0.01, Math.PI - 0.01);
    const axis = offset.clone().cross(up);
    const turn = axis.lengthSq() > 1e-12 ? new THREE.Quaternion().setFromAxisAngle(axis.normalize(), phi - next).multiply(yaw) : yaw;
    for (const v of [cam.position, t]) v.sub(pivot).applyQuaternion(turn).add(pivot);
    this.controls.update();
  }

  /** A press in the 3D view, before the controls see it: a section box grip starts a drag; an orbit (left button) with
   * a pivot of its own (the selection, the clash) turns round it; otherwise it turns about what is under the pointer:
   * the target moves along the view to that depth, so nothing jumps. */
  private press(e: PointerEvent) {
    if (this.cube.el.contains(e.target as Node)) return;   // the view cube handles its own
    this.onUserCamera?.();
    if (e.button !== 0 || !this.models.length) return;
    const grip = this.gripAt(e);
    if (grip) {
      e.stopImmediatePropagation();
      e.preventDefault();
      this.pane3d.setPointerCapture(e.pointerId);
      this.grip = grip;
      this.controls.enabled = false;
      return;
    }
    if (e.shiftKey || e.ctrlKey || e.metaKey || this.flight) return;
    const pivot = e.pointerType === "touch" ? null : this.pivotFor();
    if (pivot) {
      this.spin = { id: e.pointerId, x: e.clientX, y: e.clientY, pivot };
      this.controls.enableRotate = false;   // the controls still pan and zoom, and capture the pointer
      return;
    }
    if (this.projection === "orthographic") return;
    const hit = this.pickAt(e, { ghosts: true });
    if (!hit) return;
    const cam = this.camera.position, dir = this.controls.target.clone().sub(cam).normalize();
    const depth = hit.point.clone().sub(cam).dot(dir);
    if (depth > this.camera.near * 2) this.controls.target.copy(cam).addScaledVector(dir, depth);
  }

  private release(e: PointerEvent) {
    if (this.spin && e.pointerId === this.spin.id) { this.spin = null; this.controls.enableRotate = true; }
    if (!this.grip) return;
    this.grip = null;
    this.controls.enabled = true;
    this.swallowClick = true;
    if (this.pane3d.hasPointerCapture(e.pointerId)) this.pane3d.releasePointerCapture(e.pointerId);
    this.onChange?.();
  }

  // ---------------------------------------------------------------- panes: layouts and drawing views

  /** The panes on screen: all of them, or the one maximised. */
  visiblePanes(): Pane[] { return this.maximised != null && this.panes[this.maximised] ? [this.panes[this.maximised]] : this.panes; }
  private pane3dShown() { return this.visiblePanes().some((p) => p.spec.kind === "3d"); }
  /** The 3D pane's rectangle in the stage (the whole stage when it is the only one, or hidden). */
  rect3d(): Rect {
    const p = this.visiblePanes().find((q) => q.spec.kind === "3d");
    return p ? p.rect : { x: 0, y: 0, w: this.host.clientWidth || 1, h: this.host.clientHeight || 1 };
  }
  get maximisedPane() { return this.maximised; }

  /** Single, Two (plan beside 3D) or Quad (plan, 3D, section, elevation). Panes already showing a kind are kept. */
  setLayout(layout: Layout) {
    if (layout === this.layout && this.maximised == null) return;
    this.maximised = null;
    const old = [...this.panes];
    const made: Pane[] = [];
    const next = defaultKinds(layout).map((kind) => {
      const i = old.findIndex((p) => p.spec.kind === kind);
      if (i >= 0) return old.splice(i, 1)[0];
      const p = this.makePane(kind as DrawingSpec["kind"]);
      made.push(p);
      return p;
    });
    for (const p of old) { p.view?.dispose(); p.el.remove(); }
    this.panes = next;
    this.layout = layout;
    this.layoutPanes();
    this.configureViews(false);
    if (this.models.length) {
      // A new pane looks at the clash on screen, else the whole model (never at empty paper round the origin).
      const c = this.lastClash, box = this.modelBox();
      for (const p of made) {
        if (!p.view) continue;
        if (c) this.clashViews(c.ids, c.zone, c.point, p);
        else p.view.frame(box, p.rect, 0.08);
      }
      this.applyMode();   // the drawings' own visibility (Context and Isolate hide nothing there by default)
    }
    this.onChange?.();
  }

  /** Show one pane over the whole stage (null: back to the layout). */
  maximise(i: number | null) {
    this.maximised = i != null && this.panes[i] && this.panes.length > 1 ? i : null;
    this.layoutPanes();
    this.onChange?.();
  }

  /** Where the panes split (shares of the stage), from a drag on the line between them. */
  setSplit(x: number, y: number) { this.split = { x: THREE.MathUtils.clamp(x, 0.2, 0.8), y: THREE.MathUtils.clamp(y, 0.2, 0.8) }; this.layoutPanes(); }

  /** Change what a drawing pane shows: another kind (framed on the model), or new settings (kept framing). */
  setPaneSpec(i: number, spec: DrawingSpec) {
    const pane = this.panes[i];
    if (!pane?.view) return;
    const kindChanged = pane.spec.kind !== spec.kind;
    pane.spec = spec;
    pane.view.configure(spec, this.levels, this.modelBox());
    if (kindChanged) pane.view.frame(this.modelBox(), pane.rect, 0.08);
    this.onChange?.();
  }

  /** Where the panes split, as shares of the stage. */
  get splitShares() { return { ...this.split }; }

  /** A section's crop by default: 6 m each side of its line, the model's height and a little more. */
  defaultCrop() {
    const m = this.modelBox(), pad = this.reach(0.5, 0.05);
    return { left: this.reach(6, 0.5), right: this.reach(6, 0.5), bottom: (m.isEmpty() ? 0 : m.min.y) - pad, top: (m.isEmpty() ? 3 : m.max.y) + pad };
  }

  /** A pinned pane keeps its view when a clash is picked. */
  setPinned(i: number, on: boolean) { if (this.panes[i]) { this.panes[i].pinned = on; this.onChange?.(); } }

  /** Frame a drawing pane on the whole model. */
  fitPane(i: number) { const p = this.panes[i]; if (p?.view) { p.view.frame(this.modelBox(), p.rect, 0.08); this.onChange?.(); } }

  /** Levels and grids from the server (api.datums). */
  setDatums(d: Datums | null) {
    const before = this.levels.map((l) => `${l.name}@${l.elevation_m}`).join("|");
    this.datums = d;
    this.configureViews(false);
    // New levels (the first datums of a scene, or another project's): plans start again on the ground level, not on
    // whichever index the old levels gave.
    if (this.levels.map((l) => `${l.name}@${l.elevation_m}`).join("|") !== before) {
      const box = this.modelBox();
      for (const pane of this.panes) {
        if (pane.view && pane.spec.kind === "plan") {
          pane.spec = { ...pane.spec, level: this.groundLevel() };
          pane.view.configure(pane.spec, this.levels, box);
        }
      }
    }
    this.onChange?.();
  }

  /** Drawing views follow the 3D view's Context / Isolate (true), or show the whole model. */
  setDrawingsShow(show: DrawingsShow) { this.drawings = show; this.applyMode(); this.onChange?.(); }

  private paneSeq = 0;
  private makePane(kind: DrawingSpec["kind"]): Pane {
    const el = document.createElement("div");
    el.className = `view-pane view-drawing view-${kind}`;
    el.hidden = !this.models.length;
    const layer = document.createElement("canvas");
    layer.className = "view-anno";
    el.appendChild(layer);
    this.host.appendChild(el);
    const view = new DrawingView(this.defaultSpec(kind));
    const pane: Pane = { spec: view.spec, el, rect: { x: 0, y: 0, w: 1, h: 1 }, pinned: false, view, key: ++this.paneSeq };
    this.attachDrawingInput(pane);
    return pane;
  }

  /** What a pane of a kind shows at first: a plan of the ground level, a section through the model's middle. */
  defaultSpec(kind: DrawingSpec["kind"]): DrawingSpec {
    const c = toIfc(this.modelBox().getCenter(new THREE.Vector3()));
    if (kind === "plan") return { kind, level: this.groundLevel(), cut: 1.2, bottom: 0 };
    if (kind === "section") return { kind, origin: [c[0], c[1]], angle: 0, flip: false, far: null, crop: null };
    return { kind, facing: "south", far: null };
  }

  /** The level a plan starts on: the first at or above zero (Level 01, not the foundations), else the lowest. */
  private groundLevel(): number { return Math.max(0, this.levels.findIndex((l) => l.elevation_m >= -1e-6)); }

  /** The whole model's box (three.js world), visible models only. */
  modelBox(): THREE.Box3 {
    if (!this.boxCache) {
      const box = new THREE.Box3();
      this.models.forEach((m, i) => { if (!this.hiddenModels.has(i)) for (const b of batches(m)) { b.computeBoundingBox(); if (b.boundingBox) box.union(b.boundingBox); } });
      this.boxCache = box;
    }
    return this.boxCache.clone();
  }

  /** Levels from the server, or one for the whole model when it has none; every drawing configured again (framed on
   * the model when `frame`, as after a load). */
  private configureViews(frame: boolean) {
    const box = this.modelBox();
    this.levels = levelsOrModel(this.datums?.levels ?? [], box.isEmpty() ? 0 : box.min.y, box.isEmpty() ? 1 : box.max.y);
    for (const pane of this.panes) {
      if (!pane.view) continue;
      let spec = pane.spec as DrawingSpec;
      if (spec.kind === "plan" && (spec.level >= this.levels.length || frame)) spec = { ...spec, level: this.groundLevel() };
      if (frame && spec.kind === "section") spec = this.defaultSpec("section");
      pane.spec = spec;
      pane.view.configure(spec, this.levels, box);
      if (frame) pane.view.frame(box, pane.rect, 0.08);
    }
  }

  /** Place the panes for the layout and the split, and give the 3D camera its pane's shape. */
  private layoutPanes() {
    const W = this.host.clientWidth || 1, H = this.host.clientHeight || 1;
    this.canvasStamp++;   // panes move (a maximised one covered the rest): each composites again
    const shown = new Set(this.visiblePanes());
    const rects = paneRects(this.maximised != null ? "single" : this.layout, W, H, this.split);
    let k = 0;
    for (const pane of this.panes) {
      const on = shown.has(pane);
      pane.el.style.display = on ? "" : "none";
      if (!on) { pane.view?.dispose(); continue; }
      const before = pane.rect;
      pane.rect = rects[k++] ?? { x: 0, y: 0, w: W, h: H };
      Object.assign(pane.el.style, { inset: "auto", left: `${pane.rect.x}px`, top: `${pane.rect.y}px`, width: `${pane.rect.w}px`, height: `${pane.rect.h}px` });
      const layer = pane.el.querySelector("canvas");
      if (layer) {
        // Setting a canvas's size clears it, even to the same size: only when it changes, and then draw it again.
        const dpr = Math.min(window.devicePixelRatio || 1, 2), w = Math.round(pane.rect.w * dpr), h = Math.round(pane.rect.h * dpr);
        if (layer.width !== w || layer.height !== h) { layer.width = w; layer.height = h; pane.annotated = undefined; }
      }
      // A drawing keeps what is at its middle when its pane changes size.
      if (pane.view && before.w > 2 && (before.w !== pane.rect.w || before.h !== pane.rect.h)) pane.view.drawn = "";
    }
    const r3 = this.rect3d();
    this.camera.aspect = r3.w / Math.max(r3.h, 1);
    this.camera.updateProjectionMatrix();
    this.onChange?.();
  }

  /** The pane under a page point. */
  paneAt(x: number, y: number): Pane | null {
    const r = this.host.getBoundingClientRect();
    return this.visiblePanes().find((p) => x >= r.left + p.rect.x && x < r.left + p.rect.x + p.rect.w
      && y >= r.top + p.rect.y && y < r.top + p.rect.y + p.rect.h) ?? null;
  }

  /** Pan (drag with any button), zoom (wheel, pinch) in a drawing pane. A click still reaches the page (a drag of more
   * than a few pixels is a pan, never a pick). */
  private attachDrawingInput(pane: Pane) {
    const el = pane.el, view = pane.view!;
    const down = new Map<number, { x: number; y: number }>();
    let pinch = 0;
    let drag: { handle: Handle; specs: DrawingSpec[]; id: number } | null = null;
    let right: { x: number; y: number } | null = null;
    const local = (e: PointerEvent) => { const r = el.getBoundingClientRect(); return new THREE.Vector2(e.clientX - r.left, e.clientY - r.top); };
    el.addEventListener("pointerdown", (e) => {
      // A mark to drag (a section's line, a plan's cut…) takes the press; anything else pans.
      const h = e.button === 0 ? handleAt(pane.handles ?? [], local(e)) : null;
      if (h) {
        e.stopPropagation(); e.preventDefault();
        el.setPointerCapture(e.pointerId);
        drag = { handle: h, specs: this.panes.map((q) => q.spec as DrawingSpec), id: e.pointerId };
        const esc = (k: KeyboardEvent) => {
          if (k.key !== "Escape" || !drag) return;
          drag.specs.forEach((sp, i) => { if (this.panes[i]?.view && sp !== this.panes[i].spec) this.setPaneSpec(i, sp); });
          drag = null;
          window.removeEventListener("keydown", esc, true);
          k.stopPropagation();
        };
        window.addEventListener("keydown", esc, true);
        return;
      }
      if (e.button === 2) right = { x: e.clientX, y: e.clientY };
      down.set(e.pointerId, { x: e.clientX, y: e.clientY });
      view.held = true;
      el.setPointerCapture(e.pointerId);
      if (down.size === 2) { const [a, b] = [...down.values()]; pinch = Math.hypot(a.x - b.x, a.y - b.y); }
    });
    el.addEventListener("pointermove", (e) => {
      if (drag && drag.id === e.pointerId) { this.dragHandle(pane, drag.handle, local(e), e.shiftKey); return; }
      if (!down.size) { el.style.cursor = handleAt(pane.handles ?? [], local(e)) ? "move" : ""; return; }
      const was = down.get(e.pointerId);
      if (!was) return;
      if (down.size === 2) {
        down.set(e.pointerId, { x: e.clientX, y: e.clientY });
        const [a, b] = [...down.values()], d = Math.hypot(a.x - b.x, a.y - b.y);
        const r = el.getBoundingClientRect();
        if (pinch > 0 && d > 0) view.zoomAt(pinch / d, (a.x + b.x) / 2 - r.left, (a.y + b.y) / 2 - r.top, pane.rect);
        pinch = d;
        return;
      }
      view.pan(e.clientX - was.x, e.clientY - was.y);
      down.set(e.pointerId, { x: e.clientX, y: e.clientY });
    });
    const up = (e: PointerEvent) => {
      if (drag && drag.id === e.pointerId) {
        drag = null;
        // The click that ends a drag picks nothing.
        el.addEventListener("click", (c) => c.stopPropagation(), { once: true, capture: true });
      }
      // A right click without a drag: look there in 3D.
      if (e.button === 2 && right && Math.hypot(e.clientX - right.x, e.clientY - right.y) < 4) this.lookHere(pane, e);
      if (e.button === 2) right = null;
      down.delete(e.pointerId); if (down.size < 2) pinch = 0;
      view.held = down.size > 0;
    };
    el.addEventListener("pointerup", up);
    el.addEventListener("pointercancel", up);
    el.addEventListener("wheel", (e) => {
      e.preventDefault();
      const r = el.getBoundingClientRect();
      view.zoomAt(Math.exp(e.deltaY * 0.0015), e.clientX - r.left, e.clientY - r.top, pane.rect);
    }, { passive: false });
    el.addEventListener("contextmenu", (e) => e.preventDefault());
  }

  /** Drag one of a drawing's marks: move or turn a section, set its far clip or sides, a plan's cut or bottom, a crop's
   * top or bottom. The view it belongs to redraws as it goes. `at`: the pointer in `pane`'s pixels. */
  private dragHandle(pane: Pane, h: Handle, at: THREE.Vector2, snap: boolean) {
    const view = pane.view!, target = this.panes[h.pane];
    if (!target?.view) return;
    target.view.lastMove = performance.now(); target.view.moved = true;   // a drag: the view it reshapes draws a few times a second, then once at rest
    const w = view.fromPane(at.x, at.y, pane.rect), [x, y, z] = toIfc(w);
    const spec = target.spec as DrawingSpec;
    if (spec.kind === "section") {
      const { along, look } = sectionFrame(spec), dx = x - spec.origin[0], dy = y - spec.origin[1];
      if (h.kind === "section-line") {
        const d = dx * look[0] + dy * look[1];
        this.setPaneSpec(h.pane, { ...spec, origin: [spec.origin[0] + look[0] * d, spec.origin[1] + look[1] * d] });
      } else if (h.kind === "section-end") {
        let ang = Math.atan2(dy, dx) + (h.end === "left" ? Math.PI : 0) - (spec.flip ? Math.PI : 0);
        if (snap) ang = Math.round(ang / (Math.PI / 12)) * (Math.PI / 12);
        this.setPaneSpec(h.pane, { ...spec, angle: ang });
      } else if (h.kind === "section-far") {
        this.setPaneSpec(h.pane, { ...spec, far: Math.max(this.reach(0.05, 0.005), dx * look[0] + dy * look[1]) });
      } else if (h.kind === "section-side") {
        const u = dx * along[0] + dy * along[1], crop = spec.crop ?? this.defaultCrop();
        this.setPaneSpec(h.pane, { ...spec, crop: h.end === "left" ? { ...crop, left: Math.max(0.1, -u) } : { ...crop, right: Math.max(0.1, u) } });
      } else if ((h.kind === "crop-top" || h.kind === "crop-bottom") && spec.crop) {
        this.setPaneSpec(h.pane, { ...spec, crop: h.kind === "crop-top" ? { ...spec.crop, top: Math.max(z, spec.crop.bottom + 0.05) }
          : { ...spec.crop, bottom: Math.min(z, spec.crop.top - 0.05) } });
      }
    } else if (spec.kind === "plan") {
      const level = this.levels[spec.level]?.elevation_m ?? 0;
      if (h.kind === "plan-cut") this.setPaneSpec(h.pane, { ...spec, cut: Math.max(z - level, (spec.bottom ?? -1e9) + 0.01) });
      else if (h.kind === "plan-bottom" && spec.bottom != null) this.setPaneSpec(h.pane, { ...spec, bottom: Math.min(z - level, spec.cut - 0.01) });
    }
  }

  /** Turn the 3D view to look at what is under a point of a drawing (a right click there), from where it looks now. */
  private lookHere(pane: Pane, e: PointerEvent) {
    const hit = this.pickDrawing(pane, e);
    const r = pane.el.getBoundingClientRect();
    const at = hit?.point ?? pane.view!.fromPane(e.clientX - r.left, e.clientY - r.top, pane.rect);
    const offset = this.camera.position.clone().sub(this.controls.target);
    this.onUserCamera?.();
    this.flyTo(at.clone().add(offset), at);
  }

  /** Draw a drawing pane: into its target when anything it shows changed, then onto its rectangle of the canvas
   * (`g`: GL pixels, the viewport and scissor already set). */
  private renderDrawing(pane: Pane, g: Rect) {
    const view = pane.view!, r = this.renderer, dpr = r.getPixelRatio();
    view.updateCamera(pane.rect, this.sceneDiag() * 2 + 10);
    const [rt, nrt] = view.target(Math.max(1, Math.round(g.w * dpr)), Math.max(1, Math.round(g.h * dpr)));
    // Draw again when what it shows changed. A pan or zoom alone only moves the last picture (the composite's shift)
    // while it goes on, and draws once it rests: a drawing is several passes over the model, too slow for every pointer
    // move. A drag that reshapes the view (a cut, a section line) draws at most five times a second while it goes on.
    const content = `${this.version}|${view.contentKey(pane.rect)}|${this.drawings}|${this.hiddenModels.size}`;
    if (view.moved) { view.moved = false; view.quiet = 0; } else view.quiet++;
    // A gesture goes on while a pointer holds the pane or the view moved in the last few frames (frames, not only time:
    // on a slow machine one frame outlasts any delay).
    const now = performance.now(), busy = view.held || view.quiet < 3 || now - view.lastMove < 150;
    const moved = !view.shown || !view.shown.center.equals(view.center) || view.shown.scale !== view.scale;
    const due = view.drawn !== content ? !busy || now - view.lastDraw > 200 : moved && !busy;
    if (due) {
      this.drawInto(view, rt, nrt);
      view.drawn = content;
      view.shown = { center: view.center.clone(), scale: view.scale };
      view.lastDraw = now;
      r.setViewport(g.x, g.y, g.w, g.h);
      r.setScissor(g.x, g.y, g.w, g.h);
      r.setScissorTest(true);
    }
    const shift = view.shift(pane.rect);
    // The canvas keeps what each pane last showed (preserveDrawingBuffer): composite again only when that changes.
    const crop = view.crop ? view.crop.map((c) => view.toPane(c, pane.rect)) : null;
    const composed = [view.drawn, view.lastDraw, shift.scale, shift.x, shift.y, g.x, g.y, g.w, g.h, this.canvasStamp,
      crop?.map((q) => `${q.x.toFixed(1)},${q.y.toFixed(1)}`).join(";")].join("|");
    if (pane.composed === composed) return;
    pane.composed = composed;
    const u = this.drawStyle.composite.uniforms;
    u.shiftScale.value = shift.scale; u.shiftAt.value.set(shift.x, shift.y);
    u.color.value = rt.texture; u.normals.value = nrt.texture; u.depth.value = nrt.depthTexture;
    u.texel.value.set(1 / rt.width, 1 / rt.height);
    u.near.value = view.camera.near; u.far.value = view.camera.far; u.ortho.value = 1;
    u.tol.value = view.scale * 3; u.cutWidth.value = 1.5 * dpr; u.edges.value = 1;
    // The crop, as a share of the pane (texture coordinates: y up).
    if (crop) {
      const px = crop;
      u.cropMin.value.set(Math.min(...px.map((q) => q.x)) / pane.rect.w, 1 - Math.max(...px.map((q) => q.y)) / pane.rect.h);
      u.cropMax.value.set(Math.max(...px.map((q) => q.x)) / pane.rect.w, 1 - Math.min(...px.map((q) => q.y)) / pane.rect.h);
    } else { u.cropMin.value.set(0, 0); u.cropMax.value.set(1, 1); }
    this.drawStyle.drawComposite(r);
  }

  /** Render the model as a drawing into its targets (docs/views.md, "The drawing style"): paper fills, the pair flat
   * in its colours; then, where the view cuts, stencil passes and caps that fill each cut face (amber where A and B
   * overlap); then normals and depth for the linework. Its clip planes, the whole model unless drawings follow the 3D
   * view, never the section box or the 3D view's helpers. */
  private drawInto(view: DrawingView, rt: THREE.WebGLRenderTarget, nrt: THREE.WebGLRenderTarget) {
    const r = this.renderer, st = this.drawStyle, scene = this.scene, cam = view.camera;
    const box = this.clipping.splice(0);
    const background = scene.background, auto = r.autoClear;
    const materials = this.models.map((m) => [m.mesh.material, m.glass?.material] as const);
    const focusMats = new Map<THREE.Mesh, THREE.Material | THREE.Material[]>();
    const sel = this.selectionLayer.children.find((o) => (o as THREE.Mesh).isMesh) as THREE.Mesh | undefined;
    const restore = this.useDrawingVisibility();
    // The filters' colours, on paper: each coloured element in its colour, the rest in its file's tint.
    const paint = this.drawings !== "whole" && !this.lifted ? this.rules?.paint : null;
    const unpaint = paint?.size ? this.useDrawingPaint(paint) : null;
    const hiddenForNormals: THREE.Object3D[] = [];
    try {
      this.models.forEach((m, i) => { m.mesh.material = unpaint ? st.paintFill : st.fills[i % st.fills.length]; if (m.glass) m.glass.material = st.glass; });
      for (const o of this.focusLayer.children) {
        const mesh = o as THREE.Mesh;
        if (!mesh.isMesh || (mesh.material as THREE.Material).transparent) continue;
        focusMats.set(mesh, mesh.material);
        mesh.material = st.side[(mesh.userData.side as Side) ?? "a"];
      }
      if (sel) { focusMats.set(sel, sel.material); sel.material = st.selected; }
      scene.background = PAPER;
      r.clippingPlanes = view.planes;
      r.setRenderTarget(rt);
      r.render(scene, cam);
      if (view.cut) {
        // Stencil: each group's cut solids flip their bit; then the caps fill by what is set.
        r.autoClear = false;
        scene.background = null;
        r.clippingPlanes = [view.cut];
        view.reach(true);   // every solid the cut passes through, whole, past a bottom or a far clip
        cam.layers.set(CAP_LAYER.rest);
        for (const m of st.counting) { scene.overrideMaterial = m; r.render(scene, cam); }
        scene.overrideMaterial = null;
        st.settleCount(r);
        for (const [layer, bit] of [[CAP_LAYER.a, CUT.a], [CAP_LAYER.b, CUT.b], [CAP_LAYER.ab, CUT.ab], [CAP_LAYER.preview, CUT.preview]]) {
          cam.layers.set(layer);
          scene.overrideMaterial = st.stencilFor(bit);
          r.render(scene, cam);
        }
        scene.overrideMaterial = null;
        cam.layers.set(0);
        const preview = this.overlay.children.find((o) => (o as THREE.Mesh).isMesh && !((o as THREE.Mesh).material as THREE.Material).transparent) as THREE.Mesh | undefined;
        st.drawCaps(r, preview ? ((preview.material as THREE.MeshStandardMaterial).color ?? null) : null);
        view.reach(false);
        r.autoClear = auto;
      }
      // The pair where something hides it: faint, over what is in front (the colour pass's depth is still there).
      const pairMeshes = [...focusMats.keys()].filter((m) => m !== sel);
      if (pairMeshes.length) {
        r.autoClear = false;
        scene.background = null;
        r.clippingPlanes = view.planes;
        const group = new THREE.Group();
        const shadows = pairMeshes.map((m) => {
          const ghost = new THREE.Mesh(m.geometry, st.hidden[(m.userData.side as Side) ?? "a"]);
          ghost.matrixAutoUpdate = false; ghost.matrix.copy(m.matrix); ghost.matrixWorld.copy(m.matrixWorld); ghost.frustumCulled = false;
          return ghost;
        });
        group.add(...shadows);
        r.render(group, cam);
        r.autoClear = auto;
      }
      // Normals and depth: what is solid only.
      for (const m of this.models) if (m.glass?.visible) { m.glass.visible = false; hiddenForNormals.push(m.glass); }
      for (const o of this.overlay.children) if (((o as THREE.Mesh).material as THREE.Material)?.transparent && o.visible) { o.visible = false; hiddenForNormals.push(o); }
      scene.background = new THREE.Color(0, 0, 0);
      r.clippingPlanes = view.planes;
      scene.overrideMaterial = st.normals;
      r.setRenderTarget(nrt);
      r.render(scene, cam);
    } finally {
      scene.overrideMaterial = null;
      cam.layers.set(0);
      view.reach(false);
      for (const o of hiddenForNormals) o.visible = true;
      r.autoClear = auto;
      r.setRenderTarget(null);
      r.clippingPlanes = [];
      scene.background = background;
      this.models.forEach((m, i) => { m.mesh.material = materials[i][0]; if (m.glass && materials[i][1]) m.glass.material = materials[i][1]!; });
      for (const [mesh, mat] of focusMats) mesh.material = mat;
      unpaint?.();
      restore();
      this.clipping.push(...box);
    }
  }

  /** The 3D view, in its style: as it is, or (Shaded with edges, Hidden line) through the drawings' passes: the
   * colour (lit, or paper fills with the pair flat), normals and depth, and the composite's linework on top. `g`: its
   * viewport, already set. */
  private render3d(cam: THREE.Camera, g: Rect) {
    const r = this.renderer;
    if ((this.style !== "edges" && this.style !== "hidden") || this.lifted) {
      if (this.styled && !this.lifted) { for (const t of this.styled) t.dispose(); this.styled = null; }   // their memory back
      r.render(this.scene, cam);
      return;
    }
    const st = this.drawStyle, scene = this.scene, dpr = r.getPixelRatio();
    const w = Math.max(1, Math.round(g.w * dpr)), h = Math.max(1, Math.round(g.h * dpr));
    if (!this.styled || this.styled[0].width !== w || this.styled[0].height !== h) this.styled = targets(w, h, ...(this.styled ?? []));
    const [rt, nrt] = this.styled;
    const hidden = this.style === "hidden";
    const background = scene.background;
    const materials = this.models.map((m) => [m.mesh.material, m.glass?.material] as const);
    const swapped = new Map<THREE.Mesh, THREE.Material | THREE.Material[]>();
    const off: THREE.Object3D[] = [];
    try {
      if (hidden) {
        this.models.forEach((m, i) => {
          if (m.mesh.material === this.solid || m.mesh.material === this.consistent) m.mesh.material = st.fills[i % st.fills.length];
        });
        for (const o of [...this.focusLayer.children, ...this.selectionLayer.children]) {
          const mesh = o as THREE.Mesh;
          if (!mesh.isMesh || (mesh.material as THREE.Material).transparent && !this.selectionLayer.children.includes(o)) continue;
          swapped.set(mesh, mesh.material);
          mesh.material = this.selectionLayer.children.includes(o) ? st.selected : st.side[(mesh.userData.side as Side) ?? "a"];
        }
        scene.background = PAPER;
      }
      r.setRenderTarget(rt);
      r.render(scene, cam);
      // Normals and depth of what is solid: not glass, ghosts or the 3D view's own helpers.
      for (const m of this.models) {
        if (m.glass?.visible) { m.glass.visible = false; off.push(m.glass); }
        const mat = m.mesh.material as THREE.Material;
        if (mat.transparent && m.mesh.visible) { m.mesh.visible = false; off.push(m.mesh); }
      }
      for (const o of this.overlay.children) if (((o as THREE.Mesh).material as THREE.Material)?.transparent && o.visible) { o.visible = false; off.push(o); }
      const layers = cam.layers.mask;
      cam.layers.set(0);
      scene.overrideMaterial = st.normals;
      scene.background = new THREE.Color(0, 0, 0);
      r.setRenderTarget(nrt);
      r.render(scene, cam);
      cam.layers.mask = layers;
    } finally {
      scene.overrideMaterial = null;
      for (const o of off) o.visible = true;
      r.setRenderTarget(null);
      scene.background = background;
      this.models.forEach((m, i) => { m.mesh.material = materials[i][0]; if (m.glass && materials[i][1]) m.glass.material = materials[i][1]!; });
      for (const [mesh, mat] of swapped) mesh.material = mat;
    }
    const persp = cam === this.camera;
    const u = st.composite.uniforms;
    u.color.value = rt.texture; u.normals.value = nrt.texture; u.depth.value = nrt.depthTexture;
    u.texel.value.set(1 / w, 1 / h);
    u.near.value = (cam as THREE.PerspectiveCamera).near; u.far.value = (cam as THREE.PerspectiveCamera).far; u.ortho.value = persp ? 0 : 1;
    u.tol.value = persp ? 0.015 : ((this.ortho.top - this.ortho.bottom) / g.h) * 3;
    u.cutWidth.value = 0; u.edges.value = 1;
    u.cropMin.value.set(0, 0); u.cropMax.value.set(1, 1);
    u.shiftScale.value = 1; u.shiftAt.value.set(0, 0);
    st.drawComposite(r);
    // The 3D view's helpers (marker, outlines through walls, grips, measure) over the drawing.
    const auto = r.autoClear, layers = cam.layers.mask;
    r.autoClear = false;
    cam.layers.set(1);
    scene.background = null;
    r.clearDepth();
    r.render(scene, cam);
    scene.background = background;
    cam.layers.mask = layers;
    r.autoClear = auto;
  }

  /** Draw a drawing pane's annotation layer when what it shows changed (its view, the other views' marks, the clash,
   * the 3D camera seen in plan). */
  private annotatePane(pane: Pane) {
    const view = pane.view!, layer = pane.el.querySelector("canvas");
    if (!layer) return;
    const c = this.lastClash && this.marker.visible ? this.lastClash : null;
    const cam3 = this.pane3dShown() && pane.spec.kind === "plan" ? { position: this.camera.position, target: this.controls.target, fov: this.camera.fov } : null;
    const others = this.panes.map((p, index) => ({ index, spec: p.spec, title: viewTitle(this.levels, p.spec) }))
      .filter((o) => o.spec.kind !== "3d" && o.index !== this.panes.indexOf(pane)) as { index: number; spec: DrawingSpec; title: string }[];
    const key = [view.cameraKey(pane.rect), JSON.stringify(others.map((o) => o.spec)), JSON.stringify(pane.spec), c?.zone.min.toArray(),
      c?.zone.max.toArray(), this.markerLabel.textContent, cam3 ? [...cam3.position.toArray(), ...cam3.target.toArray()].map((n) => n.toFixed(2)) : "",
      this.datums ? this.datums.grids.length : -1, layer.width].join("|");
    if (pane.annotated === key) return;
    pane.annotated = key;
    const g = layer.getContext("2d");
    if (!g) return;
    pane.handles = annotate(g, layer.width / Math.max(pane.rect.w, 1), {
      view, rect: pane.rect, index: this.panes.indexOf(pane), title: viewTitle(this.levels, pane.spec), levels: this.levels,
      left: pane.rect.x < 4 ? 56 : 0,
      grids: this.datums?.grids ?? [], model: this.modelBox(), clash: c ? { zone: c.zone, label: this.markerLabel.textContent || "Clash" } : null,
      others, camera3d: cam3,
    });
  }

  /** Swap in the drawings' visibility (the whole model, where the 3D view's Context or Isolate hide part of it);
   * returns what puts the 3D view's back. */
  /** The filters' colours for a drawing's fill pass (`DrawingStyle.paintFill` reads each element's colour): coloured
   * elements in their colour lightened towards paper, the rest in their file's tint; the 3D colours back after. */
  private useDrawingPaint(paint: Map<string, string>): () => void {
    const saved: [LoadedElement, THREE.Vector4][] = [];
    this.models.forEach((m, i) => {
      const tint = this.drawStyle.tint(i);
      for (const el of m.byGlobalId.values()) {
        if (el.mesh !== m.mesh) continue;     // see-through elements keep the glass fill
        const was = new THREE.Vector4();
        el.mesh.getColorAt(el.instanceId, was);
        saved.push([el, was]);
        const p = paint.get(el.globalId);
        const c = p ? this.drawStyle.onPaper(p) : tint;
        el.mesh.setColorAt(el.instanceId, this.scratch.set(c.r, c.g, c.b, 1));
      }
    });
    return () => { for (const [el, was] of saved) el.mesh.setColorAt(el.instanceId, was); };
  }

  private useDrawingVisibility(): () => void {
    if (!this.drawVis.length) return () => undefined;
    for (const d of this.drawVis) d.el.mesh.setVisibleAt(d.el.instanceId, d.vDraw);
    return () => { for (const d of this.drawVis) d.el.mesh.setVisibleAt(d.el.instanceId, d.v3d); };
  }

  /** Take every unpinned drawing pane to a clash (docs/views.md, "Every view goes to the clash"): a plan at its level
   * with the cut through it, a section through it along the run that moves, an elevation facing the section's way; each
   * framed on where the pair meets. `only`: one pane (its own Go to clash). */
  private clashViews(ids: string[], zone: THREE.Box3, point: THREE.Vector3 | null, only?: Pane) {
    this.lastClash = { ids, zone: zone.clone(), point: point?.clone() ?? null };
    const panes = only ? [only] : this.panes.filter((p) => p.view && !p.pinned);
    if (!panes.length) return;
    const model = this.modelBox();
    const p = toIfc(point ?? zone.getCenter(new THREE.Vector3()));
    const runBox = this.boxOf([this.runOf(ids)].filter((g): g is string => !!g));
    const run = runBox.isEmpty() ? null : { min: [runBox.min.x, -runBox.max.z, runBox.min.y], max: [runBox.max.x, -runBox.min.z, runBox.max.y] };
    const around = zone.clone().expandByScalar(Math.max(this.reach(2, 0.2), zone.getSize(new THREE.Vector3()).length() * 0.5));
    let look: [number, number] | null = null;
    const section = this.panes.find((q) => q.spec.kind === "section");
    const last = (q: Pane) => (q.spec.kind === "elevation" ? 1 : 0);   // an elevation turns the way the section looks
    for (const pane of [...panes].sort((a, b) => last(a) - last(b))) {
      let spec = pane.spec as DrawingSpec;
      if (spec.kind === "plan") spec = planThrough(this.levels, p[2], spec);
      else if (spec.kind === "section") {
        const pad = this.reach(0.5, 0.05);
        const crop = { left: 4, right: 4, bottom: model.min.y - pad, top: model.max.y + pad };
        spec = sectionThrough(p, run, { ...spec, flip: false, crop }, this.reach(2, 0.2));
        spec = { ...spec, far: farBehind(spec, zone, this.reach(2, 0.2)) };
        look = sectionFrame(spec).look;
      } else {
        const from = look ?? (section ? sectionFrame(section.spec as never).look : null);
        if (from) spec = { ...spec, facing: facingFor(from) };
      }
      pane.spec = spec;
      pane.view!.configure(spec, this.levels, model);
      pane.view!.frame(around, pane.rect, 0.05);
    }
    this.onChange?.();
  }
  private lastClash: { ids: string[]; zone: THREE.Box3; point: THREE.Vector3 | null } | null = null;
  /** Is there a clash on screen for a pane's Go to the clash? */
  get hasClash() { return !!this.lastClash; }

  /** One pane to the last clash (its own Go to clash, pinned or not). */
  paneToClash(i: number) {
    const c = this.lastClash, pane = this.panes[i];
    if (!c) return;
    if (c && pane?.view) this.clashViews(c.ids, c.zone, c.point, pane);
  }

  /** The side of a clash that moves: not structure, else the longer run. */
  private runOf(ids: string[]): string | null {
    const found = ids.filter((g) => this.has(g));
    const free = found.filter((g) => !FIXED.test(this.info.get(g)?.cls ?? ""));
    const pool = free.length ? free : found;
    const len = (g: string) => { const b = this.boxOf([g]); return Math.max(b.max.x - b.min.x, b.max.z - b.min.z); };
    return pool.sort((a, b) => len(b) - len(a))[0] ?? null;
  }

  // ---------------------------------------------------------------- section box and marker

  /** Cut the model to a box (docs/views.md, "Section box anywhere"): `box`, else round the clash, else the selected
   * element, else what is in view; `margin` metres beyond it. Off with `on` false. Its faces have grips to drag. */
  setSection(on: boolean, margin = this.reach(1.5, 0.1), box?: THREE.Box3) {
    if (this.sectionHelper) { this.scene.remove(this.sectionHelper); this.sectionHelper = null; }
    this.clipping.length = 0;
    this.sectionBox = null;
    if (on) {
      let b = (box ?? this.boxAroundFocus()).clone();
      if (b.isEmpty() && !box) b = this.selection ? this.boxOf([this.selection]) : b;
      if (b.isEmpty() && !box) { b = this.boxInView(); margin = 0; }
      if (b.isEmpty()) return false;
      b.expandByScalar(margin);
      this.sectionBox = b;
      const { min, max } = b;
      this.clipping.push(
        new THREE.Plane(new THREE.Vector3(1, 0, 0), -min.x), new THREE.Plane(new THREE.Vector3(-1, 0, 0), max.x),
        new THREE.Plane(new THREE.Vector3(0, 1, 0), -min.y), new THREE.Plane(new THREE.Vector3(0, -1, 0), max.y),
        new THREE.Plane(new THREE.Vector3(0, 0, 1), -min.z), new THREE.Plane(new THREE.Vector3(0, 0, -1), max.z));
      this.sectionHelper = new THREE.Box3Helper(b, new THREE.Color("#2f5d8a"));
      this.sectionHelper.layers.set(1);
      this.scene.add(this.sectionHelper);
    }
    this.placeGrips();
    for (const m of [this.solid, this.ghost, this.glass, this.hitMaterial, ...Object.values(this.focusMaterials),
      ...Object.values(this.focusGlass), ...[...this.linkMaterials.values()].map((x) => x.mesh), ...this.drawStyle.fills,
      this.drawStyle.glass, ...Object.values(this.drawStyle.side), this.drawStyle.selected, this.drawStyle.normals]) m.needsUpdate = true;
    return true;
  }

  /** The section box's current extent, or null when it is off. */
  get section(): THREE.Box3 | null { return this.sectionBox?.clone() ?? null; }

  /** What is in view: the model round the target, a cube about as wide as the camera is far from it. */
  private boxInView(): THREE.Box3 {
    const all = new THREE.Box3();
    this.models.forEach((m, i) => { if (!this.hiddenModels.has(i)) for (const b of batches(m)) { b.computeBoundingBox(); all.union(b.boundingBox!); } });
    const size = Math.max(this.camera.position.distanceTo(this.controls.target), this.reach(2, 0.5));
    return new THREE.Box3().setFromCenterAndSize(this.controls.target, new THREE.Vector3().setScalar(size)).intersect(all);
  }

  private buildGrips() {
    const mat = new THREE.MeshBasicMaterial({ color: "#2f5d8a", depthTest: false, transparent: true, opacity: 0.9 });
    const geo = new THREE.SphereGeometry(1, 16, 12);
    for (const [axis, side] of [["x", "min"], ["x", "max"], ["y", "min"], ["y", "max"], ["z", "min"], ["z", "max"]] as const) {
      const m = new THREE.Mesh(geo, mat);
      m.userData = { axis, side };
      m.renderOrder = 12;
      m.layers.set(1);
      this.grips.add(m);
    }
    this.grips.visible = false;
  }

  /** Grips at the middle of each face of the section box. */
  private placeGrips() {
    const b = this.sectionBox;
    this.grips.visible = !!b && !this.lifted;   // never in a picture
    if (!b) return;
    const c = b.getCenter(new THREE.Vector3());
    for (const g of this.grips.children) {
      const { axis, side } = g.userData as { axis: "x" | "y" | "z"; side: "min" | "max" };
      g.position.copy(c);
      g.position[axis] = b[side][axis];
    }
  }

  /** The grip under the pointer (within 12 px), with what dragging it needs: the screen direction of its axis and the
   * pixels a metre along it covers. */
  private gripAt(e: PointerEvent) {
    if (!this.sectionBox || !this.grips.visible) return null;
    const r = this.pane3d.getBoundingClientRect(), cam = this.activeCamera();
    const toPx = (v: THREE.Vector3) => { const q = v.clone().project(cam); return new THREE.Vector2((q.x + 1) / 2 * r.width, (1 - q.y) / 2 * r.height); };
    const at = new THREE.Vector2(e.clientX - r.left, e.clientY - r.top);
    for (const g of this.grips.children) {
      const p = toPx(g.position);
      if (p.distanceTo(at) > 12) continue;
      const { axis, side } = g.userData as { axis: "x" | "y" | "z"; side: "min" | "max" };
      const step = new THREE.Vector3(); step[axis] = 1;
      const q = toPx(g.position.clone().add(step)).sub(p);
      const ppm = q.length();
      if (ppm < 1e-6) continue;   // the axis points at the camera: drag another grip
      return { axis, side, box: this.sectionBox.clone(), x: e.clientX, y: e.clientY, perPx: q.normalize(), ppm };
    }
    return null;
  }

  /** Drag a grip: its face follows the pointer along its axis, live; the box never turns inside out. */
  private dragGrip(e: PointerEvent) {
    const g = this.grip;
    if (!g) return;
    const metres = new THREE.Vector2(e.clientX - g.x, e.clientY - g.y).dot(g.perPx) / g.ppm;
    const b = g.box.clone(), least = this.reach(0.05, 0.01);
    if (g.side === "min") b.min[g.axis] = Math.min(g.box.min[g.axis] + metres, b.max[g.axis] - least);
    else b.max[g.axis] = Math.max(g.box.max[g.axis] + metres, b.min[g.axis] + least);
    this.setSection(true, 0, b);
  }

  /** The focus elements, clipped to a few metres around the marker so a long run does not make a huge box. */
  private boxAroundFocus(): THREE.Box3 {
    const box = this.boxOf(this.focusIds());
    if (this.marker.visible) {
      const around = new THREE.Box3().setFromCenterAndSize(this.marker.position, new THREE.Vector3().setScalar(this.reach(4, 0.3)));
      return box.isEmpty() ? around : box.intersect(around).union(new THREE.Box3().setFromCenterAndSize(this.marker.position,
        new THREE.Vector3().setScalar(this.reach(1, 0.1))));
    }
    return box;
  }

  private buildMarker() {
    const mat = new THREE.MeshBasicMaterial({ color: "#ffb000", depthTest: false, transparent: true, opacity: 0.95 });
    const dot = new THREE.Mesh(new THREE.SphereGeometry(0.05, 16, 12), mat);
    const ring = new THREE.Mesh(new THREE.TorusGeometry(0.18, 0.012, 8, 48), mat);
    dot.renderOrder = ring.renderOrder = 10;
    dot.layers.set(1); ring.layers.set(1);   // the 3D view's: a drawing marks the clash its own way
    this.marker.add(dot, ring);
    this.marker.visible = false;
  }

  setMarker(point: THREE.Vector3 | null, label = "") {
    this.version++;
    if (!point) this.lastClash = null;   // no clash on screen: Go to the clash has nowhere to go
    this.marker.visible = !!point;
    if (point) this.marker.position.copy(point);
    this.markerLabel.textContent = label;
  }

  // ---------------------------------------------------------------- picking and measuring

  /** The element (and point on it) under the pointer, including elements in focus. */
  pickAt(ev: MouseEvent, opts: { ghosts?: boolean } = {}): Pick | null {
    const pane = this.panes.length > 1 ? this.paneAt(ev.clientX, ev.clientY) : null;
    if (pane?.view) return this.pickDrawing(pane, ev);
    const r = this.pane3d.getBoundingClientRect();
    const ndc = new THREE.Vector2(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1);
    this.raycaster.setFromCamera(ndc, this.activeCamera());
    const targets: THREE.Object3D[] = [...this.focusLayer.children,
      ...this.models.filter((_, i) => !this.hiddenModels.has(i)).flatMap(batches)];
    const ghostly = !opts.ghosts && this.focusIds().length > 0 && this.mode !== "shaded";
    // A see-through element (a safety zone round a robot) is picked only where nothing solid is under the pointer,
    // or it would swallow every click on what stands inside it.
    let behindGlass: Pick | null = null;
    for (const hit of this.raycaster.intersectObjects(targets, false)) {
      if (this.clipping.length && !this.sectionBox?.containsPoint(hit.point)) continue;
      if (hit.object.userData.globalId) return { globalId: hit.object.userData.globalId, point: hit.point };
      if (ghostly) continue;  // see-through context is not pickable: click through it to the focus
      const solid = this.models.find((m) => m.mesh === hit.object);
      const glass = this.models.find((m) => m.glass === hit.object);
      if (hit.batchId === undefined) continue;
      const el = solid ? solid.byInstance.get(hit.batchId) : glass?.glassByInstance.get(hit.batchId);
      if (el && solid) return { globalId: el.globalId, point: hit.point };
      if (el) behindGlass ??= { globalId: el.globalId, point: hit.point };
    }
    return behindGlass;
  }

  pick(ev: MouseEvent): string | null { return this.pickAt(ev)?.globalId ?? null; }

  /** A pick in a drawing pane: its camera, what it shows (the whole model unless drawings follow the 3D view), and
   * only what its cut, bottom, far clip and crop keep. */
  private pickDrawing(pane: Pane, ev: MouseEvent): Pick | null {
    const view = pane.view!, r = pane.el.getBoundingClientRect();
    view.updateCamera(pane.rect, this.sceneDiag() * 2 + 10);
    const ndc = new THREE.Vector2(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1);
    this.raycaster.setFromCamera(ndc, view.camera);
    const restore = this.useDrawingVisibility();
    try {
      const targets: THREE.Object3D[] = [...this.focusLayer.children.filter((o) => (o as THREE.Mesh).isMesh),
        ...this.models.filter((_, i) => !this.hiddenModels.has(i)).flatMap(batches)];
      let behindGlass: Pick | null = null;
      for (const hit of this.raycaster.intersectObjects(targets, false)) {
        if (!view.keeps(hit.point)) continue;
        if (hit.object.userData.globalId) return { globalId: hit.object.userData.globalId, point: hit.point };
        if (hit.batchId === undefined) continue;
        const solid = this.models.find((m) => m.mesh === hit.object), glass = this.models.find((m) => m.glass === hit.object);
        const el = solid ? solid.byInstance.get(hit.batchId) : glass?.glassByInstance.get(hit.batchId);
        if (el && solid) return { globalId: el.globalId, point: hit.point };
        if (el) behindGlass ??= { globalId: el.globalId, point: hit.point };
      }
      return behindGlass;
    } finally { restore(); }
  }

  // ---------------------------------------------------------------- measuring (docs/measure.md)

  private measures: Measurement[] = [];
  private measureNext = 1;
  private measuring = false;
  private snapping = true;
  /** The first point of a measurement under way, and the view it is taken in (null: 3D, else a pane's key). */
  private draft: { point: THREE.Vector3; pane: number | null } | null = null;
  /** What the pointer snaps to now. */
  private hover: { point: THREE.Vector3; kind: SnapKind; pane: number | null } | null = null;
  private measureStamp = 0;
  private measureDrawn = "";
  private measureCanvas: HTMLCanvasElement;
  private snapCache = new Map<string, Candidates>();

  get measurements(): readonly Measurement[] { return this.measures; }
  /** A first point is set, waiting for the second. */
  get measureOpen(): boolean { return !!this.draft; }
  setMeasuring(on: boolean) { this.measuring = on; this.draft = null; this.hover = null; this.measureStamp++; }
  setSnap(on: boolean) { this.snapping = on; this.hover = null; this.measureStamp++; }
  removeMeasurement(id: number) { this.measures = this.measures.filter((m) => m.id !== id); this.measureStamp++; this.onChange?.(); }
  clearMeasurements() { this.measures = []; this.draft = null; this.measureStamp++; this.onChange?.(); }

  /** The pointer moved while measuring (null: it left the stage): what it snaps to, and the rubber band. */
  measureHover(ev: MouseEvent | null) {
    if (!this.measuring) return;
    this.hover = ev ? this.snapAt(ev) : null;
    this.measureStamp++;
  }

  /** A click while measuring: the first point, or the second, which keeps the measurement. A click in another view
   * starts there. False when there was nothing to measure on (no model under the pointer in the 3D view). */
  measureClick(ev: MouseEvent): boolean {
    const s = this.snapAt(ev);
    if (!s) return false;
    if (this.draft && this.draft.pane === s.pane && this.draft.point.distanceToSquared(s.point) > 1e-10) {
      const pane = s.pane == null ? null : this.panes.find((p) => p.key === s.pane);
      const view = pane && pane.spec.kind !== "3d" ? viewTitle(this.levels, pane.spec) : "3D";
      this.measures = [...this.measures, { id: this.measureNext++, a: this.draft.point.clone(), b: s.point.clone(), pane: s.pane, view }];
      this.draft = null;
      this.onChange?.();
    } else this.draft = { point: s.point.clone(), pane: s.pane };
    this.hover = s;
    this.measureStamp++;
    return true;
  }

  /** Esc while measuring: drop the first point of a measurement under way. False when there was none. */
  measureCancel(): boolean {
    if (!this.draft) return false;
    this.draft = null;
    this.measureStamp++;
    return true;
  }

  /** What a measuring pointer lands on: in a drawing, on its plane; in 3D, on the model. Snapped to an end, a midpoint
   * or an edge when snapping is on and one is near, else the point under the pointer. */
  private snapAt(ev: MouseEvent): { point: THREE.Vector3; kind: SnapKind; pane: number | null } | null {
    const pane = this.panes.length > 1 ? this.paneAt(ev.clientX, ev.clientY) : null;
    return pane?.view ? this.snapDrawing(pane, ev) : this.snap3d(ev);
  }

  private snap3d(ev: MouseEvent): { point: THREE.Vector3; kind: SnapKind; pane: null } | null {
    const r = this.pane3d.getBoundingClientRect();
    const cursor = new THREE.Vector2(ev.clientX - r.left, ev.clientY - r.top);
    const hit = this.pickAt(ev, { ghosts: true });
    if (!hit) return null;
    if (!this.snapping) return { point: hit.point.clone(), kind: "face", pane: null };
    const ray = this.raycaster.ray.clone(), cam = this.activeCamera();
    const project = (p: THREE.Vector3) => {
      const v = p.clone().project(cam);
      return v.z > 1 || v.z < -1 ? null : new THREE.Vector2(((v.x + 1) / 2) * r.width, ((1 - v.y) / 2) * r.height);
    };
    const s = pickSnap(cursor, this.edgesFor(hit.globalId), project, ray)
      ?? this.snapNear(ev, cursor, hit.globalId, (g) => this.edgesFor(g), project, ray, (e) => this.pickAt(e, { ghosts: true }));
    return s ? { point: s.point, kind: s.kind, pane: null } : { point: hit.point.clone(), kind: "face", pane: null };
  }

  private snapDrawing(pane: Pane, ev: MouseEvent): { point: THREE.Vector3; kind: SnapKind; pane: number } {
    const view = pane.view!, r = pane.el.getBoundingClientRect();
    const cursor = new THREE.Vector2(ev.clientX - r.left, ev.clientY - r.top);
    const hit = this.pickDrawing(pane, ev);   // also sets the view's camera for this frame
    const base = { point: hit ? onPlane(view, hit.point) : view.fromPane(cursor.x, cursor.y, pane.rect), kind: (hit ? "face" : "free") as SnapKind, pane: pane.key };
    if (!this.snapping) return base;
    const project = (p: THREE.Vector3) => view.toPane(p, pane.rect);
    const cands = (g: string) => this.drawingCandidates(view, g);
    const s = (hit ? pickSnap(cursor, cands(hit.globalId), project) : null)
      ?? this.snapNear(ev, cursor, hit?.globalId ?? null, cands, project, null, (e) => this.pickDrawing(pane, e));
    return s ? { point: s.point, kind: s.kind, pane: pane.key } : base;
  }

  /** When the element under the pointer gives no snap: the elements under four points 10 px round it. */
  private snapNear(ev: MouseEvent, cursor: THREE.Vector2, first: string | null, cands: (g: string) => Candidates,
    project: (p: THREE.Vector3) => THREE.Vector2 | null, ray: THREE.Ray | null, pick: (e: MouseEvent) => Pick | null) {
    const seen = new Set(first ? [first] : []);
    const all: Candidates = { ends: [], mids: [], segs: [] };
    for (const [dx, dy] of [[10, 0], [-10, 0], [0, 10], [0, -10]]) {
      const h = pick({ clientX: ev.clientX + dx, clientY: ev.clientY + dy } as MouseEvent);
      if (!h || seen.has(h.globalId)) continue;
      seen.add(h.globalId);
      const c = cands(h.globalId);
      all.ends.push(...c.ends); all.mids.push(...c.mids); all.segs.push(...c.segs);
    }
    return all.segs.length ? pickSnap(cursor, all, project, ray) : null;
  }

  private cached(key: string, make: () => Candidates): Candidates {
    let c = this.snapCache.get(key);
    if (!c) {
      if (this.snapCache.size > 400) this.snapCache.clear();
      c = make();
      this.snapCache.set(key, c);
    }
    return c;
  }

  /** An element's feature edges (the outlines' 25° edges) in world space: its corners, midpoints and edges. */
  private edgesFor(gid: string): Candidates {
    const f = this.find(gid);
    if (!f) return { ends: [], mids: [], segs: [] };
    const m = this.matrixOf(f.el);
    return this.cached(`e|${gid}|${m.elements.join(",")}`, () => candidatesOf(this.worldEdges(gid, f, m)));
  }

  private worldEdges(gid: string, f: Found, m: THREE.Matrix4): Segment[] {
    const pos = this.edgeGeometryOf(gid, f).getAttribute("position");
    const out: Segment[] = [];
    for (let i = 0; i + 1 < pos.count; i += 2) {
      out.push([new THREE.Vector3().fromBufferAttribute(pos, i).applyMatrix4(m), new THREE.Vector3().fromBufferAttribute(pos, i + 1).applyMatrix4(m)]);
    }
    return out;
  }

  /** What a drawing shows of an element to snap to: its edges as the view keeps them, laid on the view's plane, and
   * where it cuts, the cut outline (the element's triangles cut by the plane, joined into straight runs). */
  private drawingCandidates(view: DrawingView, gid: string): Candidates {
    const f = this.find(gid);
    if (!f) return { ends: [], mids: [], segs: [] };
    const m = this.matrixOf(f.el);
    const key = `d|${gid}|${m.elements.join(",")}|${view.contentKey({ x: 0, y: 0, w: 1, h: 1 })}|${view.look.dot(view.center).toFixed(4)}`;
    return this.cached(key, () => {
      const segs: Segment[] = [];
      for (const [a, b] of this.worldEdges(gid, f, m)) {
        const kept = clipSegment(a, b, view.planes);
        if (kept) segs.push([onPlane(view, kept[0]), onPlane(view, kept[1])]);
      }
      if (view.cut) {
        const g = this.geometryOf(f), index = g.getIndex()!, pos = g.getAttribute("position");
        const { start, count } = g.drawRange, tri = new Float32Array(count * 3), t = new THREE.Vector3();
        for (let i = 0; i < count; i++) { t.fromBufferAttribute(pos, index.getX(start + i)).applyMatrix4(m); tri[i * 3] = t.x; tri[i * 3 + 1] = t.y; tri[i * 3 + 2] = t.z; }
        segs.push(...mergeRuns(cutSegments(tri, view.cut)).map(([a, b]) => [onPlane(view, a), onPlane(view, b)] as Segment));
      }
      return candidatesOf(segs);
    });
  }

  /** The measurements, the one under way and the snap glyph, on a 2D canvas over the stage. Drawn again only when
   * something on it moved: the measurements, the pointer, a camera, a pane. */
  private drawMeasures() {
    const c = this.measureCanvas, W = this.host.clientWidth || 1, H = this.host.clientHeight || 1;
    const dpr = Math.min(window.devicePixelRatio || 1, 2), panes = this.visiblePanes(), cam = this.activeCamera();
    const on = this.measuring && !!(this.measures.length || this.draft || this.hover);
    const key = !on ? "off" : [this.measureStamp, W, H, ...panes.map((p) => `${p.rect.x},${p.rect.y},${p.rect.w},${p.rect.h}:${p.view
      ? p.view.cameraKey(p.rect) : [...cam.matrixWorld.elements, ...(cam as THREE.PerspectiveCamera).projectionMatrix.elements].map((n) => n.toFixed(5)).join(",")}`)].join("|");
    if (key === this.measureDrawn) return;
    this.measureDrawn = key;
    if (c.width !== Math.round(W * dpr) || c.height !== Math.round(H * dpr)) { c.width = Math.round(W * dpr); c.height = Math.round(H * dpr); }
    const g = c.getContext("2d");
    if (!g) return;
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, W, H);
    if (!on) return;
    for (const pane of panes) {
      const r = pane.rect, is3d = pane.spec.kind === "3d", here = is3d ? null : pane.key;
      const project = is3d
        ? (p: THREE.Vector3) => { const v = p.clone().project(cam); return v.z > 1 || v.z < -1 ? null : new THREE.Vector2(((v.x + 1) / 2) * r.w, ((1 - v.y) / 2) * r.h); }
        : (p: THREE.Vector3) => pane.view!.toPane(p, r);
      g.save();
      g.beginPath(); g.rect(r.x, r.y, r.w, r.h); g.clip();
      g.translate(r.x, r.y);
      // The 3D view shows every measurement (each is two points in the model); a drawing, the ones taken in it. A label
      // that would sit on another moves up until it is clear.
      const labels: { x: number; y: number; w: number }[] = [];
      for (const m of this.measures) {
        if (!is3d && m.pane !== here) continue;
        dimension(g, project(m.a), project(m.b), `M${m.id} · ${measureText(m).length}`, !is3d, false, labels);
      }
      const hover = this.hover && this.hover.pane === here ? this.hover : null;
      if (this.draft && this.draft.pane === here) {
        dimension(g, project(this.draft.point), hover ? project(hover.point) : null,
          hover ? measureText({ a: this.draft.point, b: hover.point }).length : "", !is3d, true);
      }
      if (hover) snapGlyph(g, project(hover.point), hover.kind);
      g.restore();
    }
  }

  // ---------------------------------------------------------------- frame loop, labels, misc

  private frameTick() {
    if (this.flight) {
      const k = Math.min((performance.now() - this.flight.t0) / this.flight.ms, 1);
      const e = k < 0.5 ? 4 * k * k * k : 1 - Math.pow(-2 * k + 2, 3) / 2;  // ease in-out
      this.camera.position.lerpVectors(this.flight.from[0], this.flight.to[0], e);
      this.controls.target.lerpVectors(this.flight.from[1], this.flight.to[1], e);
      if (k >= 1) this.flight = null;
    }
    this.controls.update();
    this.adjustClipRange();
    this.drawFrame();
  }

  /** Every pane: the 3D view rendered, each drawing view drawn when something changed and composited from its target;
   * then the view cube. Also what a capture puts back on screen. */
  private drawFrame() {
    const W = this.host.clientWidth || 1, H = this.host.clientHeight || 1;
    const r3 = this.rect3d();
    if (this.projection === "orthographic") this.syncOrtho(r3.w / Math.max(r3.h, 1));
    const cam = this.activeCamera();
    this.place(this.markerLabel, this.marker.visible ? this.marker.position : null);
    // Constant sizes on screen, at any scale: a floor in metres made the marker swallow a 100 mm part.
    const perPx = (p: THREE.Vector3) => this.projection === "orthographic" ? (this.ortho.top - this.ortho.bottom) / r3.h
      : 2 * Math.tan(THREE.MathUtils.degToRad(this.camera.fov) / 2) * Math.max(this.camera.position.distanceTo(p), 1e-4) / r3.h;
    if (this.marker.visible) {
      // As far as the camera is (distance / 8, as always), or the distance that frames as the orthographic view does.
      const d = this.projection === "orthographic" ? (this.ortho.top - this.ortho.bottom) / (2 * Math.tan(THREE.MathUtils.degToRad(this.camera.fov) / 2))
        : this.camera.position.distanceTo(this.marker.position);
      this.marker.scale.setScalar(Math.max(d / 8, 1e-4));
      this.marker.children[1].lookAt(cam.position);
    }
    for (const g of this.grips.children) g.scale.setScalar(Math.max(perPx(g.position) * 6, 1e-5));
    const r = this.renderer;
    // Nothing open (the start page, models loading): one empty stage, not the layout's panes as patches of sky and
    // paper behind the load card. The layout stays chosen; its panes come back with the models.
    const panes = this.visiblePanes();
    if (!this.models.length || (panes.length === 1 && panes[0].spec.kind === "3d")) {
      r.setScissorTest(false);
      r.setViewport(0, 0, W, H);
      this.render3d(cam, { x: 0, y: 0, w: W, h: H });
    } else {
      r.setScissorTest(true);
      for (const pane of panes) {
        const g = { x: pane.rect.x, y: H - pane.rect.y - pane.rect.h, w: pane.rect.w, h: pane.rect.h };
        r.setViewport(g.x, g.y, g.w, g.h);
        r.setScissor(g.x, g.y, g.w, g.h);
        if (pane.spec.kind === "3d") this.render3d(cam, g);
        else if (pane.view) { this.renderDrawing(pane, g); this.annotatePane(pane); }
      }
    }
    if (this.models.length && this.pane3dShown()) {
      const g = { x: r3.x, y: H - r3.y - r3.h, w: r3.w, h: r3.h };
      this.cube.render(r, cam, g);
    }
    r.setScissorTest(false);
    r.setViewport(0, 0, W, H);
    this.drawMeasures();
  }

  /** Near/far planes follow the distance to the target, so close-ups don't clip and far views don't z-fight. */
  private adjustClipRange() {
    const d = this.camera.position.distanceTo(this.controls.target);
    const near = Math.min(Math.max(d / 200, 0.0005), 1);  // small parts are seen from centimetres away
    if (Math.abs(near - this.camera.near) / near > 0.2) {
      this.camera.near = near;
      this.camera.far = Math.max(near * 100000, 2000);
      this.camera.updateProjectionMatrix();
    }
  }

  private label(cls: string) {
    const el = document.createElement("div");
    el.className = `viewer-label ${cls}`;
    this.host.appendChild(el);
    return el;
  }

  private place(el: HTMLDivElement, p: THREE.Vector3 | null) {
    if (!p || !el.textContent || !this.pane3dShown()) { el.style.display = "none"; return; }
    const v = p.clone().project(this.activeCamera());
    if (v.z > 1) { el.style.display = "none"; return; }
    const r = this.rect3d();
    el.style.display = "block";
    el.style.left = `${r.x + ((v.x + 1) / 2) * r.w}px`;
    el.style.top = `${r.y + ((1 - v.y) / 2) * r.h}px`;
  }

  /** The layout as on screen: every pane, then each drawing's annotation layer over it. */
  snapshot(): string {
    this.drawFrame();
    const src = this.renderer.domElement;
    const single = this.visiblePanes().length === 1 && this.visiblePanes()[0].spec.kind === "3d";
    if (single && !this.measuring) return src.toDataURL("image/png");
    const out = document.createElement("canvas");
    out.width = src.width; out.height = src.height;
    const g = out.getContext("2d")!;
    g.drawImage(src, 0, 0);
    const k = src.width / (this.host.clientWidth || 1);
    for (const pane of single ? [] : this.visiblePanes()) {
      const layer = pane.el.querySelector("canvas");
      if (layer) g.drawImage(layer, pane.rect.x * k, pane.rect.y * k, pane.rect.w * k, pane.rect.h * k);
      g.strokeStyle = "#c9d1da"; g.lineWidth = k;
      g.strokeRect(pane.rect.x * k + 0.5, pane.rect.y * k + 0.5, pane.rect.w * k - 1, pane.rect.h * k - 1);
    }
    if (this.measuring) g.drawImage(this.measureCanvas, 0, 0, out.width, out.height);   // the measurements on screen
    return out.toDataURL("image/png");
  }

  /** Render with the 3D camera into the whole canvas, as a single view would, whatever the layout: pictures never
   * depend on the panes (docs/views.md, "What must not change"). The panes are drawn again afterwards. */
  private fullCanvas<T>(take: () => T): T {
    const W = this.host.clientWidth || 1, H = this.host.clientHeight || 1;
    const aspect = this.camera.aspect;
    this.renderer.setScissorTest(false);
    this.renderer.setViewport(0, 0, W, H);
    this.renderer.clippingPlanes = [];
    this.canvasStamp++;   // the shot covers every pane: each composites again when the view is drawn back
    if (Math.abs(aspect - W / H) > 1e-9) { this.camera.aspect = W / H; this.camera.updateProjectionMatrix(); }
    try { return take(); } finally {
      if (this.camera.aspect !== aspect) { this.camera.aspect = aspect; this.camera.updateProjectionMatrix(); }
    }
  }

  /** A PNG of the current view's centre square, `side` pixels across. */
  private png(side: number, type = "image/png"): string {
    this.renderer.render(this.scene, this.camera);
    const src = this.renderer.domElement;
    const s = Math.min(src.width, src.height);
    const out = document.createElement("canvas");
    out.width = out.height = Math.min(side, s);
    out.getContext("2d")!.drawImage(src, (src.width - s) / 2, (src.height - s) / 2, s, s, 0, 0, out.width, out.height);
    return out.toDataURL(type, 0.85);
  }

  /** A small JPEG of the 3D view (for reports): the centre square, `side` pixels across, without the user's style,
   * filters, hides or selection. */
  capture(side = 640): string {
    if (this.lost) return "";   // a black picture otherwise
    const lifted = this.lifted, grips = this.grips.visible, version = this.version;
    this.lifted = true; this.grips.visible = false;
    this.applyMode();
    try {
      return this.fullCanvas(() => {
        if (this.marker.visible) {   // sized for the perspective camera the picture is taken with, whatever the user's
          this.marker.scale.setScalar(Math.max(this.camera.position.distanceTo(this.marker.position) / 8, 1e-4));
          this.marker.children[1].lookAt(this.camera.position);
        }
        this.renderer.render(this.scene, this.camera);
        const src = this.renderer.domElement;
        const s = Math.min(src.width, src.height);
        const out = document.createElement("canvas");
        out.width = out.height = Math.min(side, s);
        out.getContext("2d")!.drawImage(src, (src.width - s) / 2, (src.height - s) / 2, s, s, 0, 0, out.width, out.height);
        return out.toDataURL("image/jpeg", 0.85);
      });
    } finally {
      this.lifted = lifted; this.grips.visible = grips;
      this.applyMode();
      this.version = version;
      this.drawFrame();
    }
  }

  dispose() {
    this.renderer.setAnimationLoop(null);
    this.resize.disconnect();
    this.controls.dispose();
    this.cube.dispose();
    for (const p of this.panes) { p.view?.dispose(); p.el.remove(); }
    this.renderer.dispose();
    this.renderer.domElement.remove();
    this.markerLabel.remove();
    this.measureCanvas.remove();
  }

  /** The stage changed size. Resizing the canvas clears it, so only when its size really changed, and then everything
   * is drawn again at once: this runs after the frame's own drawing and before the browser paints, and a cleared
   * canvas would show as a blank frame (the viewer blinking off and on). */
  private fit() {
    const w = this.host.clientWidth || 1;
    const h = this.host.clientHeight || 1;
    const now = this.renderer.getSize(new THREE.Vector2());
    if (now.x !== w || now.y !== h) { this.renderer.setSize(w, h, false); this.canvasStamp++; }
    this.layoutPanes();
    this.drawFrame();
  }
  /** Bumped whenever something draws over the whole canvas or clears it: panes composite again. */
  private canvasStamp = 0;

  /** No WebGL context (the graphics card took it away): captures return nothing rather than a black picture. */
  get lost(): boolean { return this.renderer.getContext().isContextLost(); }

  private lostNote: HTMLDivElement | null = null;
  private lostTimer = 0;
  /** The WebGL context went (`lost`) or came back. Back, everything on the graphics card is new: draw every pane again.
   * Not back within a few seconds: offer a reload (the page picks up the session where it was). */
  private contextLost(lost: boolean) {
    clearTimeout(this.lostTimer);
    this.lostNote?.remove();
    this.lostNote = null;
    if (!lost) {
      this.version++;
      this.canvasStamp++;
      this.styled = null;
      for (const p of this.panes) { p.composed = undefined; if (p.view) { p.view.drawn = ""; p.view.shown = null; } }
      return;
    }
    const note = document.createElement("div");
    note.className = "view-lost";
    note.setAttribute("role", "status");
    note.textContent = "The graphics card dropped the 3D view. Bringing it back…";
    this.host.appendChild(note);
    this.lostNote = note;
    this.lostTimer = window.setTimeout(() => {
      note.textContent = "The graphics card has not given the 3D view back. Fewer views use less of its memory.";
      const reload = document.createElement("button");
      reload.className = "btn small";
      reload.textContent = "Reload";
      reload.addEventListener("click", () => location.reload());
      note.appendChild(reload);
    }, 5000);
  }
}

/** The mark under a pane point: within 9 px of an end, else within 6 px of a line. */
function handleAt(handles: Handle[], p: THREE.Vector2): Handle | null {
  const ends = handles.filter((h) => h.kind === "section-end" && h.a.distanceTo(p) <= 9);
  if (ends.length) return ends[0];
  let best: Handle | null = null, bestD = 6;
  for (const h of handles) {
    if (h.kind === "section-end") continue;
    const ab = h.b.clone().sub(h.a), t = THREE.MathUtils.clamp(p.clone().sub(h.a).dot(ab) / Math.max(ab.lengthSq(), 1e-9), 0, 1);
    const d = h.a.clone().addScaledVector(ab, t).distanceTo(p);
    if (d <= bestD) { best = h; bestD = d; }
  }
  return best;
}

/** Where two boxes meet: per axis their overlap, or the gap between them when they are apart on that axis. */
export function meetingZone(a: THREE.Box3, b: THREE.Box3): THREE.Box3 {
  const min = new THREE.Vector3(), max = new THREE.Vector3();
  for (const k of ["x", "y", "z"] as const) {
    const lo = Math.max(a.min[k], b.min[k]), hi = Math.min(a.max[k], b.max[k]);
    min[k] = Math.min(lo, hi);
    max[k] = Math.max(lo, hi);
  }
  return new THREE.Box3(min, max);
}

/** The box of server triangles (metres, Z up) in viewer coordinates. */
function meshBox(meshes: Mesh[]): THREE.Box3 {
  const box = new THREE.Box3();
  for (const m of meshes) for (let i = 0; i < m.verts.length; i += 3) box.expandByPoint(new THREE.Vector3(m.verts[i], m.verts[i + 2], -m.verts[i + 1]));
  return box;
}

/** A point laid on a drawing's plane (a plan's cut, a section's line, an elevation's façade plane). */
function onPlane(view: DrawingView, p: THREE.Vector3): THREE.Vector3 {
  return p.clone().addScaledVector(view.look, -view.look.dot(p.clone().sub(view.center)));
}

const MEASURE_INK = "#2f5d8a", SNAP_INK = "#d9480f";

/** A measurement on the overlay: a line, ends as a drawing's ticks or 3D dots, and its label at the middle. `open`: a
 * measurement under way (dashed, from its first point to the pointer). */
function dimension(g: CanvasRenderingContext2D, a: THREE.Vector2 | null, b: THREE.Vector2 | null, text: string, ticks: boolean, open: boolean,
  placed: { x: number; y: number; w: number }[] = []) {
  g.save();
  g.strokeStyle = MEASURE_INK; g.fillStyle = MEASURE_INK; g.lineWidth = 1.6;
  const end = (p: THREE.Vector2, dir: THREE.Vector2) => {
    if (ticks) { g.beginPath(); g.moveTo(p.x - (dir.x - dir.y) * 6, p.y - (dir.y + dir.x) * 6); g.lineTo(p.x + (dir.x - dir.y) * 6, p.y + (dir.y + dir.x) * 6); g.stroke(); }
    else { g.beginPath(); g.arc(p.x, p.y, 3.2, 0, Math.PI * 2); g.fill(); }
  };
  if (a && !b) { end(a, new THREE.Vector2(1, 0)); g.restore(); return; }
  if (!a || !b) { g.restore(); return; }
  const dir = b.clone().sub(a);
  const len = dir.length();
  if (len > 0) dir.divideScalar(len);
  if (open) g.setLineDash([6, 4]);
  g.beginPath(); g.moveTo(a.x, a.y); g.lineTo(b.x, b.y); g.stroke();
  g.setLineDash([]);
  end(a, dir); end(b, dir);
  if (!text) { g.restore(); return; }
  g.font = `600 11.5px "IBM Plex Sans", system-ui, sans-serif`;
  const w = g.measureText(text).width + 12, mx = (a.x + b.x) / 2;
  let my = (a.y + b.y) / 2;
  for (let k = 0; k < 6 && placed.some((q) => Math.abs(q.x - mx) < (q.w + w) / 2 && Math.abs(q.y - my) < 20); k++) my -= 20;
  placed.push({ x: mx, y: my, w });
  g.fillStyle = open ? "rgba(47,93,138,.85)" : MEASURE_INK;
  g.beginPath(); g.roundRect(mx - w / 2, my - 22, w, 18, 9); g.fill();
  g.fillStyle = "#fff"; g.textAlign = "center"; g.textBaseline = "middle"; g.fillText(text, mx, my - 13);
  g.restore();
}

/** What the pointer snaps to, as CAD shows it: a square at an end, a triangle at a midpoint, a cross on an edge, a dot
 * on a surface, a small cross on empty paper. */
function snapGlyph(g: CanvasRenderingContext2D, p: THREE.Vector2 | null, kind: SnapKind) {
  if (!p) return;
  g.save();
  g.strokeStyle = SNAP_INK; g.fillStyle = SNAP_INK; g.lineWidth = 1.8;
  g.beginPath();
  if (kind === "end") g.rect(p.x - 5, p.y - 5, 10, 10);
  else if (kind === "mid") { g.moveTo(p.x, p.y - 6); g.lineTo(p.x + 6, p.y + 4.5); g.lineTo(p.x - 6, p.y + 4.5); g.closePath(); }
  else if (kind === "edge") { g.moveTo(p.x - 5, p.y - 5); g.lineTo(p.x + 5, p.y + 5); g.moveTo(p.x + 5, p.y - 5); g.lineTo(p.x - 5, p.y + 5); }
  else if (kind === "face") { g.arc(p.x, p.y, 3, 0, Math.PI * 2); g.fill(); }
  else { g.moveTo(p.x - 4, p.y); g.lineTo(p.x + 4, p.y); g.moveTo(p.x, p.y - 4); g.lineTo(p.x, p.y + 4); }
  g.stroke();
  g.restore();
}
