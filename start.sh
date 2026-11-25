#!/bin/sh
# The image holds mandos only. The job pack (your jobs, prompts, pages) lives in /data/jobs: send it through the API
# (tools/push.py) or put it there. MANDOS_STARTER=1 copies the starter example in when that folder is empty.
set -e
JOBS=${MANDOS_JOBS:-/data/jobs}
mkdir -p "$JOBS"
if [ "${MANDOS_STARTER:-0}" = "1" ] && [ ! -f "$JOBS/pack.py" ] && [ -z "$(ls -A "$JOBS")" ]; then
  cp -R /opt/mandos/examples/starter/. "$JOBS/"
  echo "copied the starter pack into $JOBS"
fi
exec python /opt/mandos/app/main.py "$@"
