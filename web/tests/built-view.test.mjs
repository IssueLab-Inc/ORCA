import assert from "node:assert/strict";
import test from "node:test";
import { renderToStaticMarkup } from "react-dom/server";
import { createElement } from "react";
import { compiled } from "./app-host.mjs";

/** Show it built's picture (docs/show-it-built.md, "Page"). Owner report, Nov 3: the section was messy, its controls
 * and icons wrapping onto lines of their own in the Clash panel, and the wipe was a slider beside the picture. Now the
 * picture itself is the control: drag on it to move the wipe, with a handle on the wipe and each side named. */

const { BuiltView, wipeAt } = await import(await compiled("../src/BuiltView.tsx", {
  react: import.meta.resolve("react"), "react/jsx-runtime": import.meta.resolve("react/jsx-runtime"),
  "lucide-react": import.meta.resolve("lucide-react"), "./aiNames": await compiled("../src/aiNames.ts"),
}));

const result = { status: "done", image_url: "/pic.jpg", lines_url: "/lines.png", gate: { f: 0.93 },
  verdicts: [{ verdict: "faithful" }, { verdict: "minor_differences" }], judge: "Muse Wonder" };
const run = (over = {}) => ({ status: "done", step: "", look: "/look.jpg", cut: "Taken away for the view: a slab.", result, ...over });
const html = (r) => renderToStaticMarkup(createElement(BuiltView, { run: r }));

test("a press on the picture puts the wipe there, kept within it", () => {
  assert.equal(wipeAt(150, 100, 200), 25);
  assert.equal(wipeAt(40, 100, 200), 0, "left of the picture: all ORCA's view");
  assert.equal(wipeAt(400, 100, 200), 100, "right of it: all the illustration");
  assert.equal(wipeAt(150, 100, 0), 50, "a picture not laid out yet: the middle");
});

test("the picture is the wipe's control: half and half to start, a handle, each side named, no slider beside it", () => {
  const out = html(run());
  assert.match(out, /class="built-stage wiping[^"]*" role="slider" tabindex="0"/, "the picture takes the pointer and the arrow keys");
  assert.match(out, /aria-valuenow="50"/, "both sides at once to start");
  assert.match(out, /aria-valuetext="50% illustration, 50% ORCA&#x27;s view"/);
  assert.ok(!out.includes('type="range"'), "no slider beside the picture");
  assert.match(out, /class="built-knob"/, "a handle on the wipe says it moves");
  assert.match(out, /class="built-side" style="clip-path:inset\(0 50% 0 0\)"><img class="built-pic"[^>]*><span class="built-tag left"[^>]*>Built</);
  assert.match(out, /class="built-side" style="clip-path:inset\(0 0 0 50%\)"><img class="built-under"[^>]*><span class="built-tag right"[^>]*>ORCA&#x27;s view</,
    "each side's name is cut at the wipe with its picture");
});

test("the check is a labelled chip with its numbers in the tip, and the label is one block beside its icon", () => {
  const out = html(run());
  assert.match(out, /<span class="built-check" tabindex="0" aria-label="Checked against the model: outline match 0.93; Muse Wonder judges: faithful and minor differences."/);
  assert.match(out, /<\/svg> Checked against the model <svg/, "it says what it is, not an icon alone");
  assert.match(out, /<figcaption><svg[^>]*>.*?<\/svg><div><p>Illustration by Muse Image from ORCA&#x27;s model view. The model is the record.<\/p><p class="hint">Taken away for the view: a slab.<\/p><\/div><\/figcaption>/);
});

test("without ORCA's view to compare with, the picture is shown whole and takes no drag", () => {
  const out = html(run({ look: "" }));
  assert.ok(!out.includes('role="slider"') && !out.includes("built-knob") && !out.includes("built-tag"));
  assert.match(out, /<div class="built-side"><img class="built-pic"/, "not clipped");
});
