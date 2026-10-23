// Pure local functions. No network, storage, telemetry, or model calls.
export function timestamp(value) {
  const m = /^(?:(\d{2,}):)?(\d{2}):(\d{2})\.(\d{3})$/.exec(value);
  if (!m || +m[2] > 59 || +m[3] > 59) throw new Error('Invalid VTT timestamp.');
  return +(m[1] || 0) * 3600 + +m[2] * 60 + +m[3] + +m[4] / 1000;
}

function decodeEntities(text) {
  // Textarea parses entities without executing markup or loading resources.
  const box = document.createElement('textarea');
  box.innerHTML = text.replace(/</g, '&lt;').replace(/>/g, '&gt;');
  return box.value;
}

export function parseVtt(raw) {
  if (raw.length > 3_000_000) throw new Error('VTT exceeds the 3 MB browser limit.');
  raw = raw.replace(/^\uFEFF/, '').replace(/\r\n?/g, '\n');
  if (!/^WEBVTT(?:\s|$)/.test(raw)) throw new Error('A WEBVTT header is required.');
  const segments = [], speakers = new Map();
  let invalid = 0;
  for (const block of raw.split(/\n[ \t]*\n/)) {
    const lines = block.trim().split('\n');
    if (/^(WEBVTT|NOTE(?:\s|$)|STYLE$|REGION$)/.test(lines[0])) continue;
    const i = lines.findIndex(line => line.includes('-->'));
    if (i < 0) continue;
    try {
      const timing = /^(\S+)\s+-->\s+(\S+)(?:\s.*)?$/.exec(lines[i].trim());
      if (!timing) throw new Error();
      const start = timestamp(timing[1]), end = timestamp(timing[2]);
      if (end <= start || end > 14400) throw new Error();
      const payload = lines.slice(i + 1).join(' ');
      const voice = /<v(?:\.[^ >]+)?\s+([^>]+)>/.exec(payload);
      let speaker = null;
      if (voice) {
        if (!speakers.has(voice[1])) speakers.set(voice[1], `SPEAKER_${speakers.size + 1}`);
        speaker = speakers.get(voice[1]);
      }
      const text = decodeEntities(payload.replace(/<[^>]*>/g, '')).trim();
      if (text) segments.push({start, end, text, speaker});
    } catch { invalid++; }
  }
  if (invalid) throw new Error(`${invalid} malformed cues found. Correct the VTT locally rather than silently dropping evidence.`);
  segments.sort((a, b) => a.start - b.start);
  if (!segments.length) throw new Error('No nonempty timed captions found.');
  if (segments.length > 5000) throw new Error('Too many cues. Select a partial excerpt locally.');
  return {segments, speakerCount: speakers.size};
}

const EMAIL = /[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}/g;
const URL = /(?:https?:\/\/|www\.)\S+/gi;
const PHONE = /(?<!\w)(?:\+?\d[\d ()-]{7,}\d)(?!\w)/g;
const FILE = /(?:[A-Za-z]:[\\/][^\n]+|\b\S+\.(?:mp4|wav|mp3|vtt|mov|webm)\b)/gi;
const INTRO = /\b(?:[Mm]y name is|[Cc]all me|I am|I'm)\s+([A-Z][a-z]+(?:[ \t]+[A-Z][a-z]+){0,2})/g;
const VOCATIVE = /\b(?:[Hh]i|[Hh]ello|[Tt]hanks|[Tt]hank you|[Ww]ell done|[Gg]ood job)[, ]+([A-Z][a-z]+(?:[ \t]+[A-Z][a-z]+)?)/g;
const SPEAKER_PREFIX = /^\s*([A-Z][a-z]+(?:[ \t]+[A-Z][a-z]+){0,2})\s*:/;
const ADDRESS = /\b\d{1,5}\s+(?:[A-Z][\p{L}]+\s+){1,4}(?:Street|Road|Lane|Avenue|Nagar|Colony)\b/gu;
const ID = /\b(?:student\s*id|roll\s*(?:no|number)|meeting\s*id|school\s*id)\s*[:#-]?\s*[\w-]+/gi;

const escapeRE = value => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
function termPattern(value) {
  return new RegExp(`(?<![\\p{L}\\p{N}_])${escapeRE(value)}(?![\\p{L}\\p{N}_])`, 'giu');
}

export function redactSegments(rawSegments, termsText = '') {
  const replacements = new Map(), terms = new Set();
  let changes = 0;
  const speakerMap = new Map();
  const custom = termsText.split(/[\n,]/).map(s => s.trim()).filter(Boolean);
  for (const term of custom) {
    if (term.length < 2 || term.length > 120) throw new Error('Each supplied term must contain 2–120 characters.');
    terms.add(term);
  }
  if (terms.size > 200) throw new Error('Use at most 200 names/terms.');
  for (const segment of rawSegments) {
    for (const regex of [INTRO, VOCATIVE]) {
      regex.lastIndex = 0;
      for (const match of segment.text.matchAll(regex)) terms.add(match[1]);
    }
    const speaker = SPEAKER_PREFIX.exec(segment.text);
    if (speaker) terms.add(speaker[1]);
  }
  function replace(text, regex, kind) {
    regex.lastIndex = 0;
    return text.replace(regex, original => {
      const key = original.toLocaleLowerCase();
      if (!replacements.has(key)) replacements.set(key, `[${kind}_${replacements.size + 1}]`);
      changes++;
      return replacements.get(key);
    });
  }
  const segments = rawSegments.map((segment, i) => {
    let text = segment.text;
    const prefix = SPEAKER_PREFIX.exec(text);
    let speaker = segment.speaker || null;
    if (prefix) {
      const key = prefix[1].toLocaleLowerCase();
      if (!speakerMap.has(key)) speakerMap.set(key, `SPEAKER_${speakerMap.size + 1}`);
      speaker = speakerMap.get(key);
      text = text.slice(prefix[0].length).trim();
      changes++;
    }
    for (const [regex, kind] of [[EMAIL, 'EMAIL'], [URL, 'LINK'], [PHONE, 'NUMBER'], [ADDRESS, 'ADDRESS'], [ID, 'ID'], [FILE, 'FILE']])
      text = replace(text, regex, kind);
    for (const term of [...terms].sort((a, b) => b.length - a.length)) text = replace(text, termPattern(term), 'TERM');
    return {id: `S${String(i + 1).padStart(4, '0')}`, start: segment.start, end: segment.end, text, speaker};
  });
  // Mapping is intentionally NOT returned and never enters the assessment payload.
  return {segments, changes, detectedTerms: terms.size, speakerCount: new Set(segments.map(s => s.speaker).filter(Boolean)).size};
}

export function validateReviewed(segments, termsText) {
  if (!Array.isArray(segments) || !segments.length) throw new Error('No reviewed segments.');
  let previous = -1;
  for (let i = 0; i < segments.length; i++) {
    const s = segments[i];
    if (!s || Object.keys(s).sort().join(',') !== 'end,id,speaker,start,text') throw new Error('Keep only the displayed segment fields.');
    if (s.id !== `S${String(i + 1).padStart(4, '0')}` || !Number.isFinite(s.start) || !Number.isFinite(s.end)
      || s.start < 0 || s.end <= s.start || s.end > 14400 || s.start < previous || typeof s.text !== 'string' || !s.text.trim())
      throw new Error('Segment IDs, timestamps, or text are invalid.');
    if (s.speaker !== null && !/^SPEAKER_\d{1,3}$/.test(s.speaker)) throw new Error('Use generic speaker labels only.');
    previous = s.start;
    for (const regex of [EMAIL, URL, PHONE, FILE]) {
      regex.lastIndex = 0;
      if (regex.test(s.text)) throw new Error('Possible remaining identifier or filename. Redact it before submission.');
    }
    for (const term of termsText.split(/[\n,]/).map(x => x.trim()).filter(Boolean)) {
      if (termPattern(term).test(s.text)) throw new Error('A supplied private term remains in the reviewed text.');
    }
  }
  return segments;
}

export function makePayload(segments, coverage, speakersReliable) {
  return {reviewed: true, deidentified: true,
    segments: segments.map(s => ({id:s.id, start:s.start, end:s.end, text:s.text, speaker:speakersReliable ? s.speaker : null})),
    coverage: {kind:coverage.kind, duration_seconds:coverage.duration_seconds}, speakers_reliable:speakersReliable};
}

export function formatTime(seconds) {
  const value = Math.max(0, Math.round(seconds));
  return `${Math.floor(value / 3600).toString().padStart(2,'0')}:${Math.floor(value % 3600 / 60).toString().padStart(2,'0')}:${(value % 60).toString().padStart(2,'0')}`;
}
