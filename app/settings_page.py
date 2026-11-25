"""The Settings page (/settings/<tab>): Model, Notifications, Services (plus the job pack's own settings), Mode and schedule, Account (users, API tokens)."""
from html import escape as esc

from flask import Response, jsonify, redirect, request
from werkzeug.security import check_password_hash, generate_password_hash

import auth
import config
import db
import llm
import api
import notify
import packs
import runner
import settings
import sources

TABS = [("model", "Model"), ("notify", "Notifications"), ("services", "Services"), ("schedule", "Mode and schedule"), ("account", "Account")]


def _cur(e):
    return settings.value(e)[0] or ""


def field(e, label, hint="", options=None, placeholder=""):
    secret = settings.by_key()[e][1]
    hint_html = '<span class="muted">' + hint + "</span>" if hint else ""
    if settings.from_env(e):
        shown = "" if secret else _cur(e)
        return ('<label>' + esc(label) + (' <span class="badge ok">set</span>' if secret else "") + '<input value="' + esc(shown) + '" disabled placeholder="from '
                + e + '"><span class="muted">Set by the environment variable <code>' + e + "</code>.</span></label>")
    if secret:
        is_set = bool(_cur(e))
        return ('<label>' + esc(label) + (' <span class="badge ok">set</span>' if is_set else ' <span class="badge">not set</span>')
                + '<input type="password" name="' + e + '" autocomplete="new-password" placeholder="' + ("Leave blank to keep the saved value" if is_set else "Paste the value")
                + '">' + hint_html + "</label>"
                + ('<label class="check-item"><input type="checkbox" name="' + e + '_clear"><span>Clear it</span></label>' if is_set else ""))
    if options is not None:
        cur = _cur(e)
        opts = list(options) if cur in options or not cur else [cur] + list(options)
        return ('<label>' + esc(label) + '<select name="' + e + '">' + "".join('<option value="' + esc(o) + '"' + (" selected" if o == cur else "") + ">" + esc(o) + "</option>"
                                                                       for o in opts) + "</select>" + hint_html + "</label>")
    return '<label>' + esc(label) + '<input name="' + e + '" value="' + esc(_cur(e)) + '" placeholder="' + esc(placeholder) + '">' + hint_html + "</label>"


def section(title, keys, inner, save_label, test=None, intro=""):
    return ('<div class="settings-section"><h2>' + title + '</h2><div class="card">' + intro + '<form class="std" method="post">'
            + "".join('<input type="hidden" name="keys" value="' + k + '">' for k in keys) + inner
            + (test_button(test) if test else "") + '<div class="acts"><button type="submit">' + esc(save_label) + "</button></div></form></div></div>")


def test_button(what):
    label = {"llm": "Test the connection", "pushover": "Send a test notification"}.get(what, "Test")
    return ('<p class="testrow"><button type="button" class="secondary" data-test="' + what + '">' + label + '</button> <span class="muted"></span></p>')


def tab_model():
    ms = llm.models()
    if isinstance(ms, list) and ms:
        note = "Both lists come from the server's /v1/models (" + str(len(ms)) + " models). Save the URL first if you changed it."
        chat, emb = field("LLM_MODEL", "Chat model", options=ms), field("EMBED_MODEL", "Embedding model", note, options=ms)
    else:
        note = "Could not read /v1/models (" + esc(str((ms or {}).get("error", "no models") if isinstance(ms, dict) else "no models")) + "); type the names."
        chat, emb = field("LLM_MODEL", "Chat model"), field("EMBED_MODEL", "Embedding model", note)
    return section("Local model (llama-swap)", ["LLM_URL", "LLM_MODEL", "EMBED_MODEL", "LLM_KEY"],
                   field("LLM_URL", "Base URL", "OpenAI-compatible endpoint (/v1). llama-swap; Ollama's /v1 should also work (untested).")
                   + chat + emb + field("LLM_KEY", "API key (optional)", "Only if something in front of llama-swap asks for one."), "Save model settings", "llm")


def tab_notify():
    return (section("Pushover", ["PUSHOVER_TOKEN", "PUSHOVER_USER", "MANDOS_BASE_URL"],
                    field("PUSHOVER_TOKEN", "App token") + field("PUSHOVER_USER", "User key") + field("MANDOS_BASE_URL", "Public URL of mandos", "Used for the link in alerts."),
                    "Save notification settings", "pushover")
            + section("Uptime Kuma heartbeat", ["KUMA_PUSH_URL"], field("KUMA_PUSH_URL", "Push URL", "Contains its own token. Only sent in live mode, after each sweep."), "Save"))


def tab_services():
    pf = settings.pack_fields()
    pack_section = section("For your jobs", [k for _, k, *_ in pf], "".join(field(k, label, hint) for _, k, _, _, label, hint in pf), "Save",
                           intro='<p class="muted">Settings the job pack asks for (pack.SETTINGS).</p>') if pf else ""
    return ('<h2 style="margin-top:0">Core</h2><p class="muted">Metrics, logs, and read-only commands that jobs use.</p>'
            + section("Prometheus", ["PROM_URL"], field("PROM_URL", "Prometheus URL"), "Save Prometheus", "prom")
            + section("LogLook", ["LOGLOOK_URL", "LOGLOOK_TOKEN"], field("LOGLOOK_URL", "LogLook URL") + field("LOGLOOK_TOKEN", "Token"), "Save LogLook", "loglook")
            + section("ulmo", ["ULMO_URL", "ULMO_TOKEN", "ULMO_CHANGE_TOKEN", "ULMO_ROLE"],
                      field("ULMO_URL", "ulmo URL") + field("ULMO_TOKEN", "Agent token", "Read-only commands, the catalog, runs and approval requests.")
                      + field("ULMO_CHANGE_TOKEN", "Change token (optional)", "Only for sending change proposals.")
                      + field("ULMO_ROLE", "Role that proposals grant to"), "Save ulmo", "ulmo")
            + '<h2>Direct sources</h2>'
            + section("Pi-hole", ["PIHOLE_URL"], field("PIHOLE_URL", "Pi-hole URL"), "Save Pi-hole", "pihole")
            + section("Home Assistant", ["HA_URL", "HA_TOKEN"], field("HA_URL", "Home Assistant URL") + field("HA_TOKEN", "Long-lived token"), "Save Home Assistant", "ha")
            + pack_section)


def tab_schedule():
    cr = settings.crons()
    grid = "".join(field(k, packs.jobs()[n].get("title", n), "cron (" + str(config.TZ) + "); empty turns it off") for n, k in cr.items())
    runs = "".join('<p class="testrow"><button type="button" class="secondary" data-test="run:' + esc(n) + '">Run ' + esc(j.get("title", n)) + ' now</button> '
                   '<span class="muted"></span></p>' for n, j in packs.jobs().items())
    return (section("Mode", ["MANDOS_MODE"], field("MANDOS_MODE", "Mode", "shadow: a trial run, alerts marked [mandos shadow], no Kuma heartbeat, jobs send nothing that needs approval. "
                                                                       "live: the real thing. A schedule never saved here follows the job's default for the mode; one saved empty is off.",
                                                   options=["shadow", "live"]), "Save mode")
            + (section("Schedules", list(cr.values()), '<div class="form-grid">' + grid + "</div>", "Save schedules") if cr else "")
            + ('<div class="settings-section"><h2>Run now</h2><div class="card">' + runs + "</div></div>" if runs else ""))


def tab_account(u, new_token=None):
    rows = "".join('<div class="user-row"><span>' + esc(x["username"]) + (' <span class="badge">you</span>' if u and x["id"] == u["id"] else "") + "</span>"
                   + ('' if u and x["id"] == u["id"] else '<form method="post" action="/settings/users/delete" data-confirm="Delete ' + esc(x["username"]) + '?">'
                      '<input type="hidden" name="id" value="' + str(x["id"]) + '"><button class="danger">Delete</button></form>') + "</div>"
                   for x in auth.users())
    pw = ('<div class="settings-section"><h2>Change your password</h2><div class="card"><form class="std" method="post" action="/settings/password">'
          '<input type="text" name="username" value="' + esc(u["username"]) + '" autocomplete="username" hidden>'
          '<label>Current password<input type="password" name="current" autocomplete="current-password" required></label>'
          '<label>New password<input type="password" name="password" autocomplete="new-password" required></label>'
          '<label>Confirm new password<input type="password" name="password2" autocomplete="new-password" required></label>'
          '<button type="submit">Update password</button></form></div></div>') if u else ""
    return ('<div class="settings-section"><h2>Authentication</h2><div class="card"><p class="muted">' + (
        "The login is off (<code>MANDOS_DISABLE_AUTH=1</code>)." if config.DISABLE_AUTH else
        "To run mandos without a login screen (behind your own proxy or a VPN-only network), set <code>MANDOS_DISABLE_AUTH=1</code> and restart the container.")
            + "</p></div></div>" + pw
            + '<div class="settings-section"><h2>Users</h2><div class="card">' + rows + '<hr style="border-color:var(--border);margin:16px 0">'
              '<form class="std" method="post" action="/settings/users/add"><label>New username<input name="username" autocomplete="off" required></label>'
              '<label>Password<input type="password" name="password" autocomplete="new-password" required></label>'
              '<button type="submit" class="secondary">Add user</button></form></div></div>' + tokens_section(new_token))


def tokens_section(new=None):
    rows = "".join('<div class="user-row"><span>' + esc(t["name"]) + ' <span class="dim small">made ' + esc(str(t["createdAt"])[:10]) + ", last used "
                   + esc(str(t.get("last_used") or "never")[:16]) + '</span></span><form method="post" action="/settings/tokens/delete" data-confirm="Delete the token '
                   + esc(t["name"]) + '? Scripts using it stop working."><input type="hidden" name="id" value="' + str(t["id"]) + '"><button class="danger">Delete</button></form></div>'
                   for t in api.tokens())
    shown = ('<p class="ok">New token (shown once, copy it now):<br><code style="user-select:all">' + esc(new) + "</code></p>") if new else ""
    return ('<div class="settings-section"><h2>API tokens</h2><div class="card">' + shown
            + '<p class="muted">For Claude Code and scripts: <code>Authorization: Bearer &lt;token&gt;</code> on <code>/api/v1/…</code> (README: API).</p>'
            + (rows or '<p class="dim">No tokens yet.</p>') + '<hr style="border-color:var(--border);margin:16px 0">'
            '<form class="std" method="post" action="/settings/tokens/add"><label>Name<input name="name" placeholder="claude-code" required></label>'
            '<button type="submit" class="secondary">Make a token</button></form></div></div>')


CSS = ("<style>.split{display:grid;grid-template-columns:200px minmax(0,1fr);gap:28px}.sidenav{display:flex;flex-direction:column;gap:2px;position:sticky;top:76px;align-self:start}"
       ".sidenav a{padding:8px 12px;border-radius:7px;color:var(--muted);font-size:.92rem}.sidenav a:hover{background:rgba(255,255,255,.04);color:var(--text);text-decoration:none}"
       ".sidenav a.active{background:rgba(79,140,255,.12);color:var(--text);font-weight:600}.settings-section{margin-bottom:32px}.settings-section:last-child{margin-bottom:0}"
       ".settings-section h2{font-size:1rem;border-bottom:1px solid var(--border);padding-bottom:8px}.form-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:0 16px}"
       "form.std{max-width:none}form.std select{display:block;width:100%;margin-top:6px;padding:8px 10px;background:#11141a;border:1px solid var(--border);border-radius:6px;color:var(--text);font-size:.95rem}"
       "form.std input:disabled{opacity:.6}form.std label .muted{display:block;margin-top:4px;font-size:.8rem}"
       "form.std label.check-item{display:flex;align-items:center;gap:8px;margin:-6px 0 14px;color:var(--text)}form.std label.check-item input{display:inline;width:auto;margin:0}"
       "button.secondary{background:#2a2e38}button.danger{background:transparent;border-color:rgba(239,91,91,.45);color:var(--red)}"
       ".user-row{display:flex;align-items:center;justify-content:space-between;padding:8px 0}.user-row form{margin:0}.testrow{margin:0 0 14px}"
       "@media(max-width:760px){.split{grid-template-columns:1fr;gap:16px}.sidenav{position:static;flex-direction:row;flex-wrap:wrap;gap:6px}"
       ".sidenav a{flex:1 1 auto;text-align:center;padding:9px 12px;border:1px solid var(--border);border-radius:8px;white-space:nowrap}.sidenav a.active{border-color:var(--accent)}}</style>")

JS = ("document.addEventListener('click',function(e){var b=e.target.closest('button[data-test]');if(!b)return;var out=b.nextElementSibling;out.textContent='Working…';b.disabled=true;"
      "fetch('/settings/test/'+b.dataset.test,{method:'POST'}).then(function(r){return r.json()}).then(function(j){out.textContent=j.text;out.className=j.ok?'ok':'error'})"
      ".catch(function(x){out.textContent=String(x);out.className='error'}).finally(function(){b.disabled=false})});"
      "document.addEventListener('submit',function(e){var m=e.target.getAttribute('data-confirm');if(m&&!confirm(m))e.preventDefault()});")


def render(tab, flash="", new_token=None):
    u = None if config.DISABLE_AUTH else auth.current()
    body = {"model": tab_model, "notify": tab_notify, "services": tab_services, "schedule": tab_schedule}.get(tab)
    body = body() if body else tab_account(u, new_token)
    side = "".join('<a href="/settings/' + k + '"' + (' class="active" aria-current="page"' if k == tab else "") + ">" + v + "</a>" for k, v in TABS)
    return (CSS + flash + '<div class="page-header"><div><h1>Settings</h1><p class="sub">Model, notifications, services, schedules and accounts. '
            'An environment variable, when set, wins over the value saved here.</p></div></div><div class="split"><nav class="sidenav" aria-label="Settings sections">'
            + side + '</nav><div class="split-body">' + body + "</div></div>")


def run_test(what):
    """(ok, text) for a Test button."""
    if what == "llm":
        m = llm.models()
        return (True, f"OK: {len(m)} models ({', '.join(m[:6])}{'…' if len(m) > 6 else ''})") if isinstance(m, list) else (False, m["error"])
    if what == "pushover":
        r = notify.push("Mandos test", "Test notification from the Settings page.")
        return (r.get("status") == 1, "Sent." if r.get("status") == 1 else "Not sent: " + str(r)[:200])
    if what.startswith("run:"):
        name = what[4:]
        if name in runner.running():
            return False, "already running"
        return (True, "Started; see Runs.") if runner.start(name) else (False, "no such job")
    r = {"prom": lambda: sources.prom("up"), "loglook": lambda: sources.loglook("top", {"hours": 1, "top": 1}, timeout=15),
         "ulmo": lambda: sources.ulmo_get("/api/v1/catalog"), "pihole": lambda: sources.pihole("stats/summary"),
         "ha": lambda: sources.ha("GET", "/api/", timeout=10)}.get(what)
    if not r:
        return False, "unknown test"
    out = r()
    if isinstance(out, dict) and out.get("error"):
        return False, str(out["error"])[:200]
    if isinstance(out, dict) and "statusCode" in out and out["statusCode"] >= 400:
        return False, f"HTTP {out['statusCode']}"
    if what == "prom":
        return True, f"OK: {len((out.get('data') or {}).get('result') or [])} targets answer 'up'"
    if what == "ulmo":
        return True, f"OK: {len((out or {}).get('commands') or [])} commands in the catalog"
    return True, "OK"


def install(app, page):
    def show(tab, flash="", status=200):
        return Response(page("Settings - Mandos", "settings", render(tab, flash), JS), status=status, mimetype="text/html")

    @app.get("/settings")
    def settings_root():
        return redirect("/settings/model", 303)

    @app.get("/account")
    def account_old():
        return redirect("/settings/account", 303)

    @app.get("/settings/<tab>")
    def settings_tab(tab):
        if tab not in dict(TABS):
            return Response("no such page", status=404, mimetype="text/plain")
        return show(tab, '<p class="ok">Saved.</p>' if request.args.get("saved") else "")

    @app.post("/settings/<tab>")
    def settings_save(tab):
        if tab not in dict(TABS) or tab == "account":
            return Response("no such page", status=404, mimetype="text/plain")
        known = settings.by_key()
        keys = [k for k in request.form.getlist("keys") if k in known]
        errs = settings.save_form(request.form, keys)
        if errs:
            return show(tab, '<p class="error">Not saved: ' + esc("; ".join(errs)) + "</p>", 400)
        runner.reschedule()
        return redirect(f"/settings/{tab}?saved=1", 303)

    @app.post("/settings/test/<what>")
    def settings_test(what):
        try:
            ok, text = run_test(what)
        except Exception as e:  # noqa: BLE001
            ok, text = False, str(e)[:200]
        return jsonify(ok=ok, text=text)

    @app.post("/settings/password")
    def settings_password():
        u = auth.current()
        if not u:
            return redirect("/settings/account", 303)
        err = (None if check_password_hash(u["pw_hash"], request.form.get("current", "")) else "The current password is wrong.") \
            or auth.check_password(request.form.get("password", ""), request.form.get("password2", ""))
        if err:
            return show("account", '<p class="error">' + esc(err) + "</p>", 400)
        db.update("users", u["id"], {"pw_hash": generate_password_hash(request.form["password"])})
        auth.login_as(db.get("users", u["id"]))     # this session stays; every other session of this user is logged out
        return show("account", '<p class="ok">Password changed. Other sessions are logged out.</p>')

    @app.post("/settings/users/add")
    def users_add():
        name = request.form.get("username", "").strip()
        pw = request.form.get("password", "")
        err = "Pick a username." if not name else "That user exists." if auth.user_by_name(name) else auth.check_password(pw, pw)
        if err:
            return show("account", '<p class="error">' + esc(err) + "</p>", 400)
        db.insert("users", {"username": name, "pw_hash": generate_password_hash(pw)})
        return show("account", '<p class="ok">Added ' + esc(name) + ".</p>")

    @app.post("/settings/users/delete")
    def users_delete():
        u = auth.current()
        try:
            uid = int(request.form.get("id", ""))
        except ValueError:
            uid = 0
        if (u and uid == u["id"]) or len(auth.users()) <= 1 or not db.get("users", uid):
            return show("account", '<p class="error">You cannot delete yourself or the last user.</p>', 400)
        with db._lock, db.conn() as c:
            c.execute("DELETE FROM users WHERE id=?", (uid,))
        return show("account", '<p class="ok">Deleted.</p>')

    @app.post("/settings/tokens/add")
    def tokens_add():
        t = api.new_token(request.form.get("name", "").strip() or "token")
        return Response(page("Settings - Mandos", "settings", render("account", "", new_token=t), JS), mimetype="text/html")

    @app.post("/settings/tokens/delete")
    def tokens_delete():
        try:
            tid = int(request.form.get("id", ""))
        except ValueError:
            tid = 0
        with db._lock, db.conn() as c:
            c.execute("DELETE FROM api_tokens WHERE id=?", (tid,))
        return show("account", '<p class="ok">Token deleted.</p>')
