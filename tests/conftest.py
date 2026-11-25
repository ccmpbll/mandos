"""Engine tests run against a copy of examples/starter as the job pack, with an in-memory database."""
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACK = tempfile.mkdtemp(prefix="mandos-pack-")
shutil.copytree(os.path.join(ROOT, "examples", "starter"), PACK, dirs_exist_ok=True)
os.environ["MANDOS_JOBS"] = PACK
os.environ["MANDOS_DB"] = ":memory:"
sys.path.insert(0, os.path.join(ROOT, "app"))

import pytest  # noqa: E402

import config  # noqa: E402
import db  # noqa: E402
import notify  # noqa: E402
import packs  # noqa: E402
import settings  # noqa: E402

db.init(":memory:")
packs.load()


@pytest.fixture(autouse=True)
def fresh_db():
    db._mem = None
    db.init(":memory:")
    with db.conn() as c:
        c.executescript(packs.load().SCHEMA)
    settings.apply()
    notify.sent.clear()
    config.DISABLE_AUTH = True        # page tests run without the login; test_auth turns it back on
    yield


@pytest.fixture
def pack_dir():
    return PACK
