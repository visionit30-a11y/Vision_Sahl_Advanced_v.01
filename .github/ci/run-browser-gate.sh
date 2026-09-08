#!/usr/bin/env bash
# Invoked from apps/web by security-command.py; output is captured in memory.
set -euo pipefail
set +x
export AUTH_HMAC_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"
browser_api_pid=''
cleanup_browser_api() {
  result=$?
  trap - EXIT INT TERM
  if [[ -n "$browser_api_pid" ]]; then
    sent_term=false
    if kill -0 "$browser_api_pid" 2>/dev/null; then
      if kill "$browser_api_pid"; then
        sent_term=true
      else
        result=1
      fi
      # Bound graceful shutdown. The outer command also owns the complete process group.
      for attempt in {1..50}; do
        if ! kill -0 "$browser_api_pid" 2>/dev/null; then
          break
        fi
        sleep 0.1
      done
      if kill -0 "$browser_api_pid" 2>/dev/null; then
        kill -KILL "$browser_api_pid"
        result=1
      fi
    fi
    # Always reap the process we started, even if it exited before cleanup.
    if wait "$browser_api_pid"; then
      cleanup_result=0
    else
      cleanup_result=$?
    fi
    if [[ "$cleanup_result" != 0 ]]; then
      if [[ "$cleanup_result" != 143 || "$sent_term" != true ]]; then
        result=1
      fi
    fi
  fi
  exit "$result"
}
trap cleanup_browser_api EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
../api/.venv/bin/python -m uvicorn app.main:app --app-dir ../api \
  --host 127.0.0.1 --port 8010 --no-access-log --log-level warning &
browser_api_pid=$!
browser_api_ready=false
for attempt in {1..30}; do
  if ! kill -0 "$browser_api_pid" 2>/dev/null; then
    echo 'The owned FastAPI process exited before browser readiness.' >&2
    exit 1
  fi
  if curl --fail --silent --output /dev/null http://127.0.0.1:8010/health/db; then
    browser_api_ready=true
    break
  fi
  sleep 1
done
if [[ "$browser_api_ready" != true ]]; then
  echo 'Real FastAPI/PostgreSQL did not become healthy on 8010.' >&2
  exit 1
fi
npm run test:browser
