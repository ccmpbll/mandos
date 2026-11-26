"""The web frame (top bar, user menu), Runs, Jobs and the pack editor. The pack's own pages are served from pack.ROUTES, looked up
per request so an edit applies at once. ulmo's stylesheet (static/style.css). Every dynamic string is escaped."""
import html
import json

from flask import Flask, Response, redirect, request

import codeedit
import config
import db
import jobs_page
import packs
from version import VERSION

app = Flask(__name__, static_folder="static", static_url_path="/static")
import auth  # noqa: E402
auth.install(app)
RUNS = "/runs"


def esc(s):
    return html.escape("" if s is None else str(s), quote=True)


def arr(s):
    """A JSON list stored as text, or []."""
    try:
        v = json.loads(s or "[]")
        return v if isinstance(v, list) else []
    except (ValueError, TypeError):
        return []


def user_menu(active):
    u = None if config.DISABLE_AUTH else auth.current()
    ver = '<div class="ver">Mandos ' + esc(VERSION) + " · pack " + esc(codeedit.fingerprint()) + " · " + esc(config.MODE) + "</div>"
    settings_link = '<a href="/settings/model"' + (' aria-current="page"' if active == "settings" else "") + ">Settings</a>"
    if u:
        name = u["username"]
        btn = ('<span class="avatar">' + esc(name[:1].upper()) + '</span><span class="uname">' + esc(name) + "</span>")
        items = settings_link + '<div class="sep"></div><form method="post" action="/logout"><button type="submit">Log out</button></form>'
    else:
        btn, items = '<span class="avatar">⚙</span><span class="uname">Menu</span>', settings_link
    return ('<div class="usermenu"><button type="button" class="usermenu-btn" aria-haspopup="true" aria-expanded="false" aria-controls="user-menu">' + btn
            + '<span class="caret" aria-hidden="true">▾</span></button><div class="menu" id="user-menu">' + items + '<div class="sep"></div>' + ver + "</div></div>")


def nav_items():
    """The pack's tabs (label, path, key, count) then Runs and Jobs."""
    out = []
    for item in packs.get("NAV", []) or []:
        label, path, key, fn = (list(item) + [None, None, None])[:4]
        try:
            n = fn() if fn else 0
        except Exception:  # noqa: BLE001
            n = 0
        out.append((label, path, key, n))
    return out + [("Runs", RUNS, "runs", 0), ("Jobs", "/jobs", "jobs", 0)]


def home():
    return packs.get("HOME", "/jobs") or "/jobs"


def page(title, active, body, js=""):
    items = nav_items()
    total = sum(i[3] for i in items)

    def link(label, href, key, n):
        return ('<a href="' + esc(href) + '"' + (' class="active" aria-current="page"' if active == key else "") + (" data-attn" if n else "") + ">" + esc(label)
                + (' <span class="navcount">' + str(n) + "</span>" if n else "") + "</a>")
    nav = ('<header class="topbar"><a class="brand" href="' + esc(home()) + '"><img class="mark" src="/static/logo.png?v=4" alt="">Mandos</a>'
           '<input type="checkbox" id="nav-toggle" class="nav-toggle" aria-label="Show the menu"><label for="nav-toggle" class="menu-btn">Menu'
           + (' <span class="navcount">' + str(total) + "</span>" if total else "") + "</label><nav>" + "".join(link(*i) for i in items)
           + '</nav><span class="spacer"></span>' + user_menu(active) + "</header>")
    return ('<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
            '<meta name="robots" content="noindex"><title>' + esc(title) + '</title><link rel="icon" href="/static/favicon.png?v=5"><link rel="stylesheet" href="/static/style.css"></head><body>'
            + nav + '<main class="container">' + body + '</main><script src="/static/menu.js"></script>' + ("<script>" + js + "</script>" if js else "") + "</body></html>")


def html_page(title, active, body, js="", status=200):
    return Response(page(title, active, body, js), status=status, mimetype="text/html")


@app.get("/")
def root():
    return redirect(home())


# ================================================================ run history
@app.get(RUNS)
def runs():
    rows = db.rows("job_runs", limit=60)
    titles = {n: j.get("title", n) for n, j in packs.jobs().items()}
    out = "".join(
        '<div class="playbook-row"><div class="playbook-row-header"><a class="playbook-name" href="/jobs/' + esc(r["job"]) + '">' + esc(titles.get(r["job"], r["job"]))
        + '</a><span class="badge ' + ("ok" if r["status"] == "success" else "crit" if r["status"] == "failed" else "warn") + '">' + esc(r["status"]) + "</span></div>"
        + '<div class="playbook-facts"><span class="fact">' + esc(r["started"] or "") + "</span>" + ('<span class="fact">' + esc(_took(r)) + "</span>" if _took(r) else "") + "</div>"
        + ('<p class="dim small" style="margin:4px 0 0">' + esc(r["detail"]) + "</p>" if r.get("detail") else "")
        + ("<details style=\"margin:6px 0 0;font-size:.85rem\"><summary>Log</summary><pre>" + esc(r["log"]) + "</pre></details>" if r.get("log") else "") + "</div>"
        for r in rows)
    body = (jobs_page.CSS + '<div class="page-header"><div><h1>Runs</h1><p class="sub">The last 60 job runs (mode: ' + esc(config.MODE) + ").</p></div></div>"
            + ('<div class="card flush">' + out + "</div>" if out else '<p class="dim">No runs yet.</p>'))
    return html_page("Runs - Mandos", "runs", body)


def _took(r):
    try:
        from datetime import datetime
        s = int((datetime.fromisoformat(r["finished"]) - datetime.fromisoformat(r["started"])).total_seconds())
    except (TypeError, ValueError):
        return ""
    return "took " + (f"{s // 60}m {s % 60}s" if s >= 60 else f"{s}s")


# ================================================================ jobs and the pack editor
@app.get("/jobs")
def jobs_list():
    return html_page("Jobs - Mandos", "jobs", jobs_page.render_list())


@app.get("/jobs/<name>")
def jobs_detail(name):
    if name not in packs.jobs():
        return Response("no such job", status=404, mimetype="text/plain")
    body, js = jobs_page.render_job(name, request.args.get("file"))
    return html_page(packs.jobs()[name].get("title", name) + " - Mandos", "jobs", body, js)


def _editable(rel):
    return config.ALLOW_EDIT and codeedit.safe(rel)


def _refuse():
    return Response("editing is off or not allowed for this file", status=403, mimetype="text/plain")


@app.get("/edit")
def edit_page():
    rel = request.args.get("file", "")
    if not _editable(rel):
        return _refuse()
    return html_page("Edit " + rel + " - Mandos", "jobs", jobs_page.render_edit(codeedit.safe(rel), saved=request.args.get("saved") == "1"), jobs_page.EDIT_JS)


@app.post("/edit")
def edit_save():
    rel = request.form.get("file", "")
    if not _editable(rel):
        return _refuse()
    text = request.form.get("text", "")
    err = codeedit.save(rel, text)
    if err:
        return html_page("Edit " + rel + " - Mandos", "jobs", jobs_page.render_edit(codeedit.safe(rel), text, err), jobs_page.EDIT_JS, 400)
    packs.load()
    return redirect("/edit?file=" + jobs_page.q(codeedit.safe(rel)) + "&saved=1", 303)


@app.post("/edit/restore")
def edit_restore():
    rel = request.form.get("file", "")
    if not _editable(rel):
        return _refuse()
    err = codeedit.restore(rel, request.form.get("version", ""))
    if err:
        return html_page("Edit " + rel + " - Mandos", "jobs", jobs_page.render_edit(codeedit.safe(rel), error=err), jobs_page.EDIT_JS, 400)
    packs.load()
    return redirect("/edit?file=" + jobs_page.q(codeedit.safe(rel)) + "&saved=1", 303)


@app.get("/favicon.ico")
def favicon():
    return app.send_static_file("favicon.png")


@app.get("/healthz")
def healthz():
    return {"ok": True, "version": VERSION, "mode": config.MODE, "pack_error": bool(packs.error)}


import api  # noqa: E402
import settings_page  # noqa: E402
api.install(app)
settings_page.install(app, page)


# ================================================================ the pack's pages
@app.route("/<path:p>", methods=["GET", "POST"])
def pack_page(p):
    f = (packs.get("ROUTES", {}) or {}).get((request.method, "/" + p))
    if not f:
        return Response("not found", status=404, mimetype="text/plain")
    r = f()
    return Response(r, mimetype="text/html") if isinstance(r, str) else r
