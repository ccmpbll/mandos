"""Settings saved from the Settings page or the API (settings table). An environment variable (or NAME_FILE), when set, wins over
the saved value; with neither, the default applies. apply() writes the result onto config, so every module that reads config.X at
call time sees a change at once. Secrets are write-only: the page and the API show set / not set, never the value.
Fields = mandos' own (below) + the pack's SETTINGS + one schedule per job (default from the job's schedule for the current mode)."""
import os

import config
import db
import packs

# (config attribute, settings key / environment variable, secret, default)
CORE = [
    ("MODE", "MANDOS_MODE", False, "shadow"), ("BASE_URL", "MANDOS_BASE_URL", False, ""),
    ("LLM_URL", "LLM_URL", False, ""), ("LLM_MODEL", "LLM_MODEL", False, ""), ("EMBED_MODEL", "EMBED_MODEL", False, ""), ("LLM_KEY", "LLM_KEY", True, ""),
    ("PUSHOVER_TOKEN", "PUSHOVER_TOKEN", True, ""), ("PUSHOVER_USER", "PUSHOVER_USER", True, ""), ("KUMA_PUSH_URL", "KUMA_PUSH_URL", True, ""),
    ("PROM_URL", "PROM_URL", False, ""), ("LOGLOOK_URL", "LOGLOOK_URL", False, ""), ("LOGLOOK_TOKEN", "LOGLOOK_TOKEN", True, ""),
    ("ULMO_URL", "ULMO_URL", False, ""), ("ULMO_TOKEN", "ULMO_TOKEN", True, ""), ("ULMO_CHANGE_TOKEN", "ULMO_CHANGE_TOKEN", True, ""),
    ("ULMO_ROLE", "ULMO_ROLE", False, "mandos"),
    ("PIHOLE_URL", "PIHOLE_URL", False, ""), ("HA_URL", "HA_URL", False, ""), ("HA_TOKEN", "HA_TOKEN", True, ""),
]
URL_KEYS = {"MANDOS_BASE_URL", "LLM_URL", "PROM_URL", "LOGLOOK_URL", "ULMO_URL", "PIHOLE_URL", "HA_URL", "KUMA_PUSH_URL"}


def pack_fields():
    """(attr, key, secret, default, label, hint) from the pack's SETTINGS."""
    out = []
    for f in packs.get("SETTINGS", []) or []:
        key, label, secret, default, hint = (list(f) + ["", False, "", ""])[:5]
        out.append((key, key, bool(secret), default or "", label or key, hint or ""))
    return out


def crons():
    """{job name: settings key} for every job with a schedule."""
    return {n: packs.cron_key(n) for n, j in packs.jobs().items() if j.get("schedule")}


def fields():
    return [(a, k, s, d) for a, k, s, d in CORE] + [(a, k, s, d) for a, k, s, d, _, _ in pack_fields()] + [(None, k, False, None) for k in crons().values()]


def by_key():
    return {k: (a, s) for a, k, s, _ in fields()}


def is_url(k):
    return k in URL_KEYS or k.endswith("_URL")


def from_env(k):
    return bool(os.environ.get(k + "_FILE") and os.path.exists(os.environ[k + "_FILE"])) or k in os.environ


def saved():
    return {r["key"]: r["value"] for r in db.rows("settings", order="key")}


def _cron_default(name):
    sch = packs.jobs().get(name, {}).get("schedule") or {}
    return (sch.get("shadow") if config.SHADOW else sch.get("live")) or ""


def value(k, s=None):
    """(value, source) with source 'env', 'saved' or 'default'."""
    s = saved() if s is None else s
    if from_env(k):
        return config.env(k), "env"
    if k in s:
        return s[k], "saved"
    for n, ck in crons().items():
        if ck == k:
            return _cron_default(n), "default"
    for _, key, _, d in fields():
        if key == k:
            return d or "", "default"
    return "", "default"


def cron(name):
    return value(packs.cron_key(name))[0]


def apply():
    """Put env > saved > default onto config. Mode first: the schedule defaults depend on it."""
    s = saved()
    config.MODE = value("MANDOS_MODE", s)[0]
    config.SHADOW = config.MODE != "live"
    for a, k, _, _ in fields():
        if a:
            v = value(k, s)[0]
            if k == "MANDOS_BASE_URL":
                v = v.rstrip("/")
            if k == "LLM_URL":
                import llm
                v = llm.base_url(v)         # the clients add /v1/...; accept the URL either way
            setattr(config, a, v)


def check(k, v):
    """None, or why the value is refused."""
    if is_url(k) and v and not v.startswith(("http://", "https://")):
        return "must start with http:// or https://"
    if k in crons().values() and v:
        from apscheduler.triggers.cron import CronTrigger
        try:
            CronTrigger.from_crontab(v, timezone=config.TZ)
        except ValueError as x:
            return "not a cron line (" + str(x)[:80] + ")"
    if k == "MANDOS_MODE" and v not in ("shadow", "live"):
        return "shadow or live"
    return None


def save(values, clear=()):
    """values: {key: text}. Secrets: an empty value keeps the saved one; keys in clear are removed (back to the default).
    Unknown keys and keys set by the environment are skipped. Returns errors; nothing is saved when there is one."""
    known = by_key()
    errs, out, drop = [], {}, []
    for k in clear:
        if k in known and not from_env(k):
            drop.append(k)
    for k, v in values.items():
        if k not in known or from_env(k) or k in drop:
            continue
        v = ("" if v is None else str(v)).strip()
        if known[k][1] and not v:
            continue
        err = check(k, v)
        if err:
            errs.append(k + ": " + err)
        out[k] = v
    if errs:
        return errs
    now = db.now_iso()
    with db._lock, db.conn() as c:
        for k, v in out.items():
            c.execute("INSERT INTO settings (key, value, set_at) VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, set_at=excluded.set_at", (k, v, now))
        for k in drop:
            c.execute("DELETE FROM settings WHERE key=?", (k,))
    apply()
    return []


def save_form(form, keys):
    """The Settings page: '<KEY>_clear' boxes clear secrets."""
    return save({k: form.get(k) for k in keys if k in form}, [k for k in keys if form.get(k + "_clear")])


def public():
    """For the API: every field with its value (secrets as set / not set) and where it comes from."""
    s = saved()
    out = {}
    for _, k, secret, _ in fields():
        v, src = value(k, s)
        out[k] = {"set": bool(v), "source": src} if secret else {"value": v, "source": src}
    return out
