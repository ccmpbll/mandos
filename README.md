<img src="mandos-logo.png" alt="Mandos logo" width="265">

# Mandos

![Build Status](https://img.shields.io/github/actions/workflow/status/ccmpbll/mandos/docker.yml) ![Tests](https://img.shields.io/github/actions/workflow/status/ccmpbll/mandos/tests.yml) ![Docker Image Size](https://img.shields.io/docker/image-size/ccmpbll/mandos/latest) ![Docker Pulls](https://img.shields.io/docker/pulls/ccmpbll/mandos.svg) ![License](https://img.shields.io/badge/License-MIT-blue.svg)

> **An experiment for my own homelab.** I built Mandos for my own setup and it may not be useful for anyone else. It is very
> experimental: expect breaking changes to the job pack format, the API, settings and the database between any two releases,
> with no migration path promised. You are welcome to read it or borrow from it, but please don't depend on it.

Mandos runs monitoring jobs on a schedule with a **local** language model, keeps their results, and shows them on a few pages.
It watches and reports; it doesn't change anything. When a job wants something fixed, it asks
[ulmo](https://github.com/ccmpbll/ulmo) and a person approves it there.

The image holds only the engine. The jobs themselves (code, prompts, queries, pages) live in a **job pack** in the data volume,
changed on the Jobs page or through the API, and an edit applies at the next run with no rebuild. My own pack is private;
`examples/starter` is a small one to show the shape.

## Run it

```bash
docker run -d --name mandos -p 8080:8080 -v /path/to/appdata/mandos:/data -e TZ=America/New_York -e MANDOS_STARTER=1 ccmpbll/mandos:latest
```

Open the page and create the first account, then fill in Settings: the model server (any OpenAI-compatible `/v1`, such as
llama-swap or Ollama), Pushover, and the services your jobs read. `MANDOS_STARTER=1` copies the starter pack into an empty
`/data/jobs`. An environment variable wins over the Settings page (see `env.example`).

## Job packs

A pack is a folder with a `pack.py` that lists its jobs (a `run(log)` function, default schedules, and the steps, prompts and
queries the Jobs page shows), plus optional tables, extra settings and pages. Pack code imports Mandos' modules (`config`, `db`,
`llm`, `sources`, `notify`, `promptstore`, `web`). Start from `examples/starter`; the top of `packs.py` describes every field.

If an edited file doesn't import, Mandos keeps running the last pack that loaded and shows the error on the Jobs page.

## API

Make a token on Settings → Account (it is shown once), then send `Authorization: Bearer <token>`.

| Call | What |
|---|---|
| `GET /api/v1/status` | mode, pack state, jobs and schedules |
| `GET`, `PUT`, `DELETE /api/v1/files/<path>` | read or write a pack file; a Python file must import and JSON must parse, or it is refused |
| `GET /api/v1/files` | the pack's files with their sha256 |
| `GET`, `PATCH /api/v1/settings` | settings (secrets only as set or not); `null` clears one |
| `POST /api/v1/jobs/<name>/run` | start a run |
| `GET /api/v1/runs`, `/runs/<id>`, `/tables`, `/tables/<name>` | run history and logs, the pack's tables (read only) |

`tools/push.py` sends a pack folder (only changed files):
`python3 tools/push.py my-pack --url https://mandos.example --token-file ~/mandos-token`

## Development

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

Releases are date tags (`2026.11.25`, `2026.11.25b`). A tag builds `ccmpbll/mandos:<tag>` and `:latest` for amd64 and arm64.
