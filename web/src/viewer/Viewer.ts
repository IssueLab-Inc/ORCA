import { toCreasedNormals } from "three/examples/jsm/utils/BufferGeometryUtils.js";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { loadIfc, type LoadedElement, type LoadedModel } from "./ifcLoader";
import { patchModel, ROOM, type ElementMesh } from "./patch";

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

/** Side A (red), side B (green), or both at once (purple): the model has one element where the report has two. */
export type Side = "a" | "b" | "ab";

export interface Focus {
  a: string | null;
  b: string | null;
  group?: Record<string, Side>;  // more elements drawn as part of side A or B
}

/** A picked point on the model: the element and where on it (three.js world coordinates). */
export interface Pick { globalId: string; point: THREE.Vector3 }

export class Viewer {
  readonly renderer: THREE.WebGLRenderer;
  readonly scene = new THREE.Scene();
  readonly camera = new THREE.PerspectiveCamera(45, 1, 0.05, 5000);
  readonly controls: OrbitControls;
  /** One batched mesh per federated file (structure, MEP, architecture…). */
  models: LoadedModel[] = [];
  names: string[] = [];
  mode: ViewMode = "shaded";

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
  private measureLayer = new THREE.Group();
  private measureLabel: HTMLDivElement;
  private sectionBox: THREE.Box3 | null = null;
  private sectionHelper: THREE.Box3Helper | null = null;
  private flight: { from: [THREE.Vector3, THREE.Vector3]; to: [THREE.Vector3, THREE.Vector3]; t0: number; ms: number } | null = null;

  constructor(private host: HTMLElement) {
    this.renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.localClippingEnabled = true;
    host.appendChild(this.renderer.domElement);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.zoomToCursor = true;  // the wheel zooms to what is under the pointer, not the orbit centre
    this.controls.addEventListener("start", () => { this.flight = null; this.onUserCamera?.(); });
    this.renderer.domElement.addEventListener("pointerdown", () => this.onUserCamera?.());
    this.controls.autoRotateSpeed = 0.6;
    this.scene.background = new THREE.Color("#dfe6ee");
    this.scene.add(new THREE.HemisphereLight(0xffffff, 0x8899aa, 1.6));
    const sun = new THREE.DirectionalLight(0xffffff, 1.4);
    sun.position.set(30, 60, 20);
    this.scene.add(sun);
    this.scene.add(this.focusLayer, this.overlay, this.hitLayer, this.linkLayer, this.marker, this.measureLayer);
    for (const m of [this.solid, this.ghost, this.glass, this.hitMaterial]) m.clippingPlanes = this.clipping;
    this.markerLabel = this.label("marker-label");
    this.measureLabel = this.label("measure-label");
    this.buildMarker();
    this.resize.observe(host);
    this.fit();
    this.renderer.setAnimationLoop(() => this.frameTick());
  }

  // ---------------------------------------------------------------- models

  async load(files: Uint8Array[], names: string[] = [], isCurrent: () => boolean = () => true) {
    // Parse the entire replacement off-screen. A failed or superseded load leaves the usable scene intact.
    const staged: LoadedModel[] = [];
    try {
      for (const bytes of files) {
        staged.push(await loadIfc(bytes));
        if (!isCurrent()) { for (const m of staged) disposeBatches(m); return; }
      }
    } catch (e) { for (const m of staged) disposeBatches(m); throw e; }
    if (!isCurrent()) { for (const m of staged) disposeBatches(m); return; }
    this.preview([]);
    this.clearFocusCache();
    for (const m of this.models) { this.scene.remove(...batches(m)); disposeBatches(m); }
    this.models = staged.map((m) => this.adopt(m));
    this.sceneSize = 0;
    this.names = names;
    this.hiddenModels.clear();
    this.applyMode();
    this.fitAll(false);
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
    this.sceneSize = 0;
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
    this.sceneSize = 0;
    this.clearFocusCache();  // focus geometry shares the batches' buffers, which may have moved or grown
    this.applyMode();
    return true;
  }

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
    this.applyMode();
  }

  private adopt(m: LoadedModel): LoadedModel {
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

  /** Re-draw everything for the current mode, focus, moves and hidden elements. */
  private applyMode() {
    const ids = this.focusIds().filter((g) => !this.hidden.has(g));
    const hasFocus = ids.length > 0;
    const near = this.mode === "context" && hasFocus ? this.nearFocus(ids) : null;
    const ghostly = hasFocus && (this.mode === "xray" || this.mode === "context");
    this.models.forEach((model, mi) => {
      model.mesh.visible = !this.hiddenModels.has(mi);
      model.mesh.material = ghostly ? this.ghost : this.solid;
      if (model.glass) {
        model.glass.visible = model.mesh.visible;
        model.glass.material = ghostly ? this.ghost : this.glass;
      }
      for (const el of model.byGlobalId.values()) {
        const inFocus = !!this.focusSide(el.globalId);
        let visible = !inFocus && !this.hidden.has(el.globalId);  // focus elements are drawn by the focus layer
        if (visible && hasFocus && this.mode === "isolate") visible = false;
        if (visible && near) visible = near.has(el.globalId);
        el.mesh.setVisibleAt(el.instanceId, visible);
        const c = ghostly ? GHOST : hasFocus && this.mode === "shaded" ? GREY : el.baseColor;
        el.mesh.setColorAt(el.instanceId, new THREE.Vector4(c.r, c.g, c.b, ghostly ? 1 : el.baseAlpha));
        el.mesh.setMatrixAt(el.instanceId, this.matrixOf(el));
      }
    });
    this.drawFocus(ids);
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
    this.hitLayer.clear();
    for (const gid of ids) {
      const f = this.find(gid);
      if (!f || this.hiddenModels.has(this.models.indexOf(f.model))) continue;
      const mesh = new THREE.Mesh(this.geometryOf(f), this.hitMaterial);
      const line = new THREE.LineSegments(this.edgeGeometryOf(gid, f), this.hitEdges);
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
    this.linkLayer.clear();
    for (const group of groups) {
      const mats = this.linkMats(group.color);
      group.ids.slice(0, LINK_MAX).forEach((gid, k) => {
        const f = this.find(gid);
        if (!f || this.hidden.has(gid) || this.hiddenModels.has(this.models.indexOf(f.model))) return;
        const parts: THREE.Object3D[] = [new THREE.Mesh(this.geometryOf(f), mats.mesh)];
        if (k < LINK_EDGES) parts.push(new THREE.LineSegments(this.edgeGeometryOf(gid, f), mats.edges));
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
  orbit(on: boolean) { this.controls.autoRotate = on; }

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
    for (const p of meshes) {
      const pos = new Float32Array(p.verts.length);
      for (let i = 0; i < p.verts.length; i += 3) {
        pos[i] = p.verts[i]; pos[i + 1] = p.verts[i + 2]; pos[i + 2] = -p.verts[i + 1]; // IFC Z up → three.js Y up
      }
      const g = new THREE.BufferGeometry();
      g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
      g.setIndex(p.faces);
      g.computeVertexNormals();
      this.overlay.add(new THREE.Mesh(g, material));
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
  focusClash(ids: string[], point: THREE.Vector3 | null, label = "") {
    const boxes = ids.map((g) => this.boxOf([g])).filter((b) => !b.isEmpty());
    let zone: THREE.Box3 | null = null;
    if (boxes.length === 2) zone = meetingZone(boxes[0], boxes[1]);
    else if (boxes.length === 1 && point) zone = new THREE.Box3().setFromCenterAndSize(point, new THREE.Vector3().setScalar(this.reach(1, 0.2))).intersect(boxes[0]);
    if ((!zone || zone.isEmpty()) && point) zone = new THREE.Box3().setFromCenterAndSize(point, new THREE.Vector3().setScalar(this.reach(0.6, 0.15)));
    if (!zone || zone.isEmpty()) return false;
    this.setMarker(point ?? zone.getCenter(new THREE.Vector3()), label);
    this.flyToZone(zone, boxes.reduce((u, b) => u.union(b), zone.clone()));
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
    return this.posed(a, b, (shot, turn) => {
      const A = shot("isolate", true, side), B = shot("context", false, side);
      turn();
      return { A, B, C: shot("isolate", true, side) };
    });
  }

  /** A small picture of a clash for the list (view A's recipe, as a JPEG), taken off screen like `captureClash`. */
  thumbClash(a: string, b: string, side = 192): string | null {
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
      links: this.linkLayer.visible,
      measure: this.measureLayer.visible, clear: renderer.getClearColor(new THREE.Color()), clearAlpha: renderer.getClearAlpha() };
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
      this.measureLayer.visible = false; this.linkLayer.visible = false;
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
      this.measureLayer.visible = saved.measure;
      scene.overrideMaterial = null;
      scene.background = saved.background;
      this.hidden = saved.hidden; this.moved = saved.moved;
      this.overlay.visible = saved.overlay; this.hitLayer.visible = saved.hits; this.linkLayer.visible = saved.links;
      this.focus = saved.focus;
      if (saved.section) { this.setSection(true, 0, saved.section); } else this.setSection(false);
      this.mode = saved.mode; this.applyMode();
      camera.position.copy(saved.position); this.controls.target.copy(saved.target);
      this.flight = saved.flight; this.marker.visible = saved.marker;
      this.controls.update(); this.adjustClipRange();
      this.renderer.render(this.scene, this.camera);
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
      this.setFocus({ a, b });
      const [position, target] = this.zoneCamera(zone, boxA.clone().union(boxB));
      this.camera.position.copy(position);
      this.controls.target.copy(target);
      return take(shot, () => this.camera.position.copy(position.clone().sub(target)
        .applyAxisAngle(new THREE.Vector3(0, 1, 0), Math.PI / 2).add(target)));
    } finally {
      for (const m of pair) { m.transparent = false; m.opacity = 1; m.depthWrite = true; m.needsUpdate = true; }
      this.focus = saved.focus;
      this.setMode(saved.mode);
      this.camera.position.copy(saved.position);
      this.controls.target.copy(saved.target);
      this.flight = saved.flight;
      this.marker.visible = saved.marker;
      this.linkLayer.visible = saved.links;
      this.controls.update();
      this.adjustClipRange();
      // Draw the user's view again before the browser paints: the canvas keeps its last frame (preserveDrawingBuffer),
      // and a shot taken after this frame's own render would otherwise show until the next one (thumbnails flashing).
      this.renderer.render(this.scene, this.camera);
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

  flyTo(position: THREE.Vector3, target: THREE.Vector3, animate = true) {
    if (!animate || window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) {
      this.camera.position.copy(position);
      this.controls.target.copy(target);
      this.flight = null;
      return;
    }
    this.flight = { from: [this.camera.position.clone(), this.controls.target.clone()], to: [position, target],
      t0: performance.now(), ms: 650 };
  }

  // ---------------------------------------------------------------- section box and marker

  /** Cut the model to a box around the focus (or `box`), `margin` metres beyond it; null turns it off. */
  setSection(on: boolean, margin = this.reach(1.5, 0.1), box?: THREE.Box3) {
    if (this.sectionHelper) { this.scene.remove(this.sectionHelper); this.sectionHelper = null; }
    this.clipping.length = 0;
    this.sectionBox = null;
    if (on) {
      const b = (box ?? this.boxAroundFocus()).clone();
      if (b.isEmpty()) return false;
      b.expandByScalar(margin);
      this.sectionBox = b;
      const { min, max } = b;
      this.clipping.push(
        new THREE.Plane(new THREE.Vector3(1, 0, 0), -min.x), new THREE.Plane(new THREE.Vector3(-1, 0, 0), max.x),
        new THREE.Plane(new THREE.Vector3(0, 1, 0), -min.y), new THREE.Plane(new THREE.Vector3(0, -1, 0), max.y),
        new THREE.Plane(new THREE.Vector3(0, 0, 1), -min.z), new THREE.Plane(new THREE.Vector3(0, 0, -1), max.z));
      this.sectionHelper = new THREE.Box3Helper(b, new THREE.Color("#2f5d8a"));
      this.scene.add(this.sectionHelper);
    }
    for (const m of [this.solid, this.ghost, this.glass, this.hitMaterial, ...Object.values(this.focusMaterials),
      ...Object.values(this.focusGlass), ...[...this.linkMaterials.values()].map((x) => x.mesh)]) m.needsUpdate = true;
    return true;
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
    this.marker.add(dot, ring);
    this.marker.visible = false;
  }

  setMarker(point: THREE.Vector3 | null, label = "") {
    this.marker.visible = !!point;
    if (point) this.marker.position.copy(point);
    this.markerLabel.textContent = label;
  }

  // ---------------------------------------------------------------- picking and measuring

  /** The element (and point on it) under the pointer, including elements in focus. */
  pickAt(ev: MouseEvent, opts: { ghosts?: boolean } = {}): Pick | null {
    const r = this.renderer.domElement.getBoundingClientRect();
    const ndc = new THREE.Vector2(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1);
    this.raycaster.setFromCamera(ndc, this.camera);
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

  /** Draw a measured distance between two picked points; null clears it. Returns metres. */
  setMeasure(p1: THREE.Vector3 | null, p2: THREE.Vector3 | null): number | null {
    this.measureLayer.clear();
    this.measureLabel.textContent = "";
    if (!p1) return null;
    const mat = new THREE.MeshBasicMaterial({ color: "#2f5d8a", depthTest: false });
    for (const p of [p1, p2].filter((x): x is THREE.Vector3 => !!x)) {
      const s = new THREE.Mesh(new THREE.SphereGeometry(this.reach(0.03, 0.01), 12, 8), mat);
      s.position.copy(p);
      s.renderOrder = 11;
      this.measureLayer.add(s);
    }
    if (!p2) return null;
    const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints([p1, p2]),
      new THREE.LineBasicMaterial({ color: "#2f5d8a", depthTest: false }));
    line.renderOrder = 11;
    this.measureLayer.add(line);
    const d = p1.distanceTo(p2);
    const dx = Math.abs(p2.x - p1.x), dy = Math.abs(p2.z - p1.z), dz = Math.abs(p2.y - p1.y);
    this.measureLabel.textContent = `${(d * 1000).toFixed(0)} mm  (Δx ${(dx * 1000).toFixed(0)} · Δy ${(dy * 1000).toFixed(0)} · Δz ${(dz * 1000).toFixed(0)})`;
    this.measureLayer.userData.mid = p1.clone().add(p2).multiplyScalar(0.5);
    return d;
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
    this.place(this.markerLabel, this.marker.visible ? this.marker.position : null);
    this.place(this.measureLabel, this.measureLayer.userData.mid ?? null);
    if (this.marker.visible) {
      // A constant size on screen, at any scale: a floor in metres made it swallow a 100 mm part.
      const s = Math.max(this.camera.position.distanceTo(this.marker.position) / 8, 1e-4);
      this.marker.scale.setScalar(s);
      this.marker.children[1].lookAt(this.camera.position);
    }
    this.renderer.render(this.scene, this.camera);
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
    if (!p || !el.textContent) { el.style.display = "none"; return; }
    const v = p.clone().project(this.camera);
    if (v.z > 1) { el.style.display = "none"; return; }
    el.style.display = "block";
    el.style.left = `${((v.x + 1) / 2) * this.host.clientWidth}px`;
    el.style.top = `${((1 - v.y) / 2) * this.host.clientHeight}px`;
  }

  /** PNG of the current view: the A/B/C images come from the same renderer the user sees. */
  snapshot(): string {
    this.renderer.render(this.scene, this.camera);
    return this.renderer.domElement.toDataURL("image/png");
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

  /** A small JPEG of the current view (for reports): the centre square, `side` pixels across. */
  capture(side = 640): string {
    this.renderer.render(this.scene, this.camera);
    const src = this.renderer.domElement;
    const s = Math.min(src.width, src.height);
    const out = document.createElement("canvas");
    out.width = out.height = Math.min(side, s);
    out.getContext("2d")!.drawImage(src, (src.width - s) / 2, (src.height - s) / 2, s, s, 0, 0, out.width, out.height);
    return out.toDataURL("image/jpeg", 0.85);
  }

  dispose() {
    this.renderer.setAnimationLoop(null);
    this.resize.disconnect();
    this.controls.dispose();
    this.renderer.dispose();
    this.renderer.domElement.remove();
    this.markerLabel.remove();
    this.measureLabel.remove();
  }

  private fit() {
    const w = this.host.clientWidth || 1;
    const h = this.host.clientHeight || 1;
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
  }
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
