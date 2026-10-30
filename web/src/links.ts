/** What is linked to what in the open models (server connections.graph), for the connection highlight: an element's
 *  direct links by kind, and with Shift its whole connected run. Pure: the viewer and App draw what this says. */

export type LinkKind = "joint" | "assembly" | "hosted" | "rests_on" | "supports" | "contact";

export interface Graph {
  revision: number;
  /** [a, b, kind, source]: kind "joint" | "assembly" | "hosted" | "rests_on" (a rests on b) | "contact". */
  edges: [string, string, string, string][];
  /** Flow elements a run ends at (equipment, terminals): Shift never walks through them. */
  stops: string[];
  systems: Record<string, string[]>;
  assemblies: Record<string, { name: string; parts: string[] }>;
  /** Every linked element's name. */
  names?: Record<string, string>;
}

/** Colours none of the viewer's others use (red A, green B, purple, amber, teal, magenta, orange). */
export const LINK_COLOURS: Record<LinkKind, string> = {
  joint: "#2563eb", assembly: "#475569", hosted: "#9a6b2f", rests_on: "#84cc16", supports: "#65a30d", contact: "#38bdf8",
};
export const LINK_WORDS: Record<LinkKind, string> = {
  joint: "Joined to", assembly: "Same assembly", hosted: "Hosted", rests_on: "Rests on", supports: "Supports",
  contact: "Touches",
};
export const LINK_ORDER: LinkKind[] = ["joint", "hosted", "assembly", "rests_on", "supports", "contact"];

export interface LinkIndex {
  graph: Graph;
  byElement: Map<string, { kind: LinkKind; other: string }[]>;
  stops: Set<string>;
  partOf: Map<string, string>;
}

export function indexGraph(graph: Graph): LinkIndex {
  const byElement = new Map<string, { kind: LinkKind; other: string }[]>();
  const add = (g: string, kind: LinkKind, other: string) => {
    const list = byElement.get(g);
    if (list) list.push({ kind, other }); else byElement.set(g, [{ kind, other }]);
  };
  for (const [a, b, kind] of graph.edges) {
    if (kind === "rests_on") { add(a, "rests_on", b); add(b, "supports", a); continue; }
    add(a, kind as LinkKind, b); add(b, kind as LinkKind, a);
  }
  const partOf = new Map<string, string>();
  for (const whole of Object.keys(graph.assemblies)) for (const part of graph.assemblies[whole].parts) partOf.set(part, whole);
  return { graph, byElement, stops: new Set(graph.stops), partOf };
}

/** An element's direct links, by kind, each once. */
export function linksOf(ix: LinkIndex, gid: string): Partial<Record<LinkKind, string[]>> {
  const out: Partial<Record<LinkKind, string[]>> = {};
  for (const { kind, other } of ix.byElement.get(gid) ?? []) {
    const list = out[kind] ?? (out[kind] = []);
    if (!list.includes(other)) list.push(other);
  }
  return out;
}

/** Everything joined to `gid` through joints, walked on until equipment or a terminal (which is included, not walked
 *  through), at most `max` elements: the run the Shift highlight shows. */
export function runOf(ix: LinkIndex, gid: string, max = 400): string[] {
  const seen = new Set([gid]);
  const todo = [gid];
  while (todo.length && seen.size < max) {
    const g = todo.shift()!;
    if (g !== gid && ix.stops.has(g)) continue;
    for (const { kind, other } of ix.byElement.get(g) ?? []) {
      if (kind !== "joint" || seen.has(other)) continue;
      seen.add(other);
      todo.push(other);
    }
  }
  seen.delete(gid);
  return [...seen];
}

/** What to light for `gid`: its direct links by kind, or with `wide` its whole run (as joints) and the rest of its
 *  assembly, each group in its kind's colour. */
export function highlightGroups(ix: LinkIndex, gid: string, wide: boolean): { kind: LinkKind; color: string; ids: string[] }[] {
  const direct = linksOf(ix, gid);
  if (wide) {
    direct.joint = runOf(ix, gid);
    const whole = ix.partOf.get(gid);
    if (whole) direct.assembly = [...new Set([...(direct.assembly ?? []), ...ix.graph.assemblies[whole].parts.filter((p) => p !== gid)])];
  }
  const shown = new Set<string>();
  const out: { kind: LinkKind; color: string; ids: string[] }[] = [];
  for (const kind of LINK_ORDER) {   // an element linked two ways shows once, in the first kind
    const ids = (direct[kind] ?? []).filter((g) => !shown.has(g));
    ids.forEach((g) => shown.add(g));
    if (ids.length) out.push({ kind, color: LINK_COLOURS[kind], ids });
  }
  return out;
}

/** "3 joined · 1 rests on · 12 supports": a hover label's counts. */
export function countsText(groups: { kind: LinkKind; ids: string[] }[]): string {
  return groups.map((g) => `${g.ids.length} ${LINK_WORDS[g.kind].toLowerCase().replace("joined to", "joined")}`).join(" · ")
    || "nothing linked";
}
