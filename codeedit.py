"""Changing the job pack's files (Jobs page editor and the API). Paths are relative to config.JOBS_DIR.

A Python file is refused when it does not compile or its module does not import (checked in a separate python, with the new
text in place of the old); a .json file when it does not parse. Every change keeps the previous text in .history/ (last 20 per
file) so it can be restored. The pack reloads on its own at the next run or page view (packs.load sees the new mtime)."""
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime

import config
import packs

KEEP = 20
TEXT_TYPES = (".py", ".txt", ".json", ".j2", ".md", ".yml", ".yaml", ".csv", ".sql", ".html", ".css", ".js")
MAX_BYTES = 2_000_000


def safe(rel):
    """The normalised relative path, or None when it would leave the pack folder, is hidden, or is not a text type we keep."""
    rel = (rel or "").replace("\\", "/").strip("/")
    parts = rel.split("/")
    if not rel or any(p in ("", ".", "..") or p.startswith(".") for p in parts) or parts[0] in packs.SKIP_DIRS:
        return None
    if not rel.endswith(TEXT_TYPES):
        return None
    return rel


def path(rel):
    return os.path.join(config.JOBS_DIR, rel)


def hist_dir():
    return os.path.join(config.JOBS_DIR, ".history")


def _hist_name(rel):
    return rel.replace("/", "__")


def read(rel):
    rel = safe(rel)
    if not rel or not os.path.isfile(path(rel)):
        return None
    return open(path(rel), encoding="utf-8").read()


def check(rel, text):
    """None when the text is fine; otherwise the error to show."""
    if rel.endswith(".json"):
        try:
            json.loads(text)
        except ValueError as e:
            return "not valid JSON: " + str(e)[:200]
        return None
    if not rel.endswith(".py"):
        return None
    try:
        compile(text, rel, "exec")
    except SyntaxError as e:
        return f"line {e.lineno}: {e.msg}"
    mod = rel[:-3].replace("/", ".")
    tmp = path(rel) + ".check"
    code = ("import sys,importlib.util,importlib.machinery as im;sys.path[:0]=[" + repr(config.HERE) + "," + repr(os.path.abspath(config.JOBS_DIR)) + "];"
            "ld=im.SourceFileLoader(" + repr(mod) + "," + repr(tmp) + ");spec=importlib.util.spec_from_loader(" + repr(mod) + ",ld);"
            "m=importlib.util.module_from_spec(spec);sys.modules[" + repr(mod) + "]=m;ld.exec_module(m)")
    try:
        os.makedirs(os.path.dirname(tmp), exist_ok=True)
        open(tmp, "w", encoding="utf-8").write(text)
        r = subprocess.run([sys.executable, "-c", code], cwd=config.JOBS_DIR, capture_output=True, text=True, timeout=30,
                           env={**os.environ, "MANDOS_DB": ":memory:"})
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    if r.returncode:
        return (r.stderr.strip().splitlines() or ["import failed"])[-1][:400]
    return None


def history(rel):
    d = hist_dir()
    h = _hist_name(rel) + "."
    if not os.path.isdir(d):
        return []
    return sorted((f for f in os.listdir(d) if f.startswith(h) and f[len(h):].count(".") == 1), reverse=True)


def _keep_old(rel):
    if not os.path.isfile(path(rel)):
        return
    os.makedirs(hist_dir(), exist_ok=True)
    ext = os.path.splitext(rel)[1]
    open(os.path.join(hist_dir(), f"{_hist_name(rel)}.{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}{ext}"), "w", encoding="utf-8").write(
        open(path(rel), encoding="utf-8").read())
    for f in history(rel)[KEEP:]:
        os.remove(os.path.join(hist_dir(), f))


def save(rel, text):
    """Write a file (new or changed). Returns None or the reason it was refused."""
    rel = safe(rel)
    if not rel:
        return "not an allowed path (relative, no hidden parts, a text file type)"
    if len(text.encode("utf-8")) > MAX_BYTES:
        return "too large"
    text = text.replace("\r\n", "\n")
    if text and not text.endswith("\n"):
        text += "\n"
    err = check(rel, text)
    if err:
        return err
    if read(rel) == text:
        return None
    _keep_old(rel)
    os.makedirs(os.path.dirname(path(rel)) or config.JOBS_DIR, exist_ok=True)
    tmp = path(rel) + ".new"
    open(tmp, "w", encoding="utf-8").write(text)
    os.replace(tmp, path(rel))
    return None


def delete(rel):
    rel = safe(rel)
    if not rel or not os.path.isfile(path(rel)):
        return "no such file"
    if rel == "pack.py":
        return "pack.py is the manifest; replace it instead"
    _keep_old(rel)
    os.remove(path(rel))
    return None


def restore(rel, name):
    rel = safe(rel)
    if not rel or name not in history(rel):
        return "no such version"
    return save(rel, open(os.path.join(hist_dir(), name), encoding="utf-8").read())


def sha(rel):
    return hashlib.sha256(open(path(rel), "rb").read()).hexdigest()


def fingerprint():
    h = hashlib.sha256()
    for f in packs.files():
        h.update(f.encode() + open(path(f), "rb").read())
    return h.hexdigest()[:8]
