const SAMPLE_RATE = 16_000;

export interface Recording {
  /** Stop and get the clip as base64 16 kHz, 16-bit, mono PCM. */
  stop(): Promise<string>;
  cancel(): void;
}

/** Start recording from the microphone. Rejects if access is refused. */
export async function startRecording(): Promise<Recording> {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  const recorder = new MediaRecorder(stream);
  const chunks: Blob[] = [];
  recorder.ondataavailable = (e) => chunks.push(e.data);
  recorder.start();

  const release = () => stream.getTracks().forEach((t) => t.stop());
  return {
    cancel: () => {
      recorder.stop();
      release();
    },
    stop: () =>
      new Promise((resolve, reject) => {
        recorder.onstop = () => {
          release();
          toPcm(new Blob(chunks, { type: recorder.mimeType })).then(resolve, reject);
        };
        recorder.stop();
      }),
  };
}

/** Decode whatever the browser recorded and resample it to what the speech service takes. */
async function toPcm(blob: Blob): Promise<string> {
  const decoder = new AudioContext();
  const decoded = await decoder.decodeAudioData(await blob.arrayBuffer());
  void decoder.close();

  const offline = new OfflineAudioContext(1, Math.ceil(decoded.duration * SAMPLE_RATE), SAMPLE_RATE);
  const source = offline.createBufferSource();
  source.buffer = decoded;
  source.connect(offline.destination);
  source.start();
  const samples = (await offline.startRendering()).getChannelData(0);

  const pcm = new Int16Array(samples.length);
  for (let i = 0; i < samples.length; i++) {
    pcm[i] = Math.max(-1, Math.min(1, samples[i])) * 0x7fff;
  }
  const bytes = new Uint8Array(pcm.buffer);
  let binary = "";
  for (let i = 0; i < bytes.length; i += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  }
  return btoa(binary);
}
