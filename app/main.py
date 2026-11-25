"""mandos: runs a job pack's jobs on a schedule with a local model, and serves its pages, the Settings page and an API.

  python main.py                 serve pages and the API, run the schedule
  python main.py run <job>       run one job now
"""
import sys

import config
import db
import packs
import runner
import settings


def boot():
    db.init()
    packs.on_reload[:] = [settings.apply, runner.reschedule]
    packs.load(force=True)
    settings.apply()


def main(argv):
    boot()
    if len(argv) >= 3 and argv[1] == "run":
        print(runner.run_job(argv[2]))
        return
    runner.schedule()
    from waitress import serve

    import web
    print(f"mandos ({config.MODE}) on :8080, jobs from {config.JOBS_DIR}", flush=True)
    serve(web.app, host="0.0.0.0", port=8080, threads=6)


if __name__ == "__main__":
    main(sys.argv)
