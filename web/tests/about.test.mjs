import assert from "node:assert/strict";
import test from "node:test";
import { compiled } from "./app-host.mjs";

const about = await import(await compiled("../src/aboutRoute.ts"));

test("#about opens Overview and #about/<tab> opens that tab", () => {
  assert.equal(about.aboutTabFromHash("#about"), "overview");
  assert.equal(about.aboutTabFromHash("#about/fixes"), "fixes");
  assert.equal(about.aboutTabFromHash("#about/proof"), "proof");
  assert.equal(about.aboutTabFromHash("#about/nonsense"), "overview");
});

test("other hashes leave the About page closed", () => {
  for (const hash of ["", "#", "#owner", "#demos", "#aboutus", "#about/fixes/more"]) assert.equal(about.aboutTabFromHash(hash), null, hash);
});

test("every tab's address leads back to it", () => {
  for (const { id } of about.ABOUT_TABS) assert.equal(about.aboutTabFromHash(about.aboutHash(id)), id);
  assert.equal(about.aboutHash("overview"), "#about");
});

test("arrow keys move through the tabs and wrap round", () => {
  const ids = about.ABOUT_TABS.map((t) => t.id);
  assert.equal(about.nextTab(ids[0], 1), ids[1]);
  assert.equal(about.nextTab(ids[0], -1), ids.at(-1));
  assert.equal(about.nextTab(ids.at(-1), 1), ids[0]);
});

test("without a window there is no hash, and showing one is a no-op", () => {
  assert.equal(about.currentHash(), "");
  about.showAboutHash("fixes", true);
});
