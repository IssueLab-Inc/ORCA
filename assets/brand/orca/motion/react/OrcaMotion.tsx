import { createElement, type CSSProperties } from 'react';
import '../web/orca-motion.js';
export type Phase = 'observe' | 'resolve' | 'check' | 'apply';
type Shared = { size?: number; label?: string; paused?: boolean; reduced?: boolean; className?: string; style?: CSSProperties };
const flags = (paused?: boolean, reduced?: boolean) => ({ paused: paused ? '' : undefined, reduced: reduced ? '' : undefined });
export function OrcaLoader({variant='orbit',size=32,label='Loading',showLabel=false,paused,reduced,className,style}: Shared & {variant?:'orbit'|'breathe'|'resolve';showLabel?:boolean}) {
  return createElement('orca-loader', {variant,size:String(size),label,'show-label':showLabel?'':undefined,...flags(paused,reduced),class:className,style});
}
export function OrcaPhaseIndicator({phase,size=32,label,paused,reduced,className,style}: Shared & {phase:Phase}) {
  return createElement('orca-phase', {phase,size:String(size),label,...flags(paused,reduced),class:className,style});
}
export function OrcaLogoReveal({width=320,label='ORCA by IssueLab',paused,reduced,className,style}: Omit<Shared,'size'> & {width?:number}) {
  return createElement('orca-reveal', {width:String(width),label,...flags(paused,reduced),class:className,style});
}
export function OrcaComplete({size=48,label='Action completed',paused,reduced,className,style}: Shared) {
  return createElement('orca-settle', {size:String(size),label,...flags(paused,reduced),class:className,style});
}
