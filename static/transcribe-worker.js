// Only local File -> local decoded PCM -> local Whisper. No uploads or telemetry.
let working = false;
const RATE = 16000, WINDOW_SECONDS = 30, WINDOW_SAMPLES = RATE * WINDOW_SECONDS;
function send(type, value = {}) { self.postMessage({type, ...value}); }

self.onmessage = async event => {
  if (working || event.data.type !== 'transcribe') return;
  working = true;
  let input;
  let stage = 'capability_check';
  try {
    send('stage', {stage});
    if (!self.isSecureContext) throw new Error('A secure context is required: use HTTPS or localhost.');
    if (!('AudioDecoder' in self)) throw new Error('WebCodecs AudioDecoder is unavailable. Use an up-to-date desktop Chrome or Edge browser.');
    if (event.data.device === 'webgpu' && !self.navigator.gpu) throw new Error('WebGPU is unavailable. Select CPU / WASM instead.');
    if (event.data.device === 'webgpu' && !(await self.navigator.gpu.requestAdapter())) throw new Error('WebGPU adapter unavailable. Select CPU / WASM instead.');
    send('progress', {message: 'Loading pinned local decoding and inference libraries…', percent: 0});
    stage = 'library_import';
    send('stage', {stage});
    const [{Input, BlobSource, ALL_FORMATS, AudioSampleSink}, {pipeline, env}] = await Promise.all([
      import('/vendor/mediabunny.mjs'), import('/vendor/transformers.bundle.js')]);
    env.allowRemoteModels = false;
    env.allowLocalModels = true;
    env.localModelPath = '/models/';
    env.useBrowserCache = false;
    env.backends.onnx.wasm.wasmPaths = '/vendor/';
    env.backends.onnx.wasm.numThreads = 1;
    // No model or runtime request leaves this origin during private processing.
    stage = 'media_metadata';
    send('stage', {stage});
    input = new Input({source: new BlobSource(event.data.file), formats: ALL_FORMATS});
    const track = await input.getPrimaryAudioTrack();
    if (!track) throw new Error('The selected recording has no readable audio track.');
    if (!(await track.canDecode())) throw new Error('This browser cannot decode the recording audio codec. Convert locally to MP4 with AAC, or use a newer desktop Chrome/Edge.');
    const duration = await input.computeDuration();
    if (!Number.isFinite(duration) || duration <= 0 || duration > 14400) throw new Error('Supported recording duration is greater than zero and at most four hours.');
    send('metadata', {duration});
    send('progress', {message: 'Loading local Whisper tiny model (first use may take a moment)…', percent: 1});
    stage = 'model_load';
    send('stage', {stage});
    const transcriber = await pipeline('automatic-speech-recognition', 'Xenova/whisper-tiny', {
      device: event.data.device || 'wasm', dtype: 'q8',
      progress_callback: data => {
        if (data.status === 'progress') send('progress', {message:'Loading local model weights…', percent:1});
      },
    });
    send('ready');
    stage = 'audio_decode';
    send('stage', {stage});
    const sink = new AudioSampleSink(track);
    let waveform = new Float32Array(WINDOW_SAMPLES), windowStart = 0, filled = 0, count = 0;
    let lastSampleEnd = 0;
    async function flush(final = false) {
      const samples = final ? filled : WINDOW_SAMPLES;
      if (!samples) return;
      let energy = 0;
      for (let i = 0; i < samples; i++) energy += waveform[i] * waveform[i];
      const end = Math.min(duration, windowStart + samples / RATE);
      if (Math.sqrt(energy / samples) > 0.0001) {
        const options = {return_timestamps:true, task:'transcribe', chunk_length_s:30, stride_length_s:0};
        if (event.data.language && event.data.language !== 'auto') options.language = event.data.language;
        stage = 'local_inference';
        send('stage', {stage});
        const output = await transcriber(final ? waveform.subarray(0, samples) : waveform, options);
        stage = 'audio_decode';
        send('stage', {stage});
        const chunks = output.chunks || [];
        if (!chunks.length && output.text?.trim()) {
          send('chunk', {segments:[{start:windowStart, end, text:output.text.trim(), speaker:null}], approximate:true});
        } else {
          const segments = [];
          for (const chunk of chunks) {
            if (!chunk.text?.trim()) continue;
            const start = windowStart + Math.max(0, chunk.timestamp?.[0] ?? 0);
            const finish = Math.min(end, windowStart + (chunk.timestamp?.[1] ?? samples / RATE));
            if (finish > start) segments.push({start:+start.toFixed(3), end:+finish.toFixed(3), text:chunk.text.trim(), speaker:null});
          }
          send('chunk', {segments, approximate:false});
        }
      }
      count++;
      send('progress', {message:`Transcribed ${count} local audio window(s).`, percent:Math.min(99, end / duration * 100)});
      waveform.fill(0); filled = 0;
    }
    for await (const sample of sink.samples()) {
      try {
        if (sample.numberOfChannels > 8 || sample.numberOfFrames > 2_000_000) throw new Error('Audio frame exceeds the bounded decoding limit.');
        const mono = new Float32Array(sample.numberOfFrames);
        const channel = new Float32Array(sample.numberOfFrames);
        for (let c = 0; c < sample.numberOfChannels; c++) {
          sample.copyTo(channel, {format:'f32-planar', planeIndex:c});
          for (let i = 0; i < mono.length; i++) mono[i] += channel[i] / sample.numberOfChannels;
        }
        const sampleEnd = sample.timestamp + sample.numberOfFrames / sample.sampleRate;
        if (sample.timestamp > lastSampleEnd + 0.25) send('gap', {seconds:sample.timestamp-lastSampleEnd});
        lastSampleEnd = Math.max(lastSampleEnd, sampleEnd);
        const first = Math.max(0, Math.ceil(sample.timestamp * RATE));
        const last = Math.min(Math.ceil(duration * RATE), Math.ceil(sampleEnd * RATE));
        for (let absolute = first; absolute < last; absolute++) {
          while (absolute >= Math.round((windowStart + WINDOW_SECONDS) * RATE)) {
            await flush(); windowStart += WINDOW_SECONDS;
          }
          const local = absolute / RATE - sample.timestamp;
          const position = Math.max(0, local * sample.sampleRate), left = Math.min(mono.length - 1, Math.floor(position));
          const right = Math.min(mono.length - 1, left + 1), fraction = position - left;
          const index = absolute - Math.round(windowStart * RATE);
          if (index >= 0 && index < WINDOW_SAMPLES) {
            waveform[index] = mono[left] * (1 - fraction) + mono[right] * fraction;
            filled = Math.max(filled, index + 1);
          }
        }
      } finally { sample.close(); }
    }
    await flush(true);
    waveform.fill(0);
    await transcriber.dispose();
    send('complete', {duration, windows:count});
  } catch (error) {
    // Do not emit library stack traces, filenames, or inferred transcript text.
    const known = /secure context|WebCodecs|WebGPU|audio track|cannot decode|Supported recording|bounded decoding/.test(error.message || '');
    send('error', {message:known ? error.message : `Local transcription failed: stage ${stage}. ${event.data.syntheticDiagnostic ? String(error.message).slice(0,1500) : 'Verify local model/runtime assets and use current desktop Chrome/Edge.'} No media was uploaded.`});
  } finally {
    input?.dispose();
    working = false;
  }
};
