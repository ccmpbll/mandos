"""/api/v1: what Claude Code (or any script) uses to set mandos up and change it. Bearer tokens are made on the Settings page
(Account tab); only a hash is stored. Every call needs one, also when the login is off.

  GET    /api/v1/status                 mode, pack state (loaded, error, fingerprint), jobs and their schedules
  GET    /api/v1/files                  the pack's files [{path, size, sha256}]
  GET    /api/v1/files/<path>           one file (text)
  PUT    /api/v1/files/<path>           write it (body = the text); refused with 400 when Python does not import or JSON does not parse
  DELETE /api/v1/files/<path>           remove it (kept in the history)
  GET    /api/v1/settings               every setting: value (secrets: set or not) and source (env, saved, default)
  PATCH  /api/v1/settings               {"KEY": "value", "OTHER": null}  null clears a saved value
  POST   /api/v1/jobs/<name>/run        start a run (202), or 409 while it runs
  GET    /api/v1/runs?job=&limit=       recent runs, without logs
  GET    /api/v1/runs/<id>              one run with its log
  GET    /api/v1/tables                 the pack's tables
  GET    /api/v1/tables/<name>?limit=   newest rows of one (read only)
"""
import hashlib
import os
import secrets

from flask import Response, jsonify, request

import codeedit
import config
import db
import packs
import runner
import settings

PRIVATE_TABLES = {"users", "api_tokens", "settings"}


def _hash(t):
    return hashlib.sha256(t.encode()).hexdigest()


def new_token(name):
    """Returns the token text; shown once."""
    t = "mandos_" + secrets.token_urlsafe(32)
    db.insert("api_tokens", {"name": name[:60] or "token", "token_hash": _hash(t)})
    return t


def tokens():
    return db.rows("api_tokens", order="id ASC")


def _authorised():
    h = request.headers.get("Authorization", "")
    if not h.startswith("Bearer "):
        return False
    r = db.rows("api_tokens", "token_hash=?", (_hash(h[7:].strip()),), limit=1)
    if not r:
        return False
    db.update("api_tokens", r[0]["id"], {"last_used": db.now_iso()})
    return True


def _err(msg, status):
    return jsonify(error=msg), status


def install(app):
    @app.before_request
    def api_gate():
        if request.path.startswith("/api/") and not _authorised():
            return _err("a valid API token is needed (Authorization: Bearer ...)", 401)

    @app.get("/api/v1/status")
    def api_status():
        packs.load()
        return jsonify(mode=config.MODE, jobs_dir=config.JOBS_DIR, pack_loaded=bool(packs.jobs()) or not packs.error, pack_error=packs.error,
                       fingerprint=codeedit.fingerprint(), running=runner.running(),
                       jobs={n: {"title": j.get("title", n), "schedule": settings.cron(n)} for n, j in packs.jobs().items()})

    @app.get("/api/v1/files")
    def api_files():
        return jsonify([{"path": f, "size": os.path.getsize(codeedit.path(f)), "sha256": codeedit.sha(f)} for f in packs.files()])

    @app.get("/api/v1/files/<path:rel>")
    def api_file_get(rel):
        t = codeedit.read(rel)
        return _err("no such file", 404) if t is None else Response(t, mimetype="text/plain; charset=utf-8")

    @app.put("/api/v1/files/<path:rel>")
    def api_file_put(rel):
        err = codeedit.save(rel, request.get_data(as_text=True))
        if err:
            return _err(err, 400)
        packs.load()
        return jsonify(ok=True, path=codeedit.safe(rel), sha256=codeedit.sha(codeedit.safe(rel)), pack_error=packs.error)

    @app.delete("/api/v1/files/<path:rel>")
    def api_file_delete(rel):
        err = codeedit.delete(rel)
        if err:
            return _err(err, 404 if err == "no such file" else 400)
        packs.load()
        return jsonify(ok=True, pack_error=packs.error)

    @app.get("/api/v1/settings")
    def api_settings():
        return jsonify(settings.public())

    @app.patch("/api/v1/settings")
    def api_settings_patch():
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return _err("send a JSON object", 400)
        known = settings.by_key()
        unknown = [k for k in body if k not in known]
        if unknown:
            return _err("unknown settings: " + ", ".join(unknown), 400)
        errs = settings.save({k: v for k, v in body.items() if v is not None}, [k for k, v in body.items() if v is None])
        if errs:
            return _err("; ".join(errs), 400)
        runner.reschedule()
        return jsonify(settings.public())

    @app.post("/api/v1/jobs/<name>/run")
    def api_run(name):
        if name not in packs.jobs():
            return _err("no such job", 404)
        if name in runner.running():
            return _err("already running", 409)
        runner.start(name)
        return jsonify(started=name), 202

    @app.get("/api/v1/runs")
    def api_runs():
        job = request.args.get("job")
        limit = min(int(request.args.get("limit", 20) or 20), 200)
        rows = db.rows("job_runs", "job=?" if job else "", (job,) if job else (), limit=limit)
        return jsonify([{k: v for k, v in r.items() if k != "log"} for r in rows])

    @app.get("/api/v1/runs/<int:rid>")
    def api_run_one(rid):
        r = db.get("job_runs", rid)
        return jsonify(r) if r else _err("no such run", 404)

    def pack_tables():
        with db.conn() as c:
            names = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        return [n for n in names if n not in PRIVATE_TABLES and not n.startswith("sqlite_")]

    @app.get("/api/v1/tables")
    def api_tables():
        return jsonify(pack_tables())

    @app.get("/api/v1/tables/<name>")
    def api_table(name):
        if name not in pack_tables():
            return _err("no such table", 404)
        limit = min(int(request.args.get("limit", 20) or 20), 500)
        return jsonify(db.rows(name, limit=limit))
