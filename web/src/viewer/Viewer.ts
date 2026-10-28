import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { loadIfc, type LoadedElement, type LoadedModel } from "./ifcLoader";

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
/** Triangles from the server: flat xyz (metres, IFC Z up) and indices. */
export type Mesh = { verts: number[]; faces: number[] };
/** A fix to preview: an offset's new pieces, or a move. `before`: what it changes, as it is now. */
export type OptionShape = { kind: string; moved: string[]; deltaM: number[]; pieces: Mesh[] | null; before: Mesh[] | null };

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
  private clipping: THREE.Plane[] = [];
  private focus: Focus = { a: null, b: null };
  /** Elements in focus are drawn as their own meshes over shared GPU buffers, so any mode can keep them solid. */
  private focusLayer = new THREE.Group();
  private focusMeshes = new Map<string, THREE.Mesh>();
  private focusGeometry = new Map<string, THREE.BufferGeometry>();
  private focusMaterials = { a: this.focusMaterial(RED), b: this.focusMaterial(GREEN), ab: this.focusMaterial(PURPLE) };
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
    this.scene.add(this.focusLayer, this.overlay, this.hitLayer, this.marker, this.measureLayer);
    for (const m of [this.solid, this.ghost, this.hitMaterial]) m.clippingPlanes = this.clipping;
    this.markerLabel = this.label("marker-label");
    this.measureLabel = this.label("measure-label");
    this.buildMarker();
    this.resize.observe(host);
    this.fit();
    this.renderer.setAnimationLoop(() => this.frameTick());
  }

  // ---------------------------------------------------------------- models

  async load(files: Uint8Array[], names: string[] = []) {
    for (const m of this.models) this.scene.remove(m.mesh);
    this.models = [];
    this.names = names;
    this.clearFocusCache();
    for (const bytes of files) this.models.push(this.adopt(await loadIfc(bytes)));
    this.applyMode();
    this.fitAll(false);
    return {
      elements: this.models.reduce((n, m) => n + m.stats.elements, 0),
      triangles: this.models.reduce((n, m) => n + m.stats.triangles, 0),
      parseMs: this.models.reduce((n, m) => n + m.stats.parseMs, 0),
    };
  }

  /** Swap one federated file for a new version of it (after an edit was accepted on the server). */
  async replace(index: number, bytes: Uint8Array) {
    const old = this.models[index];
    const m = this.adopt(await loadIfc(bytes));
    if (old) this.scene.remove(old.mesh);
    this.models[index] = m;
    this.clearFocusCache();
    this.applyMode();
  }

  setModelVisible(index: number, visible: boolean) {
    if (visible) this.hiddenModels.delete(index); else this.hiddenModels.add(index);
    this.applyMode();
  }

  private adopt(m: LoadedModel): LoadedModel {
    m.mesh.material = this.solid;
    this.scene.add(m.mesh);
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
      for (const el of model.byGlobalId.values()) {
        const inFocus = !!this.focusSide(el.globalId);
        let visible = !inFocus && !this.hidden.has(el.globalId);  // focus elements are drawn by the focus layer
        if (visible && hasFocus && this.mode === "isolate") visible = false;
        if (visible && near) visible = near.has(el.globalId);
        model.mesh.setVisibleAt(el.instanceId, visible);
        model.mesh.setColorAt(el.instanceId, ghostly ? GHOST : hasFocus && this.mode === "shaded" ? GREY : el.baseColor);
        model.mesh.setMatrixAt(el.instanceId, this.matrixOf(el));
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
      let mesh = this.focusMeshes.get(gid);
      if (!mesh) {
        mesh = new THREE.Mesh(this.geometryOf(f), this.focusMaterials[side]);
        mesh.matrixAutoUpdate = false;
        mesh.frustumCulled = false;
        mesh.userData.globalId = gid;
        this.focusMeshes.set(gid, mesh);
      }
      mesh.material = this.focusMaterials[side];
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
      const src = model.mesh.geometry;
      const range = model.mesh.getGeometryRangeAt(model.mesh.getGeometryIdAt(el.instanceId))!;
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

  /** A slow turn around the current target, while the agent thinks. */
  orbit(on: boolean) { this.controls.autoRotate = on; }

  setEdges(on: boolean) { this.showEdges = on; this.applyMode(); }

  private clearFocusCache() {
    this.setHits([]);
    for (const g of this.edgeGeometry.values()) g.dispose();
    this.edgeGeometry.clear();
    this.edges.clear();
    // Not disposed: these geometries share their model's buffers, and disposing would free them.
    this.focusGeometry.clear();
    this.focusMeshes.clear();
  }

  private focusMaterial(color: THREE.Color) {
    const m = new THREE.MeshStandardMaterial({ color, metalness: 0, roughness: 0.6, side: THREE.DoubleSide });
    m.clippingPlanes = this.clipping;
    return m;
  }

  /** Elements whose box comes within `margin` metres of the focus elements' boxes. */
  private nearFocus(ids: string[], margin = 2.5): Set<string> {
    const box = this.boxOf(ids);
    const out = new Set<string>();
    if (box.isEmpty()) return out;
    box.expandByScalar(margin);
    const tmp = new THREE.Box3();
    for (const model of this.models) {
      for (const el of model.byGlobalId.values()) {
        this.instanceBox(model, el, tmp);
        if (tmp.intersectsBox(box)) out.add(el.globalId);
      }
    }
    return out;
  }

  private instanceBox(model: LoadedModel, el: LoadedElement, target: THREE.Box3) {
    model.mesh.getBoundingBoxAt(model.mesh.getGeometryIdAt(el.instanceId), target);
    return target.applyMatrix4(this.matrixOf(el));
  }

  boxOf(ids: string[]): THREE.Box3 {
    const box = new THREE.Box3();
    const tmp = new THREE.Box3();
    for (const gid of ids) {
      const f = this.find(gid);
      if (f) box.union(this.instanceBox(f.model, f.el, tmp));
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
        if ((opt.kind === "offset" || opt.kind === "trim") && opt.pieces) {  // new shapes in place of the element
          for (const gid of opt.moved) this.hidden.add(gid);
          this.addMeshes(opt.pieces, new THREE.MeshStandardMaterial({ color: opt.color, roughness: 0.6, side: THREE.DoubleSide, clippingPlanes: this.clipping }));
        } else {
          const t = new THREE.Matrix4().makeTranslation(serverDeltaToViewer(opt.deltaM));
          for (const gid of opt.moved) this.moved.set(gid, t);
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
    else if (boxes.length === 1 && point) zone = new THREE.Box3().setFromCenterAndSize(point, new THREE.Vector3(1, 1, 1)).intersect(boxes[0]);
    if ((!zone || zone.isEmpty()) && point) zone = new THREE.Box3().setFromCenterAndSize(point, new THREE.Vector3(0.6, 0.6, 0.6));
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
    const zoneDiag = zone.getSize(new THREE.Vector3()).length();
    const unionDiag = union.getSize(new THREE.Vector3()).length();
    const margin = Math.min(Math.max(0.35 * zoneDiag, 0.1 * unionDiag, 0.5), Math.max((unionDiag - zoneDiag) / (2 * Math.sqrt(3)), 0.5));
    const framed = zone.clone().expandByScalar(margin);
    const centre = framed.getCenter(new THREE.Vector3());
    const r = framed.getSize(new THREE.Vector3()).length() / 2;
    const vFov = THREE.MathUtils.degToRad(this.camera.fov);
    const hFov = 2 * Math.atan(Math.tan(vFov / 2) * this.camera.aspect);
    const dist = Math.max((r / Math.sin(Math.min(vFov, hFov) / 2)) * 1.1, 2 * r + 0.5);
    this.flyTo(centre.clone().add(this.viewDirection().multiplyScalar(dist)), centre);
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
    this.models.forEach((m, i) => { if (!this.hiddenModels.has(i)) { m.mesh.computeBoundingBox(); box.union(m.mesh.boundingBox!); } });
    if (!box.isEmpty()) this.flyToBox(box, 1.1, undefined, animate);
  }

  /** Standard views around the current target (or the section box, if one is on). */
  view(preset: Preset) {
    const target = this.controls.target.clone();
    const dist = Math.max(this.camera.position.distanceTo(target), 2);
    const dirs: Record<Preset, THREE.Vector3> = {
      top: new THREE.Vector3(0, 1, 0.0001), front: new THREE.Vector3(0, 0, 1), right: new THREE.Vector3(1, 0, 0),
      iso: new THREE.Vector3(1, 0.8, 1),
    };
    this.flyTo(target.clone().add(dirs[preset].normalize().multiplyScalar(dist)), target);
  }

  private flyToBox(box: THREE.Box3, tight: number, dir?: THREE.Vector3, animate = true) {
    const centre = box.getCenter(new THREE.Vector3());
    const size = Math.max(box.getSize(new THREE.Vector3()).length(), 1.5);
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
  setSection(on: boolean, margin = 1.5, box?: THREE.Box3) {
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
    for (const m of [this.solid, this.ghost, this.hitMaterial, ...Object.values(this.focusMaterials)]) m.needsUpdate = true;
    return true;
  }

  /** The focus elements, clipped to a few metres around the marker so a long run does not make a huge box. */
  private boxAroundFocus(): THREE.Box3 {
    const box = this.boxOf(this.focusIds());
    if (this.marker.visible) {
      const around = new THREE.Box3().setFromCenterAndSize(this.marker.position, new THREE.Vector3(4, 4, 4));
      return box.isEmpty() ? around : box.intersect(around).union(new THREE.Box3().setFromCenterAndSize(this.marker.position, new THREE.Vector3(1, 1, 1)));
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
  pickAt(ev: MouseEvent): Pick | null {
    const r = this.renderer.domElement.getBoundingClientRect();
    const ndc = new THREE.Vector2(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1);
    this.raycaster.setFromCamera(ndc, this.camera);
    const targets: THREE.Object3D[] = [...this.focusLayer.children,
      ...this.models.filter((_, i) => !this.hiddenModels.has(i)).map((m) => m.mesh)];
    const ghostly = this.focusIds().length > 0 && this.mode !== "shaded";
    for (const hit of this.raycaster.intersectObjects(targets, false)) {
      if (this.clipping.length && !this.sectionBox?.containsPoint(hit.point)) continue;
      if (hit.object.userData.globalId) return { globalId: hit.object.userData.globalId, point: hit.point };
      if (ghostly) continue;  // see-through context is not pickable: click through it to the focus
      const model = this.models.find((m) => m.mesh === hit.object);
      const el = hit.batchId !== undefined ? model?.byInstance.get(hit.batchId) : undefined;
      if (el) return { globalId: el.globalId, point: hit.point };
    }
    return null;
  }

  pick(ev: MouseEvent): string | null { return this.pickAt(ev)?.globalId ?? null; }

  /** Draw a measured distance between two picked points; null clears it. Returns metres. */
  setMeasure(p1: THREE.Vector3 | null, p2: THREE.Vector3 | null): number | null {
    this.measureLayer.clear();
    this.measureLabel.textContent = "";
    if (!p1) return null;
    const mat = new THREE.MeshBasicMaterial({ color: "#2f5d8a", depthTest: false });
    for (const p of [p1, p2].filter((x): x is THREE.Vector3 => !!x)) {
      const s = new THREE.Mesh(new THREE.SphereGeometry(0.03, 12, 8), mat);
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
      const s = Math.max(this.camera.position.distanceTo(this.marker.position) / 8, 0.3);
      this.marker.scale.setScalar(s);
      this.marker.children[1].lookAt(this.camera.position);
    }
    this.renderer.render(this.scene, this.camera);
  }

  /** Near/far planes follow the distance to the target, so close-ups don't clip and far views don't z-fight. */
  private adjustClipRange() {
    const d = this.camera.position.distanceTo(this.controls.target);
    const near = Math.min(Math.max(d / 200, 0.01), 1);
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
