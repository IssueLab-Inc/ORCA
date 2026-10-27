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

  /** Red/green pair, everything else greyed or hidden (images A and B). */
  highlight(a: string | null, b: string | null, isolate = false) {
    for (const model of this.models) {
      for (const el of model.byGlobalId.values()) {
        const inPair = el.globalId === a || el.globalId === b;
        model.mesh.setColorAt(el.instanceId, el.globalId === a ? RED : el.globalId === b ? GREEN : a || b ? GREY : el.baseColor);
        model.mesh.setVisibleAt(el.instanceId, !isolate || inPair || !(a || b));
      }
    }
  }

  /** Preview moves without touching the model: GlobalIds + server delta (metres, Z up). */
  preview(moves: { globalIds: string[]; deltaM: number[] }[]) {
    for (const model of this.models) for (const el of model.byGlobalId.values()) model.mesh.setMatrixAt(el.instanceId, el.baseMatrix);
    for (const m of moves) {
      const t = new THREE.Matrix4().makeTranslation(serverDeltaToViewer(m.deltaM));
      for (const gid of m.globalIds) {
        const f = this.find(gid);
        if (f) f.model.mesh.setMatrixAt(f.el.instanceId, f.el.baseMatrix.clone().premultiply(t));
      }
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
