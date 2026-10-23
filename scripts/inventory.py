"""Offline, standard-library inventory. Never emit private names or caption text.

Files are extracted under anonymous names. The original names exist only in a
private mapping under data_dir. Pairing is a filename heuristic, not validation.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import html
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import unicodedata
import uuid
import zipfile
import zlib

ALLOWED_EXTENSIONS = {'.mp4', '.vtt', '.pdf'}
MAX_TOTAL_BYTES = 10 * 1024**3
MAX_MEMBERS = 5000
MAX_VTT_BYTES = 64 * 1024**2
RESERVED = {'con', 'prn', 'aux', 'nul', 'conin$', 'conout$'} | {
    f'{prefix}{number}' for prefix in ('com', 'lpt') for number in '123456789¹²³'
}


class InventoryError(Exception):
    """A fixed, non-identifying error code safe to show in a terminal."""


def guard_path(root: Path, target: Path) -> Path:
    """Reject path escape and symlink/junction ancestors, including the root."""
    root, target = root.absolute(), target.absolute()
    try:
        target.relative_to(root)
        target.resolve().relative_to(root.resolve())
    except ValueError:
        raise InventoryError('path_outside_data_directory') from None
    for candidate in (target, *target.parents):
        if candidate.is_symlink() or candidate.is_junction():
            raise InventoryError('symlink_or_junction_path')
    return target


def safe_member_path(name: str, root: Path) -> Path:
    """Validate the original archive name even though extraction anonymizes it."""
    if not name or '\\' in name or name.startswith('/'):
        raise InventoryError('unsafe_archive_path')
    parts = name.removesuffix('/').split('/')
    for part in parts:
        if (part in ('', '.', '..') or part.rstrip(' .') != part
                or any(ord(c) < 32 or c in '<>:"|?*' for c in part)
                or part.split('.')[0].casefold() in RESERVED):
            raise InventoryError('unsafe_archive_path')
    return guard_path(root, root.joinpath(*parts))


def inspect_archive(zf: zipfile.ZipFile, data_dir: Path) -> list[dict]:
    """Preflight every entry before creating any extracted file."""
    infos = zf.infolist()
    if len(infos) > MAX_MEMBERS:
        raise InventoryError('too_many_archive_members')
    seen = set()
    files = []
    total = 0
    for info in infos:
        # orig_filename retains embedded NULs that ZipInfo.filename truncates.
        original = info.orig_filename
        # Google Drive ZIPs can contain directory components ending in spaces.
        # These names are NEVER materialized: validate the Windows-equivalent
        # logical name, retain the original privately, and extract to asset IDs.
        # Empty/traversal/device components and canonical collisions still fail.
        validation_name = '/'.join(part.rstrip(' ') for part in original.split('/'))
        safe_member_path(validation_name, data_dir)
        key = unicodedata.normalize('NFC', validation_name.rstrip('/')).casefold()
        if key in seen:
            raise InventoryError('duplicate_or_case_colliding_archive_path')
        seen.add(key)
        mode_type = stat.S_IFMT(info.external_attr >> 16)
        if mode_type not in (0, stat.S_IFREG, stat.S_IFDIR):
            raise InventoryError('non_regular_archive_member')
        if info.flag_bits & 1:
            raise InventoryError('encrypted_archive_member')
        if info.is_dir():
            continue
        if mode_type == stat.S_IFDIR:
            raise InventoryError('inconsistent_archive_member_type')
        extension = PurePosixPath(validation_name).suffix.lower()
        if extension not in ALLOWED_EXTENSIONS:
            raise InventoryError('unsupported_archive_extension')
        total += info.file_size
        if (info.file_size > MAX_TOTAL_BYTES or total > MAX_TOTAL_BYTES
                or info.file_size / max(1, info.compress_size) > 1000):
            raise InventoryError('archive_expansion_limit')
        files.append({'info': info, 'original_name': original,
                      'windows_space_suffix_normalized': validation_name != original,
                      'extension': extension, 'size_bytes': info.file_size})
    files.sort(key=lambda entry: entry['original_name'].casefold())
    for index, entry in enumerate(files, 1):
        entry['asset_id'] = f'A{index:04d}'
    return files


def file_crc32(path: Path) -> int:
    value = 0
    with path.open('rb') as stream:
        while chunk := stream.read(1024**2):
            value = zlib.crc32(chunk, value)
    return value & 0xffffffff


def extract_archive(zf: zipfile.ZipFile, data_dir: Path) -> list[dict]:
    """Extract safely; verify and reuse identical files, never overwrite files."""
    entries = inspect_archive(zf, data_dir)
    extraction_root = guard_path(data_dir, data_dir / 'inventory' / 'extracted')
    needed = 0
    for entry in entries:
        path = guard_path(data_dir, extraction_root / (entry['asset_id'] + entry['extension']))
        entry['local_path'] = path
        if path.exists():
            if (not path.is_file() or path.stat().st_size != entry['size_bytes']
                    or file_crc32(path) != entry['info'].CRC):
                raise InventoryError('existing_file_conflict_no_overwrite')
            entry['extraction_status'] = 'reused_crc_verified'
        else:
            needed += entry['size_bytes']
            entry['extraction_status'] = 'extracted'
    # Check the existing ancestor without creating anything before the space check.
    ancestor = data_dir.absolute()
    while not ancestor.exists():
        ancestor = ancestor.parent
    if shutil.disk_usage(ancestor).free < needed + 512 * 1024**2:
        raise InventoryError('insufficient_disk_space')
    extraction_root.mkdir(parents=True, exist_ok=True)
    for entry in entries:
        if entry['extraction_status'].startswith('reused'):
            continue
        path = guard_path(data_dir, entry['local_path'])
        # Exclusive creation closes the accidental-overwrite race.
        with path.open('xb') as target:
            try:
                count = 0
                with zf.open(entry['info'], 'r') as source:
                    while chunk := source.read(1024**2):
                        count += len(chunk)
                        if count > entry['size_bytes']:
                            raise InventoryError('archive_size_mismatch')
                        target.write(chunk)
                if count != entry['size_bytes']:
                    raise InventoryError('archive_size_mismatch')
            except BaseException:
                target.close()
                # Only remove the incomplete file this call created exclusively.
                path.unlink()
                raise
    return entries


def parse_timestamp(value: str) -> float | None:
    match = re.fullmatch(r'(?:(\d{2,}):)?(\d{2}):(\d{2})\.(\d{3})', value)
    if not match:
        return None
    hours, minutes, seconds, millis = match.groups()
    if int(minutes) > 59 or int(seconds) > 59:
        return None
    return int(hours or 0) * 3600 + int(minutes) * 60 + int(seconds) + int(millis) / 1000


def parse_vtt(path: Path) -> dict:
    """Read text only locally; return timing and aggregate counts, never payloads."""
    if path.stat().st_size > MAX_VTT_BYTES:
        raise InventoryError('vtt_size_limit')
    raw = path.read_text(encoding='utf-8-sig', errors='replace')
    lines = raw.splitlines()
    result = dict(
        webvtt_header_present=bool(lines and re.match(r'^WEBVTT(?:[ \t]|$)', lines[0])),
        cue_count=0, invalid_timing_count=0, timing_line_count=0,
        max_cue_end_seconds=None, text_cue_count=0, lexical_cue_count=0,
        text_character_count=0, alphabetic_character_count=0, word_count=0,
        non_speech_only_cue_count=0, potentially_usable_text=False,
        encoding_replacement_count=raw.count('\ufffd'),
        non_monotonic_start_count=0,
    )
    previous_start = None
    for block in re.split(r'\n[ \t]*\n', raw.replace('\r\n', '\n').replace('\r', '\n')):
        block_lines = block.strip().splitlines()
        if not block_lines:
            continue
        if re.match(r'^(NOTE(?:[ \t]|$)|STYLE$|REGION$|WEBVTT(?:[ \t]|$))', block_lines[0]):
            continue
        timing_indices = [i for i, line in enumerate(block_lines) if '-->' in line]
        for position, index in enumerate(timing_indices):
            result['timing_line_count'] += 1
            match = re.fullmatch(r'\s*(\S+)\s+-->\s+(\S+)(?:[ \t]+.*)?', block_lines[index])
            start, end = (parse_timestamp(match[1]), parse_timestamp(match[2])) if match else (None, None)
            if start is None or end is None or end <= start:
                result['invalid_timing_count'] += 1
                continue
            result['cue_count'] += 1
            result['max_cue_end_seconds'] = max(result['max_cue_end_seconds'] or 0, end)
            if previous_start is not None and start < previous_start:
                result['non_monotonic_start_count'] += 1
            previous_start = start
            next_index = timing_indices[position + 1] if position + 1 < len(timing_indices) else len(block_lines)
            payload = '\n'.join(block_lines[index + 1:next_index])
            clean = html.unescape(re.sub(r'<[^>]*>', '', payload)).strip()
            count = sum(not char.isspace() for char in clean)
            alphabetic = sum(char.isalpha() for char in clean)
            result['text_character_count'] += count
            result['alphabetic_character_count'] += alphabetic
            result['word_count'] += len(re.findall(r'[^\W_]+', clean, flags=re.UNICODE))
            result['text_cue_count'] += bool(count)
            only_non_speech = bool(re.fullmatch(
                r'\s*[\[(](?:music|applause|laughter|silence|inaudible|noise)[\])]\s*', clean, re.I))
            result['non_speech_only_cue_count'] += only_non_speech
            result['lexical_cue_count'] += bool(alphabetic and not only_non_speech)
    result['potentially_usable_text'] = result['lexical_cue_count'] > 0
    result['text_usability_rule'] = 'At least one valid timed cue with alphabetic text, excluding a few known non-speech labels; accuracy and speech relevance unverified.'
    return result


def match_key(name: str, strip_caption_suffix: bool = False) -> str:
    value = unicodedata.normalize('NFKC', PurePosixPath(name.rstrip(' ')).stem).casefold().strip()
    if strip_caption_suffix:
        value = re.sub(r'[ ._-]+(?:transcript|transcription|captions?|subtitles?|cc)$', '', value)
    return value


def pair_entries(entries: list[dict]) -> tuple[list[dict], list[dict]]:
    """Conservative basename candidates; preserve all ambiguity across folders."""
    videos = [e for e in entries if e['extension'] == '.mp4']
    captions = [e for e in entries if e['extension'] == '.vtt']
    for i, video in enumerate(videos, 1):
        video['recording_id'] = f'R{i:03d}'
    for i, caption in enumerate(captions, 1):
        caption['transcript_id'] = f'T{i:03d}'
    relationships = []
    for video in videos:
        for caption in captions:
            exact = match_key(video['original_name']) == match_key(caption['original_name'])
            suffix = match_key(video['original_name']) == match_key(caption['original_name'], True)
            if exact or suffix:
                relationships.append((video, caption, 'exact_stem' if exact else 'caption_suffix'))
    for video in videos:
        candidates = [pair for pair in relationships if pair[0] is video]
        video['candidate_transcript_ids'] = [c['transcript_id'] for _, c, _ in candidates]
        unique = len(candidates) == 1 and sum(p[1] is candidates[0][1] for p in relationships) == 1
        video['match_status'] = 'possible_unique' if unique else ('ambiguous' if candidates else 'unmatched')
        video['match_basis'] = candidates[0][2] if unique else None
        video['paired_transcript_id'] = candidates[0][1]['transcript_id'] if unique else None
    for caption in captions:
        candidates = [p[0] for p in relationships if p[1] is caption]
        caption['candidate_recording_ids'] = [v['recording_id'] for v in candidates]
        unique = len(candidates) == 1 and candidates[0]['match_status'] == 'possible_unique'
        caption['match_status'] = 'possible_unique' if unique else ('ambiguous' if candidates else 'unmatched')
    return videos, captions


def probe_video(path: Path, executable: str | None) -> dict:
    result = dict(status='unavailable', video_duration_seconds=None,
                  duration_source=None, video_stream_duration_seconds=None,
                  has_audio=None, audio_stream_count=None, video_stream_count=None)
    if not executable:
        return result
    try:
        completed = subprocess.run(
            [executable, '-v', 'error', '-show_entries', 'format=duration:stream=codec_type,duration',
             '-of', 'json', str(path)], capture_output=True, text=True,
            encoding='utf-8', errors='replace', timeout=45, check=True)
        payload = json.loads(completed.stdout)
        streams = payload.get('streams', [])
        def number(value):
            try:
                parsed = float(value)
                return parsed if math.isfinite(parsed) and parsed >= 0 else None
            except (ValueError, TypeError):
                return None
        video_lengths = [number(s.get('duration')) for s in streams if s.get('codec_type') == 'video']
        stream_duration = max((v for v in video_lengths if v is not None), default=None)
        format_duration = number(payload.get('format', {}).get('duration'))
        duration = format_duration if format_duration is not None else stream_duration
        audio_count = sum(s.get('codec_type') == 'audio' for s in streams)
        result.update(status='ok', video_duration_seconds=duration,
                      duration_source='container' if format_duration is not None else ('video_stream' if stream_duration is not None else None),
                      video_stream_duration_seconds=stream_duration,
                      has_audio=audio_count > 0, audio_stream_count=audio_count,
                      video_stream_count=sum(s.get('codec_type') == 'video' for s in streams))
    except (OSError, subprocess.SubprocessError, ValueError, TypeError, AttributeError):
        result['status'] = 'probe_failed'
    return result


def sha256_file(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write_json(path: Path, value) -> None:
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, ensure_ascii=True, allow_nan=False)
        stream.write('\n')


def run_inventory(archive: Path, data_dir: Path, ffprobe: str | None = None) -> dict:
    data_dir = data_dir.absolute()
    guard_path(data_dir, data_dir)
    # Confidential data must remain outside the application repository.
    repository = Path(__file__).resolve().parents[1]
    if data_dir.resolve().is_relative_to(repository):
        raise InventoryError('data_directory_inside_repository')
    source_before = archive.stat()
    source_hash = sha256_file(archive)
    with zipfile.ZipFile(archive, 'r') as zf:
        entries = extract_archive(zf, data_dir)
    videos, captions = pair_entries(entries)
    transcript_rows = []
    for caption in captions:
        transcript_rows.append({k: caption[k] for k in (
            'asset_id', 'transcript_id', 'extension', 'size_bytes', 'match_status', 'candidate_recording_ids')}
            | {'vtt': parse_vtt(caption['local_path'])})
    transcript_lookup = {t['transcript_id']: t for t in transcript_rows}
    video_rows = []
    for video in videos:
        row = {k: video[k] for k in ('asset_id', 'recording_id', 'extension', 'size_bytes',
                'match_status', 'match_basis', 'candidate_transcript_ids', 'paired_transcript_id')}
        row['media'] = probe_video(video['local_path'], ffprobe)
        transcript = transcript_lookup.get(row['paired_transcript_id'])
        end = transcript['vtt']['max_cue_end_seconds'] if transcript else None
        row['transcript_end_seconds'] = end
        duration = row['media']['video_duration_seconds']
        row['transcript_end_minus_media_duration_seconds'] = round(end - duration, 3) if end is not None and duration is not None else None
        video_rows.append(row)
    pdf_rows = [{'asset_id': e['asset_id'], 'extension': e['extension'], 'size_bytes': e['size_bytes'],
                 'local_path': str(e['local_path'])} for e in entries if e['extension'] == '.pdf']
    source_after = archive.stat()
    if source_before.st_size != source_after.st_size or source_before.st_mtime_ns != source_after.st_mtime_ns:
        raise InventoryError('source_archive_changed_during_inventory')
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '-' + uuid.uuid4().hex[:8]
    report_root = guard_path(data_dir, data_dir / 'inventory' / 'reports' / run_id)
    report_root.mkdir(parents=True, exist_ok=False)
    summary = {
        'schema_version': 1, 'created_utc': datetime.now(timezone.utc).isoformat(),
        'archive_member_count': len(entries), 'total_uncompressed_bytes': sum(e['size_bytes'] for e in entries),
        'extension_counts': dict(Counter(e['extension'] for e in entries)),
        'windows_space_suffix_entry_count': sum(e['windows_space_suffix_normalized'] for e in entries),
        'extraction_counts': dict(Counter(e['extraction_status'] for e in entries)),
        'ffprobe_available': bool(ffprobe), 'videos': video_rows, 'transcripts': transcript_rows, 'pdfs': pdf_rows,
        'limitations': [
            'Filename candidates only; no semantic or synchronization validation.',
            'VTT maximum cue end is a transcript endpoint, not actual video duration.',
            'Caption text counts do not establish accuracy, language, completeness, or assessment quality.',
            'PDF contents, video frames, and audio were not read for assessment.',
        ],
    }
    write_json(report_root / 'inventory.anonymous.json', summary)
    write_json(report_root / 'filename-mapping.private.json', {
        'source_archive': str(archive.absolute()), 'source_archive_sha256': source_hash,
        'source_archive_size_bytes': source_before.st_size,
        'entries': [{k: str(v) if isinstance(v, Path) else v for k, v in e.items() if k != 'info'} for e in entries],
    })
    print_summary(summary, report_root)
    return summary


def print_summary(summary: dict, report_root: Path) -> None:
    print('OFFLINE ANONYMOUS INVENTORY')
    print(json.dumps({k: summary[k] for k in ('archive_member_count', 'total_uncompressed_bytes',
                     'extension_counts', 'extraction_counts', 'windows_space_suffix_entry_count', 'ffprobe_available')}))
    print('VIDEO | EXT | BYTES | MATCH | TRANSCRIPT | VTT END s | MEDIA DURATION s | AUDIO')
    for v in summary['videos']:
        print(f"{v['recording_id']} | {v['extension']} | {v['size_bytes']} | {v['match_status']} | "
              f"{','.join(v['candidate_transcript_ids']) or '-'} | {v['transcript_end_seconds']} | "
              f"{v['media']['video_duration_seconds']} | {v['media']['has_audio']}")
    print('VTT | EXT | BYTES | CUES | INVALID | MAX END s | TEXT CUES | ALPHA CHARS | WORDS | POTENTIALLY USABLE')
    for t in summary['transcripts']:
        m = t['vtt']
        print(f"{t['transcript_id']} | {t['extension']} | {t['size_bytes']} | {m['cue_count']} | "
              f"{m['invalid_timing_count']} | {m['max_cue_end_seconds']} | {m['text_cue_count']} | "
              f"{m['alphabetic_character_count']} | {m['word_count']} | {m['potentially_usable_text']}")
    for pdf in summary['pdfs']:
        print(f"{pdf['asset_id']} | .pdf | {pdf['size_bytes']} bytes | local path: {pdf['local_path']}")
    print(f'Private reports: {report_root}')
    print('Text present does not imply accurate captions. VTT end is NOT video duration.')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--ffprobe', help='Optional explicit ffprobe executable; otherwise PATH lookup.')
    args = parser.parse_args()
    try:
        run_inventory(args.archive, args.data_dir, args.ffprobe or shutil.which('ffprobe'))
    except InventoryError as exc:
        print(f'Inventory stopped safely: {exc}', file=sys.stderr)
        return 1
    except Exception as exc:
        # Exception messages and tracebacks can expose private paths or payloads.
        print(f'Inventory stopped safely ({type(exc).__name__}); no private details displayed.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
