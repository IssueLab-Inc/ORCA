import type { ReactNode } from "react";

/**
 * The landing's pictures of each kind of fix, before and after, in the viewer's colours: the element that changes red
 * (A) and teal once fixed, what it ran into green (B), where it was dashed. Each loops between its two states (CSS,
 * landing.css "Fix kinds"); with less motion the after state shows, with the before as a dashed ghost.
 */

const Frame = ({ children, label }: { children: ReactNode; label: string }) => (
  <svg viewBox="0 0 240 150" role="img" aria-label={label} className="fa">{children}</svg>
);

export function ArtMove() {
  return (
    <Frame label="Move: a cable ladder running over a fence post is moved 150 mm clear of it, as one run.">
      <rect className="fa-b" x="109" y="64" width="22" height="22" rx="2" />
      <g className="fa-before"><rect className="fa-a" x="16" y="62" width="208" height="26" rx="3" /><rect className="fa-hit" x="109" y="64" width="22" height="22" rx="2" /></g>
      <g className="fa-after">
        <rect className="fa-ghost" x="16" y="62" width="208" height="26" rx="3" />
        <rect className="fa-ok" x="16" y="104" width="208" height="26" rx="3" />
        <path className="fa-arrow" d="M200 92V101" /><text className="fa-dim" x="186" y="100" textAnchor="end">150</text>
      </g>
      <text className="fa-note" x="16" y="22">plan</text>
    </Frame>
  );
}

export function ArtOffset() {
  return (
    <Frame label="Offset: a duct running through a girder's web is raised through the web opening, with bends either side.">
      <g className="fa-b">
        <rect x="98" y="18" width="44" height="8" rx="1.5" /><rect x="98" y="124" width="44" height="8" rx="1.5" />
        <rect x="117" y="26" width="6" height="18" /><rect x="117" y="78" width="6" height="46" />
      </g>
      <rect className="fa-open" x="115" y="44" width="10" height="34" />
      <g className="fa-before"><rect className="fa-a" x="10" y="88" width="220" height="22" rx="2" /><rect className="fa-hit" x="117" y="88" width="6" height="22" /></g>
      <g className="fa-after">
        <rect className="fa-ghost" x="10" y="88" width="220" height="22" rx="2" />
        <path className="fa-ok-line" d="M10 99H62Q76 99 76 85V75Q76 61 90 61H150Q164 61 164 75V85Q164 99 178 99H230" />
        <text className="fa-dim" x="196" y="78">+400</text>
      </g>
    </Frame>
  );
}

export function ArtRoute() {
  return (
    <Frame label="Reroute: a pipe branch running through two plant columns is rerouted round them in three stretches.">
      <rect className="fa-b" x="84" y="64" width="22" height="22" rx="2" /><rect className="fa-b" x="134" y="64" width="22" height="22" rx="2" />
      <g className="fa-before"><path className="fa-a-line thin" d="M12 75H228" /><circle className="fa-hitdot" cx="95" cy="75" r="5" /><circle className="fa-hitdot" cx="145" cy="75" r="5" /></g>
      <g className="fa-after">
        <path className="fa-ghost-line" d="M12 75H228" />
        <path className="fa-ok-line thin" d="M12 75H56Q66 75 66 65V46Q66 36 76 36H164Q174 36 174 46V65Q174 75 184 75H228" />
      </g>
      <text className="fa-note" x="16" y="22">plan</text>
    </Frame>
  );
}

export function ArtTrim() {
  return (
    <Frame label="Trim: a curtain-wall transom running 30 mm into its mullion is cut back to butt the mullion's face.">
      <rect className="fa-b" x="140" y="14" width="18" height="122" rx="1.5" />
      <g className="fa-before"><rect className="fa-a" x="22" y="66" width="152" height="18" rx="1.5" /><rect className="fa-hit" x="140" y="66" width="18" height="18" /></g>
      <g className="fa-after">
        <rect className="fa-ghost" x="140" y="66" width="34" height="18" />
        <rect className="fa-ok" x="22" y="66" width="118" height="18" rx="1.5" />
        <path className="fa-cut" d="M140 56V94" />
      </g>
      <text className="fa-note" x="16" y="22">elevation</text>
    </Frame>
  );
}

export function ArtSeat() {
  return (
    <Frame label="Seat: a wall that runs down into a pad footing is cut where it is inside the pad, so what is left bears on the pad's top.">
      <rect className="fa-b" x="52" y="96" width="136" height="38" rx="2" />
      <g className="fa-before"><rect className="fa-a" x="104" y="18" width="32" height="104" rx="1.5" /><rect className="fa-hit" x="104" y="96" width="32" height="26" /></g>
      <g className="fa-after">
        <rect className="fa-ghost" x="104" y="96" width="32" height="26" />
        <rect className="fa-ok" x="104" y="18" width="32" height="78" rx="1.5" />
        <path className="fa-cut" d="M96 96H144" />
      </g>
      <text className="fa-note" x="16" y="22">section</text>
    </Frame>
  );
}

export function ArtResize() {
  return (
    <Frame label="Resize: a stretch of duct hitting a beam is made flatter and wider, carrying the same, with transitions either side.">
      <rect className="fa-b" x="94" y="16" width="52" height="34" rx="2" />
      <g className="fa-before"><rect className="fa-a" x="10" y="42" width="220" height="44" rx="2" /><rect className="fa-hit" x="94" y="42" width="52" height="8" /></g>
      <g className="fa-after">
        <rect className="fa-ghost" x="10" y="42" width="220" height="44" rx="2" />
        <path className="fa-ok" d="M10 42H58L76 60H164L182 42H230V86H10Z" />
        <text className="fa-dim" x="120" y="110" textAnchor="middle">flatter, wider, same air</text>
      </g>
    </Frame>
  );
}

export function ArtOpening() {
  return (
    <Frame label="Opening: where a straight service crosses a wall, ORCA asks for a provision for void, an opening for the wall's designer to accept.">
      <g className="fa-before">
        <rect className="fa-b" x="106" y="12" width="28" height="126" rx="1.5" />
        <path className="fa-a-line thin" d="M12 75H228" /><rect className="fa-hit" x="106" y="70" width="28" height="10" />
      </g>
      <g className="fa-after">
        <path className="fa-b" d="M106 12H134V60H106Z M106 90H134V138H106Z" />
        <rect className="fa-pfv" x="102" y="60" width="36" height="30" rx="2" />
        <path className="fa-ok-line thin" d="M12 75H228" />
        <text className="fa-dim" x="150" y="54">provision for void</text>
      </g>
    </Frame>
  );
}

export function ArtCombined() {
  return (
    <Frame label="Combined: two services in a crowded spot are moved in one trial, checked together and kept all or nothing.">
      <rect className="fa-b" x="10" y="58" width="220" height="16" rx="2" />
      <g className="fa-before">
        <rect className="fa-a" x="58" y="40" width="34" height="50" rx="2" /><path className="fa-a-line thin" d="M150 20V130" />
        <rect className="fa-hit" x="58" y="58" width="34" height="16" /><circle className="fa-hitdot" cx="150" cy="66" r="5" />
      </g>
      <g className="fa-after">
        <rect className="fa-ghost" x="58" y="40" width="34" height="50" rx="2" /><path className="fa-ghost-line" d="M150 20V130" />
        <rect className="fa-ok" x="58" y="84" width="34" height="50" rx="2" />
        <path className="fa-ok-line thin" d="M150 20V44Q150 50 156 50H178Q184 50 184 56V78Q184 84 178 84H156Q150 84 150 90V130" />
        <path className="fa-bracket" d="M58 142H184" /><text className="fa-dim" x="121" y="138" textAnchor="middle">one trial</text>
      </g>
    </Frame>
  );
}
