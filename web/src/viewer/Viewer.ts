import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { loadIfc, type LoadedElement, type LoadedModel } from "./ifcLoader";

const RED = new THREE.Color("#d0342c");
const GREEN = new THREE.Color("#1f9d3a");
const GREY = new THREE.Color("#b9c2cc");

// The server works in IFC axes (metres, Z up); web-ifc and three.js are Y up.
export function serverDeltaToViewer([dx, dy, dz]: number[]): THREE.Vector3 {
  return new THREE.Vector3(dx, dz, -dy);
}

type Found = { model: LoadedModel; el: LoadedElement };

export class Viewer {
  readonly renderer: THREE.WebGLRenderer;
  readonly scene = new THREE.Scene();
  readonly camera = new THREE.PerspectiveCamera(45, 1, 0.05, 5000);
  readonly controls: OrbitControls;
  /** One batched mesh per federated file (structure, MEP, architecture…). */
  models: LoadedModel[] = [];
  private raycaster = new THREE.Raycaster();
  /** New pieces of a previewed edit (a local offset), drawn over the models until the preview changes. */
  private overlay = new THREE.Group();
  private hidden: string[] = [];
  private resize = new ResizeObserver(() => this.fit());

  constructor(private host: HTMLElement) {
    this.renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    host.appendChild(this.renderer.domElement);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.scene.background = new THREE.Color("#dfe6ee");
    this.scene.add(new THREE.HemisphereLight(0xffffff, 0x8899aa, 1.6));
    const sun = new THREE.DirectionalLight(0xffffff, 1.4);
    sun.position.set(30, 60, 20);
    this.scene.add(sun);
    this.scene.add(this.overlay);
    this.resize.observe(host);
    this.fit();
    this.renderer.setAnimationLoop(() => {
      this.controls.update();
      this.renderer.render(this.scene, this.camera);
    });
  }

  async load(files: Uint8Array[]) {
    for (const m of this.models) this.scene.remove(m.mesh);
    this.models = [];
    for (const bytes of files) {
      const m = await loadIfc(bytes);
      this.models.push(m);
      this.scene.add(m.mesh);
    }
    this.frame(this.models.flatMap((m) => [...m.byGlobalId.keys()]));
    return {
      elements: this.models.reduce((n, m) => n + m.stats.elements, 0),
      triangles: this.models.reduce((n, m) => n + m.stats.triangles, 0),
      parseMs: this.models.reduce((n, m) => n + m.stats.parseMs, 0),
    };
  }

  /** Swap one federated file for a new version of it (after an edit was accepted on the server). */
  async replace(index: number, bytes: Uint8Array) {
    const old = this.models[index];
    const m = await loadIfc(bytes);
    if (old) this.scene.remove(old.mesh);
    this.models[index] = m;
    this.scene.add(m.mesh);
  }

  private find(globalId: string): Found | null {
    for (const model of this.models) {
      const el = model.byGlobalId.get(globalId);
      if (el) return { model, el };
    }
    return null;
  }

  pick(ev: MouseEvent): string | null {
    const r = this.renderer.domElement.getBoundingClientRect();
    const ndc = new THREE.Vector2(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1);
    this.raycaster.setFromCamera(ndc, this.camera);
    const hit = this.raycaster.intersectObjects(this.models.map((m) => m.mesh))[0];
    if (hit?.batchId === undefined) return null;
    const model = this.models.find((m) => m.mesh === hit.object);
    return model?.byInstance.get(hit.batchId)?.globalId ?? null;
  }

  /** Red/green pair, everything else greyed or hidden (images A and B). `group` holds pieces that belong to one
   * side of the pair (the new pieces of an accepted offset): GlobalId → "a" or "b". */
  highlight(a: string | null, b: string | null, isolate = false, group: Record<string, "a" | "b"> = {}) {
    for (const model of this.models) {
      for (const el of model.byGlobalId.values()) {
        const side = el.globalId === a ? "a" : el.globalId === b ? "b" : group[el.globalId];
        const inPair = !!side;
        model.mesh.setColorAt(el.instanceId, side === "a" ? RED : side === "b" ? GREEN : a || b ? GREY : el.baseColor);
        model.mesh.setVisibleAt(el.instanceId, !isolate || inPair || !(a || b));
      }
    }
  }

  /** Preview moves without touching the model: GlobalIds + server delta (metres, Z up). Clears any edit preview. */
  preview(moves: { globalIds: string[]; deltaM: number[] }[]) {
    this.clearOverlay();
    for (const model of this.models) for (const el of model.byGlobalId.values()) model.mesh.setMatrixAt(el.instanceId, el.baseMatrix);
    for (const m of moves) {
      const t = new THREE.Matrix4().makeTranslation(serverDeltaToViewer(m.deltaM));
      for (const gid of m.globalIds) {
        const f = this.find(gid);
        if (f) f.model.mesh.setMatrixAt(f.el.instanceId, f.el.baseMatrix.clone().premultiply(t));
      }
    }
  }

  /** Preview an edit that replaces elements with new shapes: hide `replaced`, draw `pieces` (server triangles,
   * metres, Z up) in `color`. */
  previewPieces(replaced: string[], pieces: { verts: number[]; faces: number[] }[], color: THREE.ColorRepresentation) {
    this.preview([]);
    for (const gid of replaced) {
      const f = this.find(gid);
      if (f) f.model.mesh.setVisibleAt(f.el.instanceId, false);
    }
    this.hidden = [...replaced];
    const material = new THREE.MeshStandardMaterial({ color, roughness: 0.6, side: THREE.DoubleSide });
    for (const p of pieces) {
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
    for (const gid of this.hidden) {
      const f = this.find(gid);
      if (f) f.model.mesh.setVisibleAt(f.el.instanceId, true);
    }
    this.hidden = [];
    for (const child of [...this.overlay.children]) {
      const mesh = child as THREE.Mesh;
      mesh.geometry.dispose();
      (mesh.material as THREE.Material).dispose();
      this.overlay.remove(mesh);
    }
  }

  frame(globalIds: string[]) {
    const box = new THREE.Box3();
    const tmp = new THREE.Box3();
    const m = new THREE.Matrix4();
    for (const gid of globalIds) {
      const f = this.find(gid);
      if (!f) continue;
      f.model.mesh.getBoundingBoxAt(f.model.mesh.getGeometryIdAt(f.el.instanceId), tmp);
      f.model.mesh.getMatrixAt(f.el.instanceId, m);
      box.union(tmp.applyMatrix4(m));
    }
    if (box.isEmpty()) return;
    const centre = box.getCenter(new THREE.Vector3());
    const size = box.getSize(new THREE.Vector3()).length() || 1;
    this.camera.position.copy(centre).add(new THREE.Vector3(1, 0.8, 1).normalize().multiplyScalar(size * 1.4));
    this.controls.target.copy(centre);
  }

  /** PNG of the current view: the A/B/C images come from the same renderer the user sees. */
  snapshot(): string {
    this.renderer.render(this.scene, this.camera);
    return this.renderer.domElement.toDataURL("image/png");
  }

  dispose() {
    this.renderer.setAnimationLoop(null);
    this.resize.disconnect();
    this.controls.dispose();
    this.renderer.dispose();
    this.renderer.domElement.remove();
  }

  private fit() {
    const w = this.host.clientWidth || 1;
    const h = this.host.clientHeight || 1;
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
  }
}
