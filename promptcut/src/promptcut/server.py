"""Self-hosted browser UI: a stdlib HTTP server over the project directory.

    promptcut serve            # http://127.0.0.1:7859

Endpoints:
  GET  /                  UI
  GET  /api/project       project.json
  POST /api/project       save project.json (validated)
  GET  /api/status        timeline summary
  GET  /api/looks         looks / transitions / caption styles
  POST /api/render        {"mode": "preview"|"final"}  (blocks until done)
  GET  /media/... /render/...   file serving (range requests supported)
"""

import json
import mimetypes
import os
import re
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import captions as cap
from . import compiler, ffmpeg as ff, looks
from . import project as prj

STATIC = Path(__file__).parent / "static"
RENDER_LOCK = threading.Lock()


def make_handler(root):
    root = Path(root)

    token = os.environ.get("PROMPTCUT_TOKEN") or None

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *a):
            pass

        # ---------------- auth (enabled when PROMPTCUT_TOKEN is set)
        def _authorized(self):
            if not token:
                return True
            q = parse_qs(urlparse(self.path).query)
            supplied = (q.get("token", [None])[0]
                        or (self.headers.get("Authorization", "")
                            .removeprefix("Bearer ").strip() or None))
            cookie = self.headers.get("Cookie", "")
            m = re.search(r"pc_token=([A-Za-z0-9_\-]+)", cookie)
            if m and secrets.compare_digest(m.group(1), token):
                return True
            if supplied and secrets.compare_digest(supplied, token):
                self._set_cookie = True
                return True
            return False

        def _deny(self):
            body = (b"401 \xe2\x80\x94 PromptCut is token-protected. "
                    b"Open /?token=YOUR_TOKEN (see PROMPTCUT_TOKEN on the server).")
            self.send_response(401)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def end_headers(self):
            if getattr(self, "_set_cookie", False) and token:
                self.send_header("Set-Cookie",
                                 f"pc_token={token}; Path=/; HttpOnly; SameSite=Strict")
                self._set_cookie = False
            super().end_headers()

        # ---------------- helpers
        def _json(self, obj, code=200):
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _err(self, msg, code=400):
            self._json({"error": str(msg)}, code)

        def _file(self, path):
            path = Path(path)
            if not path.exists() or not path.is_file():
                return self._err("not found", 404)
            size = path.stat().st_size
            ctype = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
            rng = self.headers.get("Range")
            if rng:
                m = re.match(r"bytes=(\d+)-(\d*)", rng)
                start = int(m.group(1))
                end = int(m.group(2)) if m.group(2) else size - 1
                end = min(end, size - 1)
                self.send_response(206)
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(end - start + 1))
                self.end_headers()
                with open(path, "rb") as f:
                    f.seek(start)
                    self.wfile.write(f.read(end - start + 1))
            else:
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Length", str(size))
                self.end_headers()
                with open(path, "rb") as f:
                    while chunk := f.read(1 << 16):
                        self.wfile.write(chunk)

        def _body(self):
            n = int(self.headers.get("Content-Length", 0))
            return json.loads(self.rfile.read(n) or b"{}")

        # ---------------- routes
        def do_HEAD(self):
            if not self._authorized():
                return self._deny()
            p = self.path.split("?")[0]
            target = None
            if p.startswith("/media/") or p.startswith("/render/"):
                target = (root / p.lstrip("/")).resolve()
            elif p == "/" or p == "/index.html":
                target = STATIC / "index.html"
            if target and target.exists() and target.is_file():
                self.send_response(200)
                self.send_header("Content-Length", str(target.stat().st_size))
                self.send_header("Accept-Ranges", "bytes")
                self.end_headers()
            else:
                self.send_response(404)
                self.end_headers()

        def do_GET(self):
            if not self._authorized():
                return self._deny()
            p = self.path.split("?")[0]
            try:
                if p == "/" or p == "/index.html":
                    return self._file(STATIC / "index.html")
                if p.startswith("/static/"):
                    return self._file(STATIC / p[len("/static/"):])
                if p == "/api/project":
                    return self._json(prj.load(root))
                if p == "/api/status":
                    proj = prj.load(root)
                    starts = prj.clip_start_times(proj)
                    return self._json({
                        "duration": prj.timeline_duration(proj),
                        "starts": starts,
                        "clip_durations": [prj.clip_duration(c)
                                           for c in proj["timeline"]["video"]]})
                if p == "/api/looks":
                    return self._json({"looks": sorted(looks.LOOKS),
                                       "transitions": sorted(prj.TRANSITIONS),
                                       "caption_styles": list(cap.STYLES)})
                if p.startswith("/media/") or p.startswith("/render/"):
                    safe = (root / p.lstrip("/")).resolve()
                    if root.resolve() not in safe.parents and safe != root.resolve():
                        return self._err("forbidden", 403)
                    return self._file(safe)
                return self._err("not found", 404)
            except Exception as e:  # noqa: BLE001
                return self._err(e, 500)

        def do_POST(self):
            if not self._authorized():
                return self._deny()
            p = self.path.split("?")[0]
            try:
                if p == "/api/project":
                    proj = self._body()
                    prj.validate(proj, root)
                    prj.save(proj, root)
                    return self._json({"saved": True,
                                       "duration": prj.timeline_duration(proj)})
                if p == "/api/render":
                    mode = self._body().get("mode", "preview")
                    if not RENDER_LOCK.acquire(blocking=False):
                        return self._err("a render is already running", 409)
                    try:
                        proj = prj.load(root)
                        out = compiler.render(proj, root, mode=mode)
                        info = ff.probe(out)
                    finally:
                        RENDER_LOCK.release()
                    return self._json({"output": f"/render/{Path(out).name}",
                                       "duration": info["duration"]})
                return self._err("not found", 404)
            except Exception as e:  # noqa: BLE001
                return self._err(e, 500)

    return Handler


def serve(root, host="127.0.0.1", port=7859):
    prj.load(root)  # fail fast if no project here
    httpd = ThreadingHTTPServer((host, port), make_handler(root))
    tok = os.environ.get("PROMPTCUT_TOKEN")
    url = f"http://{host}:{port}" + (f"/?token={tok}" if tok else "")
    print(f"PromptCut UI → {url}  (project: {root})")
    if host not in ("127.0.0.1", "localhost") and not tok:
        print("WARNING: serving on a non-local interface without PROMPTCUT_TOKEN — "
              "anyone who can reach this port can edit and render. "
              "Set PROMPTCUT_TOKEN=<random string> to protect it.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
