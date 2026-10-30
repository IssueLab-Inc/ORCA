// The view cube (docs/views.md, "Navigate like a CAD tool"): a labelled cube in the 3D pane's corner that turns with
// the camera. Click a face, an edge or a corner for that view (26 in all); drag it to orbit. Drawn by the viewer's own
// renderer into a small viewport; a DOM square over it takes the pointer, so the model's controls never see it.
import * as THREE from "three";
import { cubeName, cubeRegion } from "./views";

/** Face order of a BoxGeometry: +x, −x, +y, −y, +z, −z. Front looks north, from the south (three's +z is IFC south). */
const FACES = ["RIGHT", "LEFT", "TOP", "BOTTOM", "FRONT", "BACK"];
export const CUBE_PX = 104;

export class ViewCube {
  readonly el: HTMLDivElement;
  private scene = new THREE.Scene();
  private camera = new THREE.OrthographicCamera(-1.75, 1.75, 1.75, -1.75, 0.1, 20);
  private cube: THREE.Mesh;
  private hover = new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1),
    new THREE.MeshBasicMaterial({ color: "#2f8fdf", transparent: true, opacity: 0.55, depthTest: false }));
  private raycaster = new THREE.Raycaster();
  private drag: { x: number; y: number; moved: boolean } | null = null;

  /** `onPick`: a direction to look from (three axes), `onOrbit`: a drag in pixels, `onHome`: the house above it. */
  constructor(private onPick: (dir: THREE.Vector3) => void, private onOrbit: (dx: number, dy: number) => void,
    private onHome: () => void) {
    const materials = FACES.map((t) => new THREE.MeshBasicMaterial({ map: faceTexture(t) }));
    this.cube = new THREE.Mesh(new THREE.BoxGeometry(2, 2, 2), materials);
    const edges = new THREE.LineSegments(new THREE.EdgesGeometry(this.cube.geometry),
      new THREE.LineBasicMaterial({ color: "#5d6a7a" }));
    this.hover.visible = false;
    this.hover.renderOrder = 2;
    this.scene.add(this.cube, edges, this.hover);
    this.el = document.createElement("div");
    this.el.className = "view-cube";
    this.el.setAttribute("role", "group");
    this.el.setAttribute("aria-label", "View cube: click a face, edge or corner for that view; drag to orbit");
    const home = document.createElement("button");
    home.type = "button";
    home.className = "view-cube-home";
    home.setAttribute("aria-label", "Home view");
    home.dataset.tip = "Home view  ·  H";
    home.dataset.tipSide = "left";
    home.innerHTML = `<svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true"><path d="M3 11 12 3l9 8M5 9.5V21h5v-6h4v6h5V9.5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/></svg>`;
    home.addEventListener("click", (e) => { e.stopPropagation(); this.onHome(); });
    this.el.appendChild(home);
    const stop = (e: Event) => e.stopPropagation();
    this.el.addEventListener("click", stop);
    this.el.addEventListener("dblclick", stop);
    this.el.addEventListener("pointerdown", (e) => {
      if (e.target === home || home.contains(e.target as Node)) return;
      e.stopPropagation();
      this.el.setPointerCapture(e.pointerId);
      this.drag = { x: e.clientX, y: e.clientY, moved: false };
    });
    this.el.addEventListener("pointermove", (e) => {
      if (this.drag) {
        const dx = e.clientX - this.drag.x, dy = e.clientY - this.drag.y;
        if (this.drag.moved || Math.hypot(dx, dy) > 3) {
          this.drag.moved = true;
          this.onOrbit(dx, dy);
          this.drag.x = e.clientX; this.drag.y = e.clientY;
        }
        return;
      }
      const d = this.regionAt(e);
      this.showHover(d);
      this.el.title = d ? cubeName(d) : "";
    });
    this.el.addEventListener("pointerleave", () => { if (!this.drag) this.showHover(null); });
    this.el.addEventListener("pointerup", (e) => {
      const was = this.drag;
      this.drag = null;
      if (was && !was.moved) {
        const d = this.regionAt(e);
        if (d) this.onPick(d);
      }
    });
  }

  /** Draw the cube turned like `main` into the bottom-right square of `rect` (canvas CSS pixels, GL origin). */
  render(renderer: THREE.WebGLRenderer, main: THREE.Camera, rect: { x: number; y: number; w: number; h: number }) {
    const s = CUBE_PX, x = rect.x + rect.w - s - 8, y = rect.y + 8;
    this.camera.quaternion.copy(main.quaternion);
    this.camera.position.set(0, 0, 6).applyQuaternion(main.quaternion);
    this.camera.updateMatrixWorld();
    renderer.setViewport(x, y, s, s);
    renderer.setScissor(x, y, s, s);
    renderer.setScissorTest(true);
    const auto = renderer.autoClear;
    renderer.autoClear = false;
    renderer.clearDepth();
    renderer.render(this.scene, this.camera);
    renderer.autoClear = auto;
  }

  /** The direction under the pointer, or null off the cube. */
  private regionAt(e: PointerEvent): THREE.Vector3 | null {
    const r = this.el.getBoundingClientRect();
    const ndc = new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
    this.raycaster.setFromCamera(ndc, this.camera);
    const hit = this.raycaster.intersectObject(this.cube, false)[0];
    return hit ? cubeRegion(hit.point) : null;
  }

  private showHover(d: THREE.Vector3 | null) {
    this.hover.visible = !!d;
    if (!d) return;
    const size = (v: number) => (v ? 0.5 : 1.1), at = (v: number) => v * 0.78;
    this.hover.scale.set(size(d.x), size(d.y), size(d.z));
    this.hover.position.set(at(d.x), at(d.y), at(d.z));
  }

  dispose() {
    this.el.remove();
    this.scene.traverse((o) => {
      const m = o as THREE.Mesh;
      if (!m.geometry) return;
      m.geometry.dispose();
      for (const mat of [m.material].flat() as THREE.Material[]) {
        (mat as THREE.MeshBasicMaterial).map?.dispose();
        mat.dispose();
      }
    });
  }
}

function faceTexture(text: string): THREE.Texture {
  const c = document.createElement("canvas");
  c.width = c.height = 128;
  const g = c.getContext("2d")!;
  g.fillStyle = "#eef2f6";
  g.fillRect(0, 0, 128, 128);
  g.strokeStyle = "#b7c1cc";
  g.lineWidth = 4;
  g.strokeRect(2, 2, 124, 124);
  g.fillStyle = "#2b3846";
  g.font = `600 ${text.length > 5 ? 22 : 26}px "IBM Plex Sans", system-ui, sans-serif`;
  g.textAlign = "center";
  g.textBaseline = "middle";
  g.fillText(text, 64, 66);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}
