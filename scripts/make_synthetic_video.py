"""Use a pinned public FFmpeg build ONLY to create a synthetic test MP4."""
import json
from pathlib import Path
import shutil
import subprocess
import urllib.request
import zipfile

ROOT = Path('E:/HumanitiAI/browser-assets/test')


def main():
    target = ROOT / 'synthetic.mp4'
    if target.exists():
        print('Synthetic MP4 already exists; preserved.')
        return
    cache = Path('E:/HumanitiAI/caches/test-tools')
    cache.mkdir(parents=True, exist_ok=True)
    executable = cache / 'ffmpeg.exe'
    if not executable.exists():
        with urllib.request.urlopen('https://pypi.org/pypi/imageio-ffmpeg/0.6.0/json', timeout=30) as r:
            metadata = json.load(r)
        asset = next(f for f in metadata['urls'] if f['filename'].endswith('win_amd64.whl'))
        wheel = cache / 'imageio_ffmpeg-0.6.0-win_amd64.whl'
        if not wheel.exists():
            with urllib.request.urlopen(asset['url'], timeout=90) as source, wheel.open('xb') as output:
                shutil.copyfileobj(source, output, 1024**2)
        import hashlib
        with wheel.open('rb') as source:
            if hashlib.file_digest(source, 'sha256').hexdigest() != asset['digests']['sha256']:
                raise SystemExit('Public FFmpeg wheel hash mismatch.')
        with zipfile.ZipFile(wheel) as source:
            member = next(n for n in source.namelist() if n.endswith('.exe') and '/binaries/' in n)
            with source.open(member) as binary, executable.open('xb') as output:
                shutil.copyfileobj(binary, output)
    completed = subprocess.run([str(executable), '-hide_banner', '-loglevel', 'error', '-n',
        '-f', 'lavfi', '-i', 'color=c=0x174d40:s=320x180:r=12', '-i', str(ROOT/'synthetic.wav'),
        '-c:v', 'libx264', '-preset', 'ultrafast', '-c:a', 'aac', '-b:a', '64k', '-shortest',
        '-movflags', '+faststart', str(target)], capture_output=True, timeout=60)
    if completed.returncode:
        raise SystemExit('Synthetic MP4 encoding failed.')
    print('Synthetic MP4 ready:', target.stat().st_size, 'bytes. No dataset accessed.')


if __name__ == '__main__':
    main()
