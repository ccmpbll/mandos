"""The job pack: everything specific to one installation (its jobs, prompts, queries, pages, extra settings) lives in
config.JOBS_DIR, never in the image. The pack's manifest is pack.py there:

  JOBS = {"name": {"title": ..., "about": ..., "run": callable(log), "schedule": {"shadow": "cron", "live": "cron"},
                   "steps": [(title, "module.function", what it does, "model"|"guard"|"")], "prompts": [(label, file, target|None)],
                   "queries": "file.json" or None, "cron_key": optional settings name (default CRON_<NAME>)}}
  SCHEMA = "CREATE TABLE IF NOT EXISTS ..."          tables the jobs write
  SETTINGS = [(KEY, label, secret, default, hint)]    extra fields on the Settings page (written onto config)
  PROMPT_TARGETS = {"Analyst prompt": "analyst_system.txt"}   prompts that take owner-approved additions (promptstore)
  NAV = [(label, path, key, count_fn or None)]        tabs in the top bar, before Runs and Jobs
  ROUTES = {("GET", "/report"): handler, ...}        pages, served at those paths
  HOME = "/report"                                   where the logo and / go

load() re-imports the pack when any of its files changed, so an edit (Jobs page editor, API, a copy on the share) applies at the
next run or page view without a restart. When the new code does not import, the last good pack stays in use and the error is shown."""
import importlib
import os
import sys
import threading
import traceback

import config
import db

_lock = threading.RLock()
_pack = None
_stamp = None
error = None
on_reload = []          # callbacks after a (re)load: settings, schedule
SKIP_DIRS = {".history", "__pycache__", "tests", ".venv", "export", "mockup", "tools"}


class _Empty:
    JOBS, SCHEMA, SETTINGS, PROMPT_TARGETS, NAV, ROUTES, HOME = {}, "", [], {}, [], {}, "/jobs"


def files():
    """Relative paths of the pack's files (sorted)."""
    out = []
    d = config.JOBS_DIR
    if not os.path.isdir(d):
        return out
    for root, dirs, fs in os.walk(d):
        dirs[:] = sorted(x for x in dirs if x not in SKIP_DIRS and not x.startswith("."))
        for f in sorted(fs):
            if not f.startswith(".") and not f.endswith((".pyc", ".new", ".check")):
                out.append(os.path.relpath(os.path.join(root, f), d))
    return out


def _mtimes():
    return {f: os.path.getmtime(os.path.join(config.JOBS_DIR, f)) for f in files() if f.endswith(".py")}


def _pack_module(m):
    """True for a module loaded from the pack's own files (not its tests/, tools/ and so on)."""
    d = os.path.abspath(config.JOBS_DIR) + os.sep
    f = os.path.abspath(getattr(m, "__file__", None) or "/")
    return f.startswith(d) and f[len(d):].split(os.sep)[0] not in SKIP_DIRS


def _drop_modules():
    for n, m in list(sys.modules.items()):
        if _pack_module(m):
            del sys.modules[n]


def load(force=False):
    global _pack, _stamp, error
    with _lock:
        st = _mtimes()
        if _pack is not None and not force and st == _stamp:
            return _pack
        _stamp = st
        d = os.path.abspath(config.JOBS_DIR)
        if not os.path.exists(os.path.join(d, "pack.py")):
            _drop_modules()
            _pack, error = _Empty, None
        else:
            if d not in sys.path:
                sys.path.insert(0, d)
            old = {n: m for n, m in sys.modules.items() if _pack_module(m)}
            _drop_modules()
            importlib.invalidate_caches()
            try:
                p = importlib.import_module("pack")
                if getattr(p, "SCHEMA", ""):
                    with db.conn() as c:
                        c.executescript(p.SCHEMA)
                _pack, error = p, None
            except Exception:  # noqa: BLE001
                error = traceback.format_exc(limit=4)[-1500:]
                print("job pack failed to load:\n" + error, flush=True)
                _drop_modules()
                sys.modules.update(old)          # keep running the last good pack
                if _pack is None:
                    _pack = _Empty
        for cb in on_reload:
            cb()
        return _pack


def get(name, default=None):
    return getattr(load(), name, default if default is not None else getattr(_Empty, name, None))


def jobs():
    return get("JOBS", {})


def cron_key(name):
    return jobs().get(name, {}).get("cron_key") or "CRON_" + name.upper().replace("-", "_")
