"""Settings page: env wins, secrets are write-only, bad values are refused, mode drives the cron defaults, users."""
import pytest

import config
import llm
import settings
import settings_page
import web


@pytest.fixture
def c(monkeypatch):
    for _, e, _, _ in settings.fields():
        monkeypatch.delenv(e, raising=False)
        monkeypatch.delenv(e + "_FILE", raising=False)
    monkeypatch.setattr(llm, "models", lambda: ["nomic-embed-text", "qwen3.5-9b", "other-model"])
    saved = {a: getattr(config, a) for a, _, _, _ in settings.fields() + [("SHADOW", "", False, "")] if a}
    settings.apply()
    yield web.app.test_client()
    for a, v in saved.items():
        setattr(config, a, v)


def test_pack_setting_on_services(c):
    page = c.get("/settings/services").data
    assert b"For your jobs" in page and b"TARGETS_IGNORE" in page
    c.post("/settings/services", data={"keys": ["TARGETS_IGNORE"], "TARGETS_IGNORE": "^lab-"})
    assert config.TARGETS_IGNORE == "^lab-"


def test_pages_render(c):
    c.post("/settings/model", data={"keys": ["LLM_MODEL"], "LLM_MODEL": "qwen3.5-9b"})
    for t, _ in settings_page.TABS:
        r = c.get("/settings/" + t)
        assert r.status_code == 200 and b"Settings" in r.data, t
    r = c.get("/settings/model")
    assert b'<option value="other-model">' in r.data and b'<option value="qwen3.5-9b" selected>' in r.data
    assert c.get("/settings/nope").status_code == 404 and c.get("/account").status_code == 303


def test_save_apply_and_secrets(c):
    r = c.post("/settings/services", data={"keys": ["PROM_URL", "LOGLOOK_TOKEN"], "PROM_URL": "https://prom.example", "LOGLOOK_TOKEN": "sekrit-value-123"})
    assert r.status_code == 303
    assert config.PROM_URL == "https://prom.example" and config.LOGLOOK_TOKEN == "sekrit-value-123"
    page = c.get("/settings/services").data
    assert b"sekrit-value-123" not in page and b"Leave blank to keep" in page
    c.post("/settings/services", data={"keys": ["LOGLOOK_TOKEN"], "LOGLOOK_TOKEN": ""})       # blank keeps it
    assert config.LOGLOOK_TOKEN == "sekrit-value-123"
    c.post("/settings/services", data={"keys": ["LOGLOOK_TOKEN"], "LOGLOOK_TOKEN_clear": "on"})
    assert config.LOGLOOK_TOKEN == ""


def test_refuses_bad_values(c):
    r = c.post("/settings/services", data={"keys": ["PROM_URL"], "PROM_URL": "prom.example"})
    assert r.status_code == 400 and b"http://" in r.data and config.PROM_URL != "prom.example"
    r = c.post("/settings/schedule", data={"keys": ["CRON_TARGETS", "MANDOS_BASE_URL"], "CRON_TARGETS": "every night", "MANDOS_BASE_URL": "https://m.example"})
    assert r.status_code == 400 and b"cron" in r.data and config.BASE_URL != "https://m.example"   # nothing saved when one field is bad
    assert c.post("/settings/schedule", data={"keys": ["MANDOS_MODE"], "MANDOS_MODE": "chaos"}).status_code == 400
    assert c.post("/settings/services", data={"keys": ["DB_PATH"], "DB_PATH": "/etc/x"}).status_code == 303   # unknown keys ignored
    assert config.DB_PATH != "/etc/x"


def test_env_wins(c, monkeypatch):
    monkeypatch.setenv("PROM_URL", "https://from-env.example")
    monkeypatch.setenv("HA_TOKEN", "env-secret-999")
    c.post("/settings/services", data={"keys": ["PROM_URL"], "PROM_URL": "https://saved.example"})
    assert config.PROM_URL == "https://from-env.example"
    page = c.get("/settings/services").data
    assert b"Set by the environment variable <code>PROM_URL</code>" in page and b"env-secret-999" not in page


def test_mode_drives_cron_defaults(c, monkeypatch):
    calls = []
    import runner
    monkeypatch.setattr(runner, "reschedule", lambda: calls.append(1))
    assert config.SHADOW and settings.cron("targets") == "*/30 * * * *"
    c.post("/settings/schedule", data={"keys": ["MANDOS_MODE"], "MANDOS_MODE": "live"})
    assert not config.SHADOW and settings.cron("targets") == "*/15 * * * *" and calls
    c.post("/settings/schedule", data={"keys": ["CRON_TARGETS"], "CRON_TARGETS": ""})               # saved empty = off
    assert settings.cron("targets") == ""


def test_test_buttons(c, monkeypatch):
    import sources
    monkeypatch.setattr(sources, "prom", lambda q: {"error": "boom"})
    assert c.post("/settings/test/prom").json == {"ok": False, "text": "boom"}
    assert c.post("/settings/test/llm").json["ok"]
    assert not c.post("/settings/test/nope").json["ok"]


def test_users(c, monkeypatch):
    monkeypatch.setattr(config, "DISABLE_AUTH", False)
    web.app.config["SESSION_COOKIE_SECURE"] = False
    pw = "correct horse battery"
    c.post("/setup", data={"username": "chris", "password": pw, "password2": pw})
    assert b"at least 10" in c.post("/settings/users/add", data={"username": "sam", "password": "short"}).data
    assert b"Added sam" in c.post("/settings/users/add", data={"username": "sam", "password": "another long one"}).data
    import auth
    me, sam = auth.user_by_name("chris"), auth.user_by_name("sam")
    assert c.post("/settings/users/delete", data={"id": me["id"]}).status_code == 400
    assert b"Deleted" in c.post("/settings/users/delete", data={"id": sam["id"]}).data and not auth.user_by_name("sam")
    r = c.post("/settings/password", data={"current": pw, "password": "a brand new one", "password2": "a brand new one"})
    assert b"Password changed" in r.data
