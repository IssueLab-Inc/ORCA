export type OrcaLoaderVariant = 'orbit' | 'breathe' | 'resolve';
export type OrcaPhase = 'observe' | 'resolve' | 'check' | 'apply';
export declare class OrcaLoaderElement extends HTMLElement {}
export declare class OrcaPhaseElement extends HTMLElement {}
export declare class OrcaRevealElement extends HTMLElement { replay(): void; }
export declare class OrcaSettleElement extends OrcaRevealElement {}
declare global { interface HTMLElementTagNameMap {
  'orca-loader': OrcaLoaderElement;
  'orca-phase': OrcaPhaseElement;
  'orca-reveal': OrcaRevealElement;
  'orca-settle': OrcaSettleElement;
} }
