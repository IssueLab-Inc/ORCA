import type { Matches, Measure, ReportClash, TriageVerdict } from "./api";

/** Why a reported clash needs no fix, or null when it may. Geometry and the report decide first, triage after. */
export interface NoClash { label: string; title: string; why: string }

const NON_PHYSICAL = /^Ifc(Space|DistributionPort|OpeningElement|VirtualElement|Zone)$/;
const TOUCH_M = 0.001;

/** Both sides resolve to the same model element (a port and its own valve, or two Navisworks parts of one door). */
export function oneElement(m: Matches[string] | undefined) {
  const a = m?.show?.[0] ?? m?.a, b = m?.show?.[1] ?? m?.b;
  return !!a && a === b;
}

export function sameWhy(c: ReportClash) {
  const ports = [c.a, c.b].filter((e) => /Port$/.test(e.ifc_class ?? "")).length;
  return ports === 2 ? "two of its ports" : ports === 1 ? "a port with the element it belongs to" : "two parts of it";
}

export function noClash(c: ReportClash, match?: Matches[string], measure?: Measure | null | "busy", triage?: TriageVerdict): NoClash | null {
  const m = measure && measure !== "busy" ? measure : null;
  const overlap = m?.matched && m.physical && m.distance_m != null && m.distance_m < -TOUCH_M;
  if (oneElement(match))
    return { label: "same element", title: "One element, not two",
      why: `A and B are the same element in this model: Navisworks clashed ${sameWhy(c)}. There is nothing to move.` };
  const np = [c.a, c.b].find((e) => NON_PHYSICAL.test(e.ifc_class ?? ""));
  if (np || m?.physical === false)
    return { label: "not physical", title: "Not a physical clash",
      why: `${np ? `One side is a ${np.ifc_class!.replace(/^Ifc/, "").replace(/([a-z])([A-Z])/g, "$1 $2").toLowerCase()}` : "One side is not a physical element"}: it takes no space on site, so nothing collides.` };
  if (!overlap && c.distance_m != null && Math.abs(c.distance_m) <= TOUCH_M)
    return { label: "touch", title: "They only touch",
      why: `Navisworks reports ${Math.round(Math.abs(c.distance_m) * 1000)} mm${m?.matched && m.physical ? " and Sightline measures no overlap" : ""}: the two meet face to face, which is how parts are built.` };
  if (m?.matched && m.physical && m.distance_m == null && c.distance_m != null && c.distance_m < -TOUCH_M)
    return { label: "no overlap", title: "No overlap in this model",
      why: `Navisworks reported ${Math.round(c.distance_m * 1000)} mm, but the open model shows no overlap: it was fixed since, or the model differs from the one Navisworks checked.` };
  if (triage && (triage.verdict === "by_design" || triage.verdict === "non_physical"))
    return { label: triage.verdict === "by_design" ? "by design" : "not physical", title: triage.verdict === "by_design" ? "By design, says triage" : "Not physical, says triage",
      why: triage.understanding || "Triage read this as intended, not a problem." };
  return null;
}
