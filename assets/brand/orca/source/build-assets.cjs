/* ORCA identity v1.0. All logo exports use the paths in master.json.
 * Usage: node source/build-assets.cjs [--deps /path/to/node_modules]
 * Requires sharp and @napi-rs/canvas. No source font is redistributed.
 */
const fs = require('node:fs');
const path = require('node:path');
const { createRequire } = require('node:module');
const ROOT = path.resolve(__dirname, '..');
const dependencyArg = process.argv.indexOf('--deps');
const req = dependencyArg >= 0 ? createRequire(path.resolve(process.argv[dependencyArg + 1], 'package.json')) : require;
const sharp = req('sharp');
const { convertSVGTextToPath, GlobalFonts } = req('@napi-rs/canvas');
const fontPath = process.env.ORCA_SUPPORT_FONT || 'C:/Windows/Fonts/segoeui.ttf';
if (fs.existsSync(fontPath)) GlobalFonts.registerFromPath(fontPath, 'Orca Support');
const palette = { ink: '#11161B', navy: '#052640', white: '#FFFFFF', paper: '#F5F7F8', line: '#DDE3E7', muted: '#52636E' };
const q = n => +n.toFixed(5);
const P = (op, ...points) => [op, ...points.map(q)];
const at = (cx, cy, r, a) => [cx + r * Math.cos(a), cy + r * Math.sin(a)];

function arc(cx, cy, r, from, to) {
  const out = [], n = Math.ceil(Math.abs(to - from) / (Math.PI / 2));
  for (let i = 0; i < n; ++i) {
    const a = from + (to - from) * i / n, b = from + (to - from) * (i + 1) / n;
    const k = 4 / 3 * Math.tan((b - a) / 4);
    const s = at(cx, cy, r, a), e = at(cx, cy, r, b);
    out.push(P('C', s[0] - k * r * Math.sin(a), s[1] + k * r * Math.cos(a),
      e[0] + k * r * Math.sin(b), e[1] - k * r * Math.cos(b), ...e));
  }
  return out;
}

function transform(commands, a, b, c, d, x, y) {
  return commands.map(([op, ...v]) => {
    const out = [op];
    for (let i = 0; i < v.length; i += 2) out.push(q(a * v[i] + c * v[i + 1] + x), q(b * v[i] + d * v[i + 1] + y));
    return out;
  });
}

function splitO(gap = 18) {
  const R = 128, r = 72, h = gap / 2;
  const a = Math.asin(h / R), b = Math.asin(h / r);
  const top = [P('M', -Math.sqrt(R * R - h * h), -h), ...arc(0, 0, R, -Math.PI + a, -a),
    P('L', Math.sqrt(r * r - h * h), -h), ...arc(0, 0, r, -b, -Math.PI + b), ['Z']];
  const c = Math.SQRT1_2;
  return [transform(top, c, -c, c, c, 128, 128), transform(top, -c, c, -c, -c, 128, 128)];
}

function createMaster() {
  const symbol = splitO();
  const R = [P('M', 0, 0), P('L', 149, 0), P('C', 207, 0, 238, 30, 238, 80),
    P('C', 238, 126, 212, 154, 163, 162), P('L', 251, 256), P('L', 174, 256),
    P('L', 55, 143), P('L', 28, 115), P('L', 143, 115), P('C', 168, 115, 181, 102, 181, 82),
    P('C', 181, 63, 166, 54, 143, 54), P('L', 0, 54), ['Z']];
  const stem = [P('M', 0, 121), P('L', 59, 180), P('L', 59, 256), P('L', 0, 256), ['Z']];
  const t = 40 * Math.PI / 180;
  const C = [P('M', ...at(128, 128, 128, -t)), ...arc(128, 128, 128, -t, -2 * Math.PI + t),
    P('L', ...at(128, 128, 72, t)), ...arc(128, 128, 72, t, 2 * Math.PI - t), ['Z']];
  const A1 = [P('M', 0, 256), P('L', 136, 0), P('L', 170, 64), P('L', 72, 256), ['Z']];
  const A2 = [P('M', 183, 88), P('L', 272, 256), P('L', 199, 256), P('L', 146, 157), ['Z']];
  const shift = (ps, x) => ps.map(p => transform(p, 1, 0, 0, 1, x, 0));
  return {
    name: 'ORCA', version: '1.0', date: '2026-10-30', owner: 'IssueLab', direction: '05 / ORCA TYPE',
    description: 'A geometric wordmark and split-O monogram, reconstructed as editable paths from the approved visual direction.',
    palette, geometry: { capHeight: 256, clearspace: 64, cutWidth: 18, microCutWidth: 24 },
    symbol: { width: 256, height: 256, paths: symbol },
    micro: { width: 256, height: 256, paths: splitO(24) },
    wordmark: { width: 1077, height: 256, paths: [...symbol, ...shift([R, stem], 292), ...shift([C], 565), ...shift([A1, A2], 805)] }
  };
}

const masterFile = path.join(__dirname, 'master.json');
const master = fs.existsSync(masterFile) ? JSON.parse(fs.readFileSync(masterFile, 'utf8')) : createMaster();
fs.mkdirSync(__dirname, { recursive: true });
fs.writeFileSync(masterFile, JSON.stringify(master, null, 2) + '\n');
const d = commands => commands.map(p => p.join(' ')).join(' ');
const shapes = (name, colour = 'currentColor') => `<g fill="${colour}">${master[name].paths.map(p => `<path d="${d(p)}"/>`).join('')}</g>`;
const esc = s => s.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('"', '&quot;');
const font = 'Orca Support, Segoe UI, Arial, sans-serif';
const text = (x, y, size, value, fill = palette.ink, attrs = '') => `<text x="${x}" y="${y}" font-size="${size}" font-family="${font}" fill="${fill}" ${attrs}>${esc(value)}</text>`;
const rect = (x, y, w, h, fill, rx = 0) => `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="${rx}" fill="${fill}"/>`;
const line = (x1, y1, x2, y2, colour = palette.line) => `<path d="M${x1} ${y1}L${x2} ${y2}" fill="none" stroke="${colour}"/>`;
const placed = (name, x, y, w, colour) => `<g transform="translate(${x} ${y}) scale(${w / master[name].width})">${shapes(name, colour)}</g>`;

function svg(w, h, body, title, desc = '') {
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" role="img" aria-labelledby="title desc"><title id="title">${esc(title)}</title><desc id="desc">${esc(desc || 'ORCA by IssueLab. Identity direction 05.')}</desc>${body}</svg>`;
}
const files = [];
function write(rel, content) {
  const target = path.join(ROOT, rel);
  fs.mkdirSync(path.dirname(target), { recursive: true });
  fs.writeFileSync(target, content);
  files.push(rel.replaceAll('\\', '/'));
}
function outline(source) {
  if (!source.includes('<text')) return source;
  return convertSVGTextToPath(source).toString();
}
async function png(rel, source, width, height) {
  const sourceWidth = Number(source.match(/<svg[^>]*width="([\d.]+)"/)?.[1] || width);
  const density = Math.max(72, Math.ceil(width / sourceWidth * 144));
  let pipeline = sharp(Buffer.from(source), { density }).resize(width, height, { fit: 'fill' }).toColourspace('srgb').withIccProfile('srgb');
  write(rel, await pipeline.png({ compressionLevel: 9 }).toBuffer());
}

function wordmark(colour, endorsed = false) {
  const h = endorsed ? 474 : 384;
  const body = placed('wordmark', 64, 64, 1077, colour) + (endorsed ? text(68, 399, 38, 'BY ISSUELAB', colour, 'letter-spacing="8"') : '');
  return outline(svg(1205, h, body, endorsed ? 'ORCA by IssueLab wordmark' : 'ORCA wordmark'));
}
const symbol = colour => svg(384, 384, placed('symbol', 64, 64, 256, colour), 'ORCA split-O symbol');
function icon(size, rounded = false, maskable = false, bg = palette.navy) {
  const w = size * (maskable ? .56 : .62), offset = (size - w) / 2;
  return svg(size, size, rect(0, 0, size, size, bg, rounded ? size * .19 : 0) + placed('symbol', offset, offset, w, palette.white), 'ORCA app icon');
}
function favicon(ink = palette.ink) {
  return svg(288, 288, placed('micro', 16, 16, 256, ink), 'ORCA favicon', 'Optical-size symbol with a wider cut for 16-32 pixel rendering.');
}

async function marks() {
  for (const [variant, colour] of Object.entries({ black: palette.ink, navy: palette.navy, white: palette.white })) {
    const w = wordmark(colour), lock = wordmark(colour, true), s = symbol(colour);
    write(`svg/wordmarks/orca-wordmark-${variant}.svg`, w);
    write(`svg/lockups/orca-by-issuelab-${variant}.svg`, lock);
    write(`svg/symbols/orca-symbol-${variant}.svg`, s);
    for (const width of [512, 1024, 2048, 4096]) await png(`png/wordmarks/orca-wordmark-${variant}-${width}w.png`, w, width, Math.round(width * 384 / 1205));
    for (const width of [1024, 2048, 4096]) await png(`png/lockups/orca-by-issuelab-${variant}-${width}w.png`, lock, width, Math.round(width * 474 / 1205));
    for (const size of [64, 128, 256, 512, 1024]) await png(`png/symbols/orca-symbol-${variant}-${size}.png`, s, size, size);
  }
  write('svg/wordmarks/orca-wordmark-currentcolor.svg', wordmark('currentColor'));
  write('svg/symbols/orca-symbol-currentcolor.svg', symbol('currentColor'));
}

async function icons() {
  write('icons/orca-app-icon.svg', icon(1024, true));
  write('icons/orca-app-icon-square.svg', icon(1024));
  write('icons/orca-app-icon-maskable.svg', icon(1024, false, true));
  for (const size of [64, 128, 256, 512, 1024]) await png(`icons/orca-app-icon-${size}.png`, icon(size, true), size, size);
  await png('icons/apple-touch-icon.png', icon(180), 180, 180);
  await png('icons/apple-store-icon-1024.png', icon(1024), 1024, 1024);
  await png('icons/mstile-150x150.png', icon(150), 150, 150);
  write('icons/safari-pinned-tab.svg', favicon());
  write('icons/browserconfig.xml', '<?xml version="1.0" encoding="utf-8"?><browserconfig><msapplication><tile><square150x150logo src="mstile-150x150.png"/><TileColor>#052640</TileColor></tile></msapplication></browserconfig>');
  for (const size of [192, 512]) {
    await png(`icons/android-chrome-${size}.png`, icon(size), size, size);
    await png(`icons/maskable-icon-${size}.png`, icon(size, false, true), size, size);
  }
  const adaptive = favicon('currentColor').replace('<g transform=', '<style>:root{color:#11161B}@media(prefers-color-scheme:dark){:root{color:#FFFFFF}}</style><g transform=');
  write('icons/favicon.svg', adaptive);
  write('icons/orca-symbol-micro.svg', favicon());
  for (const size of [16, 32, 48, 64, 256]) {
    await png(`icons/favicon-${size}.png`, favicon(), size, size);
    const plate = svg(288, 288, rect(0, 0, 288, 288, palette.navy) + placed('micro', 36, 36, 216, palette.white), 'ORCA favicon tile');
    await png(`icons/favicon-tile-${size}.png`, plate, size, size);
  }
  write('icons/site.webmanifest', JSON.stringify({ name: 'ORCA', short_name: 'ORCA', start_url: '/', scope: '/', display: 'standalone', background_color: palette.white, theme_color: palette.navy, icons: [
    { src: 'android-chrome-192.png', sizes: '192x192', type: 'image/png', purpose: 'any' },
    { src: 'android-chrome-512.png', sizes: '512x512', type: 'image/png', purpose: 'any' },
    { src: 'maskable-icon-192.png', sizes: '192x192', type: 'image/png', purpose: 'maskable' },
    { src: 'maskable-icon-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' }
  ] }, null, 2) + '\n');
}

function card(w, h, dark, type = 'social') {
  const bg = dark ? palette.navy : palette.paper, fg = dark ? palette.white : palette.ink;
  const muted = dark ? '#B5C4CE' : palette.muted;
  const margin = w * .085;
  let b = rect(0, 0, w, h, bg);
  if (type === 'banner') {
    b += placed('wordmark', margin, h * .28, w * .35, fg);
    b += text(w * .58, h * .44, 29, 'AI design coordination', fg);
    b += text(w * .58, h * .58, 19, 'Observe. Resolve. Check. Apply.', muted);
    b += text(margin, h * .83, 15, 'BY ISSUELAB', muted, 'letter-spacing="4"');
  } else {
    const mw = w * (w === h ? .76 : .64), mx = margin;
    const my = h * (w === h ? .31 : .30);
    b += text(margin, h * .14, Math.max(16, w * .014), 'BY ISSUELAB', muted, 'letter-spacing="4"');
    b += placed('wordmark', mx, my, mw, fg);
    b += text(margin, h * .68, w * .033, 'AI design coordination', fg);
    b += line(margin, h * .77, w - margin, h * .77, dark ? '#365267' : palette.line);
    b += text(margin, h * .86, w * .017, 'Observe. Resolve. Check. Apply.', muted, 'letter-spacing="1.3"');
  }
  return outline(svg(w, h, b, 'ORCA - AI design coordination'));
}

async function collateral() {
  const layouts = [ ['social/og-dark', 1200, 630, true], ['social/og-light', 1200, 630, false],
    ['social/square-dark', 1080, 1080, true], ['social/square-light', 1080, 1080, false],
    ['social/profile-banner', 1584, 396, true, 'banner'],
    ['video/title-dark', 1920, 1080, true], ['video/title-light', 1920, 1080, false] ];
  for (const [rel, w, h, dark, type] of layouts) {
    const s = card(w, h, dark, type);
    write(`${rel}.svg`, s);
    await png(`${rel}.png`, s, w, h);
  }
  for (const [variant, colour] of Object.entries({ black: palette.ink, white: palette.white })) {
    const s = svg(1920, 1080, placed('wordmark', 112, 906, 360, colour), 'ORCA transparent video corner bug');
    write(`video/corner-bug-${variant}.svg`, s);
    await png(`video/corner-bug-${variant}.png`, s, 1920, 1080);
  }
}

async function preview() {
  const W = 1800, H = 1500, p = palette;
  let b = rect(0, 0, W, H, p.paper);
  b += text(70, 65, 18, 'ORCA  /  ASSET PACK 01', p.ink, 'letter-spacing="3"');
  b += text(1730, 65, 16, 'DIRECTION 05', p.muted, 'text-anchor="end" letter-spacing="2"');
  b += rect(40, 108, 860, 440, p.white) + rect(900, 108, 860, 440, p.navy);
  b += text(76, 153, 13, 'PRIMARY WORDMARK', p.muted, 'letter-spacing="2"');
  b += text(940, 153, 13, 'REVERSED WORDMARK', '#B5C4CE', 'letter-spacing="2"');
  b += placed('wordmark', 100, 264, 730, p.ink) + placed('wordmark', 970, 264, 730, p.white);
  b += rect(40, 572, 550, 416, p.white) + rect(614, 572, 560, 416, p.white) + rect(1198, 572, 562, 416, p.white);
  b += text(76, 617, 13, 'SYMBOL / SHARED O GEOMETRY', p.muted, 'letter-spacing="1.7"');
  b += placed('symbol', 186, 680, 230, p.ink);
  b += text(650, 617, 13, 'APP ICON', p.muted, 'letter-spacing="2"');
  b += rect(780, 677, 230, 230, p.navy, 44) + placed('symbol', 824, 721, 142, p.white);
  b += text(1234, 617, 13, 'FAVICONS / ACTUAL PIXEL SIZES', p.muted, 'letter-spacing="1.4"');
  for (const [i, size] of [16, 24, 32, 48, 64].entries()) {
    const x = 1262 + i * 91;
    b += placed('micro', x + (64 - size) / 2, 734 + (64 - size) / 2, size, p.ink);
    b += text(x + 32, 840, 15, String(size), p.muted, 'text-anchor="middle"');
  }
  b += text(1234, 921, 15, 'Wider optical cut at small sizes', p.muted);
  b += rect(40, 1012, 860, 350, p.navy) + rect(924, 1012, 836, 350, p.white);
  b += text(76, 1057, 13, 'SOCIAL / VIDEO', '#B5C4CE', 'letter-spacing="2"');
  b += placed('wordmark', 100, 1123, 540, p.white);
  b += text(100, 1320, 23, 'Observe. Resolve. Check. Apply.', '#B5C4CE');
  b += text(960, 1057, 13, 'CORE PALETTE / ATTRIBUTION', p.muted, 'letter-spacing="2"');
  for (const [i, [name, colour]] of Object.entries({ INK: p.ink, NAVY: p.navy, WHITE: p.white }).entries()) {
    const x = 960 + i * 250;
    b += rect(x, 1106, 200, 92, colour) + (name === 'WHITE' ? `<rect x="${x}" y="1106" width="200" height="92" fill="none" stroke="${p.line}"/>` : '');
    b += text(x, 1232, 14, name, p.ink, 'letter-spacing="2"') + text(x, 1258, 15, colour, p.muted);
  }
  b += text(960, 1320, 16, 'ORCA by IssueLab', p.muted);
  b += text(70, 1438, 16, 'Editable SVG  /  Transparent PNG  /  Print PDF + EPS  /  Icons  /  Social + video  /  Usage guide', p.muted);
  const s = outline(svg(W, H, b, 'ORCA asset pack overview'));
  write('preview/asset-pack-overview.svg', s);
  await png('preview/asset-pack-overview.png', s, W, H);
  const h = `<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>ORCA asset pack</title><style>body{margin:0;background:#F5F7F8;font:16px system-ui;color:#11161B}main{max-width:1400px;margin:auto;padding:32px}img{width:100%;height:auto}a{color:#052640}h1{font-size:24px}p{line-height:1.7}nav{display:flex;gap:24px;flex-wrap:wrap;padding:8px 0 24px}</style><main><h1>ORCA / Asset pack 01</h1><nav><a href="../docs/orca-brand-guide.pdf">Brand guide</a><a href="../print/orca-print-masters.pdf">Print masters</a><a href="../START-HERE.txt">Start here</a></nav><img src="asset-pack-overview.svg" alt="ORCA wordmarks, symbol, icons, palette and collateral"><p>Direction 05. Editable vectors, transparent raster exports and one shared geometry source. Version 1.0, 30 October 2026.</p></main></html>`;
  write('preview/index.html', h);
}

async function main() {
  await marks(); await icons(); await collateral(); await preview();
  write('tokens/orca-colours.json', JSON.stringify({ name: 'ORCA', version: '1.0', colours: palette, colourSpace: 'sRGB', capHeight: 256, clearspaceRatio: .25, minimumWordmarkWidthPx: 128, minimumSymbolWidthPx: 24, minimumMicroWidthPx: 16 }, null, 2) + '\n');
  write('tokens/orca-tokens.css', ':root {\n' + Object.entries(palette).map(([key, value]) => `  --orca-${key}: ${value};`).join('\n') + '\n  --orca-font-support: "Segoe UI", Arial, sans-serif;\n  --orca-clearspace-ratio: 0.25;\n}\n');
  fs.writeFileSync(path.join(__dirname, 'export-list.json'), JSON.stringify(files, null, 2));
  console.log(JSON.stringify({ root: ROOT, generated: files.length, masterWidth: master.wordmark.width, capHeight: master.wordmark.height }));
}
main().catch(e => { console.error(e); process.exitCode = 1; });
