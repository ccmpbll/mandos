"""The starter job. Engine modules it uses: config, db, llm, notify, sources, promptstore, web (page frame)."""
import json
import re

import config
import db
import llm
import notify
import promptstore
import sources
from web import esc
from web import page as frame


def down():
    r = sources.prom("up == 0")
    if r.get("error"):
        raise RuntimeError("Prometheus: " + r["error"])
    ignore = re.compile(config.TARGETS_IGNORE) if getattr(config, "TARGETS_IGNORE", "") else None
    out = []
    for s in (r.get("data") or {}).get("result", []):
        m = s.get("metric", {})
        if ignore and ignore.search(m.get("job", "")):
            continue
        out.append(m.get("job", "?") + " " + m.get("instance", "?"))
    return sorted(out)


def summarise(items):
    if not items or not config.LLM_MODEL:
        return ""
    return llm.chat_text(promptstore.effective("Summary prompt"), "Targets down:\n" + "\n".join(items)).strip()


def run(log):
    items = down()
    log(f"{len(items)} targets down")
    summary = summarise(items)
    db.insert("targets_runs", {"down": json.dumps(items), "summary": summary})
    if items:
        notify.push(f"{len(items)} targets down", summary or "\n".join(items)[:900], url=config.BASE_URL + "/targets" if config.BASE_URL else None, url_title="Open")


def page_body():
    rows = db.rows("targets_runs", limit=20)
    tr = "".join("<tr><td>" + esc(r["createdAt"][:16]) + "</td><td>" + esc(", ".join(json.loads(r["down"] or "[]")) or "none") + "</td><td>"
                 + esc(r["summary"] or "") + "</td></tr>" for r in rows)
    return ('<div class="page-header"><div><h1>Targets</h1><p class="sub">The last 20 runs of the starter job.</p></div></div>'
            + ("<table>" + tr + "</table>" if tr else '<p class="dim">No runs yet. Settings → Mode and schedule → Run now.</p>'))


def page():
    return frame("Targets - Mandos", "targets", page_body())
