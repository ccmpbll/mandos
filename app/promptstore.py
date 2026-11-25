"""Prompts with owner-approved additions. The base text is a file in the job pack's prompts/ folder; additions (for example ones
approved on a suggestions page) live in the prompt_additions table and are appended in id order. The pack names the prompts that
take additions in pack.PROMPT_TARGETS {target name: file}."""
import config
import db
import packs

MAX_ADDITIONS = 8


def targets():
    return packs.get("PROMPT_TARGETS", {}) or {}


def additions(target):
    return db.rows("prompt_additions", "target=?", (target,), order="id ASC")


def effective(target):
    return config.prompt(targets()[target]) + "".join(a["block"] for a in additions(target))
