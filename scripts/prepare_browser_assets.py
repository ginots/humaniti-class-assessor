"""Download pinned PUBLIC browser assets to the configured directory; never dataset data."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import urllib.request

ROOT = Path(os.environ.get('BROWSER_ASSET_DIR', 'E:/HumanitiAI/browser-assets' if os.name == 'nt' else '/app/browser-assets'))
REVISION = '5332fcc35e32a33b86612b9a57a89be7906102b1'
ORT = '1.22.0-dev.20250409-89f8206ba4'


def main():
    ancestor = ROOT
    while not ancestor.exists():
        ancestor = ancestor.parent
    if shutil.disk_usage(ancestor).free < 1024**3:
        raise SystemExit('At least 1 GiB free in the asset filesystem is required.')
    sources = {
        'vendor/transformers.bundle.js': 'https://cdn.jsdelivr.net/npm/@huggingface/transformers@3.8.1/dist/transformers.min.js',
        'vendor/mediabunny.mjs': 'https://cdn.jsdelivr.net/npm/mediabunny@1.62.1/dist/bundles/mediabunny.mjs',
    }
    for filename in ['ort-wasm-simd-threaded.jsep.mjs', 'ort-wasm-simd-threaded.jsep.wasm']:
        sources['vendor/' + filename] = f'https://cdn.jsdelivr.net/npm/onnxruntime-web@{ORT}/dist/{filename}'
    for filename in ['config.json', 'generation_config.json', 'preprocessor_config.json',
                     'tokenizer.json', 'tokenizer_config.json', 'special_tokens_map.json',
                     'onnx/encoder_model_quantized.onnx', 'onnx/decoder_model_merged_quantized.onnx']:
        sources['models/Xenova/whisper-tiny/' + filename] = f'https://huggingface.co/Xenova/whisper-tiny/resolve/{REVISION}/{filename}'
    ROOT.mkdir(parents=True, exist_ok=True)
    manifest = {'transformers': '3.8.1', 'mediabunny': '1.62.1', 'onnxruntime_web': ORT,
                'model': 'Xenova/whisper-tiny', 'model_revision': REVISION, 'files': {}}
    for relative, url in sources.items():
        target = ROOT / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            partial = target.with_suffix(target.suffix + '.partial')
            with urllib.request.urlopen(url, timeout=90) as response, partial.open('wb') as output:
                shutil.copyfileobj(response, output, 1024**2)
            partial.rename(target)
        with target.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        manifest['files'][relative] = {'bytes': target.stat().st_size, 'sha256': digest, 'public_source': url}
        print(relative, target.stat().st_size, 'bytes', flush=True)
    (ROOT / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print('Public assets staged at', ROOT, '. No private content accessed.')


if __name__ == '__main__':
    main()
