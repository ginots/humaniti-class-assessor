"""Small dependency-free server. Only reviewed text can enter /api/assess."""
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import threading
import time
from urllib.parse import urlsplit
from assessment import AppError, MAX_BODY, assess, load_env, parse_json

load_env()
ROOT = Path(__file__).parent / 'static'
ASSETS = Path(os.environ.get('BROWSER_ASSET_DIR', 'E:/HumanitiAI/browser-assets' if os.name == 'nt' else '/app/browser-assets'))
ALLOWED_FILES = {'/': ('index.html', 'text/html; charset=utf-8'),
                 '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                 '/privacy.js': ('privacy.js', 'text/javascript; charset=utf-8'),
                 '/transcribe-worker.js': ('transcribe-worker.js', 'text/javascript; charset=utf-8'),
                 '/style.css': ('style.css', 'text/css; charset=utf-8')}
SLOTS = threading.BoundedSemaphore(1)
RATE_LOCK = threading.Lock()
LAST_REQUEST = 0.0


class Handler(BaseHTTPRequestHandler):
    server_version = 'ClassEvidence/1.0'
    sys_version = ''

    def log_message(self, *_):
        pass  # No access URLs, client addresses, request bodies, or provider output.

    def end_headers(self):
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Cross-Origin-Opener-Policy', 'same-origin')
        self.send_header('Cross-Origin-Embedder-Policy', 'require-corp')
        self.send_header('Permissions-Policy', 'camera=(), microphone=(), geolocation=()')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; worker-src 'self' blob:; connect-src 'self'; style-src 'self'; img-src 'self' data:; media-src 'self' blob:; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
        super().end_headers()

    def respond(self, status, value):
        raw = json.dumps(value, allow_nan=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == '/api/health':
            load_env()
            return self.respond(200, {'status': 'ok', 'api_configured': bool(os.environ.get('GEMINI_API_KEY')),
                                      'model': 'gemini-3.8-flash', 'media_uploads': False,
                                      'auth_required': bool(os.environ.get('APP_ACCESS_TOKEN')),
                                      'browser_assets_ready': (ASSETS / 'manifest.json').is_file()})
        if path.startswith(('/vendor/', '/models/')):
            manifest_path = ASSETS / 'manifest.json'
            if not manifest_path.is_file():
                return self.respond(503, {'error': 'browser_assets_missing'})
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            relative = path.removeprefix('/')
            if relative not in manifest['files'] or urlsplit(self.path).query:
                return self.respond(404, {'error': 'not_found'})
            target = ASSETS / relative
            if target.is_symlink() or not target.resolve().is_relative_to(ASSETS.resolve()):
                return self.respond(404, {'error': 'not_found'})
            types = {'.js': 'text/javascript', '.mjs': 'text/javascript', '.wasm': 'application/wasm', '.json': 'application/json'}
            self.send_response(200)
            self.send_header('Content-Type', types.get(target.suffix, 'application/octet-stream'))
            self.send_header('Content-Length', str(target.stat().st_size))
            self.end_headers()
            with target.open('rb') as source:
                shutil.copyfileobj(source, self.wfile, 1024**2)
            return
        if path == '/synthetic-test.mp4':
            target = ASSETS / 'test' / 'synthetic.mp4'
            if not target.is_file():
                return self.respond(404, {'error': 'synthetic_fixture_missing'})
            self.send_response(200)
            self.send_header('Content-Type', 'video/mp4')
            self.send_header('Content-Length', str(target.stat().st_size))
            self.end_headers()
            with target.open('rb') as source:
                shutil.copyfileobj(source, self.wfile)
            return
        if path not in ALLOWED_FILES or urlsplit(self.path).query:
            return self.respond(404, {'error': 'not_found'})
        filename, content_type = ALLOWED_FILES[path]
        raw = (ROOT / filename).read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        global LAST_REQUEST
        acquired = False
        try:
            if self.path != '/api/assess':
                raise AppError('not_found', 'Only the text assessment endpoint is available.', 404)
            origin = self.headers.get('Origin')
            if origin and (urlsplit(origin).netloc != self.headers.get('Host') or urlsplit(origin).scheme not in ('http', 'https')):
                raise AppError('origin_rejected', 'Cross-origin submissions are rejected.', 403)
            load_env()
            token = os.environ.get('APP_ACCESS_TOKEN', '')
            if token and not hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + token):
                raise AppError('unauthorized', 'Enter the reviewer access token.', 401)
            if self.headers.get_content_type() != 'application/json' or self.headers.get('Transfer-Encoding'):
                raise AppError('text_json_only', 'Only bounded application/json reviewed text is accepted.', 415)
            try:
                length = int(self.headers.get('Content-Length', '0'))
            except ValueError:
                length = 0
            if not 0 < length <= MAX_BODY:
                raise AppError('body_size', 'Request size is invalid; media uploads are rejected.', 413)
            self.connection.settimeout(15)
            try:
                payload = parse_json(self.rfile.read(length))
            except (ValueError, UnicodeError, RecursionError):
                raise AppError('invalid_json', 'Request must be a valid text-only JSON object.') from None
            from assessment import validate_request
            validate_request(payload)
            acquired = SLOTS.acquire(blocking=False)
            if not acquired:
                raise AppError('busy', 'One assessment is already running. Please wait.', 429)
            with RATE_LOCK:
                if time.monotonic() - LAST_REQUEST < 10:
                    raise AppError('rate_limited', 'Wait ten seconds between assessment requests.', 429)
                LAST_REQUEST = time.monotonic()
            self.respond(200, assess(payload))
        except AppError as error:
            self.respond(error.status, {'error': error.code, 'message': error.message})
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            pass
        except Exception:
            self.respond(500, {'error': 'internal_error', 'message': 'The request could not be completed. No assessment was created.'})
        finally:
            if acquired:
                SLOTS.release()


if __name__ == '__main__':
    load_env()
    host, port = os.environ.get('HOST', '127.0.0.1'), int(os.environ.get('PORT', '8000'))
    if host not in ('127.0.0.1', 'localhost') and not os.environ.get('APP_ACCESS_TOKEN'):
        raise SystemExit('Set APP_ACCESS_TOKEN before binding to a public interface.')
    server = ThreadingHTTPServer((host, port), Handler)
    print(f'Class Evidence running at http://{host}:{port}. Request/response logging is disabled.', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
