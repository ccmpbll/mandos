"""Starter job pack: one job that checks Prometheus for targets that are down, asks the local model for a short summary, and
sends a Pushover when something is down. Copy this folder, change it, and send it to mandos (tools/push.py) or edit it on the
Jobs page. Every manifest field is described at the top of packs.py."""
import targets

HOME = "/targets"
NAV = [("Targets", "/targets", "targets", None)]
ROUTES = {("GET", "/targets"): targets.page}
PROMPT_TARGETS = {"Summary prompt": "summary_system.txt"}

# Extra fields for the Settings page (Services tab), written onto config: (key, label, secret, default, hint)
SETTINGS = [("TARGETS_IGNORE", "Ignore jobs (regex)", False, "", "Prometheus job names to leave out, for example ^(test|lab)-")]

SCHEMA = """
CREATE TABLE IF NOT EXISTS targets_runs (id INTEGER PRIMARY KEY, down TEXT, summary TEXT, createdAt TEXT);
"""

JOBS = {
    "targets": {
        "title": "Targets down",
        "about": "Lists Prometheus targets that are down; the local model writes a one-line summary; Pushover when any are down.",
        "run": targets.run,
        "module": "targets",
        "schedule": {"shadow": "*/30 * * * *", "live": "*/15 * * * *"},
        "steps": [
            ("Ask Prometheus", "targets.down", "up == 0, minus the ignored jobs", ""),
            ("Summary", "targets.summarise", "one call to the local model (skipped when no model is set)", "model"),
            ("Save and alert", "targets.run", "a targets_runs row; Pushover when something is down", ""),
        ],
        "prompts": [("Summary", "summary_system.txt", "Summary prompt")],
    },
}
