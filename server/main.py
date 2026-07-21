# -*- coding: utf-8 -*-
"""Minimal FastAPI seed for the mna service (port 8807, route /apps/mna).

Phase 2 will grow this into the solver API. For now:
  /apps/mna/                  landing page (frontend/index.html)
  /apps/mna/api/meta          identity + status (healthMatch: mna-esd-solver)
  /apps/mna/api/regression    run tests/regression.py, return result
  /apps/mna/ref/<path>.html   read-only reference HTML artifacts (root, docs/)

Run: python -m uvicorn server.main:app --host 127.0.0.1 --port 8807  (cwd = repo root)
"""
import os
import subprocess
import sys

from fastapi import FastAPI
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PREFIX = "/apps/mna"

app = FastAPI(title="mna-esd-solver", docs_url=None, redoc_url=None)


def _refs():
    out = []
    for d in (ROOT, os.path.join(ROOT, "docs")):
        for f in sorted(os.listdir(d)):
            if f.endswith(".html"):
                out.append(os.path.relpath(os.path.join(d, f), ROOT).replace("\\", "/"))
    return out


@app.get(PREFIX + "/api/meta")
def meta():
    return {
        "app": "mna-esd-solver",
        "version": "0.0.1",
        "phase": "0 — regression baseline (tests/golden.json, 50 checks)",
        "runtime": "python {} / fastapi".format(sys.version.split()[0]),
        "refs": _refs(),
    }


@app.get(PREFIX + "/api/regression")
def regression():
    p = subprocess.run(
        [sys.executable, os.path.join(ROOT, "tests", "regression.py")],
        capture_output=True, text=True, cwd=ROOT, timeout=300,
    )
    return {"exit": p.returncode, "output": (p.stdout + p.stderr).strip()}


@app.get(PREFIX + "/ref/{path:path}")
def ref(path: str):
    cand = os.path.normpath(os.path.join(ROOT, path))
    allowed = os.path.dirname(cand) in (ROOT, os.path.join(ROOT, "docs"))
    if not (cand.endswith(".html") and allowed and os.path.isfile(cand)):
        return PlainTextResponse("not found", status_code=404)
    return FileResponse(cand)


@app.get(PREFIX + "/")
@app.get(PREFIX)
def index():
    return FileResponse(os.path.join(ROOT, "frontend", "index.html"))


@app.get("/")
def root():
    return RedirectResponse(PREFIX + "/")
