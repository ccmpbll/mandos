"""/api/v1 with bearer tokens: files, settings, runs, tables."""
import pytest

import api
import config
import db
import web


@pytest.fixture
def c():
    return web.app.test_client()


@pytest.fixture
def h():
    return {"Authorization": "Bearer " + api.new_token("test")}


def test_needs_a_token(c):
    api.new_token("other")
    assert c.get("/api/v1/status").status_code == 401
    assert c.get("/api/v1/status", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert db.rows("api_tokens")[0]["token_hash"] != ""                    # only the hash is stored


def test_status_and_files(c, h):
    s = c.get("/api/v1/status", headers=h).json
    assert s["pack_error"] is None and "targets" in s["jobs"]
    files = {f["path"] for f in c.get("/api/v1/files", headers=h).json}
    assert {"pack.py", "targets.py", "prompts/summary_system.txt"} <= files
    assert b"def run" in c.get("/api/v1/files/targets.py", headers=h).data
    r = c.put("/api/v1/files/prompts/summary_system.txt", data="Say what is down.", headers=h)
    assert r.status_code == 200 and r.json["ok"] and c.get("/api/v1/files/prompts/summary_system.txt", headers=h).data == b"Say what is down.\n"
    r = c.put("/api/v1/files/targets.py", data="def run(:\n", headers=h)
    assert r.status_code == 400 and "line 1" in r.json["error"]
    assert c.put("/api/v1/files/../x.py", data="x=1", headers=h).status_code in (400, 404)
    assert c.put("/api/v1/files/extra.py", data="X = 1\n", headers=h).status_code == 200
    assert c.delete("/api/v1/files/extra.py", headers=h).status_code == 200
    assert c.get("/api/v1/files/extra.py", headers=h).status_code == 404


def test_settings(c, h):
    r = c.patch("/api/v1/settings", json={"PROM_URL": "https://prom.example", "PUSHOVER_TOKEN": "secret-123", "TARGETS_IGNORE": "^lab-"}, headers=h)
    assert r.status_code == 200 and config.PROM_URL == "https://prom.example" and config.TARGETS_IGNORE == "^lab-"
    s = c.get("/api/v1/settings", headers=h).json
    assert s["PUSHOVER_TOKEN"] == {"set": True, "source": "saved"} and b"secret-123" not in c.get("/api/v1/settings", headers=h).data
    assert s["CRON_TARGETS"]["source"] == "default"
    assert c.patch("/api/v1/settings", json={"PUSHOVER_TOKEN": None}, headers=h).json["PUSHOVER_TOKEN"]["set"] is False
    assert c.patch("/api/v1/settings", json={"NOPE": 1}, headers=h).status_code == 400
    assert c.patch("/api/v1/settings", json={"PROM_URL": "prom"}, headers=h).status_code == 400


def test_runs_and_tables(c, h, monkeypatch):
    import runner
    started = []
    monkeypatch.setattr(runner, "start", lambda n: started.append(n) or True)
    assert c.post("/api/v1/jobs/targets/run", headers=h).status_code == 202 and started == ["targets"]
    assert c.post("/api/v1/jobs/nope/run", headers=h).status_code == 404
    rid = db.insert("job_runs", {"job": "targets", "started": "x", "status": "success", "log": "line"})
    assert "log" not in c.get("/api/v1/runs", headers=h).json[0] and c.get(f"/api/v1/runs/{rid}", headers=h).json["log"] == "line"
    t = c.get("/api/v1/tables", headers=h).json
    assert "targets_runs" in t and "users" not in t and "api_tokens" not in t and "settings" not in t
    assert c.get("/api/v1/tables/users", headers=h).status_code == 404


def test_token_ui(c):
    r = c.post("/settings/tokens/add", data={"name": "claude-code"})
    assert b"mandos_" in r.data and b"shown once" in r.data
    tid = db.rows("api_tokens")[0]["id"]
    assert b"mandos_" not in c.get("/settings/account").data
    c.post("/settings/tokens/delete", data={"id": tid})
    assert db.rows("api_tokens") == []
