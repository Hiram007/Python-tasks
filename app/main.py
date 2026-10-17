"""Minimal web runner for this repo's Python practice scripts.

Every .py file at the repo root is an interactive CLI script: it asks the user
for input() and prints results. The sandbox preview can only display a web page
on port 3000, so this small stdlib-style ASGI app lists the scripts, collects
the answers each one asks for, runs it in a subprocess and returns its output.

No third-party runtime dependency beyond the uvicorn server itself.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX = Path(__file__).resolve().parent / "static" / "index.html"

INPUT_RE = re.compile(r"\binput\s*\(")
RUN_TIMEOUT = 10


def _summary(source: str) -> str:
    """First comment line of a script, used as a one-line description."""
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") and not stripped.startswith("#!"):
            return stripped.lstrip("#").strip()
    return ""


def list_scripts() -> list[dict]:
    scripts = []
    for path in sorted(ROOT.glob("*.py")):
        source = path.read_text(encoding="utf-8", errors="replace")
        scripts.append(
            {
                "name": path.name,
                "inputs": len(INPUT_RE.findall(source)),
                "summary": _summary(source),
                "source": source,
            }
        )
    return scripts


def _resolve_script(name: str) -> Path | None:
    """Only allow running the repo's own top-level scripts."""
    candidate = (ROOT / name).resolve()
    if candidate.parent != ROOT or candidate.suffix != ".py" or not candidate.is_file():
        return None
    return candidate


def run_script(name: str, answers: list[str]) -> dict:
    path = _resolve_script(name)
    if path is None:
        return {"error": f"Unknown script: {name}"}

    stdin_text = "\n".join(str(a) for a in answers) + "\n"
    try:
        proc = subprocess.run(
            [sys.executable, str(path)],
            input=stdin_text,
            capture_output=True,
            text=True,
            timeout=RUN_TIMEOUT,
            cwd=ROOT,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or "",
            "returncode": None,
            "timed_out": True,
        }

    return {
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "returncode": proc.returncode,
        "timed_out": False,
    }


async def _read_body(receive) -> bytes:
    body = b""
    while True:
        message = await receive()
        if message["type"] == "http.request":
            body += message.get("body", b"")
            if not message.get("more_body"):
                return body
        elif message["type"] == "http.disconnect":
            return body


async def _respond(send, status: int, content_type: str, body: bytes) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", content_type.encode()),
                (b"content-length", str(len(body)).encode()),
                (b"cache-control", b"no-store"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


async def app(scope, receive, send) -> None:
    if scope["type"] != "http":
        return

    path = scope["path"].rstrip("/") or "/"
    method = scope["method"].upper()

    if method == "GET" and path == "/":
        await _respond(send, 200, "text/html; charset=utf-8", INDEX.read_bytes())
        return

    if method == "GET" and path == "/api/scripts":
        body = json.dumps(list_scripts()).encode()
        await _respond(send, 200, "application/json", body)
        return

    if method == "POST" and path == "/api/run":
        try:
            payload = json.loads(await _read_body(receive) or b"{}")
        except json.JSONDecodeError:
            await _respond(send, 400, "application/json", b'{"error":"Invalid JSON body"}')
            return
        result = run_script(str(payload.get("name", "")), list(payload.get("inputs") or []))
        status = 400 if "error" in result else 200
        await _respond(send, status, "application/json", json.dumps(result).encode())
        return

    await _respond(send, 404, "text/plain; charset=utf-8", b"Not found")
