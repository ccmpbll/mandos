"""Login like ulmo's: users with hashed passwords, a signed session cookie, a first-run /setup page, MANDOS_DISABLE_AUTH to turn it off.
The session carries a piece of the password hash, so changing a password logs out every other session of that user."""
import os
import secrets
import threading
import time
from datetime import timedelta
from html import escape as esc

from flask import Response, redirect, request, session
from werkzeug.security import check_password_hash, generate_password_hash

import config
import db

OPEN = ("/login", "/setup", "/healthz", "/static/", "/api/")
MIN_PW = 10
TRIES, WINDOW = 10, 15 * 60          # failed logins per address and username, per 15 minutes
_fails = {}
_lock = threading.Lock()


def secret_key():
    """Kept next to the database, made on first start."""
    p = os.path.join(os.path.dirname(os.path.abspath(config.DB_PATH)) if config.DB_PATH != ":memory:" else config.HERE, "session.key")
    if config.DB_PATH == ":memory:":
        return "test-only-key"
    if not os.path.exists(p):
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.write(fd, secrets.token_hex(32).encode())
        os.close(fd)
    return open(p).read().strip()


def users():
    return db.rows("users", order="id ASC")


def user_by_name(name):
    r = db.rows("users", "username=?", (name,), limit=1)
    return r[0] if r else None


def _tag(u):
    return u["pw_hash"][-12:]


def current():
    """The logged-in user row, or None."""
    uid = session.get("uid")
    if not uid:
        return None
    u = db.get("users", uid)
    return u if u and session.get("v") == _tag(u) else None


def login_as(u):
    session.clear()
    session.permanent = True
    session["uid"], session["v"] = u["id"], _tag(u)


def safe_next(n):
    return n if n and n.startswith("/") and not n.startswith("//") and "\\" not in n else "/"


def _limited(key):
    now = time.time()
    with _lock:
        _fails[key] = [t for t in _fails.get(key, []) if now - t < WINDOW]
        return len(_fails[key]) >= TRIES


def _failed(key):
    with _lock:
        _fails.setdefault(key, []).append(time.time())


def check_password(pw, pw2):
    if len(pw) < MIN_PW:
        return f"Use at least {MIN_PW} characters."
    if pw != pw2:
        return "The passwords do not match."
    return None


def card(title, inner, status=200):
    html = ('<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="noindex">'
            '<title>' + esc(title) + ' - Mandos</title><link rel="icon" href="/static/logo.png?v=3"><link rel="stylesheet" href="/static/style.css"></head><body>'
            '<main class="container"><div class="auth-card"><img class="logo" src="/static/logo-large.png?v=3" alt="Mandos">' + inner + "</div></main></body></html>")
    return Response(html, status=status, mimetype="text/html")


def install(app):
    app.secret_key = secret_key()
    app.config.update(SESSION_COOKIE_NAME="mandos_session", SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                      SESSION_COOKIE_SECURE=os.environ.get("MANDOS_INSECURE_COOKIE") != "1", PERMANENT_SESSION_LIFETIME=timedelta(days=30))

    @app.before_request
    def gate():
        if config.DISABLE_AUTH or request.path.startswith(OPEN):
            return None
        if not users():
            return redirect("/setup", 303)
        if current():
            return None
        if request.method != "GET":
            return Response("log in first", status=401, mimetype="text/plain")
        return redirect("/login?next=" + request.full_path.rstrip("?"), 303)

    @app.get("/setup")
    def setup_page(error=None, name=""):
        if users():
            return redirect("/login", 303)
        return card("Initial setup", '<h1>Welcome to Mandos</h1><p class="muted">Create the first admin account to get started.</p>'
                    + ('<p class="error">' + esc(error) + "</p>" if error else "")
                    + '<form class="std" method="post" action="/setup"><label>Username<input name="username" value="' + esc(name) + '" autocomplete="username" required autofocus></label>'
                    '<label>Password<input type="password" name="password" autocomplete="new-password" required></label>'
                    '<label>Confirm password<input type="password" name="password2" autocomplete="new-password" required></label><button type="submit">Create account</button></form>',
                    400 if error else 200)

    @app.post("/setup")
    def setup_save():
        if users():
            return redirect("/login", 303)
        name = request.form.get("username", "").strip()
        err = "Pick a username." if not name else check_password(request.form.get("password", ""), request.form.get("password2", ""))
        if err:
            return setup_page(err, name)
        db.insert("users", {"username": name, "pw_hash": generate_password_hash(request.form["password"])})
        login_as(user_by_name(name))
        return redirect("/", 303)

    @app.get("/login")
    def login_page(error=None, name=""):
        if not config.DISABLE_AUTH and not users():
            return redirect("/setup", 303)
        nxt = safe_next(request.values.get("next"))
        return card("Log in", "<h1>Mandos</h1>" + ('<p class="error">' + esc(error) + "</p>" if error else "")
                    + '<form class="std" method="post" action="/login"><input type="hidden" name="next" value="' + esc(nxt) + '">'
                    '<label>Username<input name="username" value="' + esc(name) + '" autocomplete="username" required' + ("" if name else " autofocus") + '></label>'
                    '<label>Password<input type="password" name="password" autocomplete="current-password" required' + (" autofocus" if name else "") + '></label>'
                    '<button type="submit">Log in</button></form>', 401 if error else 200)

    @app.post("/login")
    def login_post():
        name = request.form.get("username", "").strip()
        key = (request.remote_addr, name.lower())
        if _limited(key):
            return login_page("Too many tries. Wait 15 minutes.", name)
        u = user_by_name(name)
        if not u or not check_password_hash(u["pw_hash"], request.form.get("password", "")):
            _failed(key)
            return login_page("Wrong username or password.", name)
        login_as(u)
        return redirect(safe_next(request.form.get("next")), 303)

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect("/login", 303)
