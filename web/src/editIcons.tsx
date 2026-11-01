// The edit tools' icons (docs/manual-edits.md, "Icons"): each one acts out what its tool does. They play their action
// once when the button is hovered or focused, loop gently while their tool is on (`.ibtn.on`, or `loop`), and hold
// still under prefers-reduced-motion (index.css, "Edit tool icons"). Same props as a lucide icon, so IconButton and
// the dock take them; no dependency.
import { forwardRef, type ReactNode, type SVGProps } from "react";
import type { LucideIcon } from "lucide-react";

type Props = SVGProps<SVGSVGElement> & { size?: number | string; strokeWidth?: number | string; absoluteStrokeWidth?: boolean;
  /** Loop the action (its tool is on, or a check is running). */ loop?: boolean };

function make(name: string, body: ReactNode): LucideIcon {
  const Icon = forwardRef<SVGSVGElement, Props>(({ size = 24, strokeWidth = 1.75, absoluteStrokeWidth: _a, loop, className = "", ...rest }, ref) => (
    <svg ref={ref} xmlns="http://www.w3.org/2000/svg" width={size} height={size} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round"
      className={`eicon eicon-${name}${loop ? " loop" : ""} ${className}`} {...rest}>
      {body}
    </svg>
  ));
  Icon.displayName = `EditIcon(${name})`;
  return Icon as unknown as LucideIcon;
}

const lit = { fill: "currentColor", fillOpacity: 0.16 } as const;
const thin = { vectorEffect: "non-scaling-stroke" } as const;

/** The Edit tool on the rail: a block whose lit face lifts out a step and settles. */
export const EditIcon = make("edit", <>
  <path d="M12 12v9M4 7.5 12 12l8-4.5M4 7.5v9L12 21l8-4.5v-9" />
  <g className="ei-lift"><path d="M12 3 20 7.5 12 12 4 7.5Z" {...lit} /></g>
</>);

/** Push/pull: the face slides out, the box grows with it, and back. */
export const PushPullIcon = make("push", <>
  <g className="ei-grow"><rect x="3" y="7" width="10" height="10" rx="0.5" style={thin} {...lit} /></g>
  <g className="ei-slide"><path d="M13 7v10" strokeWidth={2.4} /><path d="M16 12h5m-2-2 2 2-2 2" /></g>
</>);

/** Align: the lower block's face glides to the line; the line goes solid on contact. */
export const AlignIcon = make("align", <>
  <rect x="3" y="4" width="11" height="6" rx="0.5" {...lit} />
  <g className="ei-reach"><rect x="3" y="14" width="6" height="6" rx="0.5" style={thin} {...lit} /></g>
  <path className="ei-guide" d="M14 2v20" strokeDasharray="2 2" />
</>);

/** Move: the block travels the dashed path and snaps onto the target. */
export const MoveIcon = make("move", <>
  <path d="M6.5 14.5C8 9 13 6.5 17.5 6.5" strokeDasharray="1.6 2.2" />
  <circle cx="18" cy="6" r="2.6" /><path d="M18 2v1.6M18 8.4V10M14 6h1.6M20.4 6H22" />
  <g className="ei-travel"><rect x="3.5" y="15" width="6" height="6" rx="0.5" {...lit} /></g>
</>);

/** Void: an outline on the slab irises open into a hole. */
export const VoidIcon = make("void", <>
  <path d="M2.5 9.5 7 5h14.5L17 9.5Z M2.5 9.5v9.5H17V9.5M17 19l4.5-4.5V5" {...lit} />
  <g className="ei-iris"><ellipse cx="10" cy="14.2" rx="3.1" ry="2.4" fill="currentColor" fillOpacity={0.55} /></g>
</>);

/** Cut by shape: the plate is carved away round the column, leaving a gap. */
export const CutByIcon = make("cutby", <>
  <path d="M2.5 10h18v5h-18Z" {...lit} />
  <path className="ei-gap" d="M8.6 9.2v6.6M15.4 9.2v6.6" strokeDasharray="1.2 1.4" />
  <rect x="10" y="2.5" width="4" height="19" rx="0.5" fill="currentColor" fillOpacity={0.4} />
</>);

/** Split: the blade comes down and the bar parts with a hairline gap. */
export const SplitIcon = make("split", <>
  <g className="ei-left"><path d="M12 9H3v6h9" {...lit} /></g>
  <g className="ei-right"><path d="M12 9h9v6h-9" {...lit} /></g>
  <path className="ei-blade" d="M12 3v18" strokeDasharray="2 1.6" />
</>);

/** Remove section: both cuts land, the middle piece drops away and fades. */
export const RemoveSectionIcon = make("remove", <>
  <path d="M8.5 9H2.5v6h6M15.5 9h6v6h-6" {...lit} />
  <g className="ei-drop"><rect x="9.3" y="9" width="5.4" height="6" rx="0.3" fill="currentColor" fillOpacity={0.4} /></g>
  <path className="ei-blades" d="M8.8 4v16M15.2 4v16" strokeDasharray="1.6 1.6" />
</>);

/** Clip: the angled plane sweeps across the end and the corner falls away along it. */
export const ClipIcon = make("clip", <>
  <path d="M3 9h11.6l2.4 6H3Z" {...lit} />
  <g className="ei-corner"><path d="M15.2 9H19v6h-1.6Z" fill="currentColor" fillOpacity={0.4} /></g>
  <path className="ei-plane" d="M12.5 3 19.5 21" />
</>);

/** Offset: the middle of a run lifts over something, its ends staying where they are. */
export const OffsetIcon = make("offset", <>
  <path d="M2 16h5.5M16.5 16H22" strokeWidth={2.4} />
  <g className="ei-raise"><path d="M7.5 16 9.5 10h5l2 6" {...lit} /></g>
</>);

/** Join: two free ends close in and meet round a bend. */
export const JoinIcon = make("join", <>
  <path d="M3 18h4a6 6 0 0 0 6-6V8" style={thin} strokeDasharray="1.6 1.8" />
  <g className="ei-right"><path d="M3 18h4" strokeWidth={3} /></g>
  <g className="ei-up"><path d="M13 3v5" strokeWidth={3} /></g>
</>);

/** Disconnect: a joint opens, the two ends parting. */
export const DisconnectIcon = make("disconnect", <>
  <g className="ei-part-l"><path d="M2 12h8" strokeWidth={3} /><path d="M10 8.5v7" /></g>
  <g className="ei-part-r"><path d="M14 12h8" strokeWidth={3} /><path d="M14 8.5v7" /></g>
</>);

/** Delete: the element breaks into dots and is gone. */
export const DeleteIcon = make("delete", <>
  <g className="ei-fade"><rect x="5" y="6" width="14" height="12" rx="1" {...lit} /></g>
  <g className="ei-dust" fill="currentColor" stroke="none">
    <circle cx="7" cy="9" r="1" /><circle cx="17" cy="8" r="0.9" /><circle cx="12" cy="13" r="1" />
    <circle cx="8" cy="16" r="0.8" /><circle cx="16.5" cy="16" r="1" />
  </g>
</>);

/** Undo: the arrow curls back a notch. */
export const UndoIcon = make("undo", <g className="ei-curl">
  <path d="M9 14 4 9l5-5" /><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11" />
</g>);

/** Redo: the arrow curls forward a notch. */
export const RedoIcon = make("redo", <g className="ei-curl">
  <path d="m15 14 5-5-5-5" /><path d="M20 9H9.5a5.5 5.5 0 0 0 0 11H13" />
</g>);

/** Keep: a check that settles once, after the server kept the edit (never for a preview). */
export const KeepIcon = make("keep", <>
  <rect x="3" y="3" width="18" height="18" rx="5" />
  <path className="ei-tick" d="m8 12.5 3 3 5-6.5" pathLength={1} />
</>);

/** Checking: two arrows close on the face while the server checks the arrangement (Resolve). */
export const CheckingIcon = make("checking", <>
  <path d="M12 3v18" strokeDasharray="2 2" />
  <g className="ei-in-l"><path d="M3 12h5.5m-2-2 2 2-2 2" /></g>
  <g className="ei-in-r"><path d="M21 12h-5.5m2-2-2 2 2 2" /></g>
</>);

/** The log: who kept each edit (EditPanel). */
export const LogIcon = make("log", <>
  <path d="M6 4h12M6 9h12M6 14h8M6 19h5" /><circle cx="18.5" cy="17.5" r="2.5" /><path d="M18.5 16.3v1.4l.9.6" />
</>);
