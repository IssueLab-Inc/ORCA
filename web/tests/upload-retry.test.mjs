import assert from "node:assert/strict";
import test from "node:test";
import { compiled } from "./app-host.mjs";

const { api, setRequirements, requirementsInUse } = await import(await compiled("../src/api.ts"));

test("an upload the server answers requirements_unknown is sent again once with the file registered again", async () => {
  const sent = [];
  globalThis.XMLHttpRequest = class {
    headers = {};
    upload = {};
    open(method, url) { this.url = url; }
    setRequestHeader(k, v) { this.headers[k] = v; }
    send(form) {
      sent.push({ requirements: this.headers["X-Sightline-Requirements"], files: form.getAll("files").length });
      const known = this.headers["X-Sightline-Requirements"] === "new-id";
      this.status = known ? 200 : 409;
      this.responseText = known ? JSON.stringify({ type: "done", id: "s1", files: ["A.ifc"], step: {}, revision: 0 }) + "\n"
        : JSON.stringify({ detail: "requirements_unknown" });
      queueMicrotask(() => this.onload());
    }
  };
  const posted = [];
  globalThis.fetch = async (url, init) => {
    posted.push([url, JSON.parse(init.body).name]);
    return new Response(JSON.stringify({ id: "new-id" }), { status: 200 });
  };
  setRequirements("old-id", { name: "Northbank" });
  const opened = await api.uploadModelsStream([new File(["ISO-10303-21;"], "A.ifc")], () => {});
  assert.deepEqual(opened, { id: "s1", files: ["A.ifc"], step: {}, revision: 0 });
  assert.deepEqual(sent, [{ requirements: "old-id", files: 1 }, { requirements: "new-id", files: 1 }]);
  assert.deepEqual(posted, [["/api/requirements", "Northbank"]]);
  assert.equal(requirementsInUse(), "new-id");

  sent.length = 0;
  setRequirements("gone", { name: "Northbank" });
  globalThis.fetch = async () => new Response("{}", { status: 500 });   // cannot register: the 409 stands, once
  await assert.rejects(api.uploadModelsStream([new File(["x"], "A.ifc")], () => {}), /requirements_unknown/);
  assert.equal(sent.length, 1);
});
