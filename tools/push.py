#!/usr/bin/env python3
"""Send a job pack folder to mandos through its API: uploads files that differ, optionally removes files that are gone.

  python3 tools/push.py PACK_DIR --url https://mandos.example --token-file ~/mandos-token [--delete] [--dry-run]

The token can also come from MANDOS_TOKEN. Skips tests/, tools/, export/, mockup/, .history/, hidden files and anything that is
not a text type mandos keeps. Each Python file is import-checked by mandos; a refused file is reported and the rest still go.
Standard library only."""
import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request

SKIP_DIRS = {".history", "__pycache__", "tests", ".venv", "export", "mockup", "tools"}
TYPES = (".py", ".txt", ".json", ".j2", ".md", ".yml", ".yaml", ".csv", ".sql", ".html", ".css", ".js")


def local_files(d):
    out = {}
    for root, dirs, fs in os.walk(d):
        dirs[:] = sorted(x for x in dirs if x not in SKIP_DIRS and not x.startswith("."))
        for f in fs:
            if f.startswith(".") or not f.endswith(TYPES):
                continue
            p = os.path.join(root, f)
            rel = os.path.relpath(p, d).replace(os.sep, "/")
            data = open(p, "rb").read().replace(b"\r\n", b"\n")
            if data and not data.endswith(b"\n"):
                data += b"\n"
            out[rel] = data
    return out


def call(url, token, method, path, body=None):
    req = urllib.request.Request(url.rstrip("/") + "/api/v1/" + path, data=body, method=method,
                                 headers={"Authorization": "Bearer " + token, "Content-Type": "text/plain; charset=utf-8"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def main():
    a = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    a.add_argument("pack_dir")
    a.add_argument("--url", default=os.environ.get("MANDOS_URL"), required=not os.environ.get("MANDOS_URL"))
    a.add_argument("--token-file")
    a.add_argument("--delete", action="store_true", help="remove files on mandos that are not in PACK_DIR")
    a.add_argument("--dry-run", action="store_true")
    o = a.parse_args()
    token = (open(os.path.expanduser(o.token_file)).read().strip() if o.token_file else os.environ.get("MANDOS_TOKEN", "")).strip()
    if not token:
        sys.exit("no token: --token-file or MANDOS_TOKEN")
    st, body = call(o.url, token, "GET", "files")
    if st != 200:
        sys.exit(f"listing files failed: HTTP {st} {body[:200]!r}")
    remote = {f["path"]: f["sha256"] for f in json.loads(body)}
    local = local_files(o.pack_dir)
    # pack.py last: the modules it imports should be there first
    order = sorted((p for p in local if p != "pack.py"), key=lambda p: (not p.endswith(".py"), p)) + (["pack.py"] if "pack.py" in local else [])
    changed = [p for p in order if hashlib.sha256(local[p]).hexdigest() != remote.get(p)]
    gone = sorted(p for p in remote if p not in local) if o.delete else []
    failed = 0
    if o.dry_run:
        for p in changed:
            print("would send " + p)
    todo, why = list(changed), {}
    while todo and not o.dry_run:            # a module can import one not sent yet: retry the refused until nothing more goes through
        left = []
        for p in todo:
            st, body = call(o.url, token, "PUT", "files/" + p, local[p])
            if st == 200:
                print("sent " + p)
            else:
                left.append(p)
                why[p] = json.loads(body).get("error") if body[:1] == b"{" else body[:200]
        if len(left) == len(todo):
            break
        todo = left
    for p in ([] if o.dry_run else todo):
        failed += 1
        print(f"refused {p}: {why[p]}")
    for p in gone:
        print(("would remove " if o.dry_run else "remove ") + p)
        if not o.dry_run:
            st, body = call(o.url, token, "DELETE", "files/" + p)
            if st != 200:
                failed += 1
                print(f"  refused: {body[:200]!r}")
    if not changed and not gone:
        print("nothing to send")
    if not o.dry_run:
        st, body = call(o.url, token, "GET", "status")
        s = json.loads(body) if st == 200 else {}
        print("pack " + str(s.get("fingerprint")) + (" ERROR: " + s["pack_error"].splitlines()[-1] if s.get("pack_error") else " loaded, jobs: " + ", ".join(s.get("jobs", {}))))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
