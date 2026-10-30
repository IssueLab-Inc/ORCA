/* ORCA motion assets v1.0. Node 18+, sharp. Logo geometry: master.json. */
const fs = require('node:fs');
const path = require('node:path');
const { createRequire } = require('node:module');
const ROOT = path.resolve(__dirname, '..');
const deps = process.argv.indexOf('--deps');
const requireDep = deps >= 0 ? createRequire(path.resolve(process.argv[deps + 1], 'package.json')) : require;
const sharp = requireDep('sharp');
const master = require('../../source/master.json');
const INK = master.palette.ink, NAVY = master.palette.navy, WHITE = '#FFFFFF';
const TYPES = ['orbit', 'breathe', 'resolve', 'phase-cycle', 'settle', 'reveal'];
const DURATIONS = { orbit: 1600, breathe: 2000, resolve: 2400, 'phase-cycle': 4800, settle: 760, reveal: 1600 };
const write = (rel, content) => { const p = path.join(ROOT, rel); fs.mkdirSync(path.dirname(p), { recursive: true }); fs.writeFileSync(p, content); };
const d = commands => commands.map(p => p.join(' ')).join(' ');
const paths = name => master[name].paths.map((p, i) => `<path data-path="${i}" d="${d(p)}"/>`).join('');
const part = (i, cls) => `<g class="${cls}"><path d="${d(master.symbol.paths[i])}"/></g>`;
const letters = () => [master.wordmark.paths.slice(0, 2), master.wordmark.paths.slice(2, 4), master.wordmark.paths.slice(4, 5), master.wordmark.paths.slice(5)]
  .map((ps, i) => `<g class="om-letter om-letter-${i}">${ps.map(p => `<path d="${d(p)}"/>`).join('')}</g>`).join('');

const svgCSS = `
.om-spin,.om-phase,.om-settle,.om-letter{transform-box:view-box;transform-origin:128px 128px}
.om-svg{overflow:visible}
.om-letter{transform-origin:538.5px 128px}
@keyframes om-orbit{to{transform:rotate(360deg)}}
@keyframes om-breathe-a{0%,100%{transform:translate(0,0);opacity:1}50%{transform:translate(-6px,-6px);opacity:.5}}
@keyframes om-breathe-b{0%,100%{transform:translate(0,0);opacity:1}50%{transform:translate(6px,6px);opacity:.5}}
@keyframes om-resolve-a{0%,8%,100%{transform:translate(-14px,14px);opacity:.55}32%,78%{transform:translate(0,0);opacity:1}}
@keyframes om-resolve-b{0%,8%,100%{transform:translate(14px,-14px);opacity:.55}32%,78%{transform:translate(0,0);opacity:1}}
@keyframes om-phase{0%,20%{transform:rotate(0)}25%,45%{transform:rotate(90deg)}50%,70%{transform:rotate(180deg)}75%,95%{transform:rotate(270deg)}100%{transform:rotate(360deg)}}
@keyframes om-settle{0%{transform:scale(.88);opacity:.2}60%{transform:scale(1.055);opacity:1}100%{transform:scale(1);opacity:1}}
@keyframes om-letter-in{0%{transform:translateY(18px);opacity:0}100%{transform:translateY(0);opacity:1}}
@media(prefers-reduced-motion:no-preference){
.om-orbit .om-spin{animation:om-orbit 1.6s linear infinite}
.om-breathe .om-half-a{animation:om-breathe-a 2s ease-in-out infinite}
.om-breathe .om-half-b{animation:om-breathe-b 2s ease-in-out infinite}
.om-resolve .om-half-a{animation:om-resolve-a 2.4s cubic-bezier(.4,0,.2,1) infinite}
.om-resolve .om-half-b{animation:om-resolve-b 2.4s cubic-bezier(.4,0,.2,1) infinite}
.om-phase-cycle .om-phase{animation:om-phase 4.8s cubic-bezier(.4,0,.2,1) infinite}
.om-settle .om-settle{animation:om-settle .76s cubic-bezier(.2,.8,.2,1) both}
.om-reveal .om-letter{animation:om-letter-in .7s cubic-bezier(.2,.8,.2,1) both}
.om-reveal .om-letter-1{animation-delay:.16s}.om-reveal .om-letter-2{animation-delay:.32s}.om-reveal .om-letter-3{animation-delay:.48s}
}
`;

function animatedSVG(type, colour = INK) {
  const reveal = type === 'reveal', w = reveal ? 1205 : 320, h = reveal ? 384 : 320;
  let inside;
  if (type === 'orbit') inside = `<g class="om-spin">${paths('symbol')}</g>`;
  else if (type === 'breathe' || type === 'resolve') inside = part(0, 'om-half-a') + part(1, 'om-half-b');
  else if (type === 'phase-cycle') inside = `<g class="om-phase">${paths('symbol')}</g>`;
  else if (type === 'settle') inside = `<g class="om-settle">${paths('symbol')}</g>`;
  else inside = letters();
  const label = type === 'phase-cycle' ? 'ORCA four-phase motion demonstration' : type === 'reveal' ? 'ORCA logo reveal' : type === 'settle' ? 'ORCA completion flourish' : 'ORCA loading';
  return `<svg xmlns="http://www.w3.org/2000/svg" class="om-svg om-${type}" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" role="img" aria-label="${label}" style="color:${colour}"><title>${label}</title><style>${svgCSS}</style><g fill="currentColor" transform="translate(${reveal ? 64 : 32} ${reveal ? 64 : 32})">${inside}</g></svg>`;
}

// Deterministic poses for APNG/GIF exports; CSS/SVG remains the production web source.
const ease = t => { t = Math.min(1, Math.max(0, t)); return t * t * (3 - 2 * t); };
function frameParts(type, milliseconds) {
  const period = DURATIONS[type], u = (milliseconds % period) / period;
  if (type === 'orbit') return `<g transform="rotate(${360 * u} 128 128)">${paths('symbol')}</g>`;
  if (type === 'breathe') {
    const t = .5 - .5 * Math.cos(u * 2 * Math.PI);
    return master.symbol.paths.map((p, i) => `<g opacity="${1 - .5 * t}" transform="translate(${(i ? 6 : -6) * t} ${(i ? 6 : -6) * t})"><path d="${d(p)}"/></g>`).join('');
  }
  if (type === 'resolve') {
    const t = u < .08 ? 0 : u < .32 ? ease((u - .08) / .24) : u < .78 ? 1 : 1 - ease((u - .78) / .22);
    return master.symbol.paths.map((p, i) => `<g opacity="${.55 + .45 * t}" transform="translate(${(i ? 14 : -14) * (1 - t)} ${(i ? -14 : 14) * (1 - t)})"><path d="${d(p)}"/></g>`).join('');
  }
  if (type === 'phase-cycle') {
    const phase = Math.floor(u * 4), local = u * 4 - phase;
    const angle = (phase + ease(Math.max(0, local - .8) / .2)) * 90;
    return `<g transform="rotate(${angle} 128 128)">${paths('symbol')}</g>`;
  }
  if (type === 'settle') {
    const v = Math.min(1, milliseconds / period);
    const s = v < .6 ? .88 + .175 * ease(v / .6) : 1.055 - .055 * ease((v - .6) / .4);
    return `<g opacity="${.2 + .8 * Math.min(1, v / .6)}" transform="translate(128 128) scale(${s}) translate(-128 -128)">${paths('symbol')}</g>`;
  }
  return [master.wordmark.paths.slice(0, 2), master.wordmark.paths.slice(2, 4), master.wordmark.paths.slice(4, 5), master.wordmark.paths.slice(5)]
    .map((ps, i) => { const t = ease((milliseconds - i * 160) / 700); return `<g opacity="${t}" transform="translate(0 ${18 * (1 - t)})">${ps.map(p => `<path d="${d(p)}"/>`).join('')}</g>`; }).join('');
}

function frameSVG(type, milliseconds, colour = INK, background = '') {
  const reveal = type === 'reveal', w = reveal ? 1205 : 320, h = reveal ? 384 : 320;
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">${background ? `<rect width="${w}" height="${h}" fill="${background}"/>` : ''}<g fill="${colour}" transform="translate(${reveal ? 64 : 32} ${reveal ? 64 : 32})">${frameParts(type, milliseconds)}</g></svg>`;
}

function previewHTML() {
  const cards = [ ['orbit', 'Orbit', 'Continuous / 1.6 s', 'General loading'], ['breathe', 'Breathe', 'Gentle / 2.0 s', 'Quiet background work'], ['resolve', 'Resolve', 'Align and hold / 2.4 s', 'Checking an arrangement'] ];
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>ORCA / Motion</title><style>
*{box-sizing:border-box}body{margin:0;background:#F5F7F8;color:#11161B;font:15px/1.6 'Segoe UI',Arial,sans-serif;--panel:#fff;--muted:#52636E;--line:#DDE3E7;--ink:#11161B}body.dark{background:#071D2B;color:white;--panel:#0D2C40;--muted:#B6C8D4;--line:#294454;--ink:white}main{max-width:1260px;margin:auto;padding:48px 32px 68px}.mast{display:flex;justify-content:space-between;align-items:center;gap:20px;margin-bottom:42px}.eyebrow{letter-spacing:3px;font-size:12px;font-weight:600;color:var(--muted)}h1{font-size:42px;letter-spacing:-1.5px;line-height:1.15;margin:12px 0 14px}p{color:var(--muted);margin:0}button,select{font:inherit;padding:8px 13px;min-height:42px;border:1px solid var(--line);border-radius:5px;background:var(--panel);color:inherit}button{cursor:pointer}button:focus-visible,select:focus-visible,a:focus-visible{outline:3px solid #387DA9;outline-offset:4px}.controls{display:flex;gap:10px;align-items:center;flex-wrap:wrap;padding:20px 0 30px}.controls label{display:flex;gap:8px;align-items:center}.controls input{width:18px;height:18px;accent-color:#052640}a{color:inherit;text-underline-offset:4px}.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:18px}.card{background:var(--panel);padding:26px;border-radius:8px;min-width:0}.stage{height:210px;display:flex;align-items:center;justify-content:center;color:var(--ink)}.stage>.motion{width:var(--size,96px);height:var(--size,96px)}.motion svg{display:block;width:100%;height:100%;color:inherit!important}h2{font-size:18px;margin:16px 0 3px}.meta{font-size:12px;color:var(--muted)}.caption{font-size:14px;color:var(--muted)}.wide{margin-top:18px;background:var(--panel);border-radius:8px;padding:30px;display:grid;grid-template-columns:180px 1fr;gap:30px;align-items:center}.phase-mark{width:112px;height:112px;margin:auto;color:var(--ink)}.phase-mark svg{width:100%;height:100%;color:inherit!important}.phases{display:flex;gap:22px;flex-wrap:wrap;margin:16px 0}.phases button{border:0;border-bottom:2px solid transparent;border-radius:0;background:transparent;padding:5px 0;color:var(--muted)}.phases button[aria-pressed=true]{color:inherit;border-bottom-color:currentColor;font-weight:600}.phases button:disabled{cursor:default}.hero{margin-top:18px;background:#052640;color:#fff;border-radius:8px;padding:32px}.hero .meta,.hero p{color:#B6C8D4}.reveal-stage{min-height:250px;display:flex;align-items:center;justify-content:center}.reveal-stage>.motion{width:min(780px,100%)}.reveal-stage svg{width:100%;height:auto}.hero-head{display:flex;justify-content:space-between;align-items:center;gap:16px}.hero button{background:#12364F;color:white;border-color:#365267}.settle-row{margin-top:18px;display:flex;align-items:center;gap:26px;padding:26px 30px;background:var(--panel);border-radius:8px}.settle-stage{width:84px;height:84px;color:var(--ink);flex:none}.settle-stage svg{width:100%;height:100%;color:inherit!important}.settle-row button{margin-left:auto}.footer{margin-top:36px;font-size:13px;color:var(--muted);display:flex;justify-content:space-between;gap:22px;flex-wrap:wrap}.paused .motion *{animation-play-state:paused!important}.reduced .motion *{animation:none!important;transition:none!important;opacity:1!important}@media(prefers-reduced-motion:reduce){.motion *{animation:none!important;transition:none!important}}@media(max-width:720px){main{padding:28px 18px}.grid{grid-template-columns:1fr}.stage{height:150px}.wide{grid-template-columns:1fr;padding:24px;gap:12px}.phase-mark{width:86px;height:86px}.hero{padding:24px}.reveal-stage{min-height:170px}h1{font-size:34px}.mast{align-items:flex-start;margin-bottom:20px}.settle-row{flex-wrap:wrap;padding:24px}.settle-row button{margin-left:0}.phases{gap:16px}}
${svgCSS}</style></head><body><main>
<div class="mast"><div><div class="eyebrow">ORCA / MOTION PACK 01</div><h1>The split O, in motion.</h1><p>Three loading loops, four real stages, one signature reveal.</p></div><a href="../START-HERE.txt">Usage guide</a></div>
<div class="controls" aria-label="Motion preview controls"><button id="pause" type="button">Pause</button><button id="theme" type="button" aria-pressed="false">Dark background</button><label>Size <select id="size"><option value="24">24 px</option><option value="48">48 px</option><option value="96" selected>96 px</option><option value="144">144 px</option></select></label><label>Speed <select id="speed"><option value="0.65">Slow</option><option value="1" selected>Standard</option><option value="1.4">Fast</option></select></label><label><input type="checkbox" id="reduce">Reduce motion</label></div>
<section class="grid" aria-label="Loading animations">${cards.map(([type,title,timing,use]) => `<article class="card"><div class="stage"><div class="motion" data-type="${type}">${animatedSVG(type)}</div></div><h2>${title}</h2><div class="meta">${timing}</div><div class="caption">${use}</div></article>`).join('')}</section>
<section class="wide"><div class="motion phase-mark" id="phase-mark">${animatedSVG('phase-cycle')}</div><div><div class="eyebrow">FOUR-PHASE SEQUENCE</div><h2 id="phase-title">Observe</h2><div class="phases" aria-label="Choose a workflow phase">${['Observe','Resolve','Check','Apply'].map((s,i) => `<button type="button" data-phase="${i}" aria-pressed="${i===0}">${s}</button>`).join('')}</div><p>This preview cycles through the stages. The app component follows the actual phase you supply.</p><button id="auto" type="button" aria-pressed="true">Auto preview on</button></div></section>
<section class="hero"><div class="hero-head"><div><div class="eyebrow" style="color:#B6C8D4">SIGNATURE REVEAL</div><div class="meta">One-shot / 1.6 s / settles into the original wordmark</div></div><button id="replay" type="button">Replay reveal</button></div><div class="reveal-stage"><div class="motion" id="reveal">${animatedSVG('reveal', WHITE)}</div></div></section>
<section class="settle-row"><div class="motion settle-stage" id="settle">${animatedSVG('settle')}</div><div><h2>Settle</h2><p>A short flourish for a completed action.</p><div class="meta">One-shot / 0.76 s</div></div><button id="settle-replay" type="button">Replay settle</button></section>
<div class="footer"><span>ORCA by IssueLab / Direction 05</span><span>SVG + CSS / React / GIF + APNG / Reduced-motion support</span></div>
</main><script>
const body=document.body, pause=document.getElementById('pause'), reduce=document.getElementById('reduce'), speed=document.getElementById('speed');
let paused=false, auto=true, phase=0, factor=1, clock=0, previous=0;
const media=matchMedia('(prefers-reduced-motion: reduce)');reduce.checked=media.matches;body.classList.toggle('reduced',reduce.checked);
const phaseNames=['Observe','Resolve','Check','Apply'];
function updatePhase(n){phase=n;document.getElementById('phase-title').textContent=phaseNames[n];document.querySelectorAll('[data-phase]').forEach(b=>b.setAttribute('aria-pressed',String(Number(b.dataset.phase)===n)));if(!auto){const g=document.querySelector('#phase-mark .om-phase');g.style.animation='none';g.style.transform='rotate('+(n*90)+'deg)';}}
function updateDurations(){document.querySelectorAll('.motion').forEach(host=>host.querySelectorAll('*').forEach(el=>{const name=getComputedStyle(el).animationName;if(name!=='none'){const base=name==='om-orbit'?1.6:name.startsWith('om-breathe')?2:name.startsWith('om-resolve')?2.4:name==='om-phase'?4.8:name==='om-settle'?.76:.7;el.style.animationDuration=(base/factor)+'s';}}));}
pause.onclick=()=>{paused=!paused;body.classList.toggle('paused',paused);pause.textContent=paused?'Resume':'Pause';pause.setAttribute('aria-pressed',String(paused));};
document.getElementById('theme').onclick=e=>{const dark=body.classList.toggle('dark');e.currentTarget.setAttribute('aria-pressed',String(dark));e.currentTarget.textContent=dark?'Light background':'Dark background';};
document.getElementById('size').onchange=e=>document.documentElement.style.setProperty('--size',e.target.value+'px');
speed.onchange=()=>{factor=Number(speed.value);updateDurations();};
reduce.onchange=()=>body.classList.toggle('reduced',reduce.checked);
media.addEventListener('change',e=>{reduce.checked=e.matches;body.classList.toggle('reduced',e.matches);});
document.querySelectorAll('[data-phase]').forEach(b=>b.onclick=()=>{auto=false;document.getElementById('auto').setAttribute('aria-pressed','false');document.getElementById('auto').textContent='Auto preview off';updatePhase(Number(b.dataset.phase));});
document.getElementById('auto').onclick=e=>{auto=!auto;e.currentTarget.setAttribute('aria-pressed',String(auto));e.currentTarget.textContent='Auto preview '+(auto?'on':'off');const g=document.querySelector('#phase-mark .om-phase');g.style.animation='';g.style.transform='';clock=0;updatePhase(auto?0:phase);};
function replay(id){const host=document.getElementById(id);host.innerHTML=host.innerHTML;updateDurations();}
document.getElementById('replay').onclick=()=>replay('reveal');document.getElementById('settle-replay').onclick=()=>replay('settle');
function tick(now){if(previous&&!paused&&!reduce.checked&&auto){clock+=(now-previous)*factor;updatePhase(Math.floor(clock/1200)%4);}previous=now;requestAnimationFrame(tick);}requestAnimationFrame(tick);
</script></body></html>`;
}

async function build() {
  for (const type of TYPES) for (const [tone, colour] of Object.entries({ ink: INK, navy: NAVY, white: WHITE })) write(`svg/${type}-${tone}.svg`, animatedSVG(type, colour));
  write('web/orca-motion-svg.css', svgCSS);
  write('preview/index.html', previewHTML());
  write('timings.json', JSON.stringify({ version:'1.0', durationsMs:DURATIONS, repeats:{orbit:'infinite',breathe:'infinite',resolve:'infinite','phase-cycle':'infinite, demonstration only',settle:1,reveal:1}, reducedMotion:'Static final brand mark, no repeating motion', colours:master.palette }, null, 2));
  const framesRoot = path.join(ROOT, '.build', 'frames');
  const jobs = [ ...['orbit','breathe','resolve','phase-cycle'].map(type => ({type,count:DURATIONS[type]/40,width:256,height:256,delay:40})),
    {type:'settle',count:32,width:256,height:256,delay:40}, {type:'reveal',count:80,width:960,height:306,delay:40} ];
  for (const job of jobs) for (const [tone,colour] of Object.entries({ink:INK,white:WHITE})) {
    const dir=path.join(framesRoot,`${job.type}-${tone}`);fs.mkdirSync(dir,{recursive:true});
    for(let i=0;i<job.count;i++) {
      const buffer=await sharp(Buffer.from(frameSVG(job.type,i*job.delay,colour)),{density:144}).resize(job.width,job.height).toColourspace('srgb').withIccProfile('srgb').png().toBuffer();
      fs.writeFileSync(path.join(dir,`frame-${String(i).padStart(4,'0')}.png`),buffer);
    }
    console.log(JSON.stringify({type:job.type,tone,frames:job.count}));
  }
  const board=[];
  for(let i=0;i<120;i++) {
    const time=i*40;
    let body=`<rect width="1200" height="720" fill="${NAVY}"/><text x="60" y="56" font-family="Segoe UI,Arial,sans-serif" font-size="18" letter-spacing="4" fill="#B6C8D4">ORCA / MOTION 01</text>`;
    body+=`<g fill="white" transform="translate(180 120) scale(.78)">${frameParts('reveal',time%4800)}</g>`;
    for(const [n,type] of ['orbit','breathe','resolve'].entries()) body+=`<g fill="white" transform="translate(${150+n*370} 422) scale(.55)">${frameParts(type,time)}</g><text x="${220+n*370}" y="636" text-anchor="middle" font-family="Segoe UI,Arial,sans-serif" font-size="20" fill="#B6C8D4">${type[0].toUpperCase()+type.slice(1)}</text>`;
    const s=`<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="720">${body}</svg>`;
    const buf=await sharp(Buffer.from(s)).png().toBuffer();board.push(buf);
  }
  const dir=path.join(framesRoot,'overview');fs.mkdirSync(dir,{recursive:true});
  board.forEach((buf,i)=>fs.writeFileSync(path.join(dir,`frame-${String(i).padStart(4,'0')}.png`),buf));
  console.log(JSON.stringify({root:ROOT,svgAssets:18,previewFrames:120}));
}
if(require.main===module)build().catch(e=>{console.error(e);process.exitCode=1;});
module.exports={animatedSVG,frameSVG,frameParts,svgCSS,DURATIONS};
