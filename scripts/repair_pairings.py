"""Repair filename-convention pairs locally. Never read caption text or re-extract."""
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path, PurePosixPath
import re
import unicodedata


def tokens(name):
    return re.findall(r'[^\W_]+', unicodedata.normalize('NFKC', PurePosixPath(name).stem).casefold())


def repair(mapping_path):
    mapping = json.loads(mapping_path.read_text(encoding='utf-8'))
    entries = mapping['entries']
    videos = [e for e in entries if e['extension'] == '.mp4']
    captions = [e for e in entries if e['extension'] == '.vtt']
    vf = Counter(t for e in videos for t in set(tokens(e['original_name'])))
    tf = Counter(t for e in captions for t in set(tokens(e['original_name'])))
    # Repeated recording-only suffix marker; derive locally instead of exposing it.
    markers = {t for t, n in vf.items() if n >= max(3, len(videos) * .6) and tf[t] <= len(captions) * .2}
    markers |= {'transcript', 'transcription', 'captions', 'subtitles'}
    def key(e):
        words = tokens(e['original_name'])
        stop = next((i for i,t in enumerate(words) if t in markers), len(words))
        prefix = words[:stop]
        while prefix and prefix[-1].isdigit():
            prefix.pop()
        parent = unicodedata.normalize('NFKC', str(PurePosixPath(e['original_name']).parent)).casefold()
        return parent, tuple(prefix)
    candidates = {v['recording_id']: [t for t in captions if key(v) == key(t)] for v in videos}
    reverse = Counter(t['transcript_id'] for ts in candidates.values() for t in ts)
    rows = []
    for v in videos:
        matches = candidates[v['recording_id']]
        unique = len(matches) == 1 and reverse[matches[0]['transcript_id']] == 1
        rows.append({'recording_id':v['recording_id'], 'video_asset_id':v['asset_id'],
                     'transcript_id':matches[0]['transcript_id'] if unique else None,
                     'candidate_transcript_ids':[t['transcript_id'] for t in matches],
                     'status':'matched_by_naming_convention' if unique else ('ambiguous' if matches else 'unmatched'),
                     'basis':'same private parent folder and same prefix before recording/transcript suffix; no content-based validation'})
    destination = mapping_path.parent / ('pairings-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.private.json')
    with destination.open('x', encoding='utf-8') as output:
        json.dump({'source_mapping':str(mapping_path), 'pairings':rows,
                   'label_policy':{'Weak':'Poor', 'demo':'reference_only', 'quality issue':'diagnostic_reference_only'},
                   'warning':'Labels and private paths must never enter assessor requests.'}, output, indent=2)
    for row in rows:
        print(row['recording_id'], row['transcript_id'] or '-', row['status'])
    print('Private pairing report:', destination)
    return rows


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--mapping', type=Path, required=True)
    args = parser.parse_args()
    try:
        repair(args.mapping)
    except Exception as error:
        raise SystemExit('Local pairing repair stopped: ' + type(error).__name__) from None
