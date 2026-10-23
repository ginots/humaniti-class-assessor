import {parseVtt, redactSegments, validateReviewed, makePayload, formatTime} from '/privacy.js';

const $ = id => document.getElementById(id);
let originalSegments = [], worker = null, recordingURL = null, report = null, busy = false;
let transcriptionComplete = false;
let revision = 0, transcriptionHasGaps = false, approximateTimestamps = false;
function status(id, message, error = false) { $(id).textContent = message; $(id).classList.toggle('error', error); }
function workerErrorType(error) {
  // Never display arbitrary error text: it could contain private input.
  return /\b(?:SyntaxError|TypeError|ReferenceError|CompileError|LinkError|RuntimeError|SecurityError|NetworkError|AbortError)\b/.exec(error?.name || error?.message || '')?.[0] || 'WorkerError';
}
async function checkWorkerScript() {
  let response;
  try { response = await fetch('/transcribe-worker.js', {cache:'no-store', signal:AbortSignal.timeout(4000)}); }
  catch {
    try {
      const health = await fetch('/api/health', {cache:'no-store', signal:AbortSignal.timeout(3000)});
      if (health.ok) return 'The local server is reachable, but the worker script could not be fetched. Check Network/CSP restrictions for /transcribe-worker.js.';
    } catch { }
    return 'Local server is unreachable. Run scripts\\start.ps1, then refresh this page. VTT import works independently of the worker.';
  }
  if (!response.ok) return `Worker script returned HTTP ${response.status}. Restart the local server and refresh this page.`;
  if (!/(?:javascript|ecmascript)/i.test(response.headers.get('Content-Type') || '')) return 'Worker script has an invalid JavaScript MIME type. Check the local server response.';
  try { await response.text(); } // Consume only the small public script, never recording data.
  catch { return 'Worker script download was interrupted. Restart the local server and refresh this page.'; }
  return null;
}
function invalidate() { revision++; clearReport(); $('confirm').checked = false; $('assess').disabled = true; refreshPayload(); }
function clearReport() { report = null; $('reportPanel').hidden = true; $('report').replaceChildren(); }
function editedSegments() { return validateReviewed(JSON.parse($('review').value), $('terms').value); }
function payload() {
  const duration = $('duration').value ? Number($('duration').value) : null;
  return makePayload(editedSegments(), {kind:$('coverage').value, duration_seconds:duration}, $('speakers').checked);
}
function refreshPayload() {
  try {
    const value = payload();
    $('payloadPreview').textContent = JSON.stringify(value, null, 2);
    $('assess').disabled = !$('confirm').checked || busy;
  } catch {
    $('payloadPreview').textContent = 'Fix segment formatting or remaining identifiers before preparing a payload.';
    $('assess').disabled = true;
  }
}
function redact() {
  try {
    if (!originalSegments.length) throw new Error('Import a VTT or complete local transcription first.');
    const redacted = redactSegments(originalSegments, $('terms').value);
    $('review').value = JSON.stringify(redacted.segments, null, 2);
    status('redactionStatus', `${redacted.changes} local replacement(s); ${redacted.detectedTerms} supplied/detected term(s). Review all text and indirect identifiers. Applying replacements again resets manual edits.`);
    $('speakers').checked = false;
    invalidate(); clearReport();
  } catch (error) { status('redactionStatus', error.message, true); }
}
function setInput(segments, description) {
  if (recordingURL) URL.revokeObjectURL(recordingURL);
  recordingURL = null; $('preview').hidden = true; $('preview').removeAttribute('src');
  originalSegments = segments;
  $('coverage').value = 'unknown'; $('duration').value = '';
  $('review').value = ''; $('terms').value = ''; transcriptionComplete = true;
  clearReport(); invalidate();
  status('localStatus', description);
  redact();
}

$('video').addEventListener('change', () => {
  originalSegments = []; $('review').value = ''; $('duration').value = ''; $('coverage').value = 'unknown';
  if (recordingURL) URL.revokeObjectURL(recordingURL);
  recordingURL = null; $('preview').hidden = true; $('preview').removeAttribute('src');
  invalidate(); status('localStatus', 'New local recording selected. Transcribe it before review or assessment.');
});

$('vtt').addEventListener('change', async () => {
  try {
    const file = $('vtt').files[0]; if (!file) return;
    if (file.size > 3_000_000) throw new Error('VTT exceeds the 3 MB limit.');
    const parsed = parseVtt(await file.text());
    setInput(parsed.segments, `Imported ${parsed.segments.length} timed segments locally. ${parsed.speakerCount} explicit voice label(s); review speaker reliability. Caption end: ${formatTime(Math.max(...parsed.segments.map(s => s.end)))}. Recording duration remains unknown.`);
    if (recordingURL) URL.revokeObjectURL(recordingURL);
    recordingURL = null; $('preview').hidden = true; $('preview').removeAttribute('src');
  } catch (error) { status('localStatus', error.message, true); }
});

async function transcribe(file, syntheticDiagnostic = false) {
  if (busy) return;
  if (!file) { status('localStatus', 'Select an MP4 first.', true); return; }
  if (file.size > 2 * 1024 ** 3) { status('localStatus', 'File exceeds the 2 GiB limit.', true); return; }
  if (!window.isSecureContext || !window.Worker || !window.WebAssembly) {
    status('localStatus', 'Use HTTPS or localhost in current desktop Chrome/Edge with Workers, WebAssembly, and WebCodecs enabled.', true); return;
  }
  busy = true; $('transcribe').disabled = true;
  status('localStatus', 'Checking local transcription worker availability…');
  const startupFailure = await checkWorkerScript();
  if (startupFailure) {
    busy = false; $('transcribe').disabled = false; refreshPayload();
    status('localStatus', `Transcription failed at worker_script_load: ${startupFailure} No media was uploaded.`, true);
    return;
  }
  originalSegments = []; transcriptionComplete = false;
  transcriptionHasGaps = false; approximateTimestamps = false;
  $('review').value = ''; $('terms').value = ''; $('coverage').value = 'partial';
  clearReport(); invalidate();
  if (recordingURL) URL.revokeObjectURL(recordingURL);
  recordingURL = URL.createObjectURL(file); $('preview').src = recordingURL; $('preview').hidden = false;
  busy = true; $('transcribe').disabled = true; $('cancel').disabled = false; $('vtt').disabled = true; $('video').disabled = true;
  $('synthetic').disabled = true; $('videoTest').disabled = true; $('progress').value = 0;
  let workerStage = 'worker_script_load';
  const finish = () => {
    worker?.terminate(); worker = null; busy = false;
    $('transcribe').disabled = false; $('cancel').disabled = true; $('vtt').disabled = false; $('video').disabled = false;
    $('synthetic').disabled = false; $('videoTest').disabled = false;
  };
  try { worker = new Worker('/transcribe-worker.js', {type:'module'}); }
  catch (error) {
    finish();
    status('localStatus', `Transcription failed at worker_construction (${workerErrorType(error)}). Check browser worker/CSP support. No media was uploaded.`, true);
    return;
  }
  worker.onmessage = ({data}) => {
    if (data.type === 'stage') workerStage = data.stage;
    if (data.type === 'progress') { status('localStatus', data.message); $('progress').value = data.percent; }
    if (data.type === 'metadata') $('duration').value = data.duration.toFixed(3);
    if (data.type === 'gap') { transcriptionHasGaps = true; status('localStatus', 'An audio gap was detected. Review coverage and timestamps carefully.'); }
    if (data.type === 'chunk') {
      approximateTimestamps ||= data.approximate;
      originalSegments.push(...data.segments);
      status('localStatus', `${originalSegments.length} timestamped segment(s) generated locally. No speaker diarization. Whisper can hallucinate; review every segment.`);
    }
    if (data.type === 'complete') {
      finish(); transcriptionComplete = true; $('progress').value = 100;
      $('coverage').value = transcriptionHasGaps ? 'partial' : 'complete';
      if (!originalSegments.length) { status('localStatus', 'No usable speech detected. No assessment can be created.', true); return; }
      status('localStatus', `Local transcription complete: ${originalSegments.length} segment(s), ${data.windows} bounded audio window(s), recording duration ${formatTime(data.duration)}. ${transcriptionHasGaps ? 'Audio gaps detected; coverage marked partial. ' : ''}${approximateTimestamps ? 'Some timestamps cover approximate windows. ' : ''}No media left this device.`);
      redact();
    }
    if (data.type === 'error') { finish(); status('localStatus', data.message, true); }
  };
  worker.onerror = async event => {
    const failedStage = workerStage, errorType = workerErrorType(event);
    finish();
    const unavailable = await checkWorkerScript();
    status('localStatus', `Transcription failed at ${failedStage} (${errorType}). ${unavailable || 'The server and worker URL are reachable; inspect browser Console for a worker/runtime or CSP failure.'} No media was uploaded.`, true);
  };
  worker.postMessage({type:'transcribe', file, language:$('language').value, device:$('device').value, syntheticDiagnostic});
}
$('transcribe').onclick = () => transcribe($('video').files[0]);
$('cancel').onclick = () => {
  worker?.terminate(); worker = null; busy = false; originalSegments = []; $('review').value = '';
  $('transcribe').disabled = false; $('cancel').disabled = true; $('vtt').disabled = false; $('video').disabled = false;
  $('synthetic').disabled = false; $('videoTest').disabled = false;
  invalidate(); status('localStatus', 'Cancelled. Partial transcription discarded. No media was sent.');
};
$('videoTest').onclick = async () => {
  try {
    const response = await fetch('/synthetic-test.mp4', {cache:'no-store'});
    if (!response.ok) throw new Error('Synthetic video fixture is missing. Generate it with the local test-fixture script.');
    await transcribe(new File([await response.blob()], 'synthetic.mp4', {type:'video/mp4'}), true);
  } catch (error) { status('localStatus', error.message, true); }
};

const SYNTHETIC = [
  [0,12,'Welcome to our practice class. Today we will compare fractions using the same whole. You can introduce yourself if this is your first session.'],
  [12,24,'Before we begin, what does the denominator tell us? Take a moment and explain your thinking rather than just giving a number.'],
  [24,33,'SPEAKER_2: I think it tells us how many equal pieces make one whole, but I am unsure whether the pieces must be equal.'],
  [33,47,'SPEAKER_1: Yes, equal pieces are essential. Imagine cutting the same rectangle into four equal sections. Each section is one quarter. Let us draw that example together.'],
  [47,60,'SPEAKER_1: Now compare one half and one quarter. Show your reasoning on a number line. Everyone has thirty seconds to try before we discuss.'],
  [60,70,'SPEAKER_3: I thought one quarter was larger because four is bigger than two.'],
  [70,85,'SPEAKER_1: Thank you for explaining your reasoning. Let us use two identical rectangles. With more equal pieces, each piece gets smaller. Can you revise your answer?'],
  [85,96,'SPEAKER_3: One half is larger when the whole is the same. I see that four equal pieces each contain less than two equal pieces.'],
  [96,108,'SPEAKER_1: That explanation is clear. Could another learner tell us why comparing different sized wholes could be misleading?'],
  [108,122,'SPEAKER_2: If one whole is much bigger, its quarter might be bigger than a half of a smaller whole. We must keep the whole the same.'],
  [122,140,'SPEAKER_1: Exactly. To recap, the denominator counts equal parts, and comparisons need the same whole. Try two examples after class and explain each with a drawing. What remains unclear?'],
];
$('synthetic').onclick = () => {
  const segments = SYNTHETIC.map(([start,end,text]) => {
    const label = /^(SPEAKER_\d+):\s*/.exec(text);
    return {start,end,text:label ? text.slice(label[0].length) : text,speaker:label?.[1] || 'SPEAKER_1'};
  });
  setInput(segments, 'Synthetic, nonconfidential example loaded. No real class or participant data.');
  $('duration').value = '140'; $('coverage').value = 'complete'; refreshPayload();
};
$('redact').onclick = redact;
for (const id of ['review','terms','coverage','duration','speakers']) $(id).addEventListener('input', invalidate);
$('confirm').addEventListener('change', refreshPayload);

function element(tag, text, className) {
  const item = document.createElement(tag); if (text !== undefined) item.textContent = text;
  if (className) item.className = className; return item;
}
function renderReport(value) {
  const root = $('report'); root.replaceChildren(); $('reportPanel').hidden = false;
  root.append(element('div', value.overall_category || 'Insufficient evidence', 'rating'));
  root.append(element('p', value.summary));
  root.append(element('p', `Model: ${value.model} · Rubric ${value.rubric_version} · Coverage: ${value.coverage.kind}`, 'small'));
  for (const d of value.dimensions) {
    const box = element('div', undefined, 'dimension');
    box.append(element('h3', `${d.name} — ${d.status === 'unobserved' ? 'Unobserved' : `${d.score}/3`}`));
    box.append(element('p', d.assessment)); box.append(element('p', `Evidence: ${d.evidence_ids.join(', ') || 'Unobserved'}`, 'small')); root.append(box);
  }
  root.append(element('h3','Timestamped evidence'));
  for (const evidence of value.evidence) {
    const box = element('div', undefined, 'evidence');
    const jump = element('button', `${evidence.id} · ${formatTime(evidence.start)}–${formatTime(evidence.end)}`, 'secondary');
    jump.disabled = !recordingURL;
    jump.onclick = () => { $('preview').currentTime = evidence.start; $('preview').scrollIntoView({behavior:'smooth'}); };
    box.append(jump, element('blockquote', evidence.quote));
    box.append(element('p', 'Observed: ' + evidence.observation), element('p', 'Interpretation: ' + evidence.interpretation)); root.append(box);
  }
  for (const [title,items,field] of [['Strengths',value.strengths,'detail'],['Specific improvements',value.improvements,'action']]) {
    root.append(element('h3',title)); const list = element('ul');
    for (const item of items) list.append(element('li', `${item[field]} (${item.evidence_ids.join(', ') || 'Conditional suggestion'})`));
    root.append(list);
  }
  root.append(element('h3','Limitations')); const limitations = element('ul');
  for (const note of value.limitations) limitations.append(element('li',note)); root.append(limitations);
  root.append(element('p',value.category_method,'small'));
}
$('assess').onclick = async () => {
  if (!$('confirm').checked || busy) return;
  try {
    const approved = payload();
    const approvedRevision = revision;
    busy = true; $('assess').disabled = true; clearReport();
    status('assessmentStatus','Sending only the reviewed de-identified text. Waiting for a validated evidence assessment…');
    const headers = {'Content-Type':'application/json'};
    if ($('accessToken').value) headers.Authorization = 'Bearer ' + $('accessToken').value;
    const response = await fetch('/api/assess', {method:'POST', headers, body:JSON.stringify(approved), cache:'no-store', signal:AbortSignal.timeout(195000)});
    const body = await response.json();
    if (!response.ok) throw new Error(body.message || 'Assessment unavailable.');
    if (revision !== approvedRevision || !$('confirm').checked) throw new Error('The review changed while assessment was running. The outdated result was discarded.');
    report = body; renderReport(body); status('assessmentStatus',body.overall_category ? 'Evidence and timestamps validated. Report ready.' : 'The supplied text did not support an overall category. Review the stated limitations.');
    $('reportPanel').scrollIntoView({behavior:'smooth'});
  } catch (error) { status('assessmentStatus',error.name === 'TimeoutError' ? 'Assessment timed out. No result is shown. Do not immediately repeat requests.' : error.message,true); }
  finally { busy = false; refreshPayload(); }
};
$('download').onclick = () => {
  if (!report) return;
  const url = URL.createObjectURL(new Blob([JSON.stringify(report,null,2)],{type:'application/json'}));
  const link = element('a'); link.href = url; link.download = 'class-assessment.json'; link.click(); URL.revokeObjectURL(url);
};
window.addEventListener('beforeunload', () => { worker?.terminate(); if (recordingURL) URL.revokeObjectURL(recordingURL); });
fetch('/api/health', {cache:'no-store'}).then(r=>r.json()).then(info=> {
  status('health', `${info.api_configured ? 'Text assessment configured' : 'Text assessment needs a server API key'} · ${info.browser_assets_ready ? 'Local transcription assets ready' : 'Run the public browser-assets preparation script'}.`);
  $('accessToken').hidden = !info.auth_required;
}).catch(()=>status('health','Cannot reach the local assessment service.',true));
