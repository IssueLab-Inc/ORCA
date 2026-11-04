import * as THREE from "three";
import {
  CONTEXT_BOXES, CONTEXT_RUNS, GIRDER, RUNS, SPIGOT, SPIGOT_X, cutPath, offsetPath, sweep, type Run, type Swept,
} from "./northbank";
import type { HeroFrame, RunKey } from "./timeline";

/**
 * The landing hero's 3D picture: Northbank's Level 02 girder and the services around it (northbank.ts), drawn with
 * three.js and set to a frame of the replay (timeline.ts) each animation frame. It owns its WebGL context and gives it
 * back on dispose. Colours are the viewer's (the landing's legend teaches them): element A red, B green, an idea amber
 * while checked and teal once it passed, what a failed idea hit magenta, the run as it was orange.
 */

const C = {
  bg: 0x041321, a: 0xe0473f, b: 0x2fb153, try: 0xf5a623, pass: 0x12b5cb, hit: 0xe040fb, before: 0xe67e22,
  steel: 0x9db2c6, service: 0xd3dde7, structure: 0x58758f, ctxService: 0x6a88a3, edge: 0x8fb7da, lamp: 0xcfe6ff, scan: 0x5fe3f2,
};

/** IFC metres (x east, y north, z up) to three.js (y up). */
const V = (x: number, y: number, z: number) => new THREE.Vector3(x, z, -y);

function geometry(s: Swept, lift?: Float32Array): THREE.BufferGeometry {
  const p = s.positions, n = s.normals, P = new Float32Array(p.length), N = new Float32Array(n.length);
  for (let i = 0; i < p.length; i += 3) {
    P[i] = p[i]; P[i + 1] = p[i + 2]; P[i + 2] = -p[i + 1];
    N[i] = n[i]; N[i + 1] = n[i + 2]; N[i + 2] = -n[i + 1];
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.BufferAttribute(P, 3));
  g.setAttribute("normal", new THREE.BufferAttribute(N, 3));
  if (lift) g.setAttribute("aLift", new THREE.BufferAttribute(lift, 1));
  return g;
}

/** How far each vertex's centreline stands above the run (for growing an idea out of the run it replaces). */
function liftOf(s: Swept, base: number): Float32Array {
  return s.heights.map((h) => Math.max(0, h - base));
}

interface Uniforms { [k: string]: { value: unknown } }
const SCAN: Uniforms = { uScanX: { value: -100 }, uScanAmt: { value: 0 }, uScanColor: { value: new THREE.Color(C.scan) } };
/** Everything fades out beyond an ellipse round the girder's three crossings (three.js x and z), so the runs, the
 * girder and the slab trail off instead of ending, and never crowd the words beside the picture. */
const FADE: Uniforms = { uFadeC: { value: new THREE.Vector2(3.5, 2.0) }, uFadeR: { value: new THREE.Vector2(6.4, 4.4) } };
const FADE_GLSL = "uniform vec2 uFadeC;\nuniform vec2 uFadeR;\n"
  + "float orcaFade(vec3 w) { return 1.0 - smoothstep(0.55, 1.0, length((w.xz - uFadeC) / uFadeR)); }";
const WORLD_VERTEX = "#include <project_vertex>\nvWorld = (modelMatrix * vec4(transformed, 1.0)).xyz;";
const FADE_FRAGMENT = "diffuseColor.a *= orcaFade(vWorld);\n#include <opaque_fragment>";

/** A standard material with the scene's fade and scan band (and, for ideas, the lift from the run) in its shader. */
function material(params: THREE.MeshStandardMaterialParameters, own?: Uniforms, lift = false): THREE.MeshStandardMaterial {
  const m = new THREE.MeshStandardMaterial({ roughness: 0.62, metalness: 0.12, transparent: true, ...params });
  const uniforms = own ?? SCAN;
  m.onBeforeCompile = (shader) => {
    Object.assign(shader.uniforms, uniforms, FADE, lift ? { uLift: (own as Uniforms).uLift } : {});
    shader.vertexShader = shader.vertexShader
      .replace("#include <common>", `#include <common>\nvarying vec3 vWorld;${lift ? "\nattribute float aLift;\nuniform float uLift;" : ""}`)
      .replace("#include <begin_vertex>", `#include <begin_vertex>${lift ? "\ntransformed.y -= aLift * (1.0 - uLift);" : ""}`)
      .replace("#include <project_vertex>", WORLD_VERTEX);
    shader.fragmentShader = shader.fragmentShader
      .replace("#include <common>", `#include <common>\nvarying vec3 vWorld;\nuniform float uScanX;\nuniform float uScanAmt;\nuniform vec3 uScanColor;\n${FADE_GLSL}`)
      .replace("#include <emissivemap_fragment>",
        "#include <emissivemap_fragment>\ntotalEmissiveRadiance += uScanColor * uScanAmt * exp(-pow((vWorld.x - uScanX) / 0.2, 2.0));")
      .replace("#include <opaque_fragment>", FADE_FRAGMENT);
  };
  m.customProgramCacheKey = () => (lift ? "orca-lift" : "orca-scan");
  return m;
}

/** A line material that fades with the scene. */
function lineMaterial(color: number, opacity: number, depthTest = true): THREE.LineBasicMaterial {
  const m = new THREE.LineBasicMaterial({ color, transparent: true, opacity, depthWrite: false, depthTest });
  m.onBeforeCompile = (shader) => {
    Object.assign(shader.uniforms, FADE);
    shader.vertexShader = shader.vertexShader.replace("#include <common>", "#include <common>\nvarying vec3 vWorld;").replace("#include <project_vertex>", WORLD_VERTEX);
    shader.fragmentShader = shader.fragmentShader.replace("#include <common>", `#include <common>\nvarying vec3 vWorld;\n${FADE_GLSL}`)
      .replace("#include <opaque_fragment>", FADE_FRAGMENT);
  };
  m.customProgramCacheKey = () => "orca-line";
  return m;
}

function edges(g: THREE.BufferGeometry, color: number, opacity: number, angle = 25): THREE.LineSegments {
  return new THREE.LineSegments(new THREE.EdgesGeometry(g, angle), lineMaterial(color, opacity));
}

/** One clashing run: its fixed ends, its middle as modelled and as fixed, the idea being tried, and its old self. */
interface RunParts {
  run: Run;
  base: THREE.MeshStandardMaterial;   // the ends and, until it is kept, the middle
  middle: THREE.Mesh; middleMat: THREE.MeshStandardMaterial;
  fixed: THREE.Mesh; fixedMat: THREE.MeshStandardMaterial;
  ghost: THREE.Mesh; ghostMat: THREE.MeshStandardMaterial; ghostU: Uniforms;
  before: THREE.Mesh; beforeMat: THREE.MeshStandardMaterial;
  opening: THREE.LineSegments;
}

export interface Anchor { id: string; at: THREE.Vector3 }

export class HeroScene {
  readonly renderer: THREE.WebGLRenderer;
  private scene = new THREE.Scene();
  readonly camera = new THREE.PerspectiveCamera(30, 1, 0.1, 80);
  private runs = new Map<RunKey, RunParts>();
  private girderMat: THREE.MeshStandardMaterial;
  private girderEdges: THREE.LineBasicMaterial;
  private whole: THREE.Mesh; private wholeMat: THREE.MeshStandardMaterial;
  private spigotMats: THREE.MeshStandardMaterial[] = [];
  private scanPlane: THREE.Mesh;
  private aim = { target: V(3.4, -1.95, 7.25), dist: 0 };
  private view = { target: V(3.4, -1.95, 7.25), dist: 0 };
  /** The visitor's drag, added to the slow drift (radians). */
  readonly orbit = { yaw: 0, pitch: 0 };
  private size = { w: 1, h: 1 };
  private win = { x: 0.5, y: 0.5, w: 1, h: 1 };
  private full = { w: 1, h: 1 };

  constructor(canvas: HTMLCanvasElement) {
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true, powerPreference: "high-performance" });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.setClearColor(C.bg, 1);
    this.scene.background = new THREE.Color(C.bg);
    this.scene.fog = new THREE.Fog(C.bg, 9, 25);

    this.scene.add(new THREE.HemisphereLight(0xcfe3f5, 0x0a1a2a, 1.25));
    const key = new THREE.DirectionalLight(0xffffff, 1.5);
    key.position.copy(V(-2, -6, 14));
    const rim = new THREE.DirectionalLight(0x7fc4ff, 0.7);
    rim.position.copy(V(10, 6, 9));
    this.scene.add(key, rim);

    this.addCeiling();
    this.addContext();
    ({ mat: this.girderMat, edges: this.girderEdges } = this.addGirder());
    for (const run of RUNS) this.runs.set(run.key, this.addRun(run));
    ({ mesh: this.whole, mat: this.wholeMat } = this.addWholeTray());

    this.scanPlane = new THREE.Mesh(new THREE.PlaneGeometry(7.2, 1.7),
      new THREE.MeshBasicMaterial({ color: C.scan, transparent: true, opacity: 0, blending: THREE.AdditiveBlending, depthWrite: false, side: THREE.DoubleSide }));
    this.scanPlane.rotation.y = Math.PI / 2;
    this.scanPlane.position.copy(V(0, -1.9, 7.35));
    this.scene.add(this.scanPlane);
  }

  private addCeiling() {
    // The suspended ceiling's 600 grid, a little under the services, fading into the fog.
    const pts: number[] = [];
    const z = 6.72, x0 = -3, x1 = 10.2, y0 = -6, y1 = 2.4;
    for (let x = x0; x <= x1 + 1e-6; x += 0.6) pts.push(...V(x, y0, z).toArray(), ...V(x, y1, z).toArray());
    for (let y = y0; y <= y1 + 1e-6; y += 0.6) pts.push(...V(x0, y, z).toArray(), ...V(x1, y, z).toArray());
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.Float32BufferAttribute(pts, 3));
    this.scene.add(new THREE.LineSegments(g, lineMaterial(C.edge, 0.16)));
  }

  private addContext() {
    const mats = {
      structure: material({ color: C.structure, transparent: true, opacity: 0.5, depthWrite: false }),
      services: material({ color: C.ctxService, transparent: true, opacity: 0.55, depthWrite: false }),
      ceiling: material({ color: 0x2b4560, emissive: C.lamp, emissiveIntensity: 0.32, transparent: true, opacity: 0.9 }),
      slab: material({ color: 0x9bb7d3, transparent: true, opacity: 0.045, depthWrite: false }),
    };
    for (const b of CONTEXT_BOXES) {
      const g = new THREE.BoxGeometry(b.max[0] - b.min[0], b.max[2] - b.min[2], b.max[1] - b.min[1]);
      const mesh = new THREE.Mesh(g, mats[b.kind]);
      mesh.position.copy(V((b.min[0] + b.max[0]) / 2, (b.min[1] + b.max[1]) / 2, (b.min[2] + b.max[2]) / 2));
      mesh.add(edges(g, C.edge, b.kind === "slab" ? 0.18 : b.kind === "ceiling" ? 0.1 : 0.2));
      this.scene.add(mesh);
    }
    for (const r of CONTEXT_RUNS) {
      const s = sweep(offsetPath(r.x[0], r.x[1], r.z, r.offset ? [r.offset] : []), r.y, r.section, r.smooth);
      const g = geometry(s), mesh = new THREE.Mesh(g, mats.services);
      if (!r.smooth) mesh.add(edges(g, C.edge, 0.22));
      this.scene.add(mesh);
    }
    // The return air spigots, round: along y over the tray, then down to their grilles.
    for (const x of SPIGOT_X) {
      const m = material({ color: C.ctxService, transparent: true, opacity: 0.6, depthWrite: false });
      this.spigotMats.push(m);
      const len = SPIGOT.y[1] - SPIGOT.y[0];
      const run = new THREE.Mesh(new THREE.CylinderGeometry(SPIGOT.r, SPIGOT.r, len, 20, 1, true), m);
      run.rotation.x = Math.PI / 2;
      run.position.copy(V(x, (SPIGOT.y[0] + SPIGOT.y[1]) / 2, SPIGOT.z));
      const drop = new THREE.Mesh(new THREE.CylinderGeometry(SPIGOT.r, SPIGOT.r, SPIGOT.drop[1] - SPIGOT.drop[0], 20, 1, true), m);
      drop.position.copy(V(x, SPIGOT.y[1], (SPIGOT.drop[0] + SPIGOT.drop[1]) / 2));
      const elbow = new THREE.Mesh(new THREE.SphereGeometry(SPIGOT.r, 20, 12), m);
      elbow.position.copy(V(x, SPIGOT.y[1], SPIGOT.z));
      this.scene.add(run, drop, elbow);
    }
  }

  private addGirder() {
    const mat = material({ color: C.steel, metalness: 0.35, roughness: 0.48, transparent: true, opacity: 0.86 });
    const edgeMat = lineMaterial(0xbfd8ee, 0.55);
    const group = new THREE.Group();
    const f = GIRDER.flange, [x0, x1] = GIRDER.x, [y0, y1] = GIRDER.y;
    const box = (xa: number, xb: number, ya: number, yb: number, za: number, zb: number) => {
      const g = new THREE.BoxGeometry(xb - xa, zb - za, yb - ya);
      const m = new THREE.Mesh(g, mat);
      m.position.copy(V((xa + xb) / 2, (ya + yb) / 2, (za + zb) / 2));
      m.add(new THREE.LineSegments(new THREE.EdgesGeometry(g), edgeMat));
      group.add(m);
    };
    box(x0, x1, y0, y1, GIRDER.z[0], GIRDER.z[0] + f);
    box(x0, x1, y0, y1, GIRDER.z[1] - f, GIRDER.z[1]);
    for (const s of GIRDER.stiffeners) box(s.x[0], s.x[1], GIRDER.stiffenerY[0], GIRDER.stiffenerY[1], GIRDER.web.z[0], GIRDER.web.z[1]);
    // The web: a 20 mm plate with its six openings, as the model's profile with voids.
    const [wz0, wz1] = GIRDER.web.z;
    const shape = new THREE.Shape([new THREE.Vector2(y0, wz0), new THREE.Vector2(y1, wz0), new THREE.Vector2(y1, wz1), new THREE.Vector2(y0, wz1)]);
    for (const o of GIRDER.openings) {
      shape.holes.push(new THREE.Path([new THREE.Vector2(o.y[0], o.z[0]), new THREE.Vector2(o.y[0], o.z[1]),
        new THREE.Vector2(o.y[1], o.z[1]), new THREE.Vector2(o.y[1], o.z[0])]));
    }
    const web = new THREE.ExtrudeGeometry(shape, { depth: GIRDER.web.x[1] - GIRDER.web.x[0], bevelEnabled: false, curveSegments: 1 });
    // shape (u = y, v = z, w = x) to three (x = w, y = v, z = -u)
    web.applyMatrix4(new THREE.Matrix4().set(0, 0, 1, GIRDER.web.x[0], 0, 1, 0, 0, -1, 0, 0, 0, 0, 0, 0, 1));
    web.computeVertexNormals();
    const webMesh = new THREE.Mesh(web, mat);
    webMesh.add(new THREE.LineSegments(new THREE.EdgesGeometry(web, 20), edgeMat));
    group.add(webMesh);
    this.scene.add(group);
    return { mat, edges: edgeMat };
  }

  private addRun(run: Run): RunParts {
    const flat = offsetPath(run.x[0], run.x[1], run.z);
    const fixedPath = offsetPath(run.x[0], run.x[1], run.z, [run.fix]);
    const [s0, s1] = run.split;
    const base = material({ color: C.service, transparent: true, opacity: 1 });
    // Outlines on what is drawn solid (an idea grows in its shader, so it has none), fading with their mesh.
    const part = (path: readonly (readonly [number, number])[], mat: THREE.MeshStandardMaterial, outline: boolean, lift = false) => {
      const s = sweep(path as [number, number][], run.y, run.section, run.smooth, false);
      const g = geometry(s, lift ? liftOf(s, run.z) : undefined);
      const mesh = new THREE.Mesh(g, mat);
      if (outline && !run.smooth) mesh.add(edges(g, 0xffffff, 0.35));
      this.scene.add(mesh);
      return mesh;
    };
    part(cutPath(flat, run.x[0], s0), base, true);
    part(cutPath(flat, s1, run.x[1]), base, true);
    const middleMat = base.clone();
    middleMat.onBeforeCompile = base.onBeforeCompile;
    const middle = part(cutPath(flat, s0, s1), middleMat, true);
    const fixedMat = material({ color: C.pass, emissive: C.pass, emissiveIntensity: 0.18, transparent: true, opacity: 0 });
    const fixed = part(cutPath(fixedPath, s0, s1), fixedMat, true);
    const ghostU: Uniforms = { uScanX: { value: -100 }, uScanAmt: { value: 0 }, uScanColor: { value: new THREE.Color(0xffffff) }, uLift: { value: 0 } };
    const ghostMat = material({ color: C.try, emissive: C.try, emissiveIntensity: 0.55, transparent: true, opacity: 0, depthWrite: false }, ghostU, true);
    const ghost = part(cutPath(fixedPath, s0, s1), ghostMat, false, true);
    const beforeMat = material({ color: C.before, emissive: C.before, emissiveIntensity: 0.3, transparent: true, opacity: 0, depthWrite: false });
    const before = part(cutPath(flat, s0, s1), beforeMat, false);
    before.scale.setScalar(1.002);
    // The web opening this run's fix uses, outlined on both faces of the web.
    const o = GIRDER.openings.find((q) => q.y[0] < run.y && q.y[1] > run.y && q.z[0] < run.z + run.fix.dz && q.z[1] > run.z + run.fix.dz)!;
    const pts: number[] = [];
    for (const x of [GIRDER.web.x[0] - 0.004, GIRDER.web.x[1] + 0.004]) {
      const c = [V(x, o.y[0], o.z[0]), V(x, o.y[1], o.z[0]), V(x, o.y[1], o.z[1]), V(x, o.y[0], o.z[1])];
      for (let i = 0; i < 4; i++) pts.push(...c[i].toArray(), ...c[(i + 1) % 4].toArray());
    }
    const og = new THREE.BufferGeometry();
    og.setAttribute("position", new THREE.Float32BufferAttribute(pts, 3));
    const opening = new THREE.LineSegments(og, lineMaterial(C.pass, 0, false));
    opening.renderOrder = 5;
    this.scene.add(opening);
    return { run, base, middle, middleMat, fixed, fixedMat, ghost, ghostMat, ghostU, before, beforeMat, opening };
  }

  /** The tray's first idea: the whole run moved up 250 mm (it fails on the spigots). */
  private addWholeTray() {
    const run = RUNS.find((r) => r.key === "tray")!;
    const s = sweep(offsetPath(run.x[0], run.x[1], run.z), run.y, run.section, false, false);
    const mat = material({ color: C.try, emissive: C.try, emissiveIntensity: 0.5, transparent: true, opacity: 0, depthWrite: false });
    const mesh = new THREE.Mesh(geometry(s), mat);
    this.scene.add(mesh);
    return { mesh, mat };
  }

  /** Canvas size in CSS pixels, and the part of it the subject is framed in (fractions of the canvas: its centre and
   * size). The camera's view is cut from a larger frame centred on that window, so the subject sits there. */
  setSize(w: number, h: number, win = { x: 0.5, y: 0.5, w: 1, h: 1 }) {
    this.size = { w: Math.max(1, w), h: Math.max(1, h) };
    this.win = { ...win };
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, this.size.w < 700 ? 1.6 : 2));
    this.renderer.setSize(this.size.w, this.size.h, false);
    const W = this.size.w, H = this.size.h;
    const F = win.x >= 0.5 ? 2 * win.x * W : 2 * (1 - win.x) * W, G = win.y >= 0.5 ? 2 * win.y * H : 2 * (1 - win.y) * H;
    this.full = { w: F, h: G };
    this.camera.aspect = F / G;
    this.camera.setViewOffset(F, G, win.x >= 0.5 ? 0 : F - W, win.y >= 0.5 ? 0 : G - H, W, H);
    this.camera.updateProjectionMatrix();
  }

  /** The distance that fits a subject `sw` by `sh` metres (as seen) into the window. */
  private fit(sw: number, sh: number): number {
    const ww = Math.max(40, this.win.w * this.size.w), wh = Math.max(40, this.win.h * this.size.h);
    return (this.full.h / (2 * Math.tan((this.camera.fov * Math.PI) / 360))) * Math.max(sw / ww, sh / wh);
  }

  /** Draws the replay at this frame. `dt` (s) eases the camera; `drift` (s) turns it slowly. */
  render(f: HeroFrame, dt: number, drift: number) {
    // camera: ease towards the clash being told
    const focus = f.focus === "all" ? null : RUNS.find((r) => r.key === f.focus)!;
    this.aim.target.copy(focus ? V(3.5, focus.y + 0.15, focus.z + focus.fix.dz * 0.55) : V(3.4, -1.95, 7.25));
    this.aim.dist = focus ? this.fit(5.6, 2.8) : this.fit(7.6, 3.6);
    const k = this.view.dist ? 1 - Math.exp(-Math.min(dt, 0.1) * 1.8) : 1;
    this.view.target.lerp(this.aim.target, k);
    this.view.dist += (this.aim.dist - this.view.dist) * k;
    const yaw = 0.66 + Math.sin(drift * 0.11) * 0.09 + this.orbit.yaw, pitch = 0.47 + Math.sin(drift * 0.07) * 0.035 + this.orbit.pitch;
    const p = Math.min(1.2, Math.max(-0.1, pitch));
    this.camera.position.set(
      this.view.target.x + this.view.dist * Math.cos(p) * Math.sin(yaw),
      this.view.target.y + this.view.dist * Math.sin(p),
      this.view.target.z + this.view.dist * Math.cos(p) * Math.cos(yaw));
    this.camera.lookAt(this.view.target);
    // fog by the camera's distance, so a wider framing never sinks the subject in it
    const fog = this.scene.fog as THREE.Fog;
    fog.near = this.view.dist * 0.82;
    fog.far = this.view.dist * 1.75;

    // the check's sweep across everything
    const scanning = f.scan >= 0;
    SCAN.uScanX.value = scanning ? -1.5 + f.scan * 11 : -100;
    SCAN.uScanAmt.value = scanning ? 0.9 * Math.sin(Math.PI * Math.min(1, f.scan * 1.15)) + 0.1 : 0;
    const sp = this.scanPlane.material as THREE.MeshBasicMaterial;
    sp.opacity = scanning ? 0.13 * Math.sin(Math.PI * f.scan) : 0;
    this.scanPlane.position.x = SCAN.uScanX.value as number;
    this.scanPlane.visible = scanning;

    // the girder: element B while any of its clashes is open
    this.girderMat.color.set(C.steel).lerp(new THREE.Color(C.b), f.girder * 0.8);
    this.girderMat.emissive.set(C.b).multiplyScalar(f.girder * 0.12);
    this.girderEdges.color.set(0xbfd8ee).lerp(new THREE.Color(0x8cf0a8), f.girder * 0.6);

    for (const [key, parts] of this.runs) this.paintRun(parts, f.runs[key]);

    // the tray moved whole, and what it hit
    const w = f.whole, tray = RUNS.find((r) => r.key === "tray")!;
    this.whole.visible = w.opacity > 0.001;
    this.whole.position.y = tray.fix.dz * w.lift;
    this.wholeMat.opacity = w.opacity * 0.6;
    this.wholeMat.color.set(C.try).lerp(new THREE.Color(C.hit), w.fail);
    this.wholeMat.emissive.set(C.try).lerp(new THREE.Color(C.hit), w.fail);
    for (const m of this.spigotMats) {
      m.color.set(C.ctxService).lerp(new THREE.Color(C.hit), Math.min(1, f.hits));
      m.emissive.set(C.hit).multiplyScalar(f.hits * 0.7);
      m.opacity = 0.6 + 0.35 * f.hits;
    }

    this.renderer.render(this.scene, this.camera);
  }

  private paintRun(p: RunParts, r: HeroFrame["runs"][RunKey]) {
    const red = new THREE.Color(C.a);
    p.base.color.set(C.service).lerp(red, r.flag);
    p.base.emissive.set(C.a).multiplyScalar(r.flag * 0.22);
    p.middleMat.color.copy(p.base.color);
    p.middleMat.emissive.copy(p.base.emissive);
    p.middleMat.opacity = 1 - r.fixed;
    p.middleMat.depthWrite = r.fixed < 0.5;
    p.middle.visible = r.fixed < 0.999;
    p.fixedMat.opacity = r.fixed;
    p.fixed.visible = r.fixed > 0.001;
    p.ghost.visible = r.ghost > 0.001;
    p.ghostMat.opacity = r.ghost * 0.62;
    const tone = new THREE.Color(r.tone === "pass" ? C.pass : C.try);
    p.ghostMat.color.copy(tone);
    p.ghostMat.emissive.copy(tone);
    p.ghostU.uLift.value = r.lift;
    p.ghostU.uScanX.value = r.checking >= 0 ? p.run.split[0] + (p.run.split[1] - p.run.split[0]) * r.checking : -100;
    p.ghostU.uScanAmt.value = r.checking >= 0 ? 1.4 : 0;
    p.before.visible = r.before > 0.001;
    p.beforeMat.opacity = r.before * 0.42;
    (p.opening.material as THREE.LineBasicMaterial).opacity = r.opening * 0.95;
    p.opening.visible = r.opening > 0.001;
    // the outlines of the run as modelled and as fixed cross over with them
    for (const [mesh, k] of [[p.middle, 1 - r.fixed], [p.fixed, r.fixed]] as const) {
      const e = mesh.children[0] as THREE.LineSegments | undefined;
      if (e) (e.material as THREE.LineBasicMaterial).opacity = 0.35 * k;
    }
  }

  /** Where the labels hang, for this frame. */
  anchors(f: HeroFrame): Anchor[] {
    const out: Anchor[] = [];
    for (const run of RUNS) {
      const r = f.runs[run.key], up = run.fix.dz * Math.max(r.fixed, r.lift * (r.ghost > 0 ? 1 : 0));
      // half a metre either side of the girder for the tray and the water main (inside their raised stretches), so the
      // three pins never stack
      const along = run.key === "tray" ? 0.5 : run.key === "cw" ? -0.5 : 0;
      out.push({ id: `pin-${run.key}`, at: V(3.5 + along, run.y, run.z + up + 0.04) });
    }
    SPIGOT_X.forEach((x, i) => out.push({ id: `hit-${i}`, at: V(x, -1.0, 7.2) }));
    out.push({ id: "girder", at: V(GIRDER.x[0], 1.1, GIRDER.z[1]) });
    return out;
  }

  /** A point to CSS pixels on the canvas, or null when behind the camera. */
  project(v: THREE.Vector3, out = new THREE.Vector3()): { x: number; y: number } | null {
    out.copy(v).project(this.camera);
    if (out.z > 1 || out.z < -1) return null;
    return { x: (out.x * 0.5 + 0.5) * this.size.w, y: (-out.y * 0.5 + 0.5) * this.size.h };
  }

  dispose() {
    this.scene.traverse((o) => {
      const m = o as THREE.Mesh;
      m.geometry?.dispose();
      const mat = m.material as THREE.Material | THREE.Material[] | undefined;
      (Array.isArray(mat) ? mat : mat ? [mat] : []).forEach((x) => x.dispose());
    });
    this.renderer.dispose();
    this.renderer.forceContextLoss();
  }
}

/** Whether this browser can draw the hero at all. */
export function webglAvailable(): boolean {
  try {
    const c = document.createElement("canvas");
    const ctx = (c.getContext("webgl2") || c.getContext("webgl")) as WebGLRenderingContext | null;
    ctx?.getExtension("WEBGL_lose_context")?.loseContext();
    return !!ctx;
  } catch {
    return false;
  }
}
