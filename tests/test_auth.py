"""Login, first-run setup, rate limit, password change, and that every page is behind it."""
import pytest

import auth
import config
import db
import web


@pytest.fixture
def c(monkeypatch):
    monkeypatch.setattr(config, "DISABLE_AUTH", False)
    auth._fails.clear()
    web.app.config["SESSION_COOKIE_SECURE"] = False
    return web.app.test_client()


def setup_user(c, name="chris", pw="correct horse battery"):
    return c.post("/setup", data={"username": name, "password": pw, "password2": pw})


def test_first_run_goes_to_setup(c):
    for p in ["/targets", "/jobs", "/runs", "/settings/model", "/login"]:
        r = c.get(p)
        assert r.status_code == 303 and r.headers["Location"].endswith("/setup"), p
    assert c.get("/healthz").status_code == 200 and c.get("/static/style.css").status_code == 200
    assert b"at least 10" in c.post("/setup", data={"username": "a", "password": "short", "password2": "short"}).data
    assert b"do not match" in c.post("/setup", data={"username": "a", "password": "x" * 12, "password2": "y" * 12}).data
    r = setup_user(c)
    assert r.status_code == 303 and r.headers["Location"].endswith("/")
    assert c.get("/targets").status_code == 200               # logged in by setup
    assert db.rows("users")[0]["pw_hash"] != "correct horse battery"
    assert setup_user(c, "other").status_code == 303 and len(db.rows("users")) == 1   # setup closes once a user exists


def test_login_logout_and_next(c):
    setup_user(c)
    c.post("/logout")
    r = c.get("/jobs/targets?file=targets.py")
    assert r.status_code == 303 and "next=/jobs/targets" in r.headers["Location"]
    assert c.post("/edit", data={}).status_code == 401  # POSTs are refused, not redirected
    r = c.post("/login", data={"username": "chris", "password": "nope", "next": "/jobs"})
    assert r.status_code == 401 and b"Wrong username or password" in r.data
    r = c.post("/login", data={"username": "chris", "password": "correct horse battery", "next": "//evil.example/x"})
    assert r.headers["Location"].endswith("/")          # no open redirect
    c.post("/logout")
    r = c.post("/login", data={"username": "chris", "password": "correct horse battery", "next": "/jobs"})
    assert r.headers["Location"].endswith("/jobs")
    assert b"Log out" in c.get("/jobs").data and b"chris" in c.get("/jobs").data


def test_rate_limit(c):
    setup_user(c)
    c.post("/logout")
    for _ in range(auth.TRIES):
        c.post("/login", data={"username": "chris", "password": "bad"})
    r = c.post("/login", data={"username": "chris", "password": "correct horse battery"})
    assert b"Too many tries" in r.data and c.get("/targets").status_code == 303


def test_password_change_logs_out_other_sessions(c):
    setup_user(c)
    other = web.app.test_client()
    other.post("/login", data={"username": "chris", "password": "correct horse battery"})
    assert other.get("/targets").status_code == 200
    assert b"current password is wrong" in c.post("/settings/password", data={"current": "x", "password": "n" * 12, "password2": "n" * 12}).data
    r = c.post("/settings/password", data={"current": "correct horse battery", "password": "new password 123", "password2": "new password 123"})
    assert b"Password changed" in r.data
    assert c.get("/targets").status_code == 200 and other.get("/targets").status_code == 303


def test_disable_auth(monkeypatch):
    monkeypatch.setattr(config, "DISABLE_AUTH", True)
    assert web.app.test_client().get("/targets").status_code == 200


def test_lockout_is_per_client_behind_the_proxy(c):
    setup_user(c)
    c.post("/logout")
    for _ in range(auth.TRIES):
        c.post("/login", data={"username": "chris", "password": "bad"}, headers={"X-Forwarded-For": "10.0.0.66"})
    other = web.app.test_client()
    r = other.post("/login", data={"username": "chris", "password": "correct horse battery"}, headers={"X-Forwarded-For": "10.0.0.5"})
    assert r.status_code == 303                                  # the owner on another address still gets in
    r = c.post("/login", data={"username": "chris", "password": "correct horse battery"}, headers={"X-Forwarded-For": "10.0.0.66"})
    assert b"Too many tries" in r.data


def test_failure_alert_has_no_link_without_base_url(monkeypatch):
    import config
    import notify
    import runner
    import packs
    monkeypatch.setattr(config, "BASE_URL", "")
    monkeypatch.setitem(packs.jobs()["targets"], "run", lambda log: 1 / 0)
    runner.run_job("targets")
    assert "url" not in notify.sent[-1]


def test_bad_proxy_hops_falls_back(monkeypatch):
    import flask
    monkeypatch.setenv("MANDOS_PROXY_HOPS", "yes")
    a = flask.Flask("t")
    auth.install(a)                                  # no crash
    assert type(a.wsgi_app).__name__ == "ProxyFix"
