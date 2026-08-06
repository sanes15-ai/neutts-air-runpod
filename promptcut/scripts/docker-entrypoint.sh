#!/usr/bin/env sh
# Boot the PromptCut server; seed a demo project if the volume is empty.
set -e

if [ ! -f /project/project.json ]; then
  echo "no project.json in /project — creating the demo project…"
  python /app/examples/make_demo.py
  cp -r /app/examples/demo/. /project/
fi

if [ -z "$PROMPTCUT_TOKEN" ]; then
  echo "NOTE: PROMPTCUT_TOKEN is not set — the UI is unprotected."
  echo "      docker run -e PROMPTCUT_TOKEN=\$(openssl rand -hex 16) …"
fi

exec promptcut serve --host 0.0.0.0 --port "${PORT:-7859}"
