# ORCA brand assets and motion

The owner selected **05 / ORCA Type** on 30 October 2026 and approved its refined wordmark, matching O symbol and app icon. The full static and motion kit is maintained in [`assets/brand/orca/`](../assets/brand/orca/README.md) for the upcoming application redesign.

## Identity

The custom O, R, C and A use geometric outlines and diagonal cuts. [`source/master.json`](../assets/brand/orca/source/master.json) is the single geometry source. Static generators and motion generators both read it. The O paths in the wordmark and standard symbol are identical; an optical micro symbol widens the cut from 18 to 24 master units for small rendering.

The cap height is 256 units; clear space is 64 units on all sides. Minimum artwork widths are 128 px for the wordmark, 240 px for the endorsed lockup and 24 px for the standard symbol; use the optical micro artwork at 16-20 px. Logo SVGs and transparent PNGs include clear space.

| Colour | Value | Use |
| --- | --- | --- |
| Ink | `#11161B` | Primary identity on light backgrounds |
| Navy | `#052640` | Alternate identity and dark surfaces |
| White | `#FFFFFF` | Reversed identity |
| Paper | `#F5F7F8` | Supporting light surface |
| Line | `#DDE3E7` | Supporting divider |
| Muted | `#52636E` | Supporting copy |

The logo is custom artwork, not a font. Outlined SVG lockups need no font; supporting layouts can use Segoe UI, Arial or a system sans-serif. No font files are distributed. Print PDF/EPS files are scalable RGB vectors, not CMYK or PDF/X proofs.

## Library and previews

The kit includes wordmarks, symbols, IssueLab lockups, transparent PNGs, favicons, Apple/Android/Windows icons, maskable icons, social graphics, video overlays, print masters, colour tokens and a four-page PDF guide. [The library README](../assets/brand/orca/README.md) inventories the folders and gives locked dependency installation and rebuild commands. ZIP archives and frame intermediates are generated locally and ignored by Git.

The [static gallery](../assets/brand/orca/preview/index.html), [motion gallery](../assets/brand/orca/motion/preview/index.html) and [native component example](../assets/brand/orca/motion/web/example.html) can be opened locally. For native JavaScript modules, serve the kit through a local HTTP server. The gallery supports light/dark surfaces, size and speed controls, pause, reduced-motion preview, phase selection and replay of one-shot effects.

## Motion semantics

| Motion | Duration | Application use |
| --- | --- | --- |
| Orbit | 1.6 s, loop | General indeterminate loading |
| Breathe | 2.0 s, loop | Quiet background work |
| Resolve | 2.4 s, loop | Testing an arrangement |
| Phase cycle | 4.8 s, loop | Demonstration of four phases only |
| Settle | 0.76 s, once | Feedback after a confirmed completed action |
| Reveal | 1.6 s, once | Brand entry, ending at the full static wordmark |

The production `<orca-phase>` element is controlled by its `phase` attribute. It follows real application/server events and never advances by itself. The automatically cycling SVG/GIF/APNG phase exports are demonstration material. Neither loading motion nor a completion flourish proves geometry, safety or engineering adequacy.

The native elements are dependency-free and scoped with shadow DOM. They inherit colour, expose accessible labels, support pause and reduced attributes, and honour `prefers-reduced-motion`. React TypeScript wrappers use the same native implementation. Animated SVGs contain CSS and vector paths, without script. GIF/APNG cannot detect operating-system motion preferences; their host must select static artwork when necessary.

## In the app

Adopted on Oct 30 (`claude/laughing-allen-29oggh`). The app does not import the kit: it carries copies of what it uses.

- **Header:** the desktop has no header bar. The wordmark hangs from the model's top edge in a notch (`web/src/Brand.tsx`,
  `Notch`), and the model's top right corner holds Export and the menu (`MenuSheet`, the same panel phones use). Phones
  and tablets keep their compact bar with the wordmark (tablet) or the app icon (phone).
- **Loading:** while ORCA works the notch grows to say what it is doing, with Orbit on the split-O; while the first
  models open, a card in the middle of the empty model lists the real steps (opened on the server, downloaded n of n,
  drawing model k of n). Both read live state; nothing advances on a timer. Every `.spinner` is the optical micro
  symbol (`web/public/brand/orca-spinner.svg`) as a CSS mask, at Orbit's 1.6 s.
- **Completion:** Settle plays once in a toast after the server kept a fix (`markFixed`), never for a proposal.
- **Notch size:** the wordmark there is 20 px high (84 px wide), smaller than the guide's 128 px minimum artwork width;
  an owner decision on Oct 30, so the notch stays small over the model.
- **Report:** the PDF cover starts with the wordmark and BY ISSUELAB (`document.LOCKUP`, navy).
- **Boot:** `web/index.html` shows the wordmark with the Reveal letters until React mounts.
- **Icons:** `web/public/favicon.svg` (adaptive) and `web/public/brand/` (ICO, Apple touch, Android, maskable,
  manifest, pinned tab, `og.png`); theme colour navy.
- **Colour:** the app's accent is navy `#052640`, text ink `#11161B`, the background paper, lines and muted text the
  kit's. The viewer's own 3D colours (section box, measurements) are unchanged.
- **Not used yet:** the `<orca-phase>` element (no Observe/Resolve/Check/Apply events are wired), social files other
  than `og.png`, and the video files.

Reduced motion stills Orbit, Settle and Reveal. Checked in Chromium at 1440×900 on Northbank (landing, loading card,
working notch, loaded, menu, a selected clash); web tests and build in [22](architecture/22-build-log.md).

## Provenance and validation

The approved concept image was generated during this chat with the built-in image-generation tool, then reconstructed as editable paths. `reference/approved-direction-05.png` retains the selected visual reference. All artwork and code in this kit were created during the hackathon, without customer data or imported earlier product code.

Static validation checks alpha and clear space, SVG outlines, vector PDF contents, icon dimensions, maskable safe areas, shared O geometry and file hashes. Motion validation decodes changing frames and checks alpha and loop metadata. Browser validation exercises actual animation, controls, accessibility, responsiveness, one-shot final states and reduced motion. The React wrappers have a dedicated strict TypeScript check. Recorded manifests and validation reports live with the kit and are refreshed after changes.
