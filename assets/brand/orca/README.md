# ORCA identity and motion assets

Direction **05 / ORCA Type**, selected by the owner on 30 October 2026, is the identity for the upcoming application redesign. The custom wordmark and split-O symbol share the geometry in [`source/master.json`](source/master.json).

Open the [static overview](preview/index.html) or [motion gallery](motion/preview/index.html). This directory is an asset library; the current application does not import it yet. [Design and integration notes](../../../docs/brand-assets.md) describe how the redesign should adopt it.

## Files

| Directory | Contents |
| --- | --- |
| `svg/` | Outlined wordmarks, symbols and “by IssueLab” lockups in ink, navy and white, plus currentColor variants |
| `png/` | Transparent wordmarks up to 4096 px wide and symbols up to 1024 px |
| `icons/` | Adaptive SVG favicon, multi-size ICO, Apple/Android/Windows icons, maskable variants and web manifest |
| `social/`, `video/` | Light/dark social cards, profile banner, title cards and transparent corner overlays |
| `print/`, `docs/` | Vector PDF/EPS print masters and the four-page brand guide |
| `tokens/` | CSS and JSON palette/sizing tokens |
| `reference/` | Approved image-generation concept, retained for provenance |
| `source/` | Canonical geometry, generators, export inventory and initial visual QA notes |
| `motion/svg/` | Orbit, Breathe, Resolve, phase-cycle demo, Settle and Reveal in three colours |
| `motion/apng/`, `motion/gif/` | Transparent APNG exports and light/dark GIF previews |
| `motion/web/`, `motion/react/` | Native elements, a working example, declarations and React wrappers |
| `motion/source/` | Motion generation, packaging and browser checks; consumes the shared master |

The `START-HERE.txt` files and PDF retain the original artifact handoff information. This README and `docs/brand-assets.md` are the repository build instructions. The prebuilt files work without installing the generator dependencies.

The local `.gitattributes` keeps text in LF and declares PDF/PNG/GIF/ICO files binary so Windows checkout conversion does not alter print files or invalidate their recorded hashes.

## Build and check

Use Node 22+ and Python 3.10+. From this directory:

```sh
npm ci
python -m pip install -r requirements.txt

npm run check:types
npm run build:static
npm run build:motion
python source/build-print.py --validate-only --skip-package
python motion/source/package-motion.py --package-only --brand-root .
```

`build:static` renders SVG/PNG files. `build:motion` renders motion frames and regenerates the native elements and React wrappers. To re-encode GIF/APNG from those frames, omit `--package-only` in the last command. To rebuild PDF/EPS and ICO as well, run `python source/build-print.py` without `--validate-only`. Generated archives go to ignored `dist/` directories; motion intermediates and browser screenshots go to `motion/.build/`.

Static supporting text uses a locally installed font. On Windows the default is Segoe UI; set `ORCA_SUPPORT_FONT` to a local font path on other systems. Font files are not redistributed. The logo paths are font-independent; the RGB print masters are not CMYK or PDF/X proofs.

For the browser check:

```sh
npx playwright install chromium
npm run check:browser
```

On Windows, the checker uses an existing Edge installation when present. `ORCA_BROWSER` can select another local Chromium executable. The check starts a temporary loopback HTTP server, uses a fresh headless browser and closes both on completion. It checks actual motion, pause, speed, sizes, responsive layout, final reveal states, reduced motion, accessible labels and real phase control. `validation-browser.json` is a recorded run; rerun it when changing the motion implementation.

## Integrating later

Copy only the needed assets into the application's served files or import the wrappers with their sibling `web/` module. The kit is outside `web/public` so archival concepts, print files and unused previews do not enter the current deploy.

Use Orbit for general loading. The phase component accepts actual `observe`, `resolve`, `check` and `apply` events; it never invents progress. Run Settle only after a confirmed completed action. SVG/native components honour reduced motion; GIF/APNG require a static fallback chosen by their host. See [motion usage](motion/START-HERE.txt) for examples.

All files were created during the hackathon. The approved raster concept was generated with the built-in image-generation tool; the delivered identity is manually reconstructed vector artwork. Changing the application itself belongs in the forthcoming redesign PR.
