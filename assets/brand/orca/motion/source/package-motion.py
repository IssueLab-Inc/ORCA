"""Encode the deterministic vector renders, check them, and package the motion kit.
Python 3.10+, Pillow. Optional --brand-root creates the combined v1.1 kit.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import zipfile
from PIL import Image
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
FRAMES = ROOT / '.build' / 'frames'
TYPES = ['orbit', 'breathe', 'resolve', 'phase-cycle', 'settle', 'reveal']
PAPER = (245, 247, 248)
NAVY = (5, 38, 64)


def palette(bg, fg):
    image = Image.new('P', (1, 1))
    image.putpalette([round(bg[c] + (fg[c] - bg[c]) * t / 255) for t in range(256) for c in range(3)])
    return image


def encode():
    for type_ in TYPES:
        for tone in ('ink', 'white'):
            files = sorted((FRAMES / f'{type_}-{tone}').glob('frame-*.png'))
            assert files, f'No frames: {type_}-{tone}'
            images = [Image.open(p).convert('RGBA') for p in files]
            apng = ROOT / 'apng' / f'{type_}-{tone}.png'
            apng.parent.mkdir(parents=True, exist_ok=True)
            images[0].save(apng, format='PNG', save_all=True, append_images=images[1:], duration=40,
                           loop=1 if type_ in ('settle', 'reveal') else 0, disposal=0, blend=0)
            bg = PAPER if tone == 'ink' else NAVY
            fg = (17, 22, 27) if tone == 'ink' else (255, 255, 255)
            quantizer = palette(bg, fg)
            flattened = []
            for im in images:
                canvas = Image.new('RGBA', im.size, (*bg, 255))
                canvas.alpha_composite(im)
                canvas = canvas.convert('RGB')
                if type_ == 'reveal': canvas = canvas.resize((720, 230), Image.Resampling.LANCZOS)
                flattened.append(canvas.quantize(palette=quantizer, dither=Image.Dither.NONE))
            gif = ROOT / 'gif' / f'{type_}-{"light" if tone == "ink" else "dark"}.gif'
            gif.parent.mkdir(parents=True, exist_ok=True)
            flattened[0].save(gif, save_all=True, append_images=flattened[1:], duration=40, loop=0, disposal=2, optimize=False)
            for im in images: im.close()
            print(f'Encoded {type_}-{tone}', flush=True)
    overview = [Image.open(p).convert('RGB') for p in sorted((FRAMES / 'overview').glob('frame-*.png'))]
    # A shared palette prevents edge colours from changing between animation frames.
    samples = Image.new('RGB', (1200, 720 * 3))
    for i, n in enumerate((0, 12, 42)): samples.paste(overview[n], (0, i * 720))
    quantizer = samples.quantize(colors=256)
    frames = [im.quantize(palette=quantizer, dither=Image.Dither.NONE) for im in overview]
    frames[0].save(ROOT / 'preview/motion-overview.gif', save_all=True, append_images=frames[1:], duration=40, loop=0, disposal=2, optimize=False)
    overview[42].save(ROOT / 'preview/motion-poster.png')


def asset_files(root, skip_motion=False):
    for parent, dirs, names in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in {'node_modules', '.build', 'dist', '__pycache__', '.venv'}
                         and not (skip_motion and Path(parent) == root and d == 'motion'))
        for name in sorted(names):
            yield Path(parent) / name


def inspect():
    records = []
    for p in asset_files(ROOT):
        if not p.is_file() or p.name in ('manifest.json', 'validation.json'): continue
        item = {'file': p.relative_to(ROOT).as_posix(), 'bytes': p.stat().st_size,
                'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
        if p.suffix in ('.png', '.gif'):
            with Image.open(p) as im:
                item.update(width=im.width, height=im.height, frames=getattr(im, 'n_frames', 1))
                if p.parent.name in ('apng', 'gif') or p.suffix == '.gif':
                    assert im.n_frames > 1, p
                    item['loop'] = im.info.get('loop')
                    duration, hashes = 0, set()
                    for i in range(im.n_frames):
                        im.seek(i)
                        hashes.add(hashlib.sha256(im.convert('RGBA').tobytes()).hexdigest())
                        duration += im.info.get('duration', 0)
                    item['duration_ms'] = duration
                    assert len(hashes) > 2, f'Static animation: {p}'
                    if p.parent.name == 'apng':
                        im.seek(im.n_frames - 1)
                        minimum, maximum = im.convert('RGBA').getchannel('A').getextrema()
                        assert minimum == 0 and maximum > 0, p
                        once = p.stem.startswith(('settle-', 'reveal-'))
                        assert im.info.get('loop') == (1 if once else 0), p
        elif p.suffix == '.svg':
            s = p.read_text()
            ET.fromstring(s)
            assert '@media(prefers-reduced-motion:no-preference)' in s
            assert '<path ' in s and '<image ' not in s
        records.append(item)
    report = {'status': 'pass', 'files': len(records), 'svgs': sum(p['file'].endswith('.svg') for p in records),
              'animated_pngs': sum(p['file'].startswith('apng/') for p in records),
              'gifs': sum(p['file'].endswith('.gif') for p in records),
              'checks': ['SVG parsing and vector paths', 'SVG reduced-motion media queries',
                         'Animation frame decoding and changing content', 'APNG transparency',
                         'One-shot and looping APNG playback metadata', 'SHA-256 and dimensions']}
    (ROOT / 'manifest.json').write_text(json.dumps({'name': 'ORCA motion pack', 'version': '1.0', 'date': '2026-10-30', 'files': records}, indent=2) + '\n', encoding='utf-8', newline='\n')
    (ROOT / 'validation.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8', newline='\n')
    return report


def package(brand_root=None):
    archive = ROOT / 'dist' / 'ORCA-motion-assets-v1.zip'
    archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p in asset_files(ROOT):
            z.write(p, Path('orca-motion-kit-v1') / p.relative_to(ROOT))
    with zipfile.ZipFile(archive) as z: assert z.testzip() is None
    result = {'motion_zip': str(archive), 'motion_zip_bytes': archive.stat().st_size}
    if brand_root:
        combined = brand_root / 'dist' / 'ORCA-brand-assets-v1.1.zip'
        combined.parent.mkdir(parents=True, exist_ok=True)
        base = Path('orca-brand-kit-v1.1')
        files = []
        with zipfile.ZipFile(combined, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
            for p in asset_files(brand_root, skip_motion=True):
                if p.is_file():
                    rel = p.relative_to(brand_root)
                    if rel.as_posix() == 'manifest.json': continue
                    z.write(p, base / rel)
                    files.append({'file': rel.as_posix(), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()})
            for p in asset_files(ROOT):
                if p.is_file():
                    rel = Path('motion') / p.relative_to(ROOT)
                    z.write(p, base / rel)
                    files.append({'file': rel.as_posix(), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()})
            z.writestr(str(base / 'MOTION-START-HERE.txt'), 'ORCA brand kit v1.1\n\nThe original identity assets are preserved.\nThe motion add-on is in motion/.\n\nStart with motion/preview/index.html, then motion/START-HERE.txt.\nThe root validation.json describes the static assets; motion/validation.json\nand motion/validation-browser.json describe the new motion assets.\n')
            z.writestr(str(base / 'manifest.json'), json.dumps({'name': 'ORCA brand assets', 'version': '1.1', 'date': '2026-10-30', 'files': files}, indent=2))
        with zipfile.ZipFile(combined) as z: assert z.testzip() is None
        result.update(combined_zip=str(combined), combined_zip_bytes=combined.stat().st_size)
    print(json.dumps(result))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--brand-root', type=Path)
    parser.add_argument('--package-only', action='store_true')
    args = parser.parse_args()
    if not args.package_only: encode()
    print(json.dumps(inspect()))
    package(args.brand_root)
