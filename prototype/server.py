"""Dev server for the Casidra onboarding design prototype.

Serves the static prototype in this directory on port 3000 (the port the
sandbox preview displays) and adds the two conveniences a plain static server
lacks:

* ``<!-- @include path/to/file.html -->`` server-side includes, so the shared
  app shell (head assets, sidebar, topbar, icons, dialogs) lives in exactly one
  file per partial -- the same split this prototype will use as Django
  ``{% include %}`` / template inheritance later on.
* live reload: ``/__reload`` is a Server-Sent Events stream that watches the
  prototype tree and tells the browser to reload when a file changes, so edits
  appear without a manual refresh.

Standard library only: no build step, no dependencies to install.
"""

from __future__ import annotations

import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PORT = 3000

INCLUDE_RE = re.compile(r"<!--\s*@include\s+([A-Za-z0-9_./-]+)\s*-->")
MAX_INCLUDE_DEPTH = 5
WATCH_INTERVAL = 1.0


def _snapshot() -> dict[str, float]:
    """Modification times of every file in the prototype tree."""
    stamps: dict[str, float] = {}
    for path in ROOT.rglob("*"):
        if path.is_file():
            try:
                stamps[str(path)] = path.stat().st_mtime
            except OSError:
                pass
    return stamps


def render(path: Path, depth: int = 0) -> str:
    """Read an HTML file, expanding ``@include`` directives recursively."""
    text = path.read_text(encoding="utf-8")

    def expand(match: re.Match[str]) -> str:
        name = match.group(1)
        target = (ROOT / name).resolve()
        if depth >= MAX_INCLUDE_DEPTH or ROOT not in target.parents or not target.is_file():
            return f"<!-- unresolved include: {name} -->"
        return render(target, depth + 1)

    return INCLUDE_RE.sub(expand, text)


class Handler(BaseHTTPRequestHandler):
    server_version = "CasidraPrototype/1.0"
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802 (stdlib naming)
        route = self.path.split("?", 1)[0].split("#", 1)[0]
        if route == "/__reload":
            self._stream_reloads()
            return
        self._serve(route, head_only=False)

    def do_HEAD(self) -> None:  # noqa: N802 (stdlib naming)
        self._serve(self.path.split("?", 1)[0], head_only=True)

    # -- static files ------------------------------------------------------

    def _serve(self, route: str, head_only: bool) -> None:
        relative = route.lstrip("/") or "index.html"
        target = (ROOT / relative).resolve()
        if target.is_dir():
            target = target / "index.html"
        if ROOT not in target.parents or not target.is_file():
            self._send(404, "text/plain; charset=utf-8", "404 Not found", head_only)
            return

        if target.suffix == ".html":
            body = render(target)
            content_type = "text/html; charset=utf-8"
        else:
            body = target.read_text(encoding="utf-8", errors="replace")
            content_type = self._content_type(target)

        self._send(200, content_type, body, head_only)

    @staticmethod
    def _content_type(path: Path) -> str:
        suffix = path.suffix.lower()
        return {
            ".css": "text/css; charset=utf-8",
            ".js": "text/javascript; charset=utf-8",
            ".json": "application/json; charset=utf-8",
            ".svg": "image/svg+xml",
            ".html": "text/html; charset=utf-8",
        }.get(suffix, "text/plain; charset=utf-8")

    def _send(self, status: int, content_type: str, body: str, head_only: bool) -> None:
        payload = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        # The prototype is edited live: never let a browser cache a page.
        self.send_header("Cache-Control", "no-store, must-revalidate")
        self.end_headers()
        if not head_only:
            try:
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError):
                pass

    # -- live reload -------------------------------------------------------

    def _stream_reloads(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        def send(chunk: str) -> None:
            self.wfile.write(chunk.encode("utf-8"))
            self.wfile.flush()

        try:
            send(": connected\n\n")
            last = _snapshot()
            while True:
                time.sleep(WATCH_INTERVAL)
                current = _snapshot()
                if current != last:
                    last = current
                    send("data: reload\n\n")
                else:
                    send(": ping\n\n")
        except (BrokenPipeError, ConnectionResetError, OSError):
            return


def main() -> None:
    httpd = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Casidra prototype running at http://0.0.0.0:{PORT} (live reload on)", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
