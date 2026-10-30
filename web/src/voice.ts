/**
 * Talking to ORCA with Muse Voice Transcribe.
 *
 * `LiveVoice` (the default): the microphone streams to `/api/voice/live` (server/sightline/voice_live.py), which relays
 * it to Muse Voice Transcribe's realtime socket, and the words come back while they are said. Hold to talk sends one
 * message on release; hands-free sends each sentence when the speaker pauses.
 *
 * `VoiceRecorder` (the fallback when the socket can't open): records a clip in the browser's own format (webm/opus or
 * mp4), then decodes, mixes down and resamples to 16 kHz mono WAV for `POST /api/transcribe`.
 */

export const MAX_SECONDS = 60;
const RATE = 16000;
const FRAME_SAMPLES = 1280;  // 80 ms at 16 kHz
const EARLY_FRAMES = 18;  // ~1.5 s heard while the socket connects, sent at once when it is ready (the server allows that)

export type VoiceMode = "hold" | "hands_free";
export interface LiveHandlers {
  onPartial: (text: string) => void;
  onFinal: (text: string) => void;
  onSpeech?: (on: boolean) => void;
  onLimit?: () => void;
  onError: (detail: string) => void;
  onEnd: () => void;
  onLevel: (level: number) => void;
}

/** Why a live session didn't start: no microphone, the browser said no, or the socket (then use VoiceRecorder). */
export class LiveVoiceError extends Error {
  constructor(message: string, readonly kind: "denied" | "no_mic" | "fallback" | "refused") { super(message); }
}

// Runs on the audio thread: averages the microphone down to 16 kHz (a box low-pass, enough for speech), converts to
// 16-bit and posts 80 ms frames. Resampling here, not with a 16 kHz AudioContext, because Firefox refuses to connect a
// microphone to a context at another rate.
const WORKLET = `
class OrcaPcm16k extends AudioWorkletProcessor {
  constructor() { super(); this.step = sampleRate / ${RATE}; this.pos = 0; this.acc = 0; this.n = 0; this.out = new Int16Array(${FRAME_SAMPLES}); this.i = 0; }
  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (!ch) return true;
    for (let k = 0; k < ch.length; k++) {
      this.acc += ch[k]; this.n++; this.pos++;
      if (this.pos < this.step) continue;
      this.pos -= this.step;
      const v = this.acc / this.n; this.acc = 0; this.n = 0;
      this.out[this.i++] = Math.max(-1, Math.min(1, v)) * 0x7fff;
      if (this.i === this.out.length) { this.port.postMessage(this.out.buffer, [this.out.buffer]); this.out = new Int16Array(${FRAME_SAMPLES}); this.i = 0; }
    }
    return true;
  }
}
registerProcessor("orca-pcm16k", OrcaPcm16k);
`;
let workletUrl: string | null = null;

function micConstraints(): MediaStreamConstraints {
  return { audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true } };
}

function micError(e: unknown): LiveVoiceError {
  const name = (e as Error)?.name;
  return name === "NotAllowedError" || name === "SecurityError"
    ? new LiveVoiceError("Microphone access was blocked. Allow it in the browser to talk to ORCA.", "denied")
    : new LiveVoiceError("No microphone found.", "no_mic");
}

/** The input level (0-1) every animation frame, from an analyser on the microphone. */
function meter(ctx: AudioContext, source: MediaStreamAudioSourceNode, onLevel: (level: number) => void) {
  const analyser = ctx.createAnalyser();
  analyser.fftSize = 512;
  source.connect(analyser);
  const buf = new Float32Array(analyser.fftSize);
  let raf = 0;
  const tick = () => {
    analyser.getFloatTimeDomainData(buf);
    let sum = 0;
    for (const v of buf) sum += v * v;
    onLevel(Math.min(1, Math.sqrt(sum / buf.length) * 4));
    raf = requestAnimationFrame(tick);
  };
  raf = requestAnimationFrame(tick);
  return () => cancelAnimationFrame(raf);
}

/** One live voice session: start, then `finish` (hold: the user let go) or `cancel`. */
export class LiveVoice {
  private socket: WebSocket | null = null;
  private stream: MediaStream | null = null;
  private ctx: AudioContext | null = null;
  private stopMeter: (() => void) | null = null;
  private early: ArrayBuffer[] = [];
  private ready = false;  // the server said ready: its events are the session's
  private streaming = false;  // the early audio has gone: new frames go straight out, in order
  private over = false;

  static supported() {
    return typeof navigator !== "undefined" && !!navigator.mediaDevices?.getUserMedia &&
      typeof AudioWorkletNode !== "undefined" && typeof WebSocket !== "undefined";
  }

  /** Ask for the microphone and open the session; resolves once the words can flow. The microphone starts at once,
   * so what is said while the socket connects is kept and sent when it is ready. */
  async start(mode: VoiceMode, reportId: string | null, on: LiveHandlers, sceneId: string | null = null): Promise<void> {
    const mic = navigator.mediaDevices.getUserMedia(micConstraints());
    mic.catch(() => undefined);  // handled below; this only stops an unhandled rejection while the socket opens
    const scheme = location.protocol === "https:" ? "wss:" : "ws:";
    const socket = new WebSocket(`${scheme}//${location.host}/api/voice/live`);
    socket.binaryType = "arraybuffer";
    this.socket = socket;
    const opened = new Promise<void>((resolve, reject) => {
      let refusal: string | null = null;
      const timer = setTimeout(() => reject(new LiveVoiceError("The voice connection timed out.", "fallback")), 8000);
      socket.onopen = () => socket.send(JSON.stringify({ mode, report_id: reportId, scene_id: sceneId }));
      socket.onmessage = (m) => {
        const e = JSON.parse(String(m.data));
        if (!this.ready) {
          if (e.type === "ready") { this.ready = true; clearTimeout(timer); resolve(); }
          else if (e.type === "error") refusal = e.detail;
          return;
        }
        if (e.type === "partial") on.onPartial(e.text);
        else if (e.type === "final") on.onFinal(e.text);
        else if (e.type === "speech") on.onSpeech?.(e.on);
        else if (e.type === "limit") on.onLimit?.();
        else if (e.type === "error") on.onError(e.detail);
      };
      socket.onclose = () => {
        clearTimeout(timer);
        if (!this.ready) {
          reject(refusal ? new LiveVoiceError(refusal, "refused") : new LiveVoiceError("Live voice is unavailable.", "fallback"));
        } else if (!this.over) {
          this.over = true;
          this.release();
          on.onEnd();
        }
      };
    });
    opened.catch(() => undefined);  // awaited below; this only stops an unhandled rejection while the mic starts
    try {
      this.stream = await mic;
    } catch (e) {
      this.cancel();
      throw micError(e);
    }
    try {
      await this.listen(on.onLevel);
      await opened;
    } catch (e) {
      this.cancel();
      throw e instanceof LiveVoiceError ? e : new LiveVoiceError("Live voice is unavailable.", "fallback");
    }
    for (const f of this.early) socket.send(f);
    this.early = [];
    this.streaming = true;
  }

  private async listen(onLevel: (level: number) => void) {
    const ctx = new AudioContext();
    this.ctx = ctx;
    workletUrl ??= URL.createObjectURL(new Blob([WORKLET], { type: "text/javascript" }));
    await ctx.audioWorklet.addModule(workletUrl);
    const source = ctx.createMediaStreamSource(this.stream!);
    const pcm = new AudioWorkletNode(ctx, "orca-pcm16k");
    pcm.port.onmessage = (m: MessageEvent<ArrayBuffer>) => {
      if (this.over) return;
      if (this.streaming) { if (this.socket?.readyState === WebSocket.OPEN) this.socket.send(m.data); }
      else { this.early.push(m.data); if (this.early.length > EARLY_FRAMES) this.early.shift(); }
    };
    const mute = ctx.createGain();
    mute.gain.value = 0;  // the worklet runs only when pulled by the destination; nothing is heard
    source.connect(pcm).connect(mute).connect(ctx.destination);
    this.stopMeter = meter(ctx, source, onLevel);
    if (ctx.state === "suspended") await ctx.resume();
  }

  /** Stop the microphone and ask for the last words; `onFinal` and `onEnd` follow. */
  finish() {
    if (this.over) return;
    this.release();
    if (this.socket?.readyState === WebSocket.OPEN) this.socket.send(JSON.stringify({ type: "end" }));
  }

  /** Stop without keeping anything (the user cancelled, or the panel closed). */
  cancel() {
    this.over = true;
    this.release();
    try { this.socket?.close(); } catch { /* already closed */ }
    this.socket = null;
  }

  private release() {
    this.stopMeter?.();
    this.stopMeter = null;
    if (this.ctx) { void this.ctx.close(); this.ctx = null; }
    this.stream?.getTracks().forEach((t) => t.stop());
    this.stream = null;
  }
}

export class VoiceRecorder {
  private stream: MediaStream | null = null;
  private recorder: MediaRecorder | null = null;
  private chunks: Blob[] = [];
  private meter: { ctx: AudioContext; stop: () => void } | null = null;

  static supported() {
    return typeof navigator !== "undefined" && !!navigator.mediaDevices?.getUserMedia && typeof MediaRecorder !== "undefined";
  }

  /** Ask for the microphone and start recording; `onLevel` hears the input level (0-1) every frame. */
  async start(onLevel: (level: number) => void) {
    try {
      this.stream = await navigator.mediaDevices.getUserMedia(micConstraints());
    } catch (e) {
      throw micError(e);
    }
    this.chunks = [];
    this.recorder = new MediaRecorder(this.stream);
    this.recorder.ondataavailable = (e) => { if (e.data.size) this.chunks.push(e.data); };
    this.recorder.start(250);
    const ctx = new AudioContext();
    this.meter = { ctx, stop: meter(ctx, ctx.createMediaStreamSource(this.stream), onLevel) };
  }

  /** Stop and return the recording as a 16 kHz mono WAV. */
  async stop(): Promise<Blob> {
    const recorder = this.recorder;
    if (!recorder) throw new Error("Not recording.");
    const done = new Promise<void>((resolve) => { recorder.onstop = () => resolve(); });
    recorder.stop();
    await done;
    const blob = new Blob(this.chunks, { type: recorder.mimeType });
    this.release();
    return toWav(blob);
  }

  /** Stop without keeping anything (the user cancelled, or the panel closed). */
  cancel() {
    try { this.recorder?.stop(); } catch { /* already stopped */ }
    this.release();
  }

  private release() {
    if (this.meter) {
      this.meter.stop();
      void this.meter.ctx.close();
      this.meter = null;
    }
    this.stream?.getTracks().forEach((t) => t.stop());
    this.stream = null;
    this.recorder = null;
  }
}

async function toWav(recording: Blob): Promise<Blob> {
  const decoder = new AudioContext();
  let audio: AudioBuffer;
  try {
    audio = await decoder.decodeAudioData(await recording.arrayBuffer());
  } finally {
    void decoder.close();
  }
  // Mix to mono and resample in one offline render.
  const offline = new OfflineAudioContext(1, Math.max(1, Math.ceil(audio.duration * RATE)), RATE);
  const source = offline.createBufferSource();
  source.buffer = audio;
  source.connect(offline.destination);
  source.start();
  const pcm = (await offline.startRendering()).getChannelData(0);

  const out = new DataView(new ArrayBuffer(44 + pcm.length * 2));
  const text = (at: number, s: string) => { for (let i = 0; i < s.length; i++) out.setUint8(at + i, s.charCodeAt(i)); };
  text(0, "RIFF"); out.setUint32(4, 36 + pcm.length * 2, true); text(8, "WAVE");
  text(12, "fmt "); out.setUint32(16, 16, true); out.setUint16(20, 1, true); out.setUint16(22, 1, true);
  out.setUint32(24, RATE, true); out.setUint32(28, RATE * 2, true); out.setUint16(32, 2, true); out.setUint16(34, 16, true);
  text(36, "data"); out.setUint32(40, pcm.length * 2, true);
  for (let i = 0; i < pcm.length; i++) out.setInt16(44 + i * 2, Math.max(-1, Math.min(1, pcm[i])) * 0x7fff, true);
  return new Blob([out.buffer], { type: "audio/wav" });
}
