"""Export actual visible Codex message events; no reconstructed conversation."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from dotenv import dotenv_values


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--session-id',required=True)
    args=parser.parse_args()
    state=Path(os.environ.get('CODEX_HOME',str(Path.home()/'.codex')))
    selected=[]
    for path in (state/'sessions').rglob('*.jsonl'):
        try:
            with path.open(encoding='utf-8') as stream:meta=json.loads(stream.readline())
            p=meta.get('payload',{})
            if meta.get('type')=='session_meta' and (p.get('id')==args.session_id or p.get('session_id')==args.session_id):
                selected.append((path,p.get('id')))
        except (OSError,ValueError):continue
    roots=[entry for entry in selected if entry[1]==args.session_id]
    if len(roots)!=1:raise SystemExit('Expected exactly one verified root session; nothing exported.')
    root=Path('E:/HumanitiAI/private-history')/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    root.mkdir(parents=True,exist_ok=False)
    manifest=[];root_records=[]
    for source,identifier in selected:
        with source.open('rb') as stream:
            size=os.fstat(stream.fileno()).st_size
            data=stream.read(size)
        # Preserve a coherent complete-record prefix while this session is active.
        data=data[:data.rfind(b'\n')+1]
        target=root/(identifier+'.raw.jsonl')
        with target.open('xb') as output:output.write(data)
        manifest.append({'session_id':identifier,'source':str(source),'snapshot':str(target),
                         'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),'capture':'complete-record prefix; session still active'})
        if identifier==args.session_id:root_records=[json.loads(line) for line in data.splitlines() if line.strip()]
    (root/'manifest.private.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    values=dotenv_values(Path(__file__).resolve().parents[1]/'.env')
    secrets=[value for key,value in values.items() if value and any(t in key for t in ('KEY','TOKEN','SECRET','PASSWORD'))]
    def redact(text):
        for secret in secrets:text=text.replace(secret,'[REDACTED: secret]')
        text=re.sub(r'AIza[\w-]{20,}','[REDACTED: API key]',text)
        text=re.sub(r'(?im)^.*[A-Z]:[\\/].*$', '[REDACTED: line containing local path]',text)
        text=re.sub(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}','[REDACTED: email]',text)
        text=re.sub(r'(?i)\b\S+\.(?:mp4|vtt|pdf|zip)\b','[REDACTED: filename]',text)
        return text
    lines=['# Authentic AI interaction history — redacted excerpt','',
           'Extracted from actual root-session visible user/assistant event records in original order. This is not a reconstruction.',
           'Local paths, filename references, email addresses and configured secrets are redacted. Internal reasoning, system/developer instructions, tool bodies and child sessions are omitted.',
           'This snapshot was captured during ongoing work; subsequent messages are not included. Private originals and SHA-256 metadata are preserved separately. Review this copy before submission.','']
    count=0;omitted=0
    for record in root_records:
        p=record.get('payload',{})
        if record.get('type')!='response_item' or p.get('type')!='message':
            omitted+=1;continue
        role=p.get('role')
        if role!='user' and not (role=='assistant' and p.get('phase') in ('commentary','final')):
            omitted+=1;continue
        parts=p.get('content',[])
        message='\n'.join(item['text'] for item in parts if isinstance(item,dict) and item.get('type') in ('input_text','output_text') and isinstance(item.get('text'),str))
        if not message:continue
        if omitted:lines.extend([f'[Omitted {omitted} non-message event record(s).]','']);omitted=0
        count+=1
        lines.extend([f"## {count}. {'User' if role=='user' else 'Assistant'} — {record.get('timestamp','timestamp unavailable')}",'',redact(message),''])
    if count==0:raise SystemExit('No visible message events found; private snapshot preserved, no fabricated export created.')
    target=root/'AI_HISTORY_REDACTED.md'
    target.write_text('\n'.join(lines),encoding='utf-8')
    if any(secret in target.read_text(encoding='utf-8') for secret in secrets):raise SystemExit('Secret audit failed; do not share export.')
    print('Raw snapshots preserved:',len(manifest))
    print('Actual visible messages exported:',count)
    print('Configured-secret matches in redacted copy: 0')
    print('Redacted export:',target)
    print('Manual review required; raw originals must remain private.')


if __name__=='__main__':main()
