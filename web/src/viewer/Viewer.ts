import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { loadIfc, type LoadedModel } from "./ifcLoader";

const RED = new THREE.Color("#d0342c");
const GREEN = new THREE.Color("#1f9d3a");

// The server works in IFC axes (metres, Z up); web-ifc and three.js are Y up.
export function serverDeltaToViewer([dx, dy, dz]: number[]): THREE.Vector3 {
  return new THREE.Vector3(dx, dz, -dy);
}

export class Viewer {
  readonly renderer: THREE.WebGLRenderer;
  readonly scene = new THREE.Scene();
  readonly camera = new THREE.PerspectiveCamera(45, 1, 0.05, 5000);
  readonly controls: OrbitControls;
  model: LoadedModel | null = null;
  private raycaster = new THREE.Raycaster();
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
    this.resize.observe(host);
    this.fit();
    this.renderer.setAnimationLoop(() => {
      this.controls.update();
      this.renderer.render(this.scene, this.camera);
    });
  }

  async load(bytes: Uint8Array) {
    if (this.model) this.scene.remove(this.model.mesh);
    this.model = await loadIfc(bytes);
    this.scene.add(this.model.mesh);
    this.frame([...this.model.byGlobalId.keys()]);
    return this.model.stats;
  }

  pick(ev: MouseEvent): string | null {
    if (!this.model) return null;
    const r = this.renderer.domElement.getBoundingClientRect();
    const ndc = new THREE.Vector2(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1);
    this.raycaster.setFromCamera(ndc, this.camera);
    const hit = this.raycaster.intersectObject(this.model.mesh)[0];
    return hit?.batchId !== undefined ? this.model.byInstance.get(hit.batchId)?.globalId ?? null : null;
  }

  /** Red/green pair, everything else greyed or hidden (images A and B). */
  highlight(a: string | null, b: string | null, isolate = false) {
    if (!this.model) return;
    const grey = new THREE.Color("#b9c2cc");
    for (const el of this.model.byGlobalId.values()) {
      const inPair = el.globalId === a || el.globalId === b;
      this.model.mesh.setColorAt(el.instanceId, el.globalId === a ? RED : el.globalId === b ? GREEN : a || b ? grey : el.baseColor);
      this.model.mesh.setVisibleAt(el.instanceId, !isolate || inPair || !(a || b));
    }
  }

  /** Preview a move without touching the model: GlobalId list + server delta (metres, Z up). */
  preview(moves: { globalIds: string[]; deltaM: number[] }[]) {
    if (!this.model) return;
    for (const el of this.model.byGlobalId.values()) this.model.mesh.setMatrixAt(el.instanceId, el.baseMatrix);
    for (const m of moves) {
      const t = new THREE.Matrix4().makeTranslation(serverDeltaToViewer(m.deltaM));
      for (const gid of m.globalIds) {
        const el = this.model.byGlobalId.get(gid);
        if (el) this.model.mesh.setMatrixAt(el.instanceId, el.baseMatrix.clone().premultiply(t));
      }
    }
  }

  frame(globalIds: string[]) {
    if (!this.model) return;
    const box = new THREE.Box3();
    const tmp = new THREE.Box3();
    const m = new THREE.Matrix4();
    for (const gid of globalIds) {
      const el = this.model.byGlobalId.get(gid);
      if (!el) continue;
      this.model.mesh.getBoundingBoxAt(this.model.mesh.getGeometryIdAt(el.instanceId), tmp);
      this.model.mesh.getMatrixAt(el.instanceId, m);
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
