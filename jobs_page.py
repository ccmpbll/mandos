"""Jobs page: what each job in the pack does, its prompts, queries and source, and the editor for the pack's files.
Each job's steps name the function that does the work ("module.function"); a step whose function is gone is flagged."""
import html
import json
import os
import re

import codeedit
import config
import db
import packs
import promptstore
import settings

esc = html.escape


def _module_file(mod):
    return mod.replace(".", "/") + ".py"


def line_of(rel, fn):
    """From the file on disk, so links stay right after an edit."""
    t = codeedit.read(rel)
    if t is None:
        return None
    for i, l in enumerate(t.split("\n"), 1):
        if re.match(r"\s*def " + re.escape(fn) + r"\(", l):
            return i
    return None


def schedule_text(name):
    line = settings.cron(name)
    return ("cron " + line if line else "not scheduled") + " (" + config.MODE + ")"


def last_run(name):
    r = db.rows("job_runs", "job=?", (name,), limit=1)
    if not r:
        return '<span class="badge">never</span>'
    r = r[0]
    cls = "ok" if r["status"] == "success" else "crit" if r["status"] == "failed" else "warn"
    return '<span class="badge ' + cls + '">' + esc(r["status"]) + "</span> " + esc(r["started"] or "")


def job_files(j):
    out = []
    for m in [j.get("module")] + [s[1].rsplit(".", 1)[0] for s in j.get("steps", []) if "." in s[1]]:
        if m and _module_file(m) not in out:
            out.append(_module_file(m))
    return out


def pack_state():
    err = ('<p class="error">The job pack did not load; the last good version keeps running.<br><code>' + esc(packs.error) + "</code></p>") if packs.error else ""
    return err + ('<p class="dim small">Pack ' + codeedit.fingerprint() + " · " + str(len(packs.files())) + " files in <code>" + esc(config.JOBS_DIR)
                  + "</code> · edits apply at the next run</p>")


def render_list():
    js = packs.jobs()
    rows = "".join(
        '<div class="playbook-row"><div class="playbook-row-header"><a class="playbook-name" href="/jobs/' + esc(n) + '">' + esc(j.get("title", n)) + '</a><span class="playbook-path">'
        + esc(", ".join(job_files(j)[:1])) + '</span></div><div class="playbook-facts"><span class="fact">' + esc(j.get("about", "")) + '</span></div>'
        + '<div class="playbook-facts"><span class="fact">⏱ ' + esc(schedule_text(n)) + '</span><span class="fact">' + last_run(n) + "</span></div></div>"
        for n, j in js.items())
    if not js:
        rows = ('<div class="playbook-row"><p class="dim">No jobs yet. A job pack is a folder with a <code>pack.py</code> in <code>' + esc(config.JOBS_DIR)
                + "</code>; put one there or send its files through the API (README: Job packs).</p></div>")
    files = "".join('<tr><td><code>' + esc(f) + '</code></td><td>' + (('<a href="/edit?file=' + esc(f) + '">Edit</a>') if config.ALLOW_EDIT and codeedit.safe(f) else "")
                    + "</td></tr>" for f in packs.files())
    return (CSS + '<div class="page-header"><div><h1>Jobs</h1><p class="sub">What each job does, its prompts and its code.</p>' + pack_state()
            + '</div></div><div class="card flush">' + rows + "</div>"
            + ("<h2>Pack files</h2><div class=\"card\"><details><summary>" + str(len(packs.files())) + ' files</summary><table class="q">' + files + "</table></details></div>"
               if files else ""))


def render_prompt(label, f, target):
    try:
        text = config.prompt(f)
    except OSError:
        text = "(missing: prompts/" + f + ")"
    adds = promptstore.additions(target) if target else []
    out = ('<div class="card"><div class="top"><b>' + esc(label) + '</b><span class="playbook-path">prompts/' + esc(f)
           + (" + " + str(len(adds)) + " addition" + ("" if len(adds) == 1 else "s") if adds else "") + "</span>"
           + (' <a class="small" href="/edit?file=prompts/' + esc(f) + '">Edit</a>' if config.ALLOW_EDIT else "") + "</div>"
           + "<details><summary>Base text (" + str(len(text.split())) + ' words)</summary><pre class="src wrap">' + esc(text) + "</pre></details>")
    for a in adds:
        out += ('<div class="add"><div class="meta">Addition #' + str(a["id"]) + " · " + esc(str(a.get("createdAt") or "")[:10])
                + (" · from suggestion " + str(a["suggestion_id"]) if a.get("suggestion_id") else "")
                + '</div><div class="pre">' + esc(a["block"].strip()) + "</div></div>")
    return out + "</div>"


def render_source(rel):
    t = codeedit.read(rel)
    if t is None:
        return '<p class="dim">No file <code>' + esc(rel) + "</code>.</p>"
    lines = t.splitlines()
    code = "\n".join('<span class="ln" id="L' + str(i) + '">' + str(i) + "</span>" + esc(l) for i, l in enumerate(lines, 1))
    return ('<details class="srcbox" id="source"><summary>' + esc(rel) + " · " + str(len(lines)) + " lines</summary>" + edit_link(rel)
            + '<pre class="src">' + code + "</pre></details>")


def edit_link(rel):
    if not config.ALLOW_EDIT:
        return '<p class="dim small">Editing is off (MANDOS_ALLOW_EDIT=0).</p>'
    n = len(codeedit.history(rel))
    return ('<p class="small"><a class="btn ghost" href="/edit?file=' + esc(rel) + '">Edit ' + esc(rel) + "</a>"
            + (' <span class="dim">' + str(n) + " earlier version" + ("" if n == 1 else "s") + "</span>" if n else "") + "</p>")


def render_job(name, file=None):
    j = packs.jobs()[name]
    fl = job_files(j)
    rel = file if file in fl else (fl[0] if fl else None)
    steps = ""
    for t, ref, how, k in [tuple(s) + ("",) * (4 - len(s)) for s in j.get("steps", [])]:
        mod, _, fn = ref.rpartition(".")
        n = line_of(_module_file(mod), fn) if mod else None
        link = ('<a href="/jobs/' + esc(name) + "?file=" + esc(_module_file(mod)) + "#L" + str(n) + '"><code>' + esc(ref) + "</code></a>") if n else \
            ('<code>' + esc(ref) + '</code> <span class="badge crit">not found</span>' if ref else "")
        steps += ('<li><span class="what">' + esc(t) + (' <span class="tag ' + esc(k) + '">' + esc(k) + "</span>" if k else "") + '</span><span class="how">'
                  + esc(how) + (" · " + link if link else "") + "</span></li>")
    body = ('<p class="back"><a href="/jobs">← Jobs</a></p><div class="page-header"><div><h1>' + esc(j.get("title", name)) + '</h1><p class="sub">'
            + esc(j.get("about", "")) + '</p><p class="sub">⏱ ' + esc(schedule_text(name)) + " · " + last_run(name) + ' · <a href="/runs">runs</a></p></div></div>'
            + ('<h2>Steps</h2><div class="card"><ol class="steps">' + steps + "</ol></div>" if steps else "")
            + ("<h2>Prompts</h2>" + "".join(render_prompt(*p) for p in j.get("prompts", [])) if j.get("prompts") else ""))
    if j.get("queries"):
        try:
            qs = json.loads(config.prompt(j["queries"]))
        except (OSError, ValueError):
            qs = []
        body += ("<h2>Queries <span class=\"dim\" style=\"font-weight:400\">(" + str(len(qs)) + ")</span></h2><div class=\"card\"><details><summary>Show all "
                 + str(len(qs)) + ' queries</summary><table class="q">' + "".join("<tr><td>" + esc(q.get("name", "")) + "</td><td><code>" + esc(q.get("query", ""))
                                                                                  + "</code></td></tr>" for q in qs) + "</table></details></div>")
    if rel:
        others = " · ".join(('<b>' + esc(f) + "</b>" if f == rel else '<a href="/jobs/' + esc(name) + "?file=" + esc(f) + '#source">' + esc(f) + "</a>") for f in fl)
        body += '<h2>Source</h2><div class="card">' + (('<p class="dim small" style="margin-top:0">' + others + "</p>") if len(fl) > 1 else "") + render_source(rel) + "</div>"
    return CSS + body, JS


def render_edit(rel, text=None, error=None, saved=False):
    if text is None:
        text = codeedit.read(rel) or ""
    ext = os.path.splitext(rel)[1]
    hist = "".join('<tr><td><code>' + esc(f[len(codeedit._hist_name(rel)) + 1:-len(ext)]) + '</code></td><td><form method="post" action="/edit/restore" '
                   'data-confirm="Put this version back? The current text is kept in the history."><input type="hidden" name="file" value="' + esc(rel)
                   + '"><input type="hidden" name="version" value="' + esc(f) + '"><button class="undo">Restore</button></form></td></tr>'
                   for f in codeedit.history(rel))
    return (CSS + '<p class="back"><a href="/jobs">← Jobs</a></p><div class="page-header"><div><h1>Edit ' + esc(rel)
            + '</h1><p class="sub">Saved to the job pack; the next run uses it. A Python file that does not compile or import, or JSON that does not parse, is refused. '
            'The previous text goes to the history below.</p></div></div>'
            + ('<p class="error">Not saved: ' + esc(error) + "</p>" if error else "") + ('<p class="ok">Saved.</p>' if saved else "")
            + '<form method="post" action="/edit"><input type="hidden" name="file" value="' + esc(rel) + '">'
            '<textarea name="text" class="code" spellcheck="false" autocapitalize="off" autocomplete="off">' + esc(text) + "</textarea>"
            '<div class="acts"><button type="submit">Save</button><a class="btn ghost" href="/jobs">Cancel</a></div></form>'
            + ("<h2>Earlier versions</h2><div class=\"card\"><table>" + hist + "</table></div>" if hist else ""))


# Tab indents 4 spaces in the editor; leaving with unsaved changes asks first.
EDIT_JS = ("var t=document.querySelector('textarea.code'),dirty=false;if(t){t.addEventListener('input',function(){dirty=true});"
           "t.addEventListener('keydown',function(e){if(e.key==='Tab'&&!e.shiftKey){e.preventDefault();var a=t.selectionStart;"
           "t.setRangeText('    ',a,t.selectionEnd,'end');dirty=true}});t.form.addEventListener('submit',function(){dirty=false});"
           "addEventListener('beforeunload',function(e){if(dirty){e.preventDefault();e.returnValue=''}})}"
           "document.addEventListener('submit',function(e){var m=e.target.getAttribute('data-confirm');if(m&&!confirm(m))e.preventDefault()});")



CSS = ("<style>.steps{counter-reset:s;list-style:none;padding:0;margin:0}.steps li{counter-increment:s;display:grid;grid-template-columns:28px 1fr;gap:2px 10px;"
       "padding:8px 0;border-top:1px solid var(--border)}.steps li:first-child{border-top:0}.steps li::before{content:counter(s);grid-row:1/span 2;width:24px;height:24px;"
       "border-radius:50%;background:var(--field);border:1px solid var(--border);font-size:.75rem;display:flex;align-items:center;justify-content:center;color:var(--muted)}"
       ".steps .what{font-weight:600}.steps .how{color:var(--muted);font-size:.85rem}.steps .how code{font-size:.8rem}"
       ".tag.model{color:#d79bff;border-color:rgba(215,155,255,.5)}.tag.guard{color:var(--green);border-color:rgba(62,207,142,.5)}"
       ".add{border-left:3px solid var(--accent);padding-left:10px;margin:10px 0}.add .meta{font-size:.8rem;color:var(--muted)}.top b{margin-right:6px}"
       "pre.src{max-height:70vh;overflow:auto;white-space:pre;font-size:.78rem}pre.src.wrap{white-space:pre-wrap}"
       "pre.src .ln{color:#4a5060;user-select:none;-webkit-user-select:none;display:inline-block;width:3.2em;scroll-margin-top:30vh}pre.src .ln:target{color:var(--accent);font-weight:700}"
       "table.q td:first-child{white-space:nowrap;font-weight:600}table.q td code{word-break:break-all}.back{font-size:.85rem;margin:0 0 8px}.small{font-size:.85rem}.ok-msg{color:var(--green)}"
       "textarea.code{display:block;width:100%;height:70vh;font:13px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;background:var(--field);color:var(--text);"
       "border:1px solid var(--border);border-radius:6px;padding:10px 12px;white-space:pre;overflow:auto;tab-size:4;resize:vertical}textarea.code:focus{outline:none;border-color:var(--accent)}"
       ".card.flush{padding:0}.playbook-row{display:grid;row-gap:6px;padding:16px;border-bottom:1px solid var(--border)}.playbook-row:last-child{border-bottom:0}"
       ".playbook-row-header{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap}.playbook-name{font-weight:700;font-size:1.05rem}.playbook-path{color:var(--muted);font-size:.8rem}"
       ".playbook-facts{display:flex;flex-wrap:wrap;align-items:center;gap:6px 20px;font-size:.85rem;color:var(--muted)}.fact{display:inline-flex;align-items:center;gap:4px 8px}</style>")


# A link to a line opens the source box and scrolls to it.
JS = ("function go(){var h=location.hash;if(!/^#L\\d+$/.test(h))return;var d=document.getElementById('source');if(d)d.open=true;"
      "var e=document.getElementById(h.slice(1));if(e)e.scrollIntoView({block:'center'})}addEventListener('hashchange',go);go();")


