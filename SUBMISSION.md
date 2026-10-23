# Approach, findings, and limitations

The application keeps recordings and original transcripts in the browser. A worker uses Mediabunny to decode MP4 audio incrementally and Transformers.js Whisper tiny to transcribe 30-second windows. Pinned public libraries and model weights are served from the application origin; browser network connections are restricted to that origin.

The browser replaces common identifiers and user-supplied private terms, preserves timestamps, and requires editable human review before submission. Automatic redaction is explicitly incomplete. Only reviewed, de-identified segments and coverage metadata reach the Python backend. The server loads its Gemini key using python-dotenv, accepts a strict text contract, and neither stores nor logs transcript bodies.

The assessor collects evidence before scoring explanation/structure, checking understanding, feedback/adaptation, and learner participation. The server validates exact evidence quotes, segment references, timestamps and scores, then derives Poor, Average, Good or Excellent from supported dimensions. Missing evidence is unobserved; insufficient evidence or API failure produces no invented rating. Visual presentation, emotion and vocal qualities remain unassessed; a heuristic rejects common unsupported modality claims.

Synthetic tests demonstrated local timestamp import, identifier replacement, text-only HTTP plumbing and a 31.7-second MP4 transcribed across two windows. The integrated recording-to-report path produced a validated Gemini assessment, with zero external browser requests. All 12 reference video/VTT pairings were repaired locally without re-extraction.

Whisper tiny accuracy, chunk boundaries, speaker attribution, manual redaction and model judgement limit reliability. Long-recording performance and agreement with human assessments remain unmeasured. Reference feedback informed the rubric, so evaluation on those examples is development/reference-set evaluation, not an untouched independent test. Hosting and publication are pending.
