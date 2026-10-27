export interface Hit { other: string; other_class: string; kind: string; distance_m: number }
export interface Verdict { passed: boolean; hits: Hit[]; min_clearance_m: number | null; checked_against: number }
export interface Option {
  title: string; moved: string[]; delta_m: number[]; rationale: string; also_needs: string;
  min_clearance_m: number | null;
}
export interface Attempt { title: string; delta_m: number[]; passed: boolean; reason: string }
export interface Proposal { understanding: string; options: Option[]; attempts: Attempt[] }

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`/api${path}`, { headers: { "Content-Type": "application/json" }, ...init });
  if (!r.ok) throw new Error((await r.json().catch(() => null))?.detail ?? `Request failed (${r.status})`);
  return r.json() as Promise<T>;
}

export const api = {
  samples: () => call<string[]>("/samples"),
  open: (sample: string) => call<{ id: string }>("/scenes", { method: "POST", body: JSON.stringify({ sample }) }),
  file: async (id: string) => new Uint8Array(await (await fetch(`/api/scenes/${id}/file`)).arrayBuffer()),
  verify: (id: string, moved: string[], delta_m: number[]) =>
    call<Verdict>(`/scenes/${id}/verify`, { method: "POST", body: JSON.stringify({ moved, delta_m }) }),
  propose: (id: string, element_a: string, element_b: string) =>
    call<Proposal>(`/scenes/${id}/propose`, { method: "POST", body: JSON.stringify({ element_a, element_b }) }),
  exportUrl: (id: string) => `/api/scenes/${id}/export`,
};
