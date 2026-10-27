/**
 * Push-to-talk recording for Muse Voice Transcribe, which takes mono 16-bit PCM WAV at 16 kHz. The browser records in
 * its own format (webm/opus or mp4), then decodes, mixes down and resamples to 16 kHz, and writes the WAV itself.
 */

export const MAX_SECONDS = 60;
const RATE = 16000;

export class VoiceRecorder {
  private stream: MediaStream | null = null;
  private recorder: MediaRecorder | null = null;
  private chunks: Blob[] = [];
  private meter: { ctx: AudioContext; analyser: AnalyserNode; raf: number } | null = null;

  static supported() {
    return typeof navigator !== "undefined" && !!navigator.mediaDevices?.getUserMedia && typeof MediaRecorder !== "undefined";
  }

  /** Ask for the microphone and start recording; `onLevel` hears the input level (0-1) every frame. */
  async start(onLevel: (level: number) => void) {
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    this.chunks = [];
    this.recorder = new MediaRecorder(this.stream);
    this.recorder.ondataavailable = (e) => { if (e.data.size) this.chunks.push(e.data); };
    this.recorder.start(250);

    const ctx = new AudioContext();
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 512;
    ctx.createMediaStreamSource(this.stream).connect(analyser);
    const buf = new Float32Array(analyser.fftSize);
    const tick = () => {
      analyser.getFloatTimeDomainData(buf);
      let sum = 0;
      for (const v of buf) sum += v * v;
      onLevel(Math.min(1, Math.sqrt(sum / buf.length) * 4));
      if (this.meter) this.meter.raf = requestAnimationFrame(tick);
    };
    this.meter = { ctx, analyser, raf: requestAnimationFrame(tick) };
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
      cancelAnimationFrame(this.meter.raf);
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
