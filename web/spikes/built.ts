/** S0 for Show it built (docs/show-it-built.md): ORCA's own viewer renders a fix four ways for Muse Image and the
 * check. Spike only (not part of the app's build). Driven by spikes/built/capture.cjs through `window.s0`. */
import * as THREE from "three";
import { Viewer, meetingZone, type Mesh } from "../src/viewer/Viewer";

type Case = { name: string; scene: string; files: string[]; target: string; other: string; preview: Mesh[] };

const viewer = new Viewer(document.getElementById("v")!);
const V = viewer as any;  // the spike reaches into the viewer; the real capture will be a Viewer method
V.renderer.setPixelRatio(1);
let loaded = "";

function meshBox(meshes: Mesh[]): THREE.Box3 {
  const box = new THREE.Box3();
  for (const m of meshes) for (let i = 0; i < m.verts.length; i += 3) box.expandByPoint(new THREE.Vector3(m.verts[i], m.verts[i + 2], -m.verts[i + 1]));
  return box;
}

async function load(c: Case) {
  if (loaded === c.scene) return;
  const files = await Promise.all(c.files.map(async (_, i) =>
    new Uint8Array(await (await fetch(`/api/scenes/${c.scene}/files/${i}`)).arrayBuffer())));
  await viewer.load(files, c.files);
  loaded = c.scene;
}

/** Read a render target into a PNG (rows flipped: GL reads bottom up). */
function readPng(rt: THREE.WebGLRenderTarget): string {
  const { width: w, height: h } = rt;
  const buf = new Uint8Array(w * h * 4);
  V.renderer.readRenderTargetPixels(rt, 0, 0, w, h, buf);
  const img = new ImageData(w, h);
  for (let y = 0; y < h; y++) img.data.set(buf.subarray((h - 1 - y) * w * 4, (h - y) * w * 4), y * w * 4);
  const cv = document.createElement("canvas");
  cv.width = w; cv.height = h;
  cv.getContext("2d")!.putImageData(img, 0, 0);
  return cv.toDataURL("image/png");
}

/** Every element drawn in the scene, with its batch, so passes can recolour them. */
function elements() {
  const out: { gid: string; el: any }[] = [];
  for (const m of V.models) for (const el of m.byGlobalId.values()) out.push({ gid: el.globalId, el });
  return out;
}

/** Zones are not built (a robot's restricted space, a door's working space: style alpha under 0.2): hidden.
 * Physical see-through parts (glazing, mesh guards: 0.3 to 0.5) stay. `cut`: elements taken away for the view. */
function hideZones(cut: Set<string> = new Set()) {
  for (const { gid, el } of elements()) if (el.baseAlpha < 0.2 || cut.has(gid)) el.mesh.setVisibleAt(el.instanceId, false);
}

/** zoneCamera's distance (Viewer.zoneCamera), from a given direction. */
function zoneCam(zone: THREE.Box3, union: THREE.Box3, dir: THREE.Vector3): [THREE.Vector3, THREE.Vector3] {
  const zoneDiag = zone.getSize(new THREE.Vector3()).length(), unionDiag = union.getSize(new THREE.Vector3()).length();
  const least = Math.min(0.5, Math.max(0.25 * unionDiag, 2 * zoneDiag), V.reach(0.5, 0.15));
  const margin = Math.min(Math.max(0.35 * zoneDiag, 0.1 * unionDiag, least), Math.max((unionDiag - zoneDiag) / (2 * Math.sqrt(3)), least));
  const framed = zone.clone().expandByScalar(margin);
  const centre = framed.getCenter(new THREE.Vector3());
  const r = framed.getSize(new THREE.Vector3()).length() / 2;
  const cam: THREE.PerspectiveCamera = V.camera;
  const vFov = THREE.MathUtils.degToRad(cam.fov), hFov = 2 * Math.atan(Math.tan(vFov / 2) * cam.aspect);
  const dist = Math.max((r / Math.sin(Math.min(vFov, hFov) / 2)) * 1.1, 2 * r + least);
  return [centre.clone().add(dir.clone().normalize().multiplyScalar(dist)), centre];
}

const DIRS: THREE.Vector3[] = [];
for (const y of [0.8, 0.3, -0.5]) for (const [x, z] of [[1, 1], [1, -1], [-1, 1], [-1, -1]]) DIRS.push(new THREE.Vector3(x, y, z));
/** What taking an element away for the view costs: ceilings, lights, grilles, furniture, slabs and glazing are
 * routinely left out of such a view; walls less so; services, structure and machine parts are the context itself. */
const classes = new Map<string, string>();
async function classOf(scene: string, gid: string): Promise<string> {
  if (!classes.has(gid)) {
    const e = await (await fetch(`/api/scenes/${scene}/elements/${gid}`)).json();
    classes.set(gid, e.ifc_class ?? e.class ?? "");
  }
  return classes.get(gid)!;
}
const CHEAP = /^Ifc(Covering|LightFixture|AirTerminal|Furniture|FurnishingElement|Slab|Roof|Plate|Window|Door|Space|Railing|SanitaryTerminal)$/;
const cost = (cls: string) => (CHEAP.test(cls) ? 1 : cls === "IfcWall" || cls === "IfcCurtainWall" ? 2 : 6);
const idColor = (k: number) => new THREE.Vector4((k & 255) / 255, ((k >> 8) & 255) / 255, ((k >> 16) & 255) / 255, 1);

async function passes(c: Case, radius: number, side = 1024, pick: number | null = null, maxCut = 12) {
  await load(c);
  const scene: THREE.Scene = V.scene, renderer: THREE.WebGLRenderer = V.renderer;
  let cut = new Set<string>();
  const shaded = () => { viewer.setMode("shaded"); hideZones(cut); };
  viewer.setFocus({ a: null, b: null });
  shaded();
  V.marker.visible = false;
  V.flight = null;
  // Frame the fix as the app does (Viewer.frameFix): the changed pieces and where the moved element meets its partner.
  // An offset's first and last pieces are the rest of the run, metres long: the change is the pieces between (the
  // agent checks the same pieces[1:-1]).
  const changed = c.preview.length > 2 ? c.preview.slice(1, -1) : c.preview;
  const pieces = meshBox(changed);
  const zone = pieces.clone(), union = zone.clone();
  const a = viewer.boxOf([c.target]), b = viewer.boxOf([c.other]);
  if (!a.isEmpty() && !b.isEmpty()) zone.union(meetingZone(a, b));
  union.copy(zone).expandByScalar(V.reach(0.75, 0.2));
  // Context: everything within `radius` of the fix, cut by a section box (the camera sits outside it).
  const box = zone.clone().expandByScalar(radius);
  viewer.setSection(true, 0, box);
  if (V.sectionHelper) V.sectionHelper.visible = false;
  const camera: THREE.PerspectiveCamera = V.camera;
  const background = scene.background;
  const all = elements();
  const legend: Record<number, string> = {};
  all.forEach(({ gid }, i) => { legend[i + 1] = gid; });
  // Never taken away: the pair, and anything inside the fix's own box (its pieces, what it passes through).
  const keep = new Set([c.target, c.other]);
  const tmp = new THREE.Box3(), inner = pieces.clone().expandByScalar(0.01);
  for (const { gid, el } of all) if (V.instanceBox(el, tmp).intersectsBox(inner)) keep.add(gid);
  const draw = (rt: THREE.WebGLRenderTarget, material: THREE.Material | null, bg: THREE.Color | null, clear = true) => {
    scene.overrideMaterial = material;
    scene.background = clear ? bg : null;  // a colour background clears the depth buffer too
    renderer.setRenderTarget(rt);
    if (clear) { renderer.setClearColor(bg ?? new THREE.Color(1, 1, 1), 1); renderer.clear(); }
    renderer.autoClear = false;
    renderer.render(scene, camera);
    renderer.autoClear = true;
    renderer.setRenderTarget(null);
  };
  const read = (rt: THREE.WebGLRenderTarget) => {
    const buf = new Uint8Array(rt.width * rt.height * 4);
    renderer.readRenderTargetPixels(rt, 0, 0, rt.width, rt.height, buf);
    return buf;
  };
  const clip = { clippingPlanes: V.clipping as THREE.Plane[], side: THREE.DoubleSide };
  const white = (front: boolean) => new THREE.MeshBasicMaterial({ color: 0xffffff, side: THREE.DoubleSide,
    ...(front ? { polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -8 } : {}) });
  const modelsVisible = (on: boolean) => { for (const m of V.models) { m.mesh.visible = on; if (m.glass) m.glass.visible = on; } };
  const aim = (dir: THREE.Vector3) => {
    const [position, target] = zoneCam(zone, union, dir);
    camera.position.copy(position);
    V.controls.target.copy(target);
    V.controls.update();
    V.adjustClipRange();
  };
  const small = new THREE.WebGLRenderTarget(256, 256, { samples: 0 });
  /** How much of the fix this view shows, and which elements hide the rest (pixels each). */
  const measure = () => {
    V.addMeshes(changed, white(false));
    modelsVisible(false);
    draw(small, null, new THREE.Color(0, 0, 0));
    const alone = read(small);
    V.clearOverlay();
    shaded();
    all.forEach(({ el }, i) => el.mesh.setColorAt(el.instanceId, idColor(i + 1)));
    draw(small, new THREE.MeshBasicMaterial({ ...clip, color: 0xffffff }), new THREE.Color(0, 0, 0));
    const ids = read(small);
    V.addMeshes(changed, white(true));
    modelsVisible(false);
    draw(small, null, null, false);
    const seen = read(small);
    V.clearOverlay();
    shaded();
    let n = 0, shown = 0;
    const hiders = new Map<string, number>();
    for (let i = 0; i < alone.length; i += 4) {
      if (alone[i] < 128) continue;
      n++;
      if (seen[i] > 128 && seen[i + 1] > 128 && seen[i + 2] > 128) { shown++; continue; }
      const gid = legend[ids[i] | (ids[i + 1] << 8) | (ids[i + 2] << 16)];
      if (gid) hiders.set(gid, (hiders.get(gid) ?? 0) + 1);
    }
    return { shown: n ? shown / n : 0, hiders };
  };
  // The viewpoint: of 12 directions, the one that shows at least 85% of the fix having taken away the fewest
  // elements (each time the one hiding most of what is still hidden, never the pair or what the fix passes).
  // Each step takes away the element hiding the most of the fix for what it costs; it stops at 85% shown, or at 70%
  // when only costly elements are left. The view kept costs least: cuts, what stays hidden, and a little for
  // looking up from below.
  const views: { dir: number[]; shown: number; cut: string[]; cost: number; score: number }[] = [];
  for (const dir of DIRS) {
    aim(dir);
    cut = new Set();
    let spent = 0;
    let m = measure();
    while (m.shown < 0.85 && cut.size < maxCut) {
      const options = await Promise.all([...m.hiders.entries()].filter(([g]) => !keep.has(g))
        .map(async ([g, px]) => ({ g, px, cost: cost(await classOf(c.scene, g)) })));
      const next = options.sort((x, y) => y.px / y.cost - x.px / x.cost)[0];
      if (!next || (next.cost > 2 && m.shown >= 0.7)) break;
      cut.add(next.g);
      spent += next.cost;
      m = measure();
    }
    views.push({ dir: dir.toArray(), shown: m.shown, cut: [...cut], cost: spent,
      score: spent + 10 * (1 - m.shown) + (m.shown < 0.6 ? 100 : 0) + (dir.y < 0 ? 1 : 0) });
  }
  small.dispose();
  const best = pick ?? views.reduce((bi, v, i) => (v.score < views[bi].score - 1e-6 ? i : bi), 0);
  cut = new Set(views[best].cut);
  // A slab, roof or ceiling taken away above the fix becomes the section's top (its underside), one below becomes its
  // bottom: what lies beyond it (the floor above and its furniture, the room below) goes too, cleanly cut.
  const section = box.clone(), centre = zone.getCenter(new THREE.Vector3());
  for (const gid of [...cut]) {
    if (!/^Ifc(Slab|Roof|Covering)$/.test(classes.get(gid) ?? "")) continue;
    const f = all.find((x) => x.gid === gid)!;
    const eb = V.instanceBox(f.el, new THREE.Box3());
    if (eb.min.y > centre.y) section.max.y = Math.min(section.max.y, eb.min.y - 0.002);
    else if (eb.max.y < centre.y) section.min.y = Math.max(section.min.y, eb.max.y + 0.002);
    else continue;
    cut.delete(gid);
  }
  viewer.setSection(true, 0, section);
  if (V.sectionHelper) V.sectionHelper.visible = false;
  scene.background = background;
  shaded();
  aim(DIRS[best]);

  const look = V.png(side, "image/png");

  const rt = new THREE.WebGLRenderTarget(side, side, { samples: 0 });
  const shot = (material: THREE.Material, bg: THREE.Color | null) => { draw(rt, material, bg); return readPng(rt); };

  // Ids: one flat colour per element (index + 1, 24 bits), no light, no antialiasing.
  all.forEach(({ el }, i) => el.mesh.setColorAt(el.instanceId, idColor(i + 1)));
  const glassMaterials = V.models.map((m: any) => m.glass?.material);
  const ids = shot(new THREE.MeshBasicMaterial({ ...clip, color: 0xffffff }), new THREE.Color(0, 0, 0));
  shaded();  // colours back
  V.models.forEach((m: any, i: number) => { if (m.glass) m.glass.material = glassMaterials[i]; });

  const normals = shot(new THREE.MeshNormalMaterial(clip), new THREE.Color(0, 0, 0));
  const depth = shot(new THREE.MeshDepthMaterial({ ...clip, depthPacking: THREE.RGBADepthPacking }), new THREE.Color(1, 1, 1));

  // The fix's own pieces alone (white on black): where the check looks for the fix.
  for (const m of V.models) { m.mesh.visible = false; if (m.glass) m.glass.visible = false; }
  V.addMeshes(changed, new THREE.MeshBasicMaterial({ color: 0xffffff, side: THREE.DoubleSide }));
  const fix = shot(new THREE.MeshBasicMaterial({ color: 0xffffff, side: THREE.DoubleSide }), new THREE.Color(0, 0, 0));
  V.clearOverlay();
  scene.overrideMaterial = null;
  scene.background = background;
  shaded();
  rt.dispose();
  viewer.setSection(false);
  return { look, ids, normals, depth, fix, legend, near: camera.near, far: camera.far, views, best, cut: [...cut], section: [section.min.y, section.max.y] };
}

(window as any).s0 = { passes, ready: true };

/** See-through elements (style alpha < 0.99) of a case's scene: GlobalId and alpha. */
async function glass(c: Case) {
  await load(c);
  return elements().filter(({ el }) => el.baseAlpha < 0.99).map(({ gid, el }) => [gid, +el.baseAlpha.toFixed(2)]);
}
(window as any).s0.glass = glass;
