#!/usr/bin/env bash
# Invoked from apps/web by security-command.py; output is captured in memory.
set -euo pipefail
set +x
export AUTH_HMAC_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"
browser_api_pid=''
browser_s3_pid=''
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
  if [[ -n "$browser_s3_pid" ]]; then
    if kill -0 "$browser_s3_pid" 2>/dev/null; then
      kill "$browser_s3_pid" || result=1
    fi
    if wait "$browser_s3_pid"; then
      :
    else
      cleanup_result=$?
      if [[ "$cleanup_result" != 143 ]]; then result=1; fi
    fi
  fi
  exit "$result"
}
trap cleanup_browser_api EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
export OBJECT_STORAGE_ENDPOINT_URL='http://127.0.0.1:9001'
export OBJECT_STORAGE_BUCKET='sahl-browser-documents'
export OBJECT_STORAGE_ACCESS_KEY='browser'
export OBJECT_STORAGE_SECRET_KEY='browser'
../api/.venv/bin/moto_server -H 127.0.0.1 -p 9001 >/dev/null 2>&1 &
browser_s3_pid=$!
browser_s3_ready=false
for attempt in {1..30}; do
  if ! kill -0 "$browser_s3_pid" 2>/dev/null; then
    echo 'The owned S3 test process exited before browser readiness.' >&2
    exit 1
  fi
  if ../api/.venv/bin/python - <<'PY'
import boto3
from botocore.exceptions import BotoCoreError, ClientError
try:
    client = boto3.client(
        's3', endpoint_url='http://127.0.0.1:9001',
        aws_access_key_id='browser', aws_secret_access_key='browser',
        region_name='us-east-1',
    )
    client.create_bucket(Bucket='sahl-browser-documents')
except (BotoCoreError, ClientError, OSError):
    raise SystemExit(1) from None
PY
  then
    browser_s3_ready=true
    break
  fi
  sleep 1
done
if [[ "$browser_s3_ready" != true ]]; then
  echo 'Isolated S3 test service did not become healthy on 9001.' >&2
  exit 1
fi
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
