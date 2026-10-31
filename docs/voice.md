# Talking to ORCA (voice)

The Chat panel's mic sends what you say to ORCA as a chat message, so voice can do anything chat can, filters
included ("colour the services by system", "isolate the ducts on Level 02": [filters.md](filters.md)). Recognition is
Muse Voice Transcribe (`muse-voice-transcribe-1.0`). Muse has no text-to-speech (checked Oct 28: no such model in
`/v1/models`, and chat completions refuse `audio`), so ORCA answers in text.

Code:
- `server/sightline/voice_live.py`: the relay to Meta's realtime socket;
- `/api/voice/live` and `/api/transcribe` in `app.py`;
- `web/src/voice.ts`: `LiveVoice` (live) and `VoiceRecorder` (the upload fallback);
- `web/src/Chat.tsx`: the mic, the hands-free toggle, captions and the sentence queue.

## Using it

- **Hold to talk** (the default): hold the mic and speak. The words appear in the message box as you say them, and
  the message goes when you let go. A quick tap (under 300 ms) keeps the mic open; the next press sends. Space or Enter
  held on the focused mic works the same.
- **Hands-free** (the toggle beside the mic, remembered per browser): press the mic once, then just talk. Each
  sentence goes when you pause; sentences said while ORCA is still answering wait their turn ("Next: …"). The mic
  closes on a press, after 2 minutes, after 30 s without speech, or when the tab is hidden. A single word is not sent
  (a cough, an "um").
- The status line sits above the message box, so the mic doesn't move under your finger.

## How it works

Meta reads the API key from the first frame of the stream, not a header, so the browser cannot connect itself: the
server relays.

```
mic → AudioWorklet (16 kHz, 16-bit, 80 ms frames) → /api/voice/live → wss://api.meta.ai/v1/asr/realtime
                         words in the box ← partial / final ←
```

**Browser → ORCA:** one JSON frame `{mode: "hold" | "hands_free", report_id}`, binary audio frames, then
`{"type": "end"}`. The worklet averages the microphone down to 16 kHz itself; Firefox refuses to connect a microphone
to a 16 kHz AudioContext. The mic starts while the socket connects, and up to 1.5 s of early audio is sent at once when
it is ready, so the first words are not lost.

**ORCA → Meta:** the handshake `{authorization: {accessToken: "Bearer <key>"}, audioEncoding: "PCM_16KHZ", model,
mode, partialMode: "CUMULATIVE", emitAudioProgress: false, languageBias: ["English"], keywords}`; then the audio, at
most 1.5 s ahead of the clock; then `{"type": "endStream"}`. Hold uses `PUSH_TO_TALK`, hands-free `ENDPOINTING`
(DIARIZATION invented " Yeah " from silence, and one speaker needs no labels). Keywords are BIM words plus the open
report's element names and titles, as for the upload path.

**ORCA → browser:** `ready {max_s}`, `partial {text}` (the current sentence so far), `final {text, turn}` (hold: once,
at the end; hands-free: each sentence, from Meta's `speechComplete`), `speech {on}`, `limit`, `error {detail}`, then the
socket closes. Meta's close codes become words: 1008 refused, 1011 a problem (or the longest session), 1013 busy.

**Limits:** one session counts as one voice message against `SIGHTLINE_VOICE_PER_HOUR` / `DAY` (hands-free too); the
owner has none. Hold runs up to 60 s, hands-free `SIGHTLINE_VOICE_LIVE_MAX_S` (120 s). Frames over 32 KB are refused.
A page on another origin cannot open the socket (its `Origin` must match `Host`), so other sites can't spend the Meta
budget through a visitor's browser. The owner cookie reaches the socket through `_OwnerContext`.

**Fallback:** if the socket can't open or isn't ready within 8 s, hold to talk records a clip instead (tap to stop),
which goes to `POST /api/transcribe` as before. Hands-free needs the live socket.

**Dev:** Vite proxies `/api` with `ws: true` and keeps the Host header, so the origin check passes on `localhost:5173`.

## Measured (Oct 29, from the cloud session)

- The realtime socket acks in 0.8-1.4 s.
- Speech made with espeak-ng (robotic, 22 kHz, resampled), sent at real time through `/api/voice/live`:
  - hold: first partial at 1.1 s, final 0.13 s after the end: "rain the supply air duct four hundred millimeters
    through the girder opening." ("raise" read as "rain" is the espeak voice);
  - hands-free: two sentences, each final at the pause, 0 ms after `speechEnd`.
- Keywords matter: straight to Meta without them, the same audio read "supply adequate"; with them, "supply air duct".
- Bursts: Meta takes 0.5-3 s of audio sent at once cleanly (final after 0.13-0.18 s); 5 s came back garbled ("through
  the millimeters through"). Hence the 1.5 s allowance.
- In Chromium with the speech as a fake microphone (Playwright, chat stubbed):
  - hold: captions grow while held, final 0.27 s after release, sent with the mic badge;
  - quick tap: latches, the second press sends;
  - hands-free: six sentences sent in order while each reply took 2.5 s, and a press closes it;
  - with the socket blocked: the upload path transcribes and sends.
- On Modal (deployed Oct 29): the edge passes the WebSocket through without holding anything back. The same espeak
  speech through `wss://…modal.run/api/voice/live`: ready, first partial at 1.5 s, final 0.5 s after the end; hands-free
  sentences each at their pause. A connection from another origin is refused (HTTP 403). In Chromium against the live
  URL, tap, captions and send all work.
- Not yet checked: a real human voice and a real microphone.
