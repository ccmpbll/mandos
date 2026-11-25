"""Settings. Most are set on the Settings page or through the API (settings.py writes them onto this module); an environment
variable, when set, wins. The values below are the empty defaults before anything is saved. Secrets never live in code."""
import os
from zoneinfo import ZoneInfo


def env(name, default=""):
    f = os.environ.get(name + "_FILE")
    if f and os.path.exists(f):
        return open(f).read().strip()
    return os.environ.get(name, default)


HERE = os.path.dirname(os.path.abspath(__file__))
TZ = ZoneInfo(env("TZ", "UTC") or "UTC")       # schedules and the dates jobs write use this zone

# Environment only
DB_PATH = env("MANDOS_DB", os.path.join(HERE, "data", "mandos.db"))
JOBS_DIR = env("MANDOS_JOBS", os.path.join(os.path.dirname(os.path.abspath(DB_PATH)), "jobs"))   # the job pack (pack.py and its files)
DISABLE_AUTH = env("MANDOS_DISABLE_AUTH", "0") == "1"       # no login screen (then put mandos behind your own gate)
ALLOW_EDIT = env("MANDOS_ALLOW_EDIT", "0" if DISABLE_AUTH else "1") == "1"   # the Jobs page editor

# shadow: a trial run next to whatever mandos replaces. Pushover titles get "[mandos shadow] ", no Uptime Kuma heartbeat, and
# jobs should send nothing a person would have to approve (they read config.SHADOW).
MODE = "shadow"
SHADOW = True
BASE_URL = ""

LLM_URL = ""
LLM_MODEL = ""
EMBED_MODEL = ""
LLM_KEY = ""

PUSHOVER_TOKEN = ""
PUSHOVER_USER = ""
KUMA_PUSH_URL = ""

PROM_URL = ""
PIHOLE_URL = ""
LOGLOOK_URL = ""
LOGLOOK_TOKEN = ""
ULMO_URL = ""
ULMO_TOKEN = ""              # agent token (commands, catalog, runs, approvals)
ULMO_CHANGE_TOKEN = ""       # admin change token (change proposals)
ULMO_ROLE = "mandos"         # the role command proposals grant to
HA_URL = ""
HA_TOKEN = ""


def prompt(name):
    """A text file from the job pack's prompts/ folder."""
    return open(os.path.join(JOBS_DIR, "prompts", name)).read()
