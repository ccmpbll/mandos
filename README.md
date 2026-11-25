# Mandos

Mandos runs your monitoring jobs on a schedule with a **local** language model, keeps their records, and shows them on a few
pages. It watches and reports; it does not change your systems. When a job wants something done it asks a separate service
(for example [ulmo](https://github.com/ccmpbll/ulmo)) and a person approves it there.

The image holds only the engine. **Your jobs live in a job pack**, a folder of Python files, prompts and queries in the data
volume. You change them on the Jobs page, by copying files, or through the API (for example from Claude Code), and an edit
applies at the next run without a restart or a rebuild.

Python 3.12 · Flask (waitress) · SQLite · APScheduler · httpx. Any OpenAI-compatible model server (llama-swap, Ollama's `/v1`).

## What the engine does

- **Runs jobs** from the pack on cron schedules, one at a time per job, with a run history (`/runs`) and one Pushover when a run fails.
- **Model client**: `llm.chat_json` (JSON-schema answer, retried at temperature 0 when it does not parse or fails your check),
  `llm.chat_text`, `llm.embed`, `llm.models`.
- **Clients** for Prometheus, Pi-hole, LogLook, ulmo, Home Assistant, plain HTTP probes and an Uptime Kuma heartbeat. Every call returns
  data or `{"error": ...}` and never raises, so one broken source never stops a run.
- **Prompts with approved additions** (`promptstore`): base text from the pack plus blocks a person approved, appended in order.
- **Pages**: the pack's own pages in the top bar, Runs, Jobs (each job's steps, prompts, queries and source, and an editor for the
  pack's files with history and restore), Settings, login.
- **Settings page** for URLs, tokens, the model (picked from the server's model list), notifications, mode and every job's schedule.
  An environment variable wins over the page. Secrets are write-only.
- **API** (`/api/v1`, bearer tokens) to read and write the pack's files, change settings, start runs and read runs and tables.
- **Modes**: `shadow` (a trial next to whatever mandos replaces: alerts are marked `[mandos shadow]`, no heartbeat, and jobs should
  ask for nothing that needs approval; jobs read `config.SHADOW`) and `live`.

## Run it

```bash
docker run -d --name mandos -p 8080:8080 -v /path/to/appdata/mandos:/data -e TZ=America/New_York -e MANDOS_STARTER=1 ccmpbll/mandos:latest
```

Open the page: it asks you to create the first account. Then Settings: the model URL and models, Pushover, the services your jobs
read. `MANDOS_STARTER=1` copies the starter pack (`examples/starter`: Prometheus targets that are down, a one-line summary from the
model, a Pushover) into the empty `/data/jobs`, so there is something to run.

Behind a reverse proxy, mandos needs no Docker socket and no host access. Everything it knows comes from the services in Settings.

| Path in the container | What |
|---|---|
| `/data/mandos.db` | SQLite: settings, users, API token hashes, run history, prompt additions, the pack's tables |
| `/data/jobs/` | The job pack. Its `.history/` keeps the last 20 versions of each edited file |
| `/data/session.key` | Signs login cookies; made on first start. Delete it to log everyone out |

Environment-only settings: `TZ`, `MANDOS_DISABLE_AUTH=1` (no login; also turns the editor off), `MANDOS_ALLOW_EDIT=0`,
`MANDOS_INSECURE_COOKIE=1` (plain http on a host other than localhost), `MANDOS_STARTER=1`, `MANDOS_DB`, `MANDOS_JOBS`.
Everything else is on the Settings page; see `env.example`.

## Job packs

A pack is a folder with a `pack.py` manifest and whatever modules, prompts and queries it needs. Pack modules import mandos'
modules directly (`config`, `db`, `llm`, `sources`, `notify`, `promptstore`, `timeutil`, and `web` for `page()`, `esc()`).

```python
# pack.py
import targets

JOBS = {
    "targets": {
        "title": "Targets down",
        "about": "One line on the Jobs page.",
        "run": targets.run,                                   # run(log); raise to mark the run failed
        "schedule": {"shadow": "*/30 * * * *", "live": "*/15 * * * *"},   # defaults; the Settings page overrides (CRON_TARGETS)
        "module": "targets",                                  # the source the Jobs page opens first
        "steps": [("Ask Prometheus", "targets.down", "what it does", ""),   # tag: "model", "guard" or ""
                  ("Summary", "targets.summarise", "one model call", "model")],
        "prompts": [("Summary", "summary_system.txt", "Summary prompt")],   # (label, file in prompts/, PROMPT_TARGETS key or None)
        "queries": None,                                      # a JSON list of {name, query} in prompts/, shown on the Jobs page
    },
}
SCHEMA = "CREATE TABLE IF NOT EXISTS targets_runs (id INTEGER PRIMARY KEY, down TEXT, summary TEXT, createdAt TEXT);"
SETTINGS = [("TARGETS_IGNORE", "Ignore jobs (regex)", False, "", "hint")]   # extra Settings fields, written onto config
PROMPT_TARGETS = {"Summary prompt": "summary_system.txt"}                  # prompts that take approved additions
NAV = [("Targets", "/targets", "targets", None)]                          # top-bar tabs; the 4th item may be a count function
ROUTES = {("GET", "/targets"): targets.page}                              # your pages; return HTML text or a Flask Response
HOME = "/targets"
```

The Jobs page checks that every step's function exists. When an edited file does not import, mandos keeps running the last
good pack and shows the error on the Jobs page.

## API

Make a token on Settings → Account → API tokens. It is shown once; only its hash is stored. Every call needs
`Authorization: Bearer <token>`, also when the login is off.

| Call | What |
|---|---|
| `GET /api/v1/status` | mode, pack fingerprint, load error, jobs and their schedules, running jobs |
| `GET /api/v1/files` | the pack's files with size and sha256 |
| `GET /api/v1/files/<path>` | one file |
| `PUT /api/v1/files/<path>` | write it (body = text). 400 when Python does not import or JSON does not parse; the old text goes to the history |
| `DELETE /api/v1/files/<path>` | remove it (kept in the history) |
| `GET /api/v1/settings` | every setting with its source (`env`, `saved`, `default`); secrets only as set or not |
| `PATCH /api/v1/settings` | `{"KEY": "value", "OTHER": null}`; null clears a saved value |
| `POST /api/v1/jobs/<name>/run` | start a run (202; 409 while it runs) |
| `GET /api/v1/runs?job=&limit=` · `GET /api/v1/runs/<id>` | run history; the single run includes its log |
| `GET /api/v1/tables` · `GET /api/v1/tables/<name>?limit=` | the pack's tables, newest rows first (read only) |

Send a whole pack folder (only changed files; `--delete` removes files that are gone; standard library only):

```bash
python3 tools/push.py path/to/my-pack --url https://mandos.example --token-file ~/mandos-token
```

With Claude Code: keep your pack in its own folder, put the token in a file, and ask Claude to change a job and push it.
Claude then reads `/api/v1/runs` to check the next run.

## Development

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt -r requirements-dev.txt
.venv/bin/python -m pytest -q
MANDOS_JOBS=examples/starter MANDOS_INSECURE_COOKIE=1 .venv/bin/python main.py      # http://localhost:8080
```

The tests run against a copy of `examples/starter`. A pack can have its own tests: point them at this checkout and use the pack
folder as `MANDOS_JOBS`.

## Releases

Tags are dates (`2026.11.25`, then `2026.11.25b` for a second release that day). A tag builds and pushes `ccmpbll/mandos:<tag>` and
`:latest` (amd64 and arm64), and the annotated tag message becomes the GitHub release notes.
