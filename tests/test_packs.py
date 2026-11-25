"""The job pack: loading, pages routed from pack.ROUTES, reload on change, a broken edit keeps the last good pack, the editor."""
import os
import time

import codeedit
import config
import packs
import runner
import web


def test_starter_pack_loads_and_serves():
    p = packs.load()
    assert packs.error is None and "targets" in p.JOBS
    c = web.app.test_client()
    assert c.get("/").headers["Location"].endswith("/targets")
    h = c.get("/targets").data
    assert b"No runs yet" in h and b'href="/targets"' in h and b">Jobs</a>" in h
    assert b"Targets down" in c.get("/jobs").data
    j = c.get("/jobs/targets").data
    assert b"targets.down" in j and b"not found" not in j and b"summary_system.txt" in j
    assert c.get("/nope").status_code == 404


def test_run_job(monkeypatch):
    import sources
    monkeypatch.setattr(sources, "prom", lambda q: {"status": "success", "data": {"result": [{"metric": {"job": "node", "instance": "a:9100"}}]}})
    config.LLM_MODEL = ""
    assert runner.run_job("targets") == "success"
    import db
    assert db.rows("job_runs")[0]["status"] == "success" and "node a:9100" in db.rows("targets_runs")[0]["down"]
    monkeypatch.setattr(sources, "prom", lambda q: {"error": "down"})
    assert runner.run_job("targets") == "failed" and db.rows("job_runs")[0]["detail"].startswith("Prometheus")
    assert runner.run_job("nope") == "no such job"


def _bump(path):
    t = time.time() + 5
    os.utime(path, (t, t))


def test_reload_and_broken_edit_keeps_last_good(pack_dir):
    good = open(os.path.join(pack_dir, "pack.py")).read()
    assert codeedit.save("pack.py", good.replace('"title": "Targets down"', '"title": "Targets offline"')) is None
    _bump(os.path.join(pack_dir, "pack.py"))
    assert packs.load().JOBS["targets"]["title"] == "Targets offline"
    # write a broken file behind the checks' back (as a copy on the share would): the last good pack stays
    open(os.path.join(pack_dir, "targets.py"), "a").write("\ndef broken(:\n")
    _bump(os.path.join(pack_dir, "targets.py"))
    p = packs.load()
    assert packs.error and "SyntaxError" in packs.error and p.JOBS["targets"]["title"] == "Targets offline"
    assert b"did not load" in web.app.test_client().get("/jobs").data
    t = open(os.path.join(pack_dir, "targets.py")).read().replace("\ndef broken(:\n", "")
    open(os.path.join(pack_dir, "targets.py"), "w").write(t)
    codeedit.save("pack.py", good)
    _bump(os.path.join(pack_dir, "pack.py"))
    assert packs.load().JOBS["targets"]["title"] == "Targets down" and packs.error is None


def test_editor_checks_and_history(pack_dir):
    good = codeedit.read("targets.py")
    assert "line" in codeedit.save("targets.py", good + "\ndef broken(:\n")
    assert "NameError" in codeedit.save("targets.py", good + "\nundefined_name\n")
    assert "JSON" in codeedit.save("queries.json", "{nope")
    for bad in ["../x.py", "/etc/passwd", ".history/x.py", "tests/x.py", "a/../../b.py", "bin.exe", ""]:
        assert codeedit.save(bad, "x = 1\n") and codeedit.safe(bad) is None, bad
    assert codeedit.read("targets.py") == good and codeedit.history("targets.py") == []
    err = codeedit.save("targets.py", good + "\nEDITED = 1\n")
    assert err is None, err
    [v] = codeedit.history("targets.py")
    assert codeedit.restore("targets.py", "../config.py") == "no such version"
    assert codeedit.restore("targets.py", v) is None and codeedit.read("targets.py") == good
    assert codeedit.save("prompts/new.txt", "hello") is None and codeedit.read("prompts/new.txt") == "hello\n"
    assert codeedit.delete("prompts/new.txt") is None and codeedit.read("prompts/new.txt") is None
    assert codeedit.delete("pack.py")


def test_editor_pages(monkeypatch):
    c = web.app.test_client()
    monkeypatch.setattr(config, "ALLOW_EDIT", False)
    assert c.get("/edit?file=targets.py").status_code == 403
    monkeypatch.setattr(config, "ALLOW_EDIT", True)
    assert c.get("/edit?file=../config.py").status_code == 403
    r = c.get("/edit?file=targets.py")
    assert r.status_code == 200 and b"textarea" in r.data
    r = c.post("/edit", data={"file": "targets.py", "text": "def x(:\n"})
    assert r.status_code == 400 and b"Not saved" in r.data


def test_import_timeout_and_history_names(monkeypatch):
    monkeypatch.setattr(codeedit, "CHECK_SECS", 1)
    assert "longer than 1 s" in codeedit.save("slow.py", "import time\ntime.sleep(5)\n")
    assert codeedit._hist_name("a/b.py") != codeedit._hist_name("a__b.py")
    assert codeedit.save("a__b.py", "X = 1\n") is None and codeedit.save("a__b.py", "X = 2\n") is None
    assert codeedit.history("a/b.py") == [] and len(codeedit.history("a__b.py")) == 1
    codeedit.delete("a__b.py")


def test_edit_links_are_url_encoded(monkeypatch):
    monkeypatch.setattr(config, "ALLOW_EDIT", True)
    assert codeedit.save("prompts/odd #1+x.txt", "hi") is None
    h = web.app.test_client().get("/jobs").data
    assert b"/edit?file=prompts/odd%20%231%2Bx.txt" in h
    assert web.app.test_client().get("/edit?file=prompts/odd%20%231%2Bx.txt").status_code == 200
    codeedit.delete("prompts/odd #1+x.txt")
