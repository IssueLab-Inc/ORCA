"""Create the vector print masters, brand guide, ICO and checked delivery archive.

Requires Python 3.10+, reportlab, Pillow and pypdf. All logo geometry comes
from master.json. No generated concept image is used to make an export.
"""
from __future__ import annotations

import hashlib
import argparse
import json
import math
from pathlib import Path
import os
import zipfile

from PIL import Image
from pypdf import PdfReader
from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor, Color
from reportlab.lib.pagesizes import landscape, A4

ROOT = Path(__file__).resolve().parent.parent
MASTER = json.loads((ROOT / 'source/master.json').read_text())
COL = MASTER['palette']
W, H = landscape(A4)


def rgb(value):
    return HexColor(COL.get(value, value))


def logo(c, kind, x, y, width, colour='ink'):
    """Bottom-left positioned, shared path geometry; PDF paths stay vectors."""
    m = MASTER[kind]
    scale = width / m['width']
    c.saveState()
    c.translate(x, y + m['height'] * scale)
    c.scale(scale, -scale)
    c.setFillColor(rgb(colour))
    for commands in m['paths']:
        p = c.beginPath()
        for op, *v in commands:
            if op == 'M': p.moveTo(*v)
            elif op == 'L': p.lineTo(*v)
            elif op == 'C': p.curveTo(*v)
            elif op == 'Z': p.close()
        c.drawPath(p, fill=1, stroke=0)
    c.restoreState()


def box(c, x, y, w, h, fill, radius=0):
    c.setFillColor(rgb(fill))
    if radius:
        c.roundRect(x, y, w, h, radius, fill=1, stroke=0)
    else:
        c.rect(x, y, w, h, fill=1, stroke=0)


def txt(c, x, y, content, size=11, colour='ink', bold=False):
    c.setFillColor(rgb(colour))
    c.setFont('Helvetica-Bold' if bold else 'Helvetica', size)
    c.drawString(x, y, content)


def lines(c, x, y, values, size=10, leading=16, colour='muted'):
    for n, value in enumerate(values): txt(c, x, y - n * leading, value, size, colour)


def page(c, title, number):
    box(c, 0, 0, W, H, 'paper')
    txt(c, 42, H - 45, 'ORCA / IDENTITY 01', 10, 'muted', True)
    txt(c, 42, H - 84, title, 27, 'ink', True)
    c.setStrokeColor(rgb('line'))
    c.line(42, 42, W - 42, 42)
    txt(c, 42, 26, 'Direction 05 / Version 1.0 / 30 October 2026 / By IssueLab', 8, 'muted')
    txt(c, W - 53, 26, str(number), 8, 'muted')


def guide():
    target = ROOT / 'docs/orca-brand-guide.pdf'
    target.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(target), pagesize=(W, H), pageCompression=1)
    c.setTitle('ORCA - Brand asset guide v1.0')
    c.setAuthor('IssueLab')

    box(c, 0, 0, W, H, 'navy')
    txt(c, 44, H - 48, 'ORCA / BRAND ASSET GUIDE', 11, '#B5C4CE', True)
    txt(c, 44, H - 77, 'Direction 05 / Version 1.0', 11, '#B5C4CE')
    logo(c, 'wordmark', 44, 280, 700, 'white')
    txt(c, 44, 226, 'AI design coordination', 24, 'white')
    txt(c, 44, 187, 'Observe. Resolve. Check. Apply.', 14, '#B5C4CE')
    txt(c, 44, 61, 'BY ISSUELAB', 11, 'white', True)
    txt(c, 44, 39, '30 October 2026', 9, '#B5C4CE')
    logo(c, 'symbol', W - 126, 50, 68, 'white')
    c.showPage()

    page(c, 'The mark and its space', 2)
    box(c, 42, 286, 546, 190, 'white')
    mark_width = 430
    mark_height = mark_width * 256 / 1077
    pad = mark_height / 4
    x, y = 95, 342
    c.setStrokeColor(rgb('line'))
    c.setDash(3, 3)
    c.rect(x - pad, y - pad, mark_width + 2 * pad, mark_height + 2 * pad, fill=0, stroke=1)
    c.setDash()
    logo(c, 'wordmark', x, y, mark_width)
    txt(c, 62, 303, 'Clear space = one quarter of the cap height on every side.', 9, 'muted')
    txt(c, 622, 462, 'CORE COLOURS', 10, 'muted', True)
    for i, (name, value) in enumerate([('INK', COL['ink']), ('NAVY', COL['navy']), ('WHITE', COL['white'])]):
        yy = 392 - i * 57
        box(c, 622, yy, 57, 40, value)
        if name == 'WHITE':
            c.setStrokeColor(rgb('line')); c.rect(622, yy, 57, 40, fill=0, stroke=1)
        txt(c, 693, yy + 23, name, 9, 'ink', True)
        txt(c, 693, yy + 7, value, 9, 'muted')
    for xx, label, detail in [(42, 'WORDMARK', ['Minimum artwork width: 128 px.', 'Use the endorsed lockup at 240 px or wider.']),
                              (304, 'SYMBOL', ['Standard symbol: 24 px or larger.', 'Use the optical micro symbol at 16-20 px.']),
                              (566, 'PRESERVE', ['Keep proportions and diagonal cut geometry.', 'Use solid colour and a clear background.'])]:
        txt(c, xx, 238, label, 10, 'ink', True)
        lines(c, xx, 214, detail, size=9.2, leading=16)
    txt(c, 42, 158, 'Using the files', 16, 'ink', True)
    lines(c, 42, 132, ['Black and navy marks sit on light backgrounds. White marks sit on dark backgrounds.',
                      'PNG logo exports include transparent clear space. Minimum sizes refer to the artwork, not the padded canvas.',
                      'The wordmark is custom outlined artwork. Supporting copy can use Segoe UI, Arial or a system sans-serif.',
                      'Keep the O in the wordmark and the standalone symbol consistent; the micro variant changes only the cut width.'],
          size=9.5, leading=17)
    c.showPage()

    page(c, 'Icons and ready-to-use layouts', 3)
    box(c, 42, 283, 370, 194, 'white')
    box(c, 66, 309, 123, 123, 'navy', 23)
    logo(c, 'symbol', 89, 332, 77, 'white')
    txt(c, 66, 453, 'APP ICON', 10, 'muted', True)
    box(c, 244, 309, 123, 123, 'navy')
    logo(c, 'symbol', 271, 336, 69, 'white')
    c.setStrokeColor(Color(1, 1, 1, .55)); c.setDash(2, 2)
    c.circle(305.5, 370.5, 49.2, fill=0, stroke=1); c.setDash()
    txt(c, 244, 453, 'MASKABLE / SAFE ZONE', 9, 'muted', True)
    box(c, 432, 283, W - 474, 194, 'navy')
    logo(c, 'wordmark', 458, 356, 306, 'white')
    txt(c, 458, 324, 'AI design coordination', 14, 'white')
    txt(c, 458, 302, 'Observe. Resolve. Check. Apply.', 9, '#B5C4CE')
    rows = [('Transparent logos', 'PNG: 512-4096 px wide; symbols: 64-1024 px.'),
            ('Favicons', 'SVG plus 16/32/48/64 px PNGs and a multi-size ICO.'),
            ('Apple / Android', '180 px touch icon; 192/512 px icons and maskable variants.'),
            ('Social', '1200 x 630 cards; 1080 x 1080 squares; 1584 x 396 banner.'),
            ('Video', '1920 x 1080 title cards and transparent corner logos.'),
            ('Print', 'Scalable vector PDF, SVG and EPS. Colours are RGB.')]
    yy = 249
    for label, detail in rows:
        txt(c, 42, yy, label, 10, 'ink', True)
        txt(c, 198, yy, detail, 9.4, 'muted')
        yy -= 29
    c.showPage()

    page(c, 'Handoff and production notes', 4)
    txt(c, 42, 470, 'Choose the source for the job', 15, 'ink', True)
    lines(c, 42, 443, ['SVG is the preferred master for websites, decks and design tools. Logo paths do not need a font.',
                      'Use transparent PNGs when an app cannot accept SVG. White PNGs will look empty on a white page.',
                      'Use the PDF/EPS masters for print. Convert RGB using the printer\'s own ICC profile when CMYK is required.',
                      'Use the square full-bleed icon for Apple and store uploads; the platform supplies the final corner shape.',
                      'The rounded icon is for presentations and direct display. Maskable icons have additional safe padding.'],
          size=10, leading=20)
    txt(c, 42, 311, 'Web installation', 15, 'ink', True)
    lines(c, 42, 283, ['Copy icons/ together, preserving relative file names. The supplied manifest points to icons beside it.',
                      'Set the manifest start_url and scope for the actual hosting path. A manifest alone does not add offline support.',
                      'The favicon.svg adapts to light and dark browser themes. favicon.ico uses a navy tile for contrast.',
                      'The currentcolor SVG variants inherit CSS colour when placed inline, not when loaded through an img tag.'],
          size=10, leading=20)
    txt(c, 42, 178, 'Source, checking and ownership', 15, 'ink', True)
    lines(c, 42, 151, ['source/master.json holds the logo paths. The included build scripts regenerate all deliverables.',
                      'The approved image is retained in reference/ for provenance; exports are drawn from the vector master.',
                      'No third-party font file is included. File checksums and dimensions are listed in manifest.json.',
                      'This pack supplies artwork for ORCA by IssueLab. It makes no trademark-registration claim.'],
          size=9.6, leading=18)
    c.showPage()
    c.save()


def print_masters():
    target = ROOT / 'print/orca-print-masters.pdf'
    target.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(target), pagesize=(W, H), pageCompression=1)
    c.setTitle('ORCA - Vector print masters v1.0')
    c.setAuthor('IssueLab')
    variants = [('wordmark', 'ink', 'Primary / ink', False), ('wordmark', 'navy', 'Primary / navy', False),
                ('wordmark', 'white', 'Reversed / white on navy', True), ('symbol', 'ink', 'Symbol / ink', False),
                ('symbol', 'navy', 'Symbol / navy', False), ('wordmark', 'ink', 'Endorsed / by IssueLab', False)]
    for i, (kind, colour, label, reverse) in enumerate(variants, 1):
        txt(c, 42, H - 45, 'ORCA / PRINT MASTER', 10, 'muted', True)
        txt(c, 42, H - 74, label, 18, 'ink', True)
        if reverse: box(c, 42, 130, W - 84, 309, 'navy')
        width = 670 if kind == 'wordmark' else 256
        height = width * MASTER[kind]['height'] / MASTER[kind]['width']
        x, y = (W - width) / 2, 285 - height / 2
        logo(c, kind, x, y, width, colour)
        if i == 6: txt(c, x + 3, y - 38, 'BY ISSUELAB', 15, 'ink', True)
        txt(c, 42, 62, 'Vector paths / RGB colour / Original proportions / Version 1.0', 9, 'muted')
        txt(c, W - 53, 62, str(i), 9, 'muted')
        c.showPage()
    c.save()


def eps_masters():
    for kind in ('wordmark', 'symbol'):
        for variant in ('ink', 'navy'):
            m = MASTER[kind]
            colour = COL[variant].lstrip('#')
            rgb_values = [int(colour[i:i + 2], 16) / 255 for i in (0, 2, 4)]
            out = ['%!PS-Adobe-3.0 EPSF-3.0', f'%%BoundingBox: 0 0 {m["width"]} {m["height"]}',
                   f'%%Title: ORCA {kind} {variant}', '%%Creator: IssueLab', '%%LanguageLevel: 2',
                   '%%EndComments', 'gsave', f'0 {m["height"]} translate', '1 -1 scale',
                   ' '.join(f'{v:.7f}' for v in rgb_values) + ' setrgbcolor']
            for p in m['paths']:
                out.append('newpath')
                for op, *v in p:
                    cmd = {'M': 'moveto', 'L': 'lineto', 'C': 'curveto', 'Z': 'closepath'}[op]
                    out.append(' '.join([*(str(x) for x in v), cmd]))
                out.append('fill')
            out.extend(['grestore', 'showpage', '%%EOF', ''])
            (ROOT / 'print' / f'orca-{kind}-{"black" if variant == "ink" else variant}.eps').write_text('\n'.join(out), encoding='ascii', newline='\n')


def ico():
    with Image.open(ROOT / 'icons/favicon-tile-256.png') as im:
        im.save(ROOT / 'icons/favicon.ico', format='ICO', sizes=[(n, n) for n in (16, 24, 32, 48, 64, 128, 256)])


def asset_files(root, skip_motion=False):
    for parent, dirs, names in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in {'node_modules', '.build', 'dist', '__pycache__', '.venv'}
                         and not (skip_motion and Path(parent) == root and d == 'motion'))
        for name in sorted(names):
            yield Path(parent) / name


def validate_and_manifest(package=True):
    records = []
    for p in asset_files(ROOT, skip_motion=True):
        if not p.is_file() or p.name in {'manifest.json', 'validation.json'}: continue
        record = {'file': p.relative_to(ROOT).as_posix(), 'bytes': p.stat().st_size, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
        if p.suffix == '.png':
            with Image.open(p) as im:
                im.load()
                record.update(width=im.width, height=im.height, mode=im.mode)
                if 'reference' not in p.parts:
                    assert im.info.get('icc_profile'), f'Missing sRGB ICC profile: {p}'
                if p.parts[-3] == 'png':
                    assert im.mode == 'RGBA', f'Logo is not RGBA: {p}'
                    assert im.getchannel('A').getextrema() == (0, 255), f'Logo alpha is invalid: {p}'
                    bounds = im.getchannel('A').getbbox()
                    assert bounds and bounds[0] > 0 and bounds[1] > 0 and bounds[2] < im.width and bounds[3] < im.height, f'Logo clipped: {p}'
        elif p.suffix == '.pdf':
            reader = PdfReader(p)
            record['pages'] = len(reader.pages)
            assert len(reader.pages) == (4 if p.parent.name == 'docs' else 6)
            assert all(not list(page.images) for page in reader.pages), f'Raster found in vector PDF: {p}'
            assert all(page.extract_text() for page in reader.pages)
        elif p.suffix == '.svg':
            import xml.etree.ElementTree as ET
            root = ET.fromstring(p.read_bytes())
            ns = '{http://www.w3.org/2000/svg}'
            assert root.tag == ns + 'svg'
            assert not root.findall('.//' + ns + 'text'), f'Unoutlined text in SVG: {p}'
            assert not root.findall('.//' + ns + 'image'), f'Embedded bitmap in SVG: {p}'
            assert root.findall('.//' + ns + 'path'), f'Empty SVG: {p}'
        records.append(record)
    icons = json.loads((ROOT / 'icons/site.webmanifest').read_text())
    for item in icons['icons']:
        p = ROOT / 'icons' / item['src']
        assert p.exists()
        with Image.open(p) as im: assert f'{im.width}x{im.height}' == item['sizes']
    with Image.open(ROOT / 'icons/favicon.ico') as im:
        assert len(im.ico.sizes()) == 7
    assert MASTER['wordmark']['paths'][:len(MASTER['symbol']['paths'])] == MASTER['symbol']['paths']
    for size in (192, 512):
        with Image.open(ROOT / f'icons/maskable-icon-{size}.png') as im:
            assert im.getpixel((0, 0))[:3] == (5, 38, 64)
            for y in range(size):
                for x in range(size):
                    if all(v > 240 for v in im.getpixel((x, y))[:3]):
                        assert math.hypot(x + .5 - size / 2, y + .5 - size / 2) < size * .4
    manifest = {'name': 'ORCA asset pack', 'version': '1.0', 'date': '2026-10-30', 'files': records}
    (ROOT / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8', newline='\n')
    validation = {'status': 'pass', 'files_checked': len(records), 'pngs': sum(r['file'].endswith('.png') for r in records),
                  'svgs': sum(r['file'].endswith('.svg') for r in records), 'pdfs': sum(r['file'].endswith('.pdf') for r in records),
                  'checks': ['PNG decoding, dimensions, transparent clearspace and alpha', 'SVG XML parses, text outlined, no embedded bitmaps',
                             'PDFs reopen, extract text and contain no raster images', 'Manifest icon paths and declared dimensions',
                             'ICO contains seven sizes', 'Shared O geometry across wordmark and symbol',
                             'Maskable icon foreground lies in the central 80 percent safe circle',
                             'Embedded sRGB profiles in exported PNGs', 'SHA-256 for every listed file']}
    (ROOT / 'validation.json').write_text(json.dumps(validation, indent=2) + '\n', encoding='utf-8', newline='\n')
    if not package:
        print(json.dumps(validation))
        return
    archive = ROOT / 'dist' / 'ORCA-brand-assets-v1.1.zip'
    archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p in asset_files(ROOT):
            z.write(p, Path('orca-brand-kit-v1.1') / p.relative_to(ROOT))
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
    print(json.dumps({**validation, 'archive': str(archive), 'archive_bytes': archive.stat().st_size}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--validate-only', action='store_true', help='Check existing exports without regenerating print artwork')
    parser.add_argument('--skip-package', action='store_true')
    args = parser.parse_args()
    if not args.validate_only:
        guide()
        print_masters()
        eps_masters()
        ico()
    validate_and_manifest(package=not args.skip_package)
