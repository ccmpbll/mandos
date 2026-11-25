"""Running jobs: one at a time per job, a job_runs row per run, one Pushover when a run fails. The scheduler (APScheduler, cron
lines from settings) and the API both start runs here."""
import threading
import traceback

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

import config
import db
import notify
import packs
import settings
from timeutil import et_stamp

_running = set()
_guard = threading.Lock()
_sched = None


def run_job(name):
    """Run one job now (blocking). Returns 'success', 'failed', 'already running' or 'no such job'."""
    pack = packs.load()              # picks up edits to the pack since the last run
    job = pack.JOBS.get(name) if hasattr(pack, "JOBS") else None
    if not job:
        return "no such job"
    with _guard:
        if name in _running:
            return "already running"
        _running.add(name)
    lines = []
    log = lambda m: (lines.append(et_stamp()[11:] + " " + str(m)), print(f"[{name}] {m}", flush=True))  # noqa: E731
    rid = db.insert("job_runs", {"job": name, "started": et_stamp(), "status": "running"})
    try:
        job["run"](log)
        db.update("job_runs", rid, {"finished": et_stamp(), "status": "success", "detail": (lines[-1] if lines else "")[:300], "log": "\n".join(lines)[-20000:]})
        return "success"
    except Exception as e:  # noqa: BLE001
        lines.append(traceback.format_exc())
        db.update("job_runs", rid, {"finished": et_stamp(), "status": "failed", "detail": str(e)[:300], "log": "\n".join(lines)[-20000:]})
        notify.push("mandos job failed: " + name, str(e)[:400], priority=0, url=config.BASE_URL + "/runs" if config.BASE_URL else None,
                    url_title="Open run history")
        return "failed"
    finally:
        with _guard:
            _running.discard(name)


def start(name):
    """Run in the background; for the API and the Settings page."""
    if name not in packs.jobs():
        return False
    threading.Thread(target=run_job, args=(name,), daemon=True).start()
    return True


def running():
    with _guard:
        return sorted(_running)


def schedule():
    global _sched
    _sched = BackgroundScheduler(timezone=config.TZ, job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 3600})
    _sched.start()
    reschedule()
    return _sched


def reschedule():
    """(Re)make every job's cron trigger; after a settings save or a pack reload."""
    if _sched is None:
        return
    for j in _sched.get_jobs():
        j.remove()
    for name in packs.jobs():
        line = settings.cron(name)
        if not line:
            continue
        try:
            _sched.add_job(run_job, CronTrigger.from_crontab(line, timezone=config.TZ), args=[name], id=name)
            print(f"scheduled {name}: {line} ({config.TZ})", flush=True)
        except ValueError as e:
            print(f"bad schedule for {name} ({line}): {e}", flush=True)
