# HUMANITI AI recruitment challenge

Initial inventory phase only. This repository contains an offline, standard-library
dataset utility and environment checks. It does **not** yet contain the assessment
application, a deployed service, model weights, or confidential recordings.

## Run locally (Windows PowerShell)

No dependencies are required for this phase. Keep the original ZIP where it is.
From the repository directory, use the installed Python 3.14 interpreter:

```powershell
. .\scripts\use-storage.ps1
$python = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python314\python.exe'
& $python .\scripts\check_environment.py
& $python -m unittest discover -s tests -v

# Set this locally to the ORIGINAL archive; do not copy it into the repo.
$archive = 'C:\path\to\original.zip'
& $python .\scripts\inventory.py --archive $archive --data-dir 'E:\HumanitiAI\data'
```

Dot-source `use-storage.ps1` in each new terminal. It checks E: free space and
sets process-local package/model caches and media temporary directories on E:.
It installs nothing and leaves the existing Python installation unchanged.

## Inventory behavior

- Validates every ZIP path before extraction; rejects traversal, Windows device
  names, symlinks/junctions, duplicate paths, encryption, and excessive expansion.
  Trailing ASCII spaces are normalized only for path validation; original names
  are preserved in the private mapping and never used as extraction destinations.
- Streams files into anonymous names under
  `E:\HumanitiAI\data\inventory\extracted`. Reuses byte-size/CRC-verified existing
  files; refuses conflicts. Opens the original archive read-only.
- Stores original filename mappings **only** in private timestamped report
  directories under `E:\HumanitiAI\data\inventory\reports`. Reports and media
  stay outside Git. Anonymous IDs are stable for the same archive ordering.
- Reports filename-based candidate pairs; flags ambiguity instead of choosing.
- Reads VTT text locally to count timed cues and text presence. It never emits
  caption text or speaker names. Counts do not establish transcription accuracy.
- Keeps maximum caption end time separate from media duration. Optional local
  `ffprobe` supplies media duration and audio-stream presence; otherwise both are
  unknown. An explicit executable can be passed with `--ffprobe`.
- Identifies the PDF's anonymous local path without parsing its contents.

The utility is for a trusted local operator, not yet an internet upload handler.
No recording, caption, frame, or PDF content is sent to an external service.
Synthetic tests exercise safety and metadata behavior without the dataset.

## Next implementation decision

First establish an explicitly permitted processing/hosting route. Then verify a
fresh Python 3.14 environment on E: with binary dependency resolution and import
checks; use a side-by-side fallback only for a demonstrated blocker. Benchmark
local CPU INT8 transcription on nonconfidential audio. The final application
must generate timestamps from **new audio**, with supplied VTTs used only during
development.

Implement one end-to-end path next: recording → local transcription → timestamped
evidence → explicit teaching rubric → validated result → Streamlit view. Ratings
must trace to evidence; text presence, speaking time, or silence alone cannot
justify a teaching-quality score. Measure transcription quality and runtime
before adding visual analysis.

- [Dependency evidence and next-phase checks](docs/dependency-compatibility.md)
- [Preserve actual Codex history and prepare a redacted copy](docs/session-history.md)

No repository publication, upload, hosting, or application development is part
of this phase. The final short approach statement should describe implemented
behavior and measured limitations after the application exists.
