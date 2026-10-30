// One drawing view beside the 3D one (docs/views.md): a plan, a section or an elevation. It owns an orthographic
// camera (a centre on the view's plane and a scale in metres per pixel, panned and zoomed by the user), the clip
// planes its spec asks for, and the render target the viewer draws it into before compositing it into its pane.
import * as THREE from "three";
import { facingLook, planRange, sectionFrame, toThree, type DrawingSpec, type Level, type Rect, type SectionSpec } from "./views";

/** The paper a drawing is drawn on. */
export const PAPER = new THREE.Color("#fbfbf8");

/** IFC (x, y, z) ← three.js (x, y, z): (x, −z, y). */
export const toIfc = (v: THREE.Vector3): [number, number, number] => [v.x, -v.z, v.y];

export class DrawingView {
  readonly camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0.01, 1000);
  /** The point at the middle of the view (three.js world), and metres per CSS pixel. */
  readonly center = new THREE.Vector3();
  scale = 0.05;
  /** Into the drawing, and up the screen (three.js). */
  look = new THREE.Vector3(0, -1, 0);
  up = new THREE.Vector3(0, 0, -1);
  /** Global clip planes while it draws: the cut (which fills cut faces) first, then a bottom or a far clip. */
  planes: THREE.Plane[] = [];
  cut: THREE.Plane | null = null;
  /** A section's or elevation's crop, as world corners on its plane (null: none). */
  crop: THREE.Vector3[] | null = null;
  rt: THREE.WebGLRenderTarget | null = null;
  /** Normals and depth, for the composite's linework. */
  nrt: THREE.WebGLRenderTarget | null = null;
  /** What it was last drawn with, to draw again only when something changed. */
  drawn = "";

  constructor(public spec: DrawingSpec) {
    this.camera.layers.set(0);   // never the 3D view's own helpers (layer 1)
  }

  /** Set the look, the clip planes and the crop from the spec. `levels` sorted; `model` the whole model's box. */
  configure(spec: DrawingSpec, levels: Level[], model: THREE.Box3) {
    this.spec = spec;
    this.crop = null;
    this.cut = null;
    this.planes = [];
    if (spec.kind === "plan") {
      const { cutZ, bottomZ } = planRange(levels, spec);
      this.look.set(0, -1, 0);
      this.up.set(0, 0, -1);    // north up the screen
      this.cut = new THREE.Plane(new THREE.Vector3(0, -1, 0), cutZ);   // keeps what is below the cut
      this.planes.push(this.cut);
      if (bottomZ != null) this.planes.push(new THREE.Plane(new THREE.Vector3(0, 1, 0), -bottomZ));
      this.center.y = cutZ;
    } else if (spec.kind === "section") {
      const { along, look } = sectionFrame(spec);
      this.look.copy(toThree(look[0], look[1], 0)).normalize();
      this.up.set(0, 1, 0);
      const o = toThree(spec.origin[0], spec.origin[1], 0);
      this.cut = new THREE.Plane().setFromNormalAndCoplanarPoint(this.look, o);   // keeps what lies ahead of the line
      this.planes.push(this.cut);
      if (spec.far != null) this.planes.push(new THREE.Plane().setFromNormalAndCoplanarPoint(this.look.clone().negate(),
        o.clone().addScaledVector(this.look, spec.far)));
      if (spec.crop) {
        const a = toThree(along[0], along[1], 0).normalize();
        const at = (s: number, z: number) => o.clone().addScaledVector(a, s).setY(z);
        const c = spec.crop;
        this.crop = [at(-c.left, c.bottom), at(c.right, c.bottom), at(c.right, c.top), at(-c.left, c.top)];
      }
      // Keep the centre on the section's plane.
      this.center.sub(this.look.clone().multiplyScalar(this.look.dot(this.center.clone().sub(o))));
    } else {
      const look = facingLook(spec.facing);
      this.look.copy(toThree(look[0], look[1], 0)).normalize();
      this.up.set(0, 1, 0);
      if (spec.far != null && !model.isEmpty()) {
        // From the model's face on the camera's side, `far` metres in.
        const corner = new THREE.Vector3(this.look.x > 0 ? model.min.x : model.max.x, 0, this.look.z > 0 ? model.min.z : model.max.z);
        const face = this.look.dot(corner);
        this.planes.push(new THREE.Plane(this.look.clone().negate(), face + spec.far));
      }
    }
  }

  /** The camera for a pane of `rect`: centred, `scale` metres per pixel, set back beyond the model. */
  updateCamera(rect: Rect, depth: number) {
    const w = (rect.w * this.scale) / 2, h = (rect.h * this.scale) / 2;
    Object.assign(this.camera, { left: -w, right: w, top: h, bottom: -h, near: 0.01, far: depth * 2 });
    this.camera.position.copy(this.center).addScaledVector(this.look, -depth);
    this.camera.up.copy(this.up);
    this.camera.lookAt(this.center);
    this.camera.updateProjectionMatrix();
    this.camera.updateMatrixWorld();
  }

  /** Frame a box (three.js world) with `margin` as a share round it. */
  frame(box: THREE.Box3, rect: Rect, margin = 0.15) {
    if (box.isEmpty()) return;
    const right = new THREE.Vector3().crossVectors(this.look, this.up).normalize();
    const pts = corners(box);
    const u = pts.map((p) => p.dot(right)), v = pts.map((p) => p.dot(this.up));
    const w = Math.max(...u) - Math.min(...u), h = Math.max(...v) - Math.min(...v);
    const c = box.getCenter(new THREE.Vector3());
    // Slide the centre within the view's plane only (a plan keeps its cut height, a section its line).
    this.center.addScaledVector(right, c.dot(right) - this.center.dot(right)).addScaledVector(this.up, c.dot(this.up) - this.center.dot(this.up));
    this.scale = Math.max(w / Math.max(rect.w, 1), h / Math.max(rect.h, 1), 1e-5) * (1 + 2 * margin);
  }

  /** Pan by a drag of `dx`, `dy` CSS pixels. */
  pan(dx: number, dy: number) {
    const right = new THREE.Vector3().crossVectors(this.look, this.up).normalize();
    this.center.addScaledVector(right, -dx * this.scale).addScaledVector(this.up, dy * this.scale);
  }

  /** Zoom by `k` (above 1 zooms out) keeping the point under (x, y) of the pane where it is. */
  zoomAt(k: number, x: number, y: number, rect: Rect) {
    const right = new THREE.Vector3().crossVectors(this.look, this.up).normalize();
    const ox = (x - rect.w / 2) * this.scale, oy = (rect.h / 2 - y) * this.scale;
    const next = THREE.MathUtils.clamp(this.scale * k, 1e-5, 50);
    const f = 1 - next / this.scale;
    this.center.addScaledVector(right, ox * f).addScaledVector(this.up, oy * f);
    this.scale = next;
  }

  /** Is a world point kept by the view's clip planes and crop? */
  keeps(p: THREE.Vector3): boolean {
    if (!this.planes.every((pl) => pl.distanceToPoint(p) >= -1e-4)) return false;
    if (!this.crop) return true;
    const right = new THREE.Vector3().crossVectors(this.look, this.up).normalize();
    const us = this.crop.map((c) => c.dot(right)), vs = this.crop.map((c) => c.dot(this.up));
    const u = p.dot(right), v = p.dot(this.up);
    return u >= Math.min(...us) - 1e-4 && u <= Math.max(...us) + 1e-4 && v >= Math.min(...vs) - 1e-4 && v <= Math.max(...vs) + 1e-4;
  }

  /** A pane pixel (x, y from its top-left) for a world point. */
  toPane(p: THREE.Vector3, rect: Rect): THREE.Vector2 {
    const q = p.clone().project(this.camera);
    return new THREE.Vector2((q.x + 1) / 2 * rect.w, (1 - q.y) / 2 * rect.h);
  }

  /** The world point on the view's plane under a pane pixel. */
  fromPane(x: number, y: number, rect: Rect): THREE.Vector3 {
    const right = new THREE.Vector3().crossVectors(this.look, this.up).normalize();
    return this.center.clone().addScaledVector(right, (x - rect.w / 2) * this.scale).addScaledVector(this.up, (rect.h / 2 - y) * this.scale);
  }

  /** A key for what the camera shows, to draw again only when it changes. */
  cameraKey(rect: Rect): string {
    return [this.center.toArray(), this.scale, rect.w, rect.h, this.planes.map((p) => [p.normal.toArray(), p.constant]),
      this.crop?.map((c) => c.toArray())].flat(3).map((n) => (typeof n === "number" ? n.toFixed(5) : String(n))).join(",");
  }

  /** The render targets at `w` × `h` device pixels: colour (depth, stencil, 4× multisampling) and normals with a
   * depth texture. */
  target(w: number, h: number): [THREE.WebGLRenderTarget, THREE.WebGLRenderTarget] {
    if (!this.rt || !this.nrt || this.rt.width !== w || this.rt.height !== h) {
      [this.rt, this.nrt] = targets(w, h, this.rt, this.nrt);
      this.drawn = "";
    }
    return [this.rt, this.nrt];
  }

  dispose() { this.rt?.dispose(); this.nrt?.dispose(); this.rt = this.nrt = null; }
}

/** A drawing's two targets, the old ones disposed. */
export function targets(w: number, h: number, ...old: (THREE.WebGLRenderTarget | null)[]): [THREE.WebGLRenderTarget, THREE.WebGLRenderTarget] {
  for (const t of old) t?.dispose();
  return [new THREE.WebGLRenderTarget(w, h, { samples: 4, depthBuffer: true, stencilBuffer: true }),
    new THREE.WebGLRenderTarget(w, h, { depthTexture: new THREE.DepthTexture(w, h), samples: 0 })];
}

export function corners(b: THREE.Box3): THREE.Vector3[] {
  const out: THREE.Vector3[] = [];
  for (const x of [b.min.x, b.max.x]) for (const y of [b.min.y, b.max.y]) for (const z of [b.min.z, b.max.z]) out.push(new THREE.Vector3(x, y, z));
  return out;
}

/** A section's far clip by default: everything of the pair behind its line, and 2 m (or a share of the model) more. */
export function farBehind(spec: SectionSpec, pair: THREE.Box3, extra: number): number {
  const { look } = sectionFrame(spec);
  const n = toThree(look[0], look[1], 0).normalize(), o = toThree(spec.origin[0], spec.origin[1], 0);
  const d = corners(pair).map((p) => n.dot(p.clone().sub(o)));
  return Math.max(0, ...d) + extra;
}

// ---------------------------------------------------------------- the drawing style (docs/views.md, "The drawing style")

/** Stencil bits a cut solid flips (by parity: a pixel whose bit is set lies inside a solid the cut passes through). */
export const CUT = { rest: 1, a: 2, b: 4, ab: 8, preview: 16 } as const;
/** Layers the stencil passes draw: everything else, side A, side B, both sides, a fix's preview. */
export const CAP_LAYER = { rest: 2, a: 3, b: 4, ab: 5, preview: 6 } as const;
/** What a cap writes in the colour target's alpha, so the composite knows a cut face and outlines it. */
const CLASS = { fill: 1, rest: 0.75, preview: 0.65, a: 0.55, b: 0.45, ab: 0.35, both: 0.25 };

/** A fill: one flat colour whatever the batch's per-element colours (the mode's grey or ghost would tint it). */
function flat(color: THREE.ColorRepresentation, opacity = 1): THREE.MeshBasicMaterial {
  const m = new THREE.MeshBasicMaterial({ color, side: THREE.DoubleSide, ...(opacity < 1 ? { transparent: true, opacity, depthWrite: false } : {}) });
  m.onBeforeCompile = (sh) => { sh.fragmentShader = sh.fragmentShader.replace("#include <color_fragment>", ""); };
  m.customProgramCacheKey = () => "flat-fill";
  return m;
}

function behind(color: string): THREE.MeshBasicMaterial {
  const m = new THREE.MeshBasicMaterial({ color, side: THREE.DoubleSide, transparent: true, opacity: 0.28, depthWrite: false,
    depthFunc: THREE.GreaterDepth, blending: THREE.CustomBlending, blendSrc: THREE.SrcAlphaFactor, blendDst: THREE.OneMinusSrcAlphaFactor,
    blendSrcAlpha: THREE.ZeroFactor, blendDstAlpha: THREE.OneFactor });
  return m;
}

/** Near-white paper, faintly tinted per file (structure grey, services blue, architecture warm…). */
const TINTS = ["#eceef0", "#e6eef7", "#f4efe7", "#eaf3ec", "#f3ebf1", "#eef2e4"];

/** The materials and passes every drawing shares: fills, the pair flat, the stencil caps and the composite. */
export class DrawingStyle {
  readonly fills = TINTS.map((c) => flat(c));
  readonly glass = flat("#dbe7f0", 0.35);
  readonly side = { a: flat("#e9877f"), b: flat("#86c896"), ab: flat("#c39be0") };
  readonly selected = flat("#7fb8ec");
  /** The pair where something hides it (behind a façade in an elevation): faint, over what hides it, the cut faces'
   * classes in alpha untouched. */
  readonly hidden = { a: behind("#d0342c"), b: behind("#1f9d3a"), ab: behind("#8e44ad") };
  readonly normals = new THREE.MeshNormalMaterial({ side: THREE.DoubleSide });
  private stencil = new Map<number, THREE.MeshBasicMaterial>();
  private caps: { mesh: THREE.Mesh; ref: number; mask: number }[];
  private quadCamera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
  readonly composite: THREE.ShaderMaterial;
  private quad: THREE.Mesh;

  constructor() {
    const cap = (color: string, line: string, alpha: number, hatch: boolean, ref: number, mask: number) => {
      const mat = new THREE.ShaderMaterial({
        uniforms: { color: { value: new THREE.Color(color) }, line: { value: new THREE.Color(line) }, alpha: { value: alpha } },
        defines: hatch ? { HATCH: 1 } : {}, depthTest: false, depthWrite: false,
        stencilWrite: true, stencilRef: ref, stencilFuncMask: mask, stencilFunc: THREE.EqualStencilFunc,
        stencilFail: THREE.KeepStencilOp, stencilZFail: THREE.KeepStencilOp, stencilZPass: THREE.KeepStencilOp,
        vertexShader: "void main() { gl_Position = vec4(position.xy, 0.0, 1.0); }",
        fragmentShader: `uniform vec3 color; uniform vec3 line; uniform float alpha;
          void main() {
            vec3 c = color;
            #ifdef HATCH
              float k = mod(gl_FragCoord.x + gl_FragCoord.y, 9.0);   // a 45° hatch, as concrete is drawn cut
              if (k < 1.2) c = line;
            #endif
            gl_FragColor = vec4(c, alpha);
          }`,
      });
      const mesh = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), mat);
      mesh.frustumCulled = false;
      return { mesh, ref, mask };
    };
    this.caps = [
      cap("#c7ccd3", "#7d8794", CLASS.rest, true, CUT.rest, 31),
      cap("#9fb6cc", "#5d7790", CLASS.preview, true, CUT.preview, CUT.preview | CUT.a | CUT.b),
      cap("#e46a61", "#a0251f", CLASS.a, false, CUT.a, CUT.a | CUT.b),
      cap("#5dbb73", "#17692b", CLASS.b, false, CUT.b, CUT.a | CUT.b),
      cap("#b37fd6", "#6d3f8f", CLASS.ab, false, CUT.ab, CUT.ab),
      cap("#ffb000", "#9a6100", CLASS.both, false, CUT.a | CUT.b, CUT.a | CUT.b),   // where A and B overlap: the clash
    ];
    this.composite = new THREE.ShaderMaterial({
      uniforms: {
        color: { value: null }, normals: { value: null }, depth: { value: null }, texel: { value: new THREE.Vector2() },
        near: { value: 0.01 }, far: { value: 100 }, ortho: { value: 1 }, tol: { value: 0.05 }, ink: { value: new THREE.Color("#1d2530") },
        cutWidth: { value: 2 }, edges: { value: 1 }, cropMin: { value: new THREE.Vector2(0, 0) }, cropMax: { value: new THREE.Vector2(1, 1) },
        paper: { value: PAPER },
      },
      depthTest: false, depthWrite: false,
      vertexShader: "varying vec2 vUv; void main() { vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }",
      fragmentShader: COMPOSITE,
    });
    this.quad = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), this.composite);
    this.quad.frustumCulled = false;
  }

  /** A stencil pass's material: both faces, nothing drawn, flipping `mask`'s bit wherever a face is. */
  stencilFor(mask: number): THREE.MeshBasicMaterial {
    let m = this.stencil.get(mask);
    if (!m) {
      m = new THREE.MeshBasicMaterial({ side: THREE.DoubleSide, colorWrite: false, depthWrite: false, depthTest: false,
        stencilWrite: true, stencilFunc: THREE.AlwaysStencilFunc, stencilWriteMask: mask,
        stencilFail: THREE.InvertStencilOp, stencilZFail: THREE.InvertStencilOp, stencilZPass: THREE.InvertStencilOp });
      this.stencil.set(mask, m);
    }
    return m;
  }

  /** Fill the cut faces by their stencil value (after the stencil passes, in the same target). */
  drawCaps(renderer: THREE.WebGLRenderer, previewColour: THREE.Color | null) {
    for (const c of this.caps) {
      if (c.ref === CUT.preview && previewColour) (c.mesh.material as THREE.ShaderMaterial).uniforms.color.value.copy(previewColour).lerp(new THREE.Color(1, 1, 1), 0.25);
      renderer.render(c.mesh, this.quadCamera);
    }
  }

  /** Draw the composite (colour, linework from normals and depth, the cut outline) onto the current viewport. */
  drawComposite(renderer: THREE.WebGLRenderer) { renderer.render(this.quad, this.quadCamera); }
}

/** Paper, fills and caps from the colour target; thin projection lines where normals turn or depth steps (not inside a
 * cut face); a heavy line round every cut face (where the cap class changes within a pixel or two). */
const COMPOSITE = `
uniform sampler2D color; uniform sampler2D normals; uniform sampler2D depth;
uniform vec2 texel; uniform float near; uniform float far; uniform float ortho; uniform float tol;
uniform vec3 ink; uniform float cutWidth; uniform float edges; uniform vec2 cropMin; uniform vec2 cropMax; uniform vec3 paper;
varying vec2 vUv;
float lin(float d) { return ortho > 0.5 ? near + d * (far - near) : (near * far) / (far - d * (far - near)); }
float cls(float a) { return floor(a * 20.0 + 0.5); }
void main() {
  if (any(lessThan(vUv, cropMin)) || any(greaterThan(vUv, cropMax))) { gl_FragColor = vec4(paper, 1.0); return; }
  vec4 c = texture2D(color, vUv);
  float me = cls(c.a);
  float cut = 0.0;
  vec3 cutInk = ink;
  for (int i = -2; i <= 2; i++) for (int j = -2; j <= 2; j++) {
    if (float(i * i + j * j) > cutWidth * cutWidth + 0.5) continue;
    vec4 o = texture2D(color, vUv + vec2(float(i), float(j)) * texel);
    float them = cls(o.a);
    if (them != me && (me < 19.5 || them < 19.5)) {
      cut = 1.0;
      float k = min(me, them);   // the cap's own ink: dark red round A, dark green round B, black round the rest
      if (k > 13.5 && k < 15.5) cutInk = vec3(0.12, 0.17, 0.23);
      else if (abs(k - 11.0) < 0.6) cutInk = vec3(0.45, 0.08, 0.06);
      else if (abs(k - 9.0) < 0.6) cutInk = vec3(0.05, 0.3, 0.12);
      else if (abs(k - 5.0) < 0.6) cutInk = vec3(0.55, 0.32, 0.0);
    }
  }
  float edge = 0.0;
  if (edges > 0.5 && me > 19.5) {
    vec3 n0 = texture2D(normals, vUv).xyz * 2.0 - 1.0;
    float z0 = lin(texture2D(depth, vUv).x);
    for (int k = 0; k < 4; k++) {
      vec2 off = k == 0 ? vec2(texel.x, 0.0) : k == 1 ? vec2(-texel.x, 0.0) : k == 2 ? vec2(0.0, texel.y) : vec2(0.0, -texel.y);
      vec3 n = texture2D(normals, vUv + off).xyz * 2.0 - 1.0;
      float z = lin(texture2D(depth, vUv + off).x);
      float t = ortho > 0.5 ? tol : tol * z0;
      if (dot(n0, n) < 0.82 || abs(z - z0) > t) edge = 1.0;
    }
  }
  vec3 outc = c.rgb;
  outc = mix(outc, ink, edge * 0.75);
  outc = mix(outc, cutInk, cut);
  gl_FragColor = vec4(outc, 1.0);
  #include <colorspace_fragment>
}`;
