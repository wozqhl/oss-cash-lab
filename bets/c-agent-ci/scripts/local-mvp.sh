#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH=src

python3 -m agent_ci smoke

echo "==> demo suite (expect PASS)"
rm -f out/junit-demo.xml out/baseline.json out/demo-suite.zip
mkdir -p out
python3 -m agent_ci run --suite fixtures/demo --junit out/junit-demo.xml --save-baseline out/baseline.json
test -f out/junit-demo.xml
test -f out/baseline.json
grep -q 'failures="0"' out/junit-demo.xml
grep -q '<testsuite' out/junit-demo.xml
grep -q 'france-capital' out/baseline.json
echo "==> run --format junit (stdout XML)"
python3 -m agent_ci run --suite fixtures/demo --format junit > out/junit-format.xml
grep -q '<testsuite' out/junit-format.xml
grep -q 'failures="0"' out/junit-format.xml
echo "==> run --format tap (stdout TAP13)"
python3 -m agent_ci run --suite fixtures/demo --format tap > out/tap-format.txt
grep -q 'TAP version 13' out/tap-format.txt
grep -q 'ok ' out/tap-format.txt
echo "==> run --format md (stdout Markdown / GITHUB_STEP_SUMMARY)"
python3 -m agent_ci run --suite fixtures/demo --format md > out/md-format.md
grep -q '# ' out/md-format.md
grep -q '| case | status | time |' out/md-format.md
echo "==> run --format html (stdout self-contained HTML)"
python3 -m agent_ci run --suite fixtures/demo --format html > out/html-format.html
grep -q '<table' out/html-format.html
grep -q 'agent-ci' out/html-format.html
echo "==> run --format gha (stdout GHA workflow commands; pass-only has no ::error)"
python3 -m agent_ci run --suite fixtures/demo --format gha > out/gha-pass.txt
if grep -q '::error' out/gha-pass.txt; then
  echo "pass-only --format gha unexpectedly contains ::error"
  cat out/gha-pass.txt
  exit 1
fi

echo "==> quality gate CLI --fail-under 80 on demo (score 100, expect PASS / exit 0)"
python3 -m agent_ci run --suite fixtures/demo --fail-under 80

echo "==> quality gate CLI --fail-under 80 on mixed 1 pass / 1 fail (score 50, expect FAIL / exit 1)"
MIXED="$ROOT/out/gate-mixed"
rm -rf "$MIXED"
mkdir -p "$MIXED"
cp fixtures/demo/france-capital.json "$MIXED/"
cp fixtures/drift/france-drift.json "$MIXED/"
set +e
python3 -m agent_ci run --suite "$MIXED" --fail-under 80 --junit out/junit-gate-mixed.xml
gate_code=$?
set -e
if [ "$gate_code" -eq 0 ]; then
  echo "fail-under 80 unexpectedly passed on mixed 1/1 suite"
  exit 1
fi
test -f out/junit-gate-mixed.xml
grep -q 'failures="1"' out/junit-gate-mixed.xml

echo "==> promptfoo adapter good fixture (expect PASS / exit 0 + junit + tap)"
python3 -m agent_ci from-promptfoo --in fixtures/promptfoo/good.json --junit out/junit-promptfoo-good.xml --tap out/promptfoo-good.tap --fail-under 80
test -f out/junit-promptfoo-good.xml
test -f out/promptfoo-good.tap
grep -q 'failures="0"' out/junit-promptfoo-good.xml
grep -q '<testsuite' out/junit-promptfoo-good.xml
grep -q 'france-capital' out/junit-promptfoo-good.xml
grep -q 'TAP version 13' out/promptfoo-good.tap
grep -q 'ok ' out/promptfoo-good.tap

echo "==> promptfoo adapter bad fixture (expect FAIL / exit 1 + junit)"
set +e
python3 -m agent_ci from-promptfoo --in fixtures/promptfoo/bad.json --junit out/junit-promptfoo-bad.xml --fail-under 80
pf_code=$?
set -e
if [ "$pf_code" -eq 0 ]; then
  echo "from-promptfoo unexpectedly passed on bad fixture"
  exit 1
fi
test -f out/junit-promptfoo-bad.xml
grep -q '<failure' out/junit-promptfoo-bad.xml
grep -q '&amp;' out/junit-promptfoo-bad.xml

echo "==> deepeval adapter good fixture (expect PASS / exit 0 + junit + tap)"
python3 -m agent_ci from-deepeval --in fixtures/deepeval/good.json --junit out/junit-deepeval-good.xml --tap out/deepeval-good.tap --md out/deepeval-good.md --fail-under 80
test -f out/junit-deepeval-good.xml
test -f out/deepeval-good.tap
test -f out/deepeval-good.md
grep -q 'failures="0"' out/junit-deepeval-good.xml
grep -q '<testsuite' out/junit-deepeval-good.xml
grep -q 'france-capital' out/junit-deepeval-good.xml
grep -q 'TAP version 13' out/deepeval-good.tap
grep -q 'ok ' out/deepeval-good.tap
echo "deepeval-ok"

echo "==> deepeval adapter bad fixture (expect FAIL / exit 1 + junit)"
set +e
python3 -m agent_ci from-deepeval --in fixtures/deepeval/bad.json --junit out/junit-deepeval-bad.xml --fail-under 80
de_code=$?
set -e
if [ "$de_code" -eq 0 ]; then
  echo "from-deepeval unexpectedly passed on bad fixture"
  exit 1
fi
test -f out/junit-deepeval-bad.xml
grep -q '<failure' out/junit-deepeval-bad.xml
grep -q '&amp;' out/junit-deepeval-bad.xml

echo "==> baseline diff against same suite (expect PASS)"
python3 -m agent_ci run --suite fixtures/demo --diff-baseline out/baseline.json

echo "==> import-suite demo -> private-demo"
rm -rf fixtures/private-demo
python3 -m agent_ci import-suite --from fixtures/demo --to fixtures/private-demo
test -f fixtures/private-demo/france-capital.json
test -f fixtures/private-demo/math-2plus2.json

echo "==> zip import path"
python3 - <<'PY'
import zipfile
from pathlib import Path
src = Path("fixtures/demo")
zpath = Path("out/demo-suite.zip")
with zipfile.ZipFile(zpath, "w") as zf:
    for f in sorted(src.glob("*.json")):
        zf.write(f, arcname=f.name)
print(f"wrote {zpath}")
PY
rm -rf fixtures/from-zip
python3 -m agent_ci import-suite --from out/demo-suite.zip --to fixtures/from-zip
test -f fixtures/from-zip/france-capital.json
test -f fixtures/from-zip/math-2plus2.json
python3 -m agent_ci run --suite fixtures/from-zip --diff-baseline out/baseline.json

echo "==> mutate private-demo to force trajectory/score regression"
python3 - <<'PY'
import json
from pathlib import Path
p = Path("fixtures/private-demo/france-capital.json")
data = json.loads(p.read_text())
# cassette expects wrong answer so case fails vs mock agent (Paris)
data["trajectory"][-1]["arguments"]["text"] = "Berlin"
p.write_text(json.dumps(data, indent=2) + "\n")
PY

echo "==> baseline diff on regressing private-demo (expect FAIL)"
set +e
python3 -m agent_ci run --suite fixtures/private-demo --diff-baseline out/baseline.json
code=$?
set -e
if [ "$code" -eq 0 ]; then
  echo "baseline diff unexpectedly passed on regressing suite"
  exit 1
fi

echo "==> drift suite (expect FAIL / exit 1)"
set +e
python3 -m agent_ci run --suite fixtures/drift --junit out/junit-drift.xml
code=$?
set -e
if [ "$code" -eq 0 ]; then
  echo "drift suite unexpectedly passed"
  exit 1
fi
test -f out/junit-drift.xml
grep -q 'failures="1"' out/junit-drift.xml
echo "==> run --format gha on drift (expect FAIL + ::error)"
set +e
python3 -m agent_ci run --suite fixtures/drift --format gha > out/gha-fail.txt
gha_code=$?
set -e
if [ "$gha_code" -eq 0 ]; then
  echo "drift --format gha unexpectedly passed"
  exit 1
fi
grep -q '::error' out/gha-fail.txt

echo "==> local hosted-runner stub (serve API, concurrency=1 max-queue=1)"
PORT=8791
RUNS_DIR="$ROOT/data/runs"
rm -rf "$RUNS_DIR"
mkdir -p "$RUNS_DIR" data
SERVE_LOG="$ROOT/data/serve.log"
WH_PORT="${WH_PORT:-$((PORT + 19))}"
WH_OUT="$ROOT/data/webhook-last.json"
WH_HDR="$ROOT/data/webhook-last.headers.json"
WH_LOG="$ROOT/data/mock-webhook.log"
rm -f "$WH_OUT" "$WH_HDR"
# Default deny CORS: do not pass --cors-origins; ignore leftover env.
unset AGENT_CI_CORS_ORIGINS || true
unset AGENT_CI_WEBHOOK_URL || true
unset AGENT_CI_WEBHOOK_SECRET || true
unset LOG_FORMAT || true
unset RATE_LIMIT_PER_MINUTE RATE_LIMIT_RPM || true
unset RUNS_MAX || true

echo "==> mock run-complete webhook receiver :${WH_PORT}"
python3 "$ROOT/mock-webhook-receiver.py" --port "$WH_PORT" --out "$WH_OUT" --headers-out "$WH_HDR" >"$WH_LOG" 2>&1 &
WH_PID=$!
python3 -m agent_ci serve --port "$PORT" --runs-dir "$RUNS_DIR" \
  --concurrency 1 --max-queue 1 \
  --webhook-url "http://127.0.0.1:${WH_PORT}/hook" >"$SERVE_LOG" 2>&1 &
SERVE_PID=$!
CORS_PID=""
HMAC_PID=""
HMAC_WH_PID=""
WATCH_PID=""
WATCH_DIR=""
LOG_PID=""
RL_PID=""
RUNSMAX_PID=""
cleanup_serve() {
  if [ -n "${RUNSMAX_PID:-}" ] && kill -0 "$RUNSMAX_PID" 2>/dev/null; then
    kill "$RUNSMAX_PID" 2>/dev/null || true
    wait "$RUNSMAX_PID" 2>/dev/null || true
  fi
  if [ -n "${RL_PID:-}" ] && kill -0 "$RL_PID" 2>/dev/null; then
    kill "$RL_PID" 2>/dev/null || true
    wait "$RL_PID" 2>/dev/null || true
  fi
  if [ -n "${LOG_PID:-}" ] && kill -0 "$LOG_PID" 2>/dev/null; then
    kill "$LOG_PID" 2>/dev/null || true
    wait "$LOG_PID" 2>/dev/null || true
  fi
  if [ -n "${CORS_PID:-}" ] && kill -0 "$CORS_PID" 2>/dev/null; then
    kill "$CORS_PID" 2>/dev/null || true
    wait "$CORS_PID" 2>/dev/null || true
  fi
  if [ -n "${HMAC_PID:-}" ] && kill -0 "$HMAC_PID" 2>/dev/null; then
    kill "$HMAC_PID" 2>/dev/null || true
    wait "$HMAC_PID" 2>/dev/null || true
  fi
  if [ -n "${HMAC_WH_PID:-}" ] && kill -0 "$HMAC_WH_PID" 2>/dev/null; then
    kill "$HMAC_WH_PID" 2>/dev/null || true
    wait "$HMAC_WH_PID" 2>/dev/null || true
  fi
  if [ -n "${WATCH_PID:-}" ] && kill -0 "$WATCH_PID" 2>/dev/null; then
    kill "$WATCH_PID" 2>/dev/null || true
    wait "$WATCH_PID" 2>/dev/null || true
  fi
  if [ -n "${WATCH_DIR:-}" ]; then
    rm -rf "$WATCH_DIR"
  fi
  if [ -n "${WH_PID:-}" ] && kill -0 "$WH_PID" 2>/dev/null; then
    kill "$WH_PID" 2>/dev/null || true
    wait "$WH_PID" 2>/dev/null || true
  fi
  if kill -0 "$SERVE_PID" 2>/dev/null; then
    kill "$SERVE_PID" 2>/dev/null || true
    wait "$SERVE_PID" 2>/dev/null || true
  fi
}
trap cleanup_serve EXIT

# wait for mock webhook /health
for i in $(seq 1 40); do
  if curl -sf "http://127.0.0.1:$WH_PORT/health" >/dev/null; then
    break
  fi
  sleep 0.1
  if [ "$i" -eq 40 ]; then
    echo "mock webhook receiver did not become healthy"
    cat "$WH_LOG" || true
    exit 1
  fi
done

# wait for /health
for i in $(seq 1 40); do
  if curl -sf "http://127.0.0.1:$PORT/health" >/dev/null; then
    break
  fi
  sleep 0.1
  if [ "$i" -eq 40 ]; then
    echo "serve did not become healthy"
    cat "$SERVE_LOG" || true
    exit 1
  fi
done

HEALTH="$(curl -sf "http://127.0.0.1:$PORT/health")"
echo "$HEALTH" | grep -Eq '"ok"[[:space:]]*:[[:space:]]*true'
echo "$HEALTH" | grep -Eq '"concurrency"[[:space:]]*:[[:space:]]*1'

echo "==> GET /ready idle (queue empty) → 200 {ok:true, queue}"
READY_IDLE="$(curl -s -o data/ready-idle.json -w '%{http_code}' "http://127.0.0.1:$PORT/ready")"
echo "ready_idle_status=$READY_IDLE body=$(cat data/ready-idle.json)"
test "$READY_IDLE" = "200"
python3 - <<'PYREADYIDLE'
import json
from pathlib import Path
r = json.loads(Path("data/ready-idle.json").read_text(encoding="utf-8"))
assert r.get("ok") is True, r
assert not r.get("reason"), r
q = r.get("queue") or {}
assert int(q.get("concurrency") or 0) == 1, q
assert int(q.get("queued") or 0) == 0, q
print("ready_idle_ok", q)
PYREADYIDLE

echo "==> X-Request-Id omitted → generated UUID echoed on every response"
curl -s -o /tmp/c-health-rid.json -D /tmp/c-health-rid.h "http://127.0.0.1:$PORT/health" >/dev/null
grep -qiE '^x-request-id:' /tmp/c-health-rid.h
GEN_RID="$(tr -d '\r' < /tmp/c-health-rid.h | awk 'tolower($0) ~ /^x-request-id:/{print $2; exit}')"
echo "generated_request_id=$GEN_RID"
echo "$GEN_RID" | grep -qE '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
echo "request_id_generated_ok"

echo "==> GET /openapi.json (file-backed spec)"
curl -s -o data/openapi.json -D data/openapi.h "http://127.0.0.1:$PORT/openapi.json"
test -s data/openapi.json
grep -q '"openapi"' data/openapi.json
grep -qiE '^x-request-id:' data/openapi.h
python3 - <<'PY'
import json
from pathlib import Path
spec = json.loads(Path("data/openapi.json").read_text(encoding="utf-8"))
assert str(spec.get("openapi") or "").startswith("3."), spec.get("openapi")
paths = spec.get("paths") or {}
need = [
    "/health",
    "/ready",
    "/metrics",
    "/v1/runs",
    "/v1/runs/{id}",
    "/v1/runs/{id}/junit",
    "/v1/runs/{id}/junit.xml",
    "/v1/runs/junit.xml",
    "/v1/runs/{id}/tap",
    "/v1/runs/{id}/tap.txt",
    "/v1/runs/tap.txt",
    "/v1/runs/{id}/md",
    "/v1/runs/{id}/report.md",
    "/v1/runs/report.md",
    "/v1/runs/{id}/html",
    "/v1/runs/{id}/report.html",
    "/v1/runs/report.html",
    "/v1/runs/{id}/annotations",
    "/v1/runs/{id}/annotations.txt",
    "/v1/runs/annotations.txt",
    "/v1/runs/{id}/diff",
    "/v1/runs/{id}/diff.md",
    "/v1/runs/{id}/diff.html",
    "/v1/runs/{id}/cases",
    "/v1/check-runs",
    "/v1/suites",
    "/v1/suites/{name}",
    "/v1/config",
]
missing = [p for p in need if p not in paths]
assert not missing, missing
assert "get" in (paths.get("/health") or {})
assert "get" in (paths.get("/ready") or {})
assert ((paths.get("/ready") or {}).get("get") or {}).get("operationId") == "getReady"
ready_resp = ((paths.get("/ready") or {}).get("get") or {}).get("responses") or {}
assert "200" in ready_resp and "503" in ready_resp, sorted(ready_resp)
ready200_ref = (((ready_resp.get("200") or {}).get("content") or {}).get("application/json") or {}).get("schema") or {}
ready503_ref = (((ready_resp.get("503") or {}).get("content") or {}).get("application/json") or {}).get("schema") or {}
assert "Ready" in str(ready200_ref.get("$ref") or ""), ready200_ref
assert "Ready" in str(ready503_ref.get("$ref") or ""), ready503_ref
assert (ready_resp.get("503") or {}).get("headers") and "Retry-After" in (ready_resp.get("503") or {}).get("headers"), ready_resp.get("503")
assert "get" in (paths.get("/metrics") or {})
assert ((paths.get("/metrics") or {}).get("get") or {}).get("operationId") == "getMetrics"
assert "get" in (paths.get("/v1/runs") or {}) and "post" in (paths.get("/v1/runs") or {})
assert "get" in (paths.get("/v1/runs/{id}") or {})
assert "get" in (paths.get("/v1/runs/{id}/junit") or {})
assert "get" in (paths.get("/v1/runs/{id}/junit.xml") or {})
assert "get" in (paths.get("/v1/runs/junit.xml") or {})
assert "get" in (paths.get("/v1/runs/{id}/tap") or {})
assert "get" in (paths.get("/v1/runs/{id}/tap.txt") or {})
assert "get" in (paths.get("/v1/runs/tap.txt") or {})
assert "get" in (paths.get("/v1/runs/{id}/md") or {})
assert "get" in (paths.get("/v1/runs/{id}/report.md") or {})
assert "get" in (paths.get("/v1/runs/report.md") or {})
assert "get" in (paths.get("/v1/runs/{id}/html") or {})
assert "get" in (paths.get("/v1/runs/{id}/report.html") or {})
assert "get" in (paths.get("/v1/runs/report.html") or {})
assert ((paths.get("/v1/runs/{id}/html") or {}).get("get") or {}).get("operationId") == "getRunHtml"
assert "get" in (paths.get("/v1/runs/{id}/annotations") or {})
assert "get" in (paths.get("/v1/runs/{id}/annotations.txt") or {})
assert "get" in (paths.get("/v1/runs/annotations.txt") or {})
assert "get" in (paths.get("/v1/runs/{id}/diff") or {})
assert ((paths.get("/v1/runs/{id}/diff") or {}).get("get") or {}).get("operationId") == "getRunDiff"
assert "get" in (paths.get("/v1/runs/{id}/diff.md") or {})
assert ((paths.get("/v1/runs/{id}/diff.md") or {}).get("get") or {}).get("operationId") == "getRunDiffMd"
assert "get" in (paths.get("/v1/runs/{id}/diff.html") or {})
assert ((paths.get("/v1/runs/{id}/diff.html") or {}).get("get") or {}).get("operationId") == "getRunDiffHtml"
assert "get" in (paths.get("/v1/runs/{id}/cases") or {})
assert ((paths.get("/v1/runs/{id}/cases") or {}).get("get") or {}).get("operationId") == "listRunCases"
assert "post" in (paths.get("/v1/check-runs") or {})
assert "get" in (paths.get("/v1/suites") or {})
assert "get" in (paths.get("/v1/suites/{name}") or {})
assert ((paths.get("/v1/suites/{name}") or {}).get("get") or {}).get("operationId") == "getSuite"
assert "get" in (paths.get("/v1/config") or {})
assert ((paths.get("/v1/config") or {}).get("get") or {}).get("operationId") == "getConfig"
post_runs = ((paths.get("/v1/runs") or {}).get("post") or {}).get("responses") or {}
for code in ("202", "401", "429"):
    assert code in post_runs, (code, sorted(post_runs))
get_run = ((paths.get("/v1/runs/{id}") or {}).get("get") or {}).get("responses") or {}
get_junit = ((paths.get("/v1/runs/{id}/junit") or {}).get("get") or {}).get("responses") or {}
get_junit_xml = ((paths.get("/v1/runs/{id}/junit.xml") or {}).get("get") or {}).get("responses") or {}
get_runs_junit = ((paths.get("/v1/runs/junit.xml") or {}).get("get") or {}).get("responses") or {}
get_tap = ((paths.get("/v1/runs/{id}/tap") or {}).get("get") or {}).get("responses") or {}
get_tap_txt = ((paths.get("/v1/runs/{id}/tap.txt") or {}).get("get") or {}).get("responses") or {}
get_runs_tap = ((paths.get("/v1/runs/tap.txt") or {}).get("get") or {}).get("responses") or {}
get_md = ((paths.get("/v1/runs/{id}/md") or {}).get("get") or {}).get("responses") or {}
get_report_md = ((paths.get("/v1/runs/{id}/report.md") or {}).get("get") or {}).get("responses") or {}
get_runs_md = ((paths.get("/v1/runs/report.md") or {}).get("get") or {}).get("responses") or {}
get_html = ((paths.get("/v1/runs/{id}/html") or {}).get("get") or {}).get("responses") or {}
get_report_html = ((paths.get("/v1/runs/{id}/report.html") or {}).get("get") or {}).get("responses") or {}
get_runs_html = ((paths.get("/v1/runs/report.html") or {}).get("get") or {}).get("responses") or {}
get_ann = ((paths.get("/v1/runs/{id}/annotations") or {}).get("get") or {}).get("responses") or {}
get_ann_txt = ((paths.get("/v1/runs/{id}/annotations.txt") or {}).get("get") or {}).get("responses") or {}
get_runs_ann = ((paths.get("/v1/runs/annotations.txt") or {}).get("get") or {}).get("responses") or {}
get_diff = ((paths.get("/v1/runs/{id}/diff") or {}).get("get") or {}).get("responses") or {}
get_diff_md = ((paths.get("/v1/runs/{id}/diff.md") or {}).get("get") or {}).get("responses") or {}
get_diff_html = ((paths.get("/v1/runs/{id}/diff.html") or {}).get("get") or {}).get("responses") or {}
get_suite = ((paths.get("/v1/suites/{name}") or {}).get("get") or {}).get("responses") or {}
assert "404" in get_run, get_run
assert "404" in get_junit, get_junit
assert "404" in get_junit_xml, get_junit_xml
assert "200" in get_runs_junit, get_runs_junit
assert "404" in get_tap, get_tap
assert "404" in get_tap_txt, get_tap_txt
assert "200" in get_runs_tap, get_runs_tap
assert "404" in get_md, get_md
assert "404" in get_report_md, get_report_md
assert "200" in get_runs_md, get_runs_md
assert "404" in get_html, get_html
assert "404" in get_report_html, get_report_html
assert "200" in get_runs_html, get_runs_html
assert "404" in get_ann, get_ann
assert "404" in get_ann_txt, get_ann_txt
assert "200" in get_runs_ann, get_runs_ann
assert "200" in get_diff and "404" in get_diff and "409" in get_diff, get_diff
assert "200" in get_diff_md and "404" in get_diff_md and "409" in get_diff_md, get_diff_md
assert "200" in get_diff_html and "404" in get_diff_html and "409" in get_diff_html, get_diff_html
get_cases = ((paths.get("/v1/runs/{id}/cases") or {}).get("get") or {}).get("responses") or {}
assert "200" in get_cases and "404" in get_cases, get_cases
assert "404" in get_suite, get_suite
schemes = (spec.get("components") or {}).get("securitySchemes") or {}
assert "BearerAuth" in schemes, schemes
params = (spec.get("components") or {}).get("parameters") or {}
headers = (spec.get("components") or {}).get("headers") or {}
assert "XRequestId" in params, params
assert "XRequestId" in headers, headers
desc = str((spec.get("info") or {}).get("description") or "")
assert "X-Request-Id" in desc or "requestId" in desc, "missing X-Request-Id note"
assert "AGENT_CI_WEBHOOK_URL" in desc or "webhook-url" in desc, "missing webhook note"
assert "AGENT_CI_WEBHOOK_SECRET" in desc or "webhook-secret" in desc, "missing webhook secret note"
assert "X-Webhook-Signature" in desc, "missing HMAC signature note"
assert "X-Webhook-Timestamp" in desc, "missing webhook timestamp note"
assert "/ready" in desc or "GET /ready" in desc, "missing GET /ready note"
assert "queue_full" in desc, "missing queue_full readiness note"
schemas = (spec.get("components") or {}).get("schemas") or {}
assert "RunCompleteWebhook" in schemas, sorted(schemas)
assert "Ready" in schemas, sorted(schemas)
assert "WatchSnapshot" in schemas, sorted(schemas)
responses = (spec.get("components") or {}).get("responses") or {}
assert "RateLimited" in responses, sorted(responses)
assert "429" in (((paths.get("/v1/suites") or {}).get("get") or {}).get("responses") or {}), "suites 429"
assert "429" in (((paths.get("/v1/runs") or {}).get("get") or {}).get("responses") or {}), "runs GET 429"
assert "Retry-After" in desc and "rate_limited" in desc, "missing rate-limit note"
assert "failUnder" in str((schemas.get("CreateRunRequest") or {}).get("properties") or {}), "missing failUnder"
assert "score" in str((schemas.get("RunRecord") or {}).get("properties") or {}), "missing score"
assert "gate" in str((schemas.get("RunRecord") or {}).get("properties") or {}), "missing gate"
assert "failed" in str((schemas.get("RunRecord") or {}).get("properties") or {}), "missing failed status"
assert "QualityGate" in schemas, sorted(schemas)
assert "RunDiff" in schemas, sorted(schemas)
assert "RuntimeConfig" in schemas, sorted(schemas)
assert "RunCases" in schemas, sorted(schemas)
assert "RunCaseRow" in schemas, sorted(schemas)
assert "failUnder" in desc and "below_threshold" in desc, "missing quality-gate note"
assert "run_not_done" in desc, "missing run_not_done note"
assert "/diff" in desc, "missing /diff note"
assert "diff.md" in desc, "missing /diff.md note"
assert "diff.html" in desc, "missing /diff.html note"
assert "report.md" in desc, "missing report.md note"
assert "GITHUB_STEP_SUMMARY" in desc, "missing GITHUB_STEP_SUMMARY note"
assert "report.html" in desc, "missing report.html note"
assert "annotations.txt" in desc, "missing annotations.txt note"
assert "RUNS_MAX" in desc or "runs-max" in desc, "missing runs-max note"
assert "GET /v1/config" in desc, "missing GET /v1/config note"
assert "listRunCases" in desc or "/cases" in desc, "missing /cases note"
assert "SuiteDetail" in schemas, sorted(schemas)
assert "getSuite" in desc or "SuiteDetail" in desc, "missing getSuite note"
assert "score" in str((schemas.get("RunCompleteWebhook") or {}).get("properties") or {}), "missing webhook score"
assert "gate" in str((schemas.get("RunCompleteWebhook") or {}).get("properties") or {}), "missing webhook gate"
watch_props = (schemas.get("WatchSnapshot") or {}).get("properties") or {}
assert "generation" in watch_props, watch_props
health_props = (schemas.get("Health") or {}).get("properties") or {}
assert "watch" in health_props, health_props
assert "--watch" in desc, "missing serve --watch note"
ready_props = (schemas.get("Ready") or {}).get("properties") or {}
assert "ok" in ready_props and "queue" in ready_props, ready_props
reason_enum = ((ready_props.get("reason") or {}).get("enum") or [])
assert "queue_full" in reason_enum, reason_enum
print("openapi_paths_ok", len(paths))
PY

echo "==> default deny CORS (main serve has no --cors-origins)"
DEF_GET="$(curl -s -o /tmp/c-def-cors.json -D /tmp/c-def-cors.h -w "%{http_code}" \
  "http://127.0.0.1:$PORT/health" -H "Origin: http://localhost:3000")"
echo "default_cors_get_status=$DEF_GET"
test "$DEF_GET" = "200"
if grep -qiE "^access-control-allow-origin:" /tmp/c-def-cors.h; then
  echo "default serve must not send ACAO"
  cat /tmp/c-def-cors.h
  exit 1
fi
DEF_OPT="$(curl -s -o /tmp/c-def-opt.json -D /tmp/c-def-opt.h -w "%{http_code}" \
  -X OPTIONS "http://127.0.0.1:$PORT/health" -H "Origin: http://localhost:3000" \
  -H "Access-Control-Request-Method: GET" \
  -H "X-Request-Id: mvp-opt-rid-404")"
echo "default_cors_options_status=$DEF_OPT"
test "$DEF_OPT" = "404"
if grep -qiE "^access-control-allow-origin:" /tmp/c-def-opt.h; then
  echo "default OPTIONS must not send ACAO"
  cat /tmp/c-def-opt.h
  exit 1
fi
grep -qiE "^x-request-id:[[:space:]]*mvp-opt-rid-404" /tmp/c-def-opt.h

echo "==> GET /v1/config (redacted; no secrets)"
CFG_CODE="$(curl -s -o data/c-config.json -D data/c-config.h -w '%{http_code}' \
  "http://127.0.0.1:$PORT/v1/config" -H "X-Request-Id: mvp-config-rid")"
echo "config_status=$CFG_CODE body=$(cat data/c-config.json)"
test "$CFG_CODE" = "200"
grep -qiE "^x-request-id:[[:space:]]*mvp-config-rid" data/c-config.h
python3 - <<'PYCFG'
import json
from pathlib import Path
body = json.loads(Path("data/c-config.json").read_text(encoding="utf-8"))
assert body.get("ok") is True, body
q = body.get("queue") or {}
cors = body.get("cors") or {}
assert q.get("max") is not None or cors.get("origins") is not None, body
assert "rateLimit" in body and "runsMax" in body, body
assert "webhooks" in body, body
assert "hasUrl" in (body.get("webhooks") or {}), body
assert "hasSecret" in (body.get("webhooks") or {}), body
blob = json.dumps(body)
for needle in (
    "webhookUrl",
    "webhookSecret",
    "webhook_url",
    "webhook_secret",
    "Authorization",
    "AGENT_CI_WEBHOOK_SECRET",
    "whsec_",
):
    assert needle not in blob, needle
print("config_ok", "queue", q, "runsMax", body.get("runsMax"), "hasUrl", (body.get("webhooks") or {}).get("hasUrl"))
PYCFG
echo "config_ok"

echo "==> GET /v1/suites lists fixture dirs"
SUITES="$(curl -sf "http://127.0.0.1:$PORT/v1/suites")"
echo "$SUITES" | tee data/suites.json
echo "$SUITES" | grep -Eq '"name"[[:space:]]*:[[:space:]]*"demo"'
python3 -c 'import json; from pathlib import Path; data=json.loads(Path("data/suites.json").read_text()); suites=data.get("suites") or []; demo=next((s for s in suites if s.get("name")=="demo"), None); assert demo is not None, data; assert int(demo.get("caseCount",0))>=1, demo; assert "fixtures/demo" in str(demo.get("path","")), demo; print("list ok:", demo)'
curl -sf "http://127.0.0.1:$PORT/v1/suites/demo" | tee data/suite-demo.json >/dev/null
python3 -c 'import json; from pathlib import Path; demo=json.loads(Path("data/suite-demo.json").read_text()); blob=json.dumps(demo); names=[c.get("name") for c in (demo.get("cases") or [])]; assert demo.get("ok") is True, demo; assert demo.get("id")=="demo", demo; assert demo.get("name")=="demo", demo; assert int(demo.get("caseCount",0))>=1, demo; assert "fixtures/demo" in str(demo.get("path","")), demo; assert "france-capital" in names, names; assert all(set((c or {}).keys()) <= {"name"} for c in (demo.get("cases") or [])), demo; assert "prompt" not in blob and "trajectory" not in blob, blob; print("get ok:", demo)'
set +e
MISS_SUITE="$(curl -s -o data/missing-suite.json -D data/missing-suite.h -w '%{http_code}' \
  "http://127.0.0.1:$PORT/v1/suites/no-such-suite-xyz" \
  -H "X-Request-Id: mvp-4xx-rid-404")"
set -e
echo "missing suite status=$MISS_SUITE"
test "$MISS_SUITE" = "404"
grep -q 'suite_not_found' data/missing-suite.json
grep -qiE "^x-request-id:[[:space:]]*mvp-4xx-rid-404" data/missing-suite.h

poll_run() {
  # $1 = run id, $2 = out file, $3 = optional base URL (default main serve)
  local rid="$1"
  local out="$2"
  local base="${3:-http://127.0.0.1:$PORT}"
  local body=""
  local i
  for i in $(seq 1 80); do
    body="$(curl -sf "$base/v1/runs/$rid")"
    echo "$body" >"$out"
    if echo "$body" | grep -Eq '"status"[[:space:]]*:[[:space:]]*"(done|failed|error)"'; then
      echo "$body"
      return 0
    fi
    sleep 0.1
  done
  echo "timed out waiting for run $rid" >&2
  echo "$body" >&2
  return 1
}

RID="mvp-req-id-a1b2c3d4"
CREATE="$(curl -sf -D data/create-run.h -X POST "http://127.0.0.1:$PORT/v1/runs" \
  -H 'content-type: application/json' \
  -H 'Authorization: Bearer demo' \
  -H "X-Request-Id: $RID" \
  -d '{"suite":"fixtures/demo"}')"
echo "$CREATE" | tee data/create-run.json
echo "$CREATE" | grep -Eq '"status"[[:space:]]*:[[:space:]]*"(queued|running)"'
grep -qiE "^x-request-id:[[:space:]]*${RID}" data/create-run.h
echo "$CREATE" | grep -q "$RID"
RUN_ID="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["runId"])' <<<"$CREATE")"
test -n "$RUN_ID"
test -f "$RUNS_DIR/$RUN_ID.json"
python3 -c 'import json,sys; from pathlib import Path; rec=json.loads(Path(sys.argv[1]).read_text()); assert rec.get("requestId")==sys.argv[2], rec' "$RUNS_DIR/$RUN_ID.json" "$RID"

GET="$(poll_run "$RUN_ID" data/get-run.json)"
echo "$GET" | grep -q "$RUN_ID"
echo "$GET" | grep -Eq '"status"[[:space:]]*:[[:space:]]*"done"'
echo "$GET" | grep -Eq '"passed"[[:space:]]*:[[:space:]]*true'
echo "$GET" | grep -q "$RID"
python3 -c 'import json,sys; from pathlib import Path; d=json.loads(Path("data/get-run.json").read_text()); assert d.get("requestId")==sys.argv[1], d; assert float(d.get("score"))==100.0, d; assert "gate" not in d, d' "$RID"
python3 -c 'import json,sys; from pathlib import Path; rec=json.loads(Path(sys.argv[1]).read_text()); assert rec.get("requestId")==sys.argv[2], rec; print("stored_requestId_ok")' "$RUNS_DIR/$RUN_ID.json" "$RID"

echo "==> GET /v1/runs/{id}/cases (inventory 200 + 404)"
CASES_CODE="$(curl -s -o data/get-run-cases.json -D data/get-run-cases.h -w '%{http_code}' \
  "http://127.0.0.1:$PORT/v1/runs/$RUN_ID/cases" -H "X-Request-Id: mvp-cases-rid")"
echo "cases_status=$CASES_CODE body=$(cat data/get-run-cases.json)"
test "$CASES_CODE" = "200"
grep -qiE "^x-request-id:[[:space:]]*mvp-cases-rid" data/get-run-cases.h
python3 - "$RUN_ID" <<'PYCASES'
import json, sys
from pathlib import Path
rid = sys.argv[1]
d = json.loads(Path("data/get-run-cases.json").read_text(encoding="utf-8"))
assert d.get("ok") is True, d
assert d.get("runId") == rid, d
assert d.get("status") == "done", d
assert int(d.get("count") or 0) >= 1, d
names = [c.get("name") for c in (d.get("cases") or [])]
assert "france-capital" in names, names
blob = json.dumps(d)
for needle in ("SECRET_PROMPT", "Authorization", "webhookUrl", "sk-"):
    assert needle not in blob, needle
print("cases_ok", d.get("count"), names)
PYCASES
CASES_FAIL="$(curl -sf "http://127.0.0.1:$PORT/v1/runs/$RUN_ID/cases?status=failed")"
echo "$CASES_FAIL" | tee data/get-run-cases-failed.json
python3 - <<'PYCASESFAIL'
import json
from pathlib import Path
d = json.loads(Path("data/get-run-cases-failed.json").read_text(encoding="utf-8"))
assert d.get("ok") is True, d
assert int(d.get("count") or 0) == 0, d
assert d.get("cases") == [], d
print("cases_status_failed_empty_ok")
PYCASESFAIL
set +e
MISS_CASES="$(curl -s -o data/missing-cases.json -w '%{http_code}' \
  "http://127.0.0.1:$PORT/v1/runs/deadbeefdead/cases")"
set -e
echo "missing cases status=$MISS_CASES"
test "$MISS_CASES" = "404"
python3 -c 'import json; from pathlib import Path; d=json.loads(Path("data/missing-cases.json").read_text()); assert d.get("error")=="run_not_found", d; assert d.get("ok") is False, d'
echo "cases_inventory_ok"

echo "==> GET /metrics (Prometheus text after completed run)"
curl -s -o data/metrics.txt -D data/metrics.h "http://127.0.0.1:$PORT/metrics" \
  -H "X-Request-Id: mvp-metrics-rid"
test -s data/metrics.txt
grep -qiE "^x-request-id:[[:space:]]*mvp-metrics-rid" data/metrics.h
grep -q 'agent_ci_queue_depth' data/metrics.txt
grep -q 'agent_ci_running' data/metrics.txt
grep -q 'agent_ci_runs_completed_total' data/metrics.txt
grep -q 'agent_ci_runs_failed_total' data/metrics.txt
python3 - <<'PYMETRICS'
from pathlib import Path
text = Path("data/metrics.txt").read_text(encoding="utf-8")
vals = {}
for line in text.splitlines():
    if not line or line.startswith("#"):
        continue
    parts = line.split()
    if len(parts) >= 2 and "{" not in parts[0]:
        vals[parts[0]] = float(parts[1])
assert "agent_ci_queue_depth" in vals, text
assert "agent_ci_running" in vals, text
assert "agent_ci_runs_completed_total" in vals, text
assert "agent_ci_runs_failed_total" in vals, text
assert vals["agent_ci_runs_completed_total"] >= 1, vals
print("metrics_names_ok", vals)
PYMETRICS
echo "metrics_names_ok"

echo "==> run-complete webhook (OSS fire-and-forget)"
WH_OK=0
for i in $(seq 1 40); do
  if test -f "$WH_OUT" && grep -q "$RUN_ID" "$WH_OUT" 2>/dev/null; then
    WH_OK=1
    break
  fi
  sleep 0.05
done
test "$WH_OK" = "1"
test -s "$WH_OUT"
grep -q "$RUN_ID" "$WH_OUT"
python3 -c 'import json,sys; from pathlib import Path; rid=sys.argv[1]; want=sys.argv[2]; d=json.loads(Path(sys.argv[3]).read_text()); assert d.get("runId")==rid, d; assert d.get("status") in ("done","error","failed"), d; assert d.get("requestId")==want, d; assert d.get("conclusion") in ("success","failure","error"), d; assert "summary" in d, d; assert float(d.get("score"))==100.0, d; assert "gate" not in d, d; print("webhook_ok", d.get("conclusion"), d.get("status"), d.get("score"))' "$RUN_ID" "$RID" "$WH_OUT"
echo "webhook_run_complete_ok"

echo "==> run-complete webhook timestamp header (OSS; replay window = paid)"
test -f "$WH_HDR"
python3 -c '
import json, sys, time
from pathlib import Path
meta = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))

raw = meta.get("timestamp")
if raw is None:
    headers = meta.get("headers") or {}
    raw = headers.get("X-Webhook-Timestamp") or headers.get("x-webhook-timestamp")
    if raw is None:
        for k, v in headers.items():
            if str(k).lower() == "x-webhook-timestamp":
                raw = v
                break
try:
    ts = int(str(raw or "").strip())
except (TypeError, ValueError):
    raise SystemExit("missing X-Webhook-Timestamp %r" % (meta,))
import time
now = int(time.time())
if abs(now - ts) > 120:
    raise SystemExit("timestamp not now ts=%s now=%s" % (ts, now))

print("webhook_timestamp_ok", ts)
' "$WH_HDR"
echo "webhook_timestamp_ok"

echo "==> GET /v1/runs lists recent runs including posted runId"
LIST="$(curl -sf "http://127.0.0.1:$PORT/v1/runs")"
echo "$LIST" | tee data/list-runs.json
echo "$LIST" | grep -q "$RUN_ID"
python3 -c 'import json,sys; from pathlib import Path; rid=sys.argv[1]; want=sys.argv[2]; data=json.loads(Path("data/list-runs.json").read_text()); runs=data.get("runs") or []; assert any(r.get("runId")==rid for r in runs), data; item=next(r for r in runs if r.get("runId")==rid); assert item.get("status") in ("done","error","failed","queued","running"), item; assert item.get("createdAt"), item; s=item.get("summary") or {}; assert "passed" in s and "failed" in s, item; assert item.get("requestId")==want, item; print("list ok:", item)' "$RUN_ID" "$RID"
# exact /v1/runs must not shadow GET /v1/runs/{id}
curl -sf "http://127.0.0.1:$PORT/v1/runs/$RUN_ID" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d.get("runId")==sys.argv[1], d; assert d.get("status")=="done", d' "$RUN_ID"
LIST1="$(curl -sf "http://127.0.0.1:$PORT/v1/runs?limit=1")"
echo "$LIST1" | tee data/list-runs-limit.json
python3 -c 'import json; from pathlib import Path; data=json.loads(Path("data/list-runs-limit.json").read_text()); runs=data.get("runs") or []; assert len(runs)<=1, data; print("limit=1 ok:", len(runs))'

echo "==> concurrent queue: two POSTs with concurrency=1"
curl -sf -X POST "http://127.0.0.1:$PORT/v1/runs" \
  -H 'content-type: application/json' \
  -H 'Authorization: Bearer demo' \
  -d '{"suite":"fixtures/demo","delayMs":400}' >data/create-run-a.json &
PID_A=$!
curl -sf -X POST "http://127.0.0.1:$PORT/v1/runs" \
  -H 'content-type: application/json' \
  -H 'Authorization: Bearer demo' \
  -d '{"suite":"fixtures/demo","delayMs":400}' >data/create-run-b.json &
PID_B=$!
wait "$PID_A"
wait "$PID_B"
cat data/create-run-a.json
cat data/create-run-b.json
RUN_A="$(python3 -c 'import json; print(json.load(open("data/create-run-a.json"))["runId"])')"
RUN_B="$(python3 -c 'import json; print(json.load(open("data/create-run-b.json"))["runId"])')"
test -n "$RUN_A"
test -n "$RUN_B"
test "$RUN_A" != "$RUN_B"
GET_A="$(poll_run "$RUN_A" data/get-run-a.json)"
GET_B="$(poll_run "$RUN_B" data/get-run-b.json)"
echo "$GET_A" | grep -Eq '"status"[[:space:]]*:[[:space:]]*"done"'
echo "$GET_B" | grep -Eq '"status"[[:space:]]*:[[:space:]]*"done"'
echo "$GET_A" | grep -Eq '"passed"[[:space:]]*:[[:space:]]*true'
echo "$GET_B" | grep -Eq '"passed"[[:space:]]*:[[:space:]]*true'

echo "==> GET /v1/runs/{id}/diff (identical 200 + CLI)"
DIFF_SAME="$(curl -sf -D data/get-run-diff-same.h "http://127.0.0.1:$PORT/v1/runs/$RUN_B/diff?against=$RUN_A")"
echo "$DIFF_SAME" | tee data/get-run-diff-same.json
grep -qiE '^x-request-id:' data/get-run-diff-same.h
python3 -c '
import json, sys
from pathlib import Path
a, b = sys.argv[1], sys.argv[2]
d = json.loads(Path("data/get-run-diff-same.json").read_text())
assert d.get("ok") is True, d
assert d.get("from") == a and d.get("to") == b, d
assert d.get("added") == [] and d.get("removed") == [] and d.get("regressed") == [] and d.get("fixed") == [], d
assert int(d.get("unchanged") or 0) >= 1, d
print("diff_identical_ok", d.get("unchanged"))
' "$RUN_A" "$RUN_B"
python3 -m agent_ci diff --from data/get-run-a.json --to data/get-run-b.json > data/cli-diff-same.json
python3 -c '
import json
from pathlib import Path
d = json.loads(Path("data/cli-diff-same.json").read_text())
assert d.get("ok") is True, d
assert d.get("regressed") == [] and d.get("added") == [] and d.get("removed") == [] and d.get("fixed") == [], d
print("cli_diff_identical_ok", d.get("unchanged"))
'

echo "==> GET /v1/runs/{id}/diff.md (identical 200 text/markdown)"
DIFF_SAME_MD_CODE="$(curl -s -o data/get-run-diff-same.md -D data/get-run-diff-same-md.h -w "%{http_code}" "http://127.0.0.1:$PORT/v1/runs/$RUN_B/diff.md?against=$RUN_A")"
echo "diff_same_md=$DIFF_SAME_MD_CODE"
test "$DIFF_SAME_MD_CODE" = "200"
grep -qiE '^content-type:[[:space:]]*text/markdown' data/get-run-diff-same-md.h
grep -qiE '^x-request-id:' data/get-run-diff-same-md.h
grep -q '# ' data/get-run-diff-same.md
grep -q 'no changes' data/get-run-diff-same.md
python3 -m agent_ci diff --from data/get-run-a.json --to data/get-run-b.json --format md > data/cli-diff-same.md
grep -q '# ' data/cli-diff-same.md
grep -q 'no changes' data/cli-diff-same.md
DIFF_FMT_MD_CODE="$(curl -s -o data/get-run-diff-same-fmt.md -D data/get-run-diff-same-fmt.h -w "%{http_code}" "http://127.0.0.1:$PORT/v1/runs/$RUN_B/diff?against=$RUN_A&format=md")"
echo "diff_same_fmt_md=$DIFF_FMT_MD_CODE"
test "$DIFF_FMT_MD_CODE" = "200"
grep -qiE '^content-type:[[:space:]]*text/markdown' data/get-run-diff-same-fmt.h
grep -q 'no changes' data/get-run-diff-same-fmt.md
echo "diff_identical_md_ok"

echo "==> GET /v1/runs/{id}/diff.html (identical 200 text/html)"
DIFF_SAME_HTML_CODE="$(curl -s -o data/get-run-diff-same.html -D data/get-run-diff-same-html.h -w "%{http_code}" "http://127.0.0.1:$PORT/v1/runs/$RUN_B/diff.html?against=$RUN_A")"
echo "diff_same_html=$DIFF_SAME_HTML_CODE"
test "$DIFF_SAME_HTML_CODE" = "200"
grep -qiE '^content-type:[[:space:]]*text/html' data/get-run-diff-same-html.h
grep -qiE '^x-request-id:' data/get-run-diff-same-html.h
grep -q 'no changes' data/get-run-diff-same.html
python3 -m agent_ci diff --from data/get-run-a.json --to data/get-run-b.json --format html > data/cli-diff-same.html
grep -q 'no changes' data/cli-diff-same.html
DIFF_FMT_HTML_CODE="$(curl -s -o data/get-run-diff-same-fmt.html -D data/get-run-diff-same-fmt-html.h -w "%{http_code}" "http://127.0.0.1:$PORT/v1/runs/$RUN_B/diff?against=$RUN_A&format=html")"
echo "diff_same_fmt_html=$DIFF_FMT_HTML_CODE"
test "$DIFF_FMT_HTML_CODE" = "200"
grep -qiE '^content-type:[[:space:]]*text/html' data/get-run-diff-same-fmt-html.h
grep -q 'no changes' data/get-run-diff-same-fmt.html
echo "diff_identical_html_ok"

echo "==> GET /v1/runs/{id}/diff missing → 404"
DIFF_404="$(curl -s -o data/missing-diff.json -w "%{http_code}" "http://127.0.0.1:$PORT/v1/runs/deadbeefdead/diff?against=$RUN_A")"
echo "diff_404=$DIFF_404"
test "$DIFF_404" = "404"
python3 -c 'import json; from pathlib import Path; d=json.loads(Path("data/missing-diff.json").read_text()); assert d.get("error")=="run_not_found", d'

echo "==> GET /v1/runs/{id}/diff incomplete → 409 run_not_done"
CREATE_HOLD_DIFF="$(curl -sf -X POST "http://127.0.0.1:$PORT/v1/runs" \
  -H "content-type: application/json" \
  -H "Authorization: Bearer demo" \
  -d "{\"suite\":\"fixtures/demo\",\"delayMs\":600}")"
echo "$CREATE_HOLD_DIFF" | tee data/create-run-hold-diff.json
HOLD_DIFF_ID="$(python3 -c "import json,sys; print(json.load(sys.stdin)[\"runId\"])" <<<"$CREATE_HOLD_DIFF")"
test -n "$HOLD_DIFF_ID"
DIFF_409="$(curl -s -o data/get-run-diff-hold.json -w "%{http_code}" \
  "http://127.0.0.1:$PORT/v1/runs/$HOLD_DIFF_ID/diff?against=$RUN_A")"
echo "diff_409=$DIFF_409"
test "$DIFF_409" = "409"
python3 -c 'import json; from pathlib import Path; d=json.loads(Path("data/get-run-diff-hold.json").read_text()); assert d.get("error")=="run_not_done", d'
poll_run "$HOLD_DIFF_ID" data/get-run-hold-diff-done.json >/dev/null

echo "==> GET /v1/runs/{id}/diff extra fail → regressed"
CREATE_FAIL="$(curl -sf -X POST "http://127.0.0.1:$PORT/v1/runs" \
  -H "content-type: application/json" \
  -H "Authorization: Bearer demo" \
  -d "{\"suiteName\":\"demo\",\"cases\":[{\"name\":\"france-capital\",\"prompt\":\"What is the capital of France?\",\"expect\":\"Paris\"},{\"name\":\"math-2plus2\",\"prompt\":\"Compute 2+2\",\"expect\":\"WRONG\"}]}")"
echo "$CREATE_FAIL" | tee data/create-run-diff-fail.json
FAIL_ID="$(python3 -c "import json,sys; print(json.load(sys.stdin)[\"runId\"])" <<<"$CREATE_FAIL")"
test -n "$FAIL_ID"
poll_run "$FAIL_ID" data/get-run-diff-fail.json >/dev/null
DIFF_REG="$(curl -sf "http://127.0.0.1:$PORT/v1/runs/$FAIL_ID/diff?against=$RUN_A")"
echo "$DIFF_REG" | tee data/get-run-diff.json
python3 -c '
import json, sys
from pathlib import Path
a, b = sys.argv[1], sys.argv[2]
d = json.loads(Path("data/get-run-diff.json").read_text())
assert d.get("ok") is True, d
assert d.get("from") == a and d.get("to") == b, d
assert "demo/math-2plus2" in (d.get("regressed") or []), d
print("diff_regressed_ok", d.get("regressed"))
' "$RUN_A" "$FAIL_ID"
echo "==> GET /v1/runs/{id}/diff.md extra fail → regressed markdown"
DIFF_REG_MD_CODE="$(curl -s -o data/get-run-diff.md -D data/get-run-diff-md.h -w "%{http_code}" "http://127.0.0.1:$PORT/v1/runs/$FAIL_ID/diff.md?against=$RUN_A")"
echo "diff_reg_md=$DIFF_REG_MD_CODE"
test "$DIFF_REG_MD_CODE" = "200"
grep -qiE '^content-type:[[:space:]]*text/markdown' data/get-run-diff-md.h
grep -qiE '^x-request-id:' data/get-run-diff-md.h
grep -q 'regressed' data/get-run-diff.md
grep -q 'demo/math-2plus2' data/get-run-diff.md
echo "==> GET /v1/runs/{id}/diff.md missing → 404 (JSON error)"
DIFF_MD_404="$(curl -s -o data/missing-diff-md.json -D data/missing-diff-md.h -w "%{http_code}" "http://127.0.0.1:$PORT/v1/runs/deadbeefdead/diff.md?against=$RUN_A")"
echo "diff_md_404=$DIFF_MD_404"
test "$DIFF_MD_404" = "404"
python3 -c 'import json; from pathlib import Path; d=json.loads(Path("data/missing-diff-md.json").read_text()); assert d.get("error")=="run_not_found", d'
echo "==> GET /v1/runs/{id}/diff.html extra fail → regressed html"
DIFF_REG_HTML_CODE="$(curl -s -o data/get-run-diff.html -D data/get-run-diff-html.h -w "%{http_code}" "http://127.0.0.1:$PORT/v1/runs/$FAIL_ID/diff.html?against=$RUN_A")"
echo "diff_reg_html=$DIFF_REG_HTML_CODE"
test "$DIFF_REG_HTML_CODE" = "200"
grep -qiE '^content-type:[[:space:]]*text/html' data/get-run-diff-html.h
grep -qiE '^x-request-id:' data/get-run-diff-html.h
grep -q '<table' data/get-run-diff.html
grep -q 'demo/math-2plus2' data/get-run-diff.html
echo "==> GET /v1/runs/{id}/diff.html missing → 404 (JSON error)"
DIFF_HTML_404="$(curl -s -o data/missing-diff-html.json -D data/missing-diff-html.h -w "%{http_code}" "http://127.0.0.1:$PORT/v1/runs/deadbeefdead/diff.html?against=$RUN_A")"
echo "diff_html_404=$DIFF_HTML_404"
test "$DIFF_HTML_404" = "404"
python3 -c 'import json; from pathlib import Path; d=json.loads(Path("data/missing-diff-html.json").read_text()); assert d.get("error")=="run_not_found", d'
echo "run_diff_http_ok"

echo "==> queue full → 429 Retry-After (max-queue=1)"
# Hold one running + one queued, then third must 429.
curl -sf -X POST "http://127.0.0.1:$PORT/v1/runs" \
  -H 'content-type: application/json' \
  -H 'Authorization: Bearer demo' \
  -d '{"suite":"fixtures/demo","delayMs":2500}' >data/create-run-hold.json &
PID_HOLD=$!
# tiny pause so first occupies the worker before second enqueue
sleep 0.05
curl -sf -X POST "http://127.0.0.1:$PORT/v1/runs" \
  -H 'content-type: application/json' \
  -H 'Authorization: Bearer demo' \
  -d '{"suite":"fixtures/demo","delayMs":200}' >data/create-run-q.json &
PID_Q=$!
sleep 0.05
set +e
Q429_HEADERS="$(mktemp)"
Q429_BODY="data/queue-full.json"
Q429_CODE="$(curl -s -D "$Q429_HEADERS" -o "$Q429_BODY" -w '%{http_code}' -X POST "http://127.0.0.1:$PORT/v1/runs" \
  -H 'content-type: application/json' \
  -H 'Authorization: Bearer demo' \
  -d '{"suite":"fixtures/demo"}')"
set -e
echo "queue-full status=$Q429_CODE body=$(cat "$Q429_BODY")"
test "$Q429_CODE" = "429"
grep -qi '^Retry-After:' "$Q429_HEADERS"
grep -Eq '"error"[[:space:]]*:[[:space:]]*"queue_full"' "$Q429_BODY"

echo "==> queue full: GET /health stays 200; GET /ready 503 queue_full (does not consume a slot)"
H_FULL="$(curl -s -o data/health-full.json -w '%{http_code}' "http://127.0.0.1:$PORT/health")"
echo "health_full_status=$H_FULL body=$(cat data/health-full.json)"
test "$H_FULL" = "200"
python3 - <<'PYHEALTHFULL'
import json
from pathlib import Path
h = json.loads(Path("data/health-full.json").read_text(encoding="utf-8"))
assert h.get("ok") is True, h
print("health_full_ok")
PYHEALTHFULL
R_FULL="$(curl -s -o data/ready-full.json -D data/ready-full.h -w '%{http_code}' "http://127.0.0.1:$PORT/ready")"
echo "ready_full_status=$R_FULL body=$(cat data/ready-full.json)"
test "$R_FULL" = "503"
grep -qiE '^retry-after:' data/ready-full.h
python3 - <<'PYREADYFULL'
import json
from pathlib import Path
r = json.loads(Path("data/ready-full.json").read_text(encoding="utf-8"))
assert r.get("ok") is False, r
assert r.get("reason") == "queue_full", r
q = r.get("queue") or {}
assert int(q.get("queued") or 0) >= 1, q
assert int(q.get("running") or 0) >= 1, q
print("ready_full_503_ok", q)
PYREADYFULL
# GET /ready must not consume a queue slot — another POST still 429
set +e
R_SLOT="$(curl -s -o data/ready-slot.json -w '%{http_code}' -X POST "http://127.0.0.1:$PORT/v1/runs" \
  -H 'content-type: application/json' \
  -H 'Authorization: Bearer demo' \
  -d '{"suite":"fixtures/demo"}')"
set -e
echo "ready_no_slot_post_status=$R_SLOT body=$(cat data/ready-slot.json)"
test "$R_SLOT" = "429"

wait "$PID_HOLD" || true
wait "$PID_Q" || true
rm -f "$Q429_HEADERS"
HOLD_ID="$(python3 -c 'import json; print(json.load(open("data/create-run-hold.json"))["runId"])')"
Q_ID="$(python3 -c 'import json; print(json.load(open("data/create-run-q.json"))["runId"])')"
poll_run "$HOLD_ID" data/get-run-hold.json >/dev/null
poll_run "$Q_ID" data/get-run-q.json >/dev/null

echo "==> after drain GET /ready → 200"
R_DRAIN="$(curl -s -o data/ready-drain.json -w '%{http_code}' "http://127.0.0.1:$PORT/ready")"
echo "ready_drain_status=$R_DRAIN body=$(cat data/ready-drain.json)"
test "$R_DRAIN" = "200"
python3 - <<'PYREADYDRAIN'
import json
from pathlib import Path
r = json.loads(Path("data/ready-drain.json").read_text(encoding="utf-8"))
assert r.get("ok") is True, r
assert not r.get("reason"), r
q = r.get("queue") or {}
assert int(q.get("queued") or 0) == 0, q
assert int(q.get("running") or 0) == 0, q
print("ready_drain_ok", q)
PYREADYDRAIN

echo "==> junit artifact endpoint"
test -f "$RUNS_DIR/$RUN_ID.junit.xml"
JUNIT="$(curl -sf "http://127.0.0.1:$PORT/v1/runs/$RUN_ID/junit")"
echo "$JUNIT" | tee data/get-run.junit.xml
echo "$JUNIT" | grep -q '<testsuite'
echo "$JUNIT" | grep -q '<testcase'
grep -q '<testsuite' "$RUNS_DIR/$RUN_ID.junit.xml"
grep -q '<testcase' "$RUNS_DIR/$RUN_ID.junit.xml"

echo "==> GET /v1/runs/{id}/junit.xml (200 + testsuite)"
JUNIT_XML_CODE="$(curl -s -o data/get-run.junit.xml.body -D data/get-run.junit.xml.h -w '%{http_code}' \
  "http://127.0.0.1:$PORT/v1/runs/$RUN_ID/junit.xml")"
echo "junit_xml_status=$JUNIT_XML_CODE"
test "$JUNIT_XML_CODE" = "200"
grep -q '<testsuite' data/get-run.junit.xml.body
grep -q '<testcase' data/get-run.junit.xml.body
grep -qiE '^content-type:[[:space:]]*(application|text)/xml' data/get-run.junit.xml.h

echo "==> GET /v1/runs/junit.xml (all completed runs)"
AGG_CODE="$(curl -s -o data/runs.junit.xml -D data/runs.junit.xml.h -w '%{http_code}' \
  "http://127.0.0.1:$PORT/v1/runs/junit.xml")"
echo "runs_junit_xml_status=$AGG_CODE"
test "$AGG_CODE" = "200"
grep -q '<testsuite' data/runs.junit.xml
grep -qiE '^content-type:[[:space:]]*(application|text)/xml' data/runs.junit.xml.h

echo "==> GET /v1/runs/{id}/tap.txt (200 + TAP version 13)"
TAP_XML_CODE="$(curl -s -o data/get-run.tap.txt -D data/get-run.tap.txt.h -w '%{http_code}' \
  "http://127.0.0.1:$PORT/v1/runs/$RUN_ID/tap.txt")"
echo "tap_txt_status=$TAP_XML_CODE"
test "$TAP_XML_CODE" = "200"
grep -q 'TAP version 13' data/get-run.tap.txt
grep -q 'ok ' data/get-run.tap.txt
grep -qiE '^content-type:[[:space:]]*text/plain' data/get-run.tap.txt.h
TAP_ALIAS="$(curl -sf "http://127.0.0.1:$PORT/v1/runs/$RUN_ID/tap")"
echo "$TAP_ALIAS" | grep -q 'TAP version 13'

echo "==> GET /v1/runs/tap.txt (all completed runs)"
AGG_TAP="$(curl -s -o data/runs.tap.txt -D data/runs.tap.txt.h -w '%{http_code}' \
  "http://127.0.0.1:$PORT/v1/runs/tap.txt")"
echo "runs_tap_txt_status=$AGG_TAP"
test "$AGG_TAP" = "200"
grep -q 'TAP version 13' data/runs.tap.txt
grep -qiE '^content-type:[[:space:]]*text/plain' data/runs.tap.txt.h

echo "==> GET /v1/runs/{id}/report.md (200 + heading)"
MD_CODE="$(curl -s -o data/get-run.report.md -D data/get-run.report.md.h -w '%{http_code}' \
  "http://127.0.0.1:$PORT/v1/runs/$RUN_ID/report.md")"
echo "report_md_status=$MD_CODE"
test "$MD_CODE" = "200"
grep -q '# ' data/get-run.report.md
grep -q '| case | status | time |' data/get-run.report.md
grep -qiE '^content-type:[[:space:]]*text/markdown' data/get-run.report.md.h
MD_ALIAS="$(curl -sf "http://127.0.0.1:$PORT/v1/runs/$RUN_ID/md")"
echo "$MD_ALIAS" | grep -q '# '

echo "==> GET /v1/runs/report.md (all completed runs)"
AGG_MD="$(curl -s -o data/runs.report.md -D data/runs.report.md.h -w '%{http_code}' \
  "http://127.0.0.1:$PORT/v1/runs/report.md")"
echo "runs_report_md_status=$AGG_MD"
test "$AGG_MD" = "200"
grep -q '# ' data/runs.report.md
grep -qiE '^content-type:[[:space:]]*text/markdown' data/runs.report.md.h

echo "==> GET /v1/runs/{id}/report.html (200 + table)"
HTML_CODE="$(curl -s -o data/get-run.report.html -D data/get-run.report.html.h -w '%{http_code}' \
  "http://127.0.0.1:$PORT/v1/runs/$RUN_ID/report.html")"
echo "report_html_status=$HTML_CODE"
test "$HTML_CODE" = "200"
grep -q '<table' data/get-run.report.html
grep -q 'agent-ci' data/get-run.report.html
grep -qiE '^content-type:[[:space:]]*text/html' data/get-run.report.html.h
HTML_ALIAS="$(curl -sf "http://127.0.0.1:$PORT/v1/runs/$RUN_ID/html")"
echo "$HTML_ALIAS" | grep -q '<table'

echo "==> GET /v1/runs/report.html (all completed runs)"
AGG_HTML="$(curl -s -o data/runs.report.html -D data/runs.report.html.h -w '%{http_code}' \
  "http://127.0.0.1:$PORT/v1/runs/report.html")"
echo "runs_report_html_status=$AGG_HTML"
test "$AGG_HTML" = "200"
grep -q '<table' data/runs.report.html
grep -qiE '^content-type:[[:space:]]*text/html' data/runs.report.html.h

echo "==> GET /v1/runs/{id}/annotations.txt (pass run: 200, no ::error)"
ANN_CODE="$(curl -s -o data/get-run.annotations.txt -D data/get-run.annotations.txt.h -w '%{http_code}' \
  "http://127.0.0.1:$PORT/v1/runs/$RUN_ID/annotations.txt")"
echo "annotations_txt_status=$ANN_CODE"
test "$ANN_CODE" = "200"
if grep -q '::error' data/get-run.annotations.txt; then
  echo "pass-run annotations.txt unexpectedly contains ::error"
  cat data/get-run.annotations.txt
  exit 1
fi
grep -qiE '^content-type:[[:space:]]*text/plain' data/get-run.annotations.txt.h
ANN_ALIAS="$(curl -sf "http://127.0.0.1:$PORT/v1/runs/$RUN_ID/annotations")"
if echo "$ANN_ALIAS" | grep -q '::error'; then
  echo "pass-run /annotations alias unexpectedly contains ::error"
  echo "$ANN_ALIAS"
  exit 1
fi

echo "==> GET /v1/runs/annotations.txt (all completed runs)"
AGG_ANN="$(curl -s -o data/runs.annotations.txt -D data/runs.annotations.txt.h -w '%{http_code}' \
  "http://127.0.0.1:$PORT/v1/runs/annotations.txt")"
echo "runs_annotations_txt_status=$AGG_ANN"
test "$AGG_ANN" = "200"
grep -qiE '^content-type:[[:space:]]*text/plain' data/runs.annotations.txt.h

echo "==> quality gate POST failUnder 101 on demo (score 100 → status failed)"
GATE_CREATE="$(curl -sf -X POST "http://127.0.0.1:$PORT/v1/runs" \
  -H 'content-type: application/json' \
  -H 'Authorization: Bearer demo' \
  -H 'X-Request-Id: mvp-gate-rid' \
  -d '{"suite":"fixtures/demo","failUnder":101}')"
echo "$GATE_CREATE" | tee data/create-run-gate.json
GATE_ID="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["runId"])' <<<"$GATE_CREATE")"
test -n "$GATE_ID"
GATE_GET="$(poll_run "$GATE_ID" data/get-run-gate.json)"
python3 - <<'PYGATE'
import json
from pathlib import Path
d = json.loads(Path("data/get-run-gate.json").read_text(encoding="utf-8"))
assert d.get("status") == "failed", d
assert d.get("error") == "below_threshold", d
assert d.get("passed") is False, d
assert float(d.get("score")) == 100.0, d
gate = d.get("gate") or {}
assert float(gate.get("failUnder")) == 101, gate
assert gate.get("passed") is False, gate
print("gate_http_failed_ok", d.get("score"), gate)
PYGATE
GATE_JUNIT="$(curl -sf "http://127.0.0.1:$PORT/v1/runs/$GATE_ID/junit.xml")"
echo "$GATE_JUNIT" | tee data/get-run-gate.junit.xml >/dev/null
echo "$GATE_JUNIT" | grep -q '<testsuite'
echo "$GATE_JUNIT" | grep -q 'failures="1"'
echo "$GATE_JUNIT" | grep -q 'below_threshold'
GATE_TAP="$(curl -sf "http://127.0.0.1:$PORT/v1/runs/$GATE_ID/tap.txt")"
echo "$GATE_TAP" | tee data/get-run-gate.tap.txt >/dev/null
echo "$GATE_TAP" | grep -q 'TAP version 13'
echo "$GATE_TAP" | grep -q 'not ok'
echo "$GATE_TAP" | grep -q 'below_threshold'
GATE_MD="$(curl -sf "http://127.0.0.1:$PORT/v1/runs/$GATE_ID/report.md")"
echo "$GATE_MD" | tee data/get-run-gate.report.md >/dev/null
echo "$GATE_MD" | grep -q '# '
echo "$GATE_MD" | grep -q 'fail'
echo "$GATE_MD" | grep -q 'below_threshold'
GATE_HTML="$(curl -sf "http://127.0.0.1:$PORT/v1/runs/$GATE_ID/report.html")"
echo "$GATE_HTML" | tee data/get-run-gate.report.html >/dev/null
echo "$GATE_HTML" | grep -q '<table'
echo "$GATE_HTML" | grep -q 'fail'
echo "$GATE_HTML" | grep -q 'below_threshold'
GATE_ANN="$(curl -sf "http://127.0.0.1:$PORT/v1/runs/$GATE_ID/annotations.txt")"
echo "$GATE_ANN" | tee data/get-run-gate.annotations.txt >/dev/null
echo "$GATE_ANN" | grep -q '::error'
echo "$GATE_ANN" | grep -q 'title=gate'
echo "$GATE_ANN" | grep -q 'failUnder'
echo "==> quality gate webhook includes score + gate"
WH_GATE_OK=0
for i in $(seq 1 40); do
  if test -f "$WH_OUT" && grep -q "$GATE_ID" "$WH_OUT" 2>/dev/null; then
    WH_GATE_OK=1
    break
  fi
  sleep 0.05
done
test "$WH_GATE_OK" = "1"
python3 -c 'import json,sys; from pathlib import Path; rid=sys.argv[1]; d=json.loads(Path(sys.argv[2]).read_text()); assert d.get("runId")==rid, d; assert d.get("status")=="failed", d; assert d.get("conclusion")=="failure", d; assert float(d.get("score"))==100.0, d; g=d.get("gate") or {}; assert float(g.get("failUnder"))==101, g; assert g.get("passed") is False, g; print("webhook_gate_ok", d.get("status"), d.get("score"), g)' "$GATE_ID" "$WH_OUT"

echo "==> POST without failUnder still succeeds as today"
NOGATE_CREATE="$(curl -sf -X POST "http://127.0.0.1:$PORT/v1/runs" \
  -H 'content-type: application/json' \
  -H 'Authorization: Bearer demo' \
  -d '{"suite":"fixtures/demo"}')"
NOGATE_ID="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["runId"])' <<<"$NOGATE_CREATE")"
NOGATE_GET="$(poll_run "$NOGATE_ID" data/get-run-nogate.json)"
python3 - <<'PYNOGATE'
import json
from pathlib import Path
d = json.loads(Path("data/get-run-nogate.json").read_text(encoding="utf-8"))
assert d.get("status") == "done", d
assert d.get("passed") is True, d
assert float(d.get("score")) == 100.0, d
assert "gate" not in d, d
print("no_failUnder_still_done", d.get("score"))
PYNOGATE

echo "==> missing junit must 404"
set +e
MISS_CODE="$(curl -s -o data/missing-junit.json -w '%{http_code}' "http://127.0.0.1:$PORT/v1/runs/deadbeefdead/junit")"
set -e
echo "missing junit status=$MISS_CODE"
test "$MISS_CODE" = "404"

echo "==> missing tap must 404"
set +e
MISS_TAP="$(curl -s -o data/missing-tap.json -w '%{http_code}' "http://127.0.0.1:$PORT/v1/runs/deadbeefdead/tap.txt")"
set -e
echo "missing tap status=$MISS_TAP"
test "$MISS_TAP" = "404"

echo "==> missing markdown report must 404"
set +e
MISS_MD="$(curl -s -o data/missing-md.json -w '%{http_code}' "http://127.0.0.1:$PORT/v1/runs/deadbeefdead/report.md")"
set -e
echo "missing md status=$MISS_MD"
test "$MISS_MD" = "404"

echo "==> missing html report must 404"
set +e
MISS_HTML="$(curl -s -o data/missing-html.json -w '%{http_code}' "http://127.0.0.1:$PORT/v1/runs/deadbeefdead/report.html")"
set -e
echo "missing html status=$MISS_HTML"
test "$MISS_HTML" = "404"

echo "==> missing annotations must 404"
set +e
MISS_ANN="$(curl -s -o data/missing-ann.json -w '%{http_code}' "http://127.0.0.1:$PORT/v1/runs/deadbeefdead/annotations.txt")"
set -e
echo "missing annotations status=$MISS_ANN"
test "$MISS_ANN" = "404"

echo "==> bad API key must 401"
set +e
BAD_CODE="$(curl -s -o data/bad-key.json -w '%{http_code}' -X POST "http://127.0.0.1:$PORT/v1/runs" \
  -H 'content-type: application/json' \
  -H 'Authorization: Bearer wrong-key' \
  -d '{"suite":"fixtures/demo"}')"
set -e
echo "bad key status=$BAD_CODE body=$(cat data/bad-key.json)"
test "$BAD_CODE" = "401"


echo "==> GitHub Check Run adapter (local payload + mock post)"
rm -f out/check-run.json data/check-run-posted.json
python3 -m agent_ci report-check --suite fixtures/demo --out out/check-run.json \
  --post-url "http://127.0.0.1:$PORT/v1/check-runs"
test -f out/check-run.json
grep -q '"conclusion"' out/check-run.json
grep -q '"success"' out/check-run.json
grep -q '"summary"' out/check-run.json
grep -q 'agent-ci' out/check-run.json
test -f data/check-run-posted.json
grep -q '"conclusion"' data/check-run-posted.json
grep -q '"success"' data/check-run-posted.json
# failure conclusion path (drift suite)
rm -f out/check-run-drift.json
set +e
python3 -m agent_ci report-check --suite fixtures/drift --out out/check-run-drift.json
drift_code=$?
set -e
test "$drift_code" -ne 0
test -f out/check-run-drift.json
grep -q '"failure"' out/check-run-drift.json

echo "==> [cors] isolated serve --cors-origins http://localhost:3000"
CORS_PORT="${CORS_PORT:-$((PORT + 17))}"
CORS_RUNS="$ROOT/data/cors-runs"
CORS_LOG="$ROOT/data/cors-serve.log"
rm -rf "$CORS_RUNS"
mkdir -p "$CORS_RUNS" data
python3 -m agent_ci serve --port "$CORS_PORT" --runs-dir "$CORS_RUNS" \
  --concurrency 1 --max-queue 1 \
  --cors-origins "http://localhost:3000" >"$CORS_LOG" 2>&1 &
CORS_PID=$!
for i in $(seq 1 40); do
  if curl -sf "http://127.0.0.1:$CORS_PORT/health" >/dev/null; then
    break
  fi
  sleep 0.1
  if [ "$i" -eq 40 ]; then
    echo "cors serve did not become healthy"
    cat "$CORS_LOG" || true
    exit 1
  fi
done

CORS_OK="$(curl -s -o /tmp/c-cors-ok -D /tmp/c-cors-ok.h -w "%{http_code}" \
  -X OPTIONS "http://127.0.0.1:$CORS_PORT/health" \
  -H "Origin: http://localhost:3000" \
  -H "Access-Control-Request-Method: GET" \
  -H "X-Request-Id: mvp-cors-opt-204")"
echo "cors_preflight_ok_status=$CORS_OK"
test "$CORS_OK" = "204"
grep -qiE "^access-control-allow-origin:[[:space:]]*http://localhost:3000" /tmp/c-cors-ok.h
grep -qiE "^access-control-allow-methods:" /tmp/c-cors-ok.h
grep -qiE "^access-control-allow-headers:" /tmp/c-cors-ok.h
grep -qiE "^access-control-allow-headers:.*x-request-id" /tmp/c-cors-ok.h
grep -qiE "^access-control-expose-headers:.*retry-after" /tmp/c-cors-ok.h
grep -qiE "^access-control-expose-headers:.*x-request-id" /tmp/c-cors-ok.h
grep -qiE "^x-request-id:[[:space:]]*mvp-cors-opt-204" /tmp/c-cors-ok.h

CORS_POST_PF="$(curl -s -o /tmp/c-cors-post -D /tmp/c-cors-post.h -w "%{http_code}" \
  -X OPTIONS "http://127.0.0.1:$CORS_PORT/v1/runs" \
  -H "Origin: http://localhost:3000" \
  -H "Access-Control-Request-Method: POST" \
  -H "Access-Control-Request-Headers: authorization,content-type,x-request-id")"
echo "cors_preflight_post_status=$CORS_POST_PF"
test "$CORS_POST_PF" = "204"
grep -qiE "^access-control-allow-origin:[[:space:]]*http://localhost:3000" /tmp/c-cors-post.h
grep -qiE "^access-control-expose-headers:.*retry-after" /tmp/c-cors-post.h
grep -qiE "^access-control-expose-headers:.*x-request-id" /tmp/c-cors-post.h

CORS_EVIL="$(curl -s -o /tmp/c-cors-evil.json -D /tmp/c-cors-evil.h -w "%{http_code}" \
  -X OPTIONS "http://127.0.0.1:$CORS_PORT/health" \
  -H "Origin: http://evil.example" \
  -H "Access-Control-Request-Method: GET" \
  -H "X-Request-Id: mvp-cors-opt-403")"
echo "cors_preflight_evil_status=$CORS_EVIL body=$(cat /tmp/c-cors-evil.json)"
test "$CORS_EVIL" = "403"
grep -q "cors_denied" /tmp/c-cors-evil.json
if grep -qiE "^access-control-allow-origin:[[:space:]]*http://evil.example" /tmp/c-cors-evil.h; then
  echo "evil origin must not receive ACAO"
  exit 1
fi
if grep -qiE "^access-control-expose-headers:" /tmp/c-cors-evil.h; then
  echo "evil origin must not receive ACEH"
  exit 1
fi
grep -qiE "^x-request-id:[[:space:]]*mvp-cors-opt-403" /tmp/c-cors-evil.h

HEALTH_CORS="$(curl -s -o /tmp/c-health-cors.json -D /tmp/c-health-cors.h -w "%{http_code}" \
  "http://127.0.0.1:$CORS_PORT/health" -H "Origin: http://localhost:3000")"
echo "cors_get_health_status=$HEALTH_CORS"
test "$HEALTH_CORS" = "200"
grep -qiE "^access-control-allow-origin:[[:space:]]*http://localhost:3000" /tmp/c-health-cors.h
grep -qiE "^access-control-expose-headers:.*retry-after" /tmp/c-health-cors.h
grep -qiE "^access-control-expose-headers:.*x-request-id" /tmp/c-health-cors.h
grep -qiE "^x-request-id:" /tmp/c-health-cors.h

OPENAPI_CORS="$(curl -s -o /tmp/c-openapi-cors.json -D /tmp/c-openapi-cors.h -w "%{http_code}" \
  "http://127.0.0.1:$CORS_PORT/openapi.json" -H "Origin: http://localhost:3000")"
echo "cors_get_openapi_status=$OPENAPI_CORS"
test "$OPENAPI_CORS" = "200"
grep -q '"openapi"' /tmp/c-openapi-cors.json
grep -qiE "^access-control-allow-origin:[[:space:]]*http://localhost:3000" /tmp/c-openapi-cors.h
grep -qiE "^x-request-id:" /tmp/c-openapi-cors.h

CORS_METRICS_PF="$(curl -s -o /tmp/c-cors-metrics-pf -D /tmp/c-cors-metrics-pf.h -w "%{http_code}" \
  -X OPTIONS "http://127.0.0.1:$CORS_PORT/metrics" \
  -H "Origin: http://localhost:3000" \
  -H "Access-Control-Request-Method: GET")"
echo "cors_preflight_metrics_status=$CORS_METRICS_PF"
test "$CORS_METRICS_PF" = "204"
grep -qiE "^access-control-allow-origin:[[:space:]]*http://localhost:3000" /tmp/c-cors-metrics-pf.h

METRICS_CORS="$(curl -s -o /tmp/c-metrics-cors.txt -D /tmp/c-metrics-cors.h -w "%{http_code}" \
  "http://127.0.0.1:$CORS_PORT/metrics" -H "Origin: http://localhost:3000" \
  -H "X-Request-Id: mvp-cors-metrics-rid")"
echo "cors_get_metrics_status=$METRICS_CORS"
test "$METRICS_CORS" = "200"
grep -q 'agent_ci_queue_depth' /tmp/c-metrics-cors.txt
grep -q 'agent_ci_running' /tmp/c-metrics-cors.txt
grep -q 'agent_ci_runs_completed_total' /tmp/c-metrics-cors.txt
grep -q 'agent_ci_runs_failed_total' /tmp/c-metrics-cors.txt
grep -qiE "^access-control-allow-origin:[[:space:]]*http://localhost:3000" /tmp/c-metrics-cors.h
grep -qiE "^access-control-expose-headers:.*retry-after" /tmp/c-metrics-cors.h
grep -qiE "^access-control-expose-headers:.*x-request-id" /tmp/c-metrics-cors.h
grep -qiE "^x-request-id:[[:space:]]*mvp-cors-metrics-rid" /tmp/c-metrics-cors.h

SUITES_CORS="$(curl -s -o /tmp/c-suites-cors.json -D /tmp/c-suites-cors.h -w "%{http_code}" \
  "http://127.0.0.1:$CORS_PORT/v1/suites" -H "Origin: http://localhost:3000")"
echo "cors_get_suites_status=$SUITES_CORS"
test "$SUITES_CORS" = "200"
grep -qiE "^access-control-allow-origin:[[:space:]]*http://localhost:3000" /tmp/c-suites-cors.h

POST_CORS="$(curl -s -o /tmp/c-post-cors.json -D /tmp/c-post-cors.h -w "%{http_code}" \
  -X POST "http://127.0.0.1:$CORS_PORT/v1/runs" \
  -H "content-type: application/json" \
  -H "Authorization: Bearer demo" \
  -H "Origin: http://localhost:3000" \
  -H "X-Request-Id: mvp-cors-post-rid" \
  -d "{\"suite\":\"fixtures/demo\"}")"
echo "cors_post_runs_status=$POST_CORS"
test "$POST_CORS" = "202"
grep -qiE "^access-control-allow-origin:[[:space:]]*http://localhost:3000" /tmp/c-post-cors.h
grep -qiE "^access-control-expose-headers:.*retry-after" /tmp/c-post-cors.h
grep -qiE "^access-control-expose-headers:.*x-request-id" /tmp/c-post-cors.h
grep -qiE "^x-request-id:[[:space:]]*mvp-cors-post-rid" /tmp/c-post-cors.h

HEALTH_EVIL="$(curl -s -o /tmp/c-health-evil.json -D /tmp/c-health-evil.h -w "%{http_code}" \
  "http://127.0.0.1:$CORS_PORT/health" -H "Origin: http://evil.example")"
echo "cors_get_evil_status=$HEALTH_EVIL"
test "$HEALTH_EVIL" = "200"
if grep -qiE "^access-control-allow-origin:" /tmp/c-health-evil.h; then
  echo "disallowed origin should not get ACAO"
  cat /tmp/c-health-evil.h
  exit 1
fi
if grep -qiE "^access-control-expose-headers:" /tmp/c-health-evil.h; then
  echo "disallowed origin should not get ACEH"
  cat /tmp/c-health-evil.h
  exit 1
fi

if [ -n "${CORS_PID:-}" ]; then
  kill "$CORS_PID" 2>/dev/null || true
  wait "$CORS_PID" 2>/dev/null || true
  CORS_PID=""
fi
echo "==> [cors] allow localhost:3000 / deny evil.example OK (isolated)"

echo "==> [rate-limit] isolated serve --rate-limit 2 (third /v1/suites is 429; /health still 200)"
RL_PORT="${RL_PORT:-$((PORT + 26))}"
RL_RUNS="$ROOT/data/rl-runs"
RL_LOG="$ROOT/data/rl-serve.log"
rm -rf "$RL_RUNS"
mkdir -p "$RL_RUNS" data
rm -f "$RL_LOG" data/c-rl-1.json data/c-rl-2.json data/c-rl-3.json data/c-rl-3.h data/c-rl-health.json data/c-rl-ready.json data/c-rl-metrics.txt
unset AGENT_CI_CORS_ORIGINS || true
unset RATE_LIMIT_PER_MINUTE RATE_LIMIT_RPM || true
unset RUNS_MAX || true
python3 -m agent_ci serve --port "$RL_PORT" --runs-dir "$RL_RUNS" \
  --concurrency 1 --max-queue 4 --rate-limit 2 >"$RL_LOG" 2>&1 &
RL_PID=$!
for i in $(seq 1 50); do
  if curl -sf "http://127.0.0.1:$RL_PORT/health" >/dev/null; then
    break
  fi
  sleep 0.1
  if [ "$i" -eq 50 ]; then
    echo "rate-limit serve did not become healthy"
    cat "$RL_LOG" || true
    exit 1
  fi
done
RL1="$(curl -s -o data/c-rl-1.json -w "%{http_code}" "http://127.0.0.1:$RL_PORT/v1/suites")"
RL2="$(curl -s -o data/c-rl-2.json -w "%{http_code}" "http://127.0.0.1:$RL_PORT/v1/suites")"
RL3="$(curl -s -o data/c-rl-3.json -D data/c-rl-3.h -w "%{http_code}" "http://127.0.0.1:$RL_PORT/v1/suites" -H "X-Request-Id: mvp-rl-rid-429")"
echo "rl_hit_1=$RL1 rl_hit_2=$RL2 rl_hit_3=$RL3 body=$(cat data/c-rl-3.json)"
test "$RL1" = "200"
test "$RL2" = "200"
test "$RL3" = "429"
grep -qi '^Retry-After:' data/c-rl-3.h
grep -qiE '^x-request-id:[[:space:]]*mvp-rl-rid-429' data/c-rl-3.h
grep -Eq '"ok"[[:space:]]*:[[:space:]]*false' data/c-rl-3.json
grep -Eq '"reason"[[:space:]]*:[[:space:]]*"rate_limited"' data/c-rl-3.json
RL_HEALTH="$(curl -s -o data/c-rl-health.json -w "%{http_code}" "http://127.0.0.1:$RL_PORT/health")"
RL_READY="$(curl -s -o data/c-rl-ready.json -w "%{http_code}" "http://127.0.0.1:$RL_PORT/ready")"
RL_METRICS="$(curl -s -o data/c-rl-metrics.txt -w "%{http_code}" "http://127.0.0.1:$RL_PORT/metrics")"
echo "rl_health=$RL_HEALTH rl_ready=$RL_READY rl_metrics=$RL_METRICS"
test "$RL_HEALTH" = "200"
test "$RL_READY" = "200"
test "$RL_METRICS" = "200"
grep -Eq '"ok"[[:space:]]*:[[:space:]]*true' data/c-rl-health.json
if [ -n "${RL_PID:-}" ]; then
  kill "$RL_PID" 2>/dev/null || true
  wait "$RL_PID" 2>/dev/null || true
  RL_PID=""
fi
echo "==> [rate-limit] 429 + Retry-After OK (isolated); probes excluded; main serve unchanged"

echo "==> [hmac] isolated serve --webhook-secret (unsigned prove above stays intact)"
HMAC_PORT="${HMAC_PORT:-$((PORT + 21))}"
HMAC_WH_PORT="${HMAC_WH_PORT:-$((PORT + 22))}"
HMAC_SECRET="whsec_local_mvp"
HMAC_RUNS="$ROOT/data/hmac-runs"
HMAC_OUT="$ROOT/data/webhook-hmac-last.json"
HMAC_HDR="$ROOT/data/webhook-hmac-last.headers.json"
HMAC_LOG="$ROOT/data/hmac-serve.log"
HMAC_WH_LOG="$ROOT/data/mock-webhook.hmac.log"
rm -rf "$HMAC_RUNS"
rm -f "$HMAC_OUT" "$HMAC_HDR"
mkdir -p "$HMAC_RUNS" data
python3 "$ROOT/mock-webhook-receiver.py" --port "$HMAC_WH_PORT" --out "$HMAC_OUT" \
  --headers-out "$HMAC_HDR" --secret "$HMAC_SECRET" >"$HMAC_WH_LOG" 2>&1 &
HMAC_WH_PID=$!
for i in $(seq 1 40); do
  if curl -sf "http://127.0.0.1:$HMAC_WH_PORT/health" >/dev/null; then
    break
  fi
  sleep 0.1
  if [ "$i" -eq 40 ]; then
    echo "hmac mock webhook receiver did not become healthy"
    cat "$HMAC_WH_LOG" || true
    exit 1
  fi
done
python3 -m agent_ci serve --port "$HMAC_PORT" --runs-dir "$HMAC_RUNS" \
  --concurrency 1 --max-queue 1 \
  --webhook-url "http://127.0.0.1:${HMAC_WH_PORT}/hook" \
  --webhook-secret "$HMAC_SECRET" >"$HMAC_LOG" 2>&1 &
HMAC_PID=$!
for i in $(seq 1 40); do
  if curl -sf "http://127.0.0.1:$HMAC_PORT/health" >/dev/null; then
    break
  fi
  sleep 0.1
  if [ "$i" -eq 40 ]; then
    echo "hmac serve did not become healthy"
    cat "$HMAC_LOG" || true
    exit 1
  fi
done
echo "==> [hmac] GET /v1/config must not leak webhook secret/url"
HMAC_CFG_CODE="$(curl -s -o /tmp/c-hmac-config.json -w '%{http_code}' \
  "http://127.0.0.1:$HMAC_PORT/v1/config")"
echo "hmac_config_status=$HMAC_CFG_CODE body=$(cat /tmp/c-hmac-config.json)"
test "$HMAC_CFG_CODE" = "200"
python3 - "$HMAC_SECRET" "$HMAC_WH_PORT" <<'PYHMACCFG'
import json, sys
from pathlib import Path
secret, port = sys.argv[1], sys.argv[2]
body = json.loads(Path("/tmp/c-hmac-config.json").read_text(encoding="utf-8"))
blob = json.dumps(body)
assert body.get("ok") is True, body
assert (body.get("webhooks") or {}).get("hasUrl") is True, body
assert (body.get("webhooks") or {}).get("hasSecret") is True, body
assert secret not in blob, blob
assert f"127.0.0.1:{port}" not in blob, blob
assert "whsec_" not in blob, blob
print("hmac_config_redacted_ok")
PYHMACCFG

HMAC_RID="mvp-hmac-rid-c1"
HMAC_CREATE="$(curl -sf -D /tmp/c-hmac-create.h -X POST "http://127.0.0.1:$HMAC_PORT/v1/runs" \
  -H 'content-type: application/json' \
  -H 'Authorization: Bearer demo' \
  -H "X-Request-Id: $HMAC_RID" \
  -d '{"suite":"fixtures/demo"}')"
echo "$HMAC_CREATE" | tee data/create-run-hmac.json
HMAC_RUN_ID="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["runId"])' <<<"$HMAC_CREATE")"
test -n "$HMAC_RUN_ID"
HMAC_GET="$(poll_run "$HMAC_RUN_ID" data/get-run-hmac.json "http://127.0.0.1:$HMAC_PORT")"
echo "$HMAC_GET" | grep -Eq '"status"[[:space:]]*:[[:space:]]*"done"'
HMAC_OK=0
for i in $(seq 1 40); do
  if test -f "$HMAC_OUT" && grep -q "$HMAC_RUN_ID" "$HMAC_OUT" 2>/dev/null \
     && test -f "$HMAC_HDR" && grep -q 'sha256=' "$HMAC_HDR" 2>/dev/null; then
    HMAC_OK=1
    break
  fi
  sleep 0.05
done
test "$HMAC_OK" = "1"
test -s "$HMAC_OUT"
grep -q "$HMAC_RUN_ID" "$HMAC_OUT"
grep -qi 'sha256=' "$HMAC_HDR"
grep -q '"verified": true' "$HMAC_HDR"
python3 -c '
import json, sys
from pathlib import Path
from agent_ci.webhook import sign_webhook_body, verify_webhook_signature
secret, body_path, hdr_path, rid, want = sys.argv[1:6]
body = Path(body_path).read_bytes()
meta = json.loads(Path(hdr_path).read_text(encoding="utf-8"))
sig = str(meta.get("signature") or "")
if not sig.lower().startswith("sha256="):
    raise SystemExit("missing X-Webhook-Signature sha256= prefix")
expected = sign_webhook_body(secret, body)
if sig.lower() != expected:
    raise SystemExit(f"HMAC mismatch got={sig} expected={expected}")
if not verify_webhook_signature(secret, body, sig):
    raise SystemExit("verify_webhook_signature failed")
if meta.get("verified") is not True:
    raise SystemExit("receiver verified flag %r" % (meta.get("verified"),))
d = json.loads(body.decode("utf-8"))
assert d.get("runId") == rid, d
assert d.get("requestId") == want, d
assert d.get("status") in ("done", "error", "failed"), d
assert d.get("conclusion") in ("success", "failure", "error"), d

raw = meta.get("timestamp")
if raw is None:
    headers = meta.get("headers") or {}
    raw = headers.get("X-Webhook-Timestamp") or headers.get("x-webhook-timestamp")
    if raw is None:
        for k, v in headers.items():
            if str(k).lower() == "x-webhook-timestamp":
                raw = v
                break
try:
    ts = int(str(raw or "").strip())
except (TypeError, ValueError):
    raise SystemExit("missing X-Webhook-Timestamp %r" % (meta,))
import time
now = int(time.time())
if abs(now - ts) > 120:
    raise SystemExit("timestamp not now ts=%s now=%s" % (ts, now))

print("webhook_hmac_ok", expected[:18] + "…", "ts=" + str(ts))
' "$HMAC_SECRET" "$HMAC_OUT" "$HMAC_HDR" "$HMAC_RUN_ID" "$HMAC_RID"
echo "webhook_hmac_ok"
if [ -n "${HMAC_PID:-}" ]; then
  kill "$HMAC_PID" 2>/dev/null || true
  wait "$HMAC_PID" 2>/dev/null || true
  HMAC_PID=""
fi
if [ -n "${HMAC_WH_PID:-}" ]; then
  kill "$HMAC_WH_PID" 2>/dev/null || true
  wait "$HMAC_WH_PID" 2>/dev/null || true
  HMAC_WH_PID=""
fi

echo "==> [watch] isolated serve --watch (fixtures max-mtime poll; must not hang / break queue)"
WATCH_PORT="${WATCH_PORT:-$((PORT + 23))}"
WATCH_RUNS="$ROOT/data/watch-runs"
WATCH_LOG="$ROOT/data/watch-serve.log"
WATCH_SUITE="watch-tmp-mvp-$$"
WATCH_DIR="$ROOT/fixtures/$WATCH_SUITE"
rm -rf "$WATCH_RUNS" "$WATCH_DIR"
mkdir -p "$WATCH_RUNS" data
unset AGENT_CI_CORS_ORIGINS || true
unset AGENT_CI_WEBHOOK_URL || true
unset AGENT_CI_WEBHOOK_SECRET || true
python3 -m agent_ci serve --port "$WATCH_PORT" --runs-dir "$WATCH_RUNS" \
  --concurrency 1 --max-queue 1 --watch >"$WATCH_LOG" 2>&1 &
WATCH_PID=$!
for i in $(seq 1 50); do
  if curl -sf "http://127.0.0.1:$WATCH_PORT/health" >/dev/null; then
    break
  fi
  sleep 0.1
  if [ "$i" -eq 50 ]; then
    echo "watch serve did not become healthy"
    cat "$WATCH_LOG" || true
    exit 1
  fi
  if ! kill -0 "$WATCH_PID" 2>/dev/null; then
    echo "watch serve exited early"
    cat "$WATCH_LOG" || true
    exit 1
  fi
done
grep -q "watch=poll 400ms" "$WATCH_LOG"
grep -q "watching" "$WATCH_LOG"

curl -sf "http://127.0.0.1:$WATCH_PORT/health" -o data/watch-before-health.json
python3 - <<'PYWATCHBEFORE'
import json
from pathlib import Path
h = json.loads(Path("data/watch-before-health.json").read_text(encoding="utf-8"))
assert h.get("ok") is True, h
w = h.get("watch") or {}
assert "generation" in w, h
gen = w.get("generation")
assert isinstance(gen, int) and gen >= 0, w
print("watch_before_generation", gen)
PYWATCHBEFORE
BEFORE_GEN="$(python3 -c 'import json; print(json.load(open("data/watch-before-health.json"))["watch"]["generation"])')"

# Main serve (no --watch) must omit watch field so stack-demo /health stays unchanged.
curl -sf "http://127.0.0.1:$PORT/health" -o data/watch-main-health.json
python3 - <<'PYMAINWATCH'
import json
from pathlib import Path
h = json.loads(Path("data/watch-main-health.json").read_text(encoding="utf-8"))
assert h.get("ok") is True, h
assert "watch" not in h, h
print("main_serve_no_watch_field_ok")
PYMAINWATCH

mkdir -p "$WATCH_DIR"
python3 -c '
import os, time
from pathlib import Path
p = Path("'"$WATCH_DIR"'")
now = time.time() + 1
os.utime(p, (now, now))
os.utime(p.parent, (now, now))
print("added_suite_dir", p)
'

REGEN_OK=0
for _ in $(seq 1 25); do
  curl -sf "http://127.0.0.1:$WATCH_PORT/health" -o data/watch-after-health.json || true
  curl -sf "http://127.0.0.1:$WATCH_PORT/v1/suites" -o data/watch-after-suites.json || true
  AFTER_GEN=""
  HAS_SUITE=""
  if test -s data/watch-after-health.json; then
    AFTER_GEN="$(python3 -c 'import json
try:
  print(json.load(open("data/watch-after-health.json")).get("watch",{}).get("generation",""))
except Exception:
  pass' || true)"
  fi
  if test -s data/watch-after-suites.json; then
    HAS_SUITE="$(python3 -c 'import json,sys
name=sys.argv[1]
try:
  data=json.load(open("data/watch-after-suites.json"))
except Exception:
  raise SystemExit
suites=data.get("suites") or []
print("1" if any(s.get("name")==name for s in suites) else "0")
' "$WATCH_SUITE" || true)"
  fi
  if grep -q regenerated "$WATCH_LOG" 2>/dev/null \
     && [ -n "$AFTER_GEN" ] && [ "$AFTER_GEN" -gt "$BEFORE_GEN" ] 2>/dev/null \
     && [ "$HAS_SUITE" = "1" ]; then
    REGEN_OK=1
    break
  fi
  if [ "$HAS_SUITE" = "1" ] && grep -q regenerated "$WATCH_LOG" 2>/dev/null; then
    curl -sf "http://127.0.0.1:$WATCH_PORT/health" -o data/watch-after-health.json || true
    REGEN_OK=1
    break
  fi
  if ! kill -0 "$WATCH_PID" 2>/dev/null; then
    echo "watch serve died before regenerate"
    cat "$WATCH_LOG" || true
    exit 1
  fi
  sleep 0.2
done

if [ -n "${WATCH_PID:-}" ]; then
  kill "$WATCH_PID" 2>/dev/null || true
  wait "$WATCH_PID" 2>/dev/null || true
  WATCH_PID=""
fi
rm -rf "$WATCH_DIR"
WATCH_DIR=""

if [ "$REGEN_OK" != "1" ]; then
  echo "watch did not regenerate within 5s"
  echo "--- watch-serve.log ---"
  cat "$WATCH_LOG" || true
  exit 1
fi
test -s data/watch-after-suites.json
python3 - <<PYWATCHAFTER
import json
from pathlib import Path
name = "$WATCH_SUITE"
suites = (json.loads(Path("data/watch-after-suites.json").read_text(encoding="utf-8")).get("suites") or [])
assert any(s.get("name") == name for s in suites), suites
h = json.loads(Path("data/watch-after-health.json").read_text(encoding="utf-8"))
assert int((h.get("watch") or {}).get("generation") or 0) >= 1, h
print("watch_reload_ok", {"suite": name, "generation": (h.get("watch") or {}).get("generation")})
PYWATCHAFTER
if ! grep -q regenerated "$WATCH_LOG"; then
  echo "watch regenerate detected via HTTP but missing regenerated log line"
  cat "$WATCH_LOG" || true
  exit 1
fi
grep -q "watching" "$WATCH_LOG"
echo "watch regenerate OK"

echo "==> [shutdown] isolated SIGTERM drain (ready 503 shutting_down; health 200 shuttingDown; exit)"
SD_PORT="${SD_PORT:-$((PORT + 24))}"
SD_RUNS="$ROOT/data/shutdown-runs"
SD_LOG="$ROOT/data/shutdown-serve.log"
rm -rf "$SD_RUNS"
mkdir -p "$SD_RUNS"
rm -f "$SD_LOG"
PYTHONPATH=src python3 -m agent_ci serve --port "$SD_PORT" --runs-dir "$SD_RUNS" \
  --concurrency 1 --max-queue 4 --drain-ms 800 >"$SD_LOG" 2>&1 &
SD_PID=$!
for i in $(seq 1 50); do
  if curl -sf "http://127.0.0.1:$SD_PORT/health" >/dev/null; then
    break
  fi
  sleep 0.1
  if [ "$i" -eq 50 ]; then
    echo "shutdown serve did not become healthy"
    cat "$SD_LOG" || true
    exit 1
  fi
  if ! kill -0 "$SD_PID" 2>/dev/null; then
    echo "shutdown serve exited early"
    cat "$SD_LOG" || true
    exit 1
  fi
done
kill -TERM "$SD_PID"
SD_READY=""
SD_HEALTH=""
for i in $(seq 1 20); do
  SD_READY="$(curl -s -o /tmp/c-sd-ready.json -w '%{http_code}' "http://127.0.0.1:$SD_PORT/ready" || true)"
  SD_HEALTH="$(curl -s -o /tmp/c-sd-health.json -w '%{http_code}' "http://127.0.0.1:$SD_PORT/health" || true)"
  if [ "$SD_READY" = "503" ]; then
    break
  fi
  sleep 0.05
done
if [ "$SD_READY" != "503" ]; then
  echo "shutdown /ready expected 503 got $SD_READY"
  cat /tmp/c-sd-ready.json 2>/dev/null || true
  cat "$SD_LOG" || true
  exit 1
fi
if [ "$SD_HEALTH" != "200" ]; then
  echo "shutdown /health expected 200 got $SD_HEALTH"
  cat /tmp/c-sd-health.json 2>/dev/null || true
  exit 1
fi
python3 - <<'PYSD'
import json
from pathlib import Path
ready = json.loads(Path("/tmp/c-sd-ready.json").read_text(encoding="utf-8"))
health = json.loads(Path("/tmp/c-sd-health.json").read_text(encoding="utf-8"))
assert ready.get("ok") is False and ready.get("reason") == "shutting_down", ready
assert health.get("ok") is True and health.get("shuttingDown") is True, health
print("shutdown_http_ok", {"ready": ready.get("reason"), "shuttingDown": health.get("shuttingDown")})
PYSD
for i in $(seq 1 30); do
  if ! kill -0 "$SD_PID" 2>/dev/null; then
    break
  fi
  sleep 0.1
done
if kill -0 "$SD_PID" 2>/dev/null; then
  echo "shutdown process did not exit within drain window"
  cat "$SD_LOG" || true
  exit 1
fi
wait "$SD_PID" 2>/dev/null || true
SD_PID=""
grep -q "shutting down" "$SD_LOG"
grep -q "exit" "$SD_LOG"
echo "shutdown SIGTERM OK"

echo "==> [access-log] default serve has no JSON access flood"
if grep -q '{"msg":"http"' "$SERVE_LOG"; then
  echo "default serve must not emit JSON access logs"
  grep '{"msg":"http"' "$SERVE_LOG" || true
  exit 1
fi

echo "==> [access-log] isolated serve --log-json (app path + X-Request-Id; skip probes)"
LOG_PORT="${LOG_PORT:-$((PORT + 25))}"
LOG_RUNS="$ROOT/data/runs-access"
LOG_LOG="$ROOT/data/serve.access.log"
rm -rf "$LOG_RUNS"
mkdir -p "$LOG_RUNS"
rm -f "$LOG_LOG"
python3 -m agent_ci serve --port "$LOG_PORT" --runs-dir "$LOG_RUNS" --log-json --drain-ms 200 >"$LOG_LOG" 2>&1 &
LOG_PID=$!
for i in $(seq 1 50); do
  if curl -sf "http://127.0.0.1:$LOG_PORT/health" >/dev/null; then
    break
  fi
  sleep 0.1
  if [ "$i" -eq 50 ]; then
    echo "access-log serve did not become healthy"
    cat "$LOG_LOG" || true
    exit 1
  fi
  if ! kill -0 "$LOG_PID" 2>/dev/null; then
    echo "access-log serve exited early"
    cat "$LOG_LOG" || true
    exit 1
  fi
done
curl -sf "http://127.0.0.1:$LOG_PORT/health" >/dev/null
curl -sf "http://127.0.0.1:$LOG_PORT/ready" >/dev/null
curl -sf "http://127.0.0.1:$LOG_PORT/metrics" >/dev/null
curl -sf -D /tmp/c-access.h -o /tmp/c-access.body \
  -H "X-Request-Id: test-log-1" \
  "http://127.0.0.1:$LOG_PORT/v1/suites" >/dev/null
grep -qiE '^x-request-id:[[:space:]]*test-log-1' /tmp/c-access.h
sleep 0.15
python3 - <<'PYLOG'
import json
from pathlib import Path
log = Path("data/serve.access.log").read_text(encoding="utf-8")
hits = []
for line in log.splitlines():
    if '"msg":"http"' not in line:
        continue
    try:
        hits.append(json.loads(line))
    except json.JSONDecodeError:
        pass
http = [o for o in hits if isinstance(o, dict) and o.get("msg") == "http"]
if len(http) != 1:
    raise SystemExit(f"expected exactly 1 http access line (probes skipped) {http!r}\n{log}")
rec = http[0]
if (
    rec.get("level") != "info"
    or rec.get("service") != "agent-ci"
    or rec.get("method") != "GET"
    or rec.get("path") != "/v1/suites"
    or rec.get("status") != 200
    or rec.get("requestId") != "test-log-1"
    or not isinstance(rec.get("durationMs"), (int, float))
):
    raise SystemExit(f"access log fields {rec}")
print("access_log_ok", {"requestId": rec["requestId"], "status": rec["status"], "durationMs": rec["durationMs"], "path": rec["path"]})
PYLOG
kill "$LOG_PID" 2>/dev/null || true
for i in $(seq 1 20); do
  if ! kill -0 "$LOG_PID" 2>/dev/null; then
    break
  fi
  sleep 0.1
done
kill -9 "$LOG_PID" 2>/dev/null || true
wait "$LOG_PID" 2>/dev/null || true
LOG_PID=""
echo "access-log JSON OK"

echo "==> [runs-max] isolated serve --runs-max 2 (POST 3 quick demo runs; list has 2; oldest 404; queue not hung)"
RUNSMAX_PORT="${RUNSMAX_PORT:-$((PORT + 27))}"
RUNSMAX_RUNS="$ROOT/data/runs-max-runs"
RUNSMAX_LOG="$ROOT/data/runs-max-serve.log"
rm -rf "$RUNSMAX_RUNS"
mkdir -p "$RUNSMAX_RUNS" data
rm -f "$RUNSMAX_LOG" data/runs-max-1.json data/runs-max-2.json data/runs-max-3.json data/runs-max-list.json data/runs-max-old.json
unset AGENT_CI_CORS_ORIGINS || true
unset AGENT_CI_WEBHOOK_URL || true
unset AGENT_CI_WEBHOOK_SECRET || true
unset RATE_LIMIT_PER_MINUTE RATE_LIMIT_RPM || true
unset RUNS_MAX || true
python3 -m agent_ci serve --port "$RUNSMAX_PORT" --runs-dir "$RUNSMAX_RUNS" \
  --concurrency 1 --max-queue 8 --runs-max 2 >"$RUNSMAX_LOG" 2>&1 &
RUNSMAX_PID=$!
for i in $(seq 1 50); do
  if curl -sf "http://127.0.0.1:$RUNSMAX_PORT/health" >/dev/null; then
    break
  fi
  sleep 0.1
  if [ "$i" -eq 50 ]; then
    echo "runs-max serve did not become healthy"
    cat "$RUNSMAX_LOG" || true
    exit 1
  fi
  if ! kill -0 "$RUNSMAX_PID" 2>/dev/null; then
    echo "runs-max serve exited early"
    cat "$RUNSMAX_LOG" || true
    exit 1
  fi
done
grep -q "runs_max=2" "$RUNSMAX_LOG"

post_demo() {
  local out="$1"
  curl -sf -X POST "http://127.0.0.1:$RUNSMAX_PORT/v1/runs" \
    -H 'content-type: application/json' \
    -H 'Authorization: Bearer demo' \
    -d '{"suite":"fixtures/demo"}' >"$out"
}

post_demo data/runs-max-1.json
post_demo data/runs-max-2.json
post_demo data/runs-max-3.json
RM1="$(python3 -c 'import json; print(json.load(open("data/runs-max-1.json"))["runId"])')"
RM2="$(python3 -c 'import json; print(json.load(open("data/runs-max-2.json"))["runId"])')"
RM3="$(python3 -c 'import json; print(json.load(open("data/runs-max-3.json"))["runId"])')"
test -n "$RM1" && test -n "$RM2" && test -n "$RM3"
test "$RM1" != "$RM2" && test "$RM2" != "$RM3"
poll_run "$RM3" data/runs-max-3-done.json "http://127.0.0.1:$RUNSMAX_PORT" >/dev/null
python3 - <<PYRM
import json
from pathlib import Path
d = json.loads(Path("data/runs-max-3-done.json").read_text(encoding="utf-8"))
assert d.get("status") in ("done", "failed", "error"), d
print("runs_max_last_done", d.get("runId"), d.get("status"))
PYRM
LIST_RM="$(curl -sf "http://127.0.0.1:$RUNSMAX_PORT/v1/runs?limit=10")"
echo "$LIST_RM" | tee data/runs-max-list.json
python3 - "$RM1" "$RM2" "$RM3" <<'PYRMLIST'
import json, sys
from pathlib import Path
old, mid, new = sys.argv[1], sys.argv[2], sys.argv[3]
data = json.loads(Path("data/runs-max-list.json").read_text(encoding="utf-8"))
runs = data.get("runs") or []
ids = [r.get("runId") for r in runs]
assert len(runs) == 2, data
assert data.get("count") == 2, data
assert old not in ids, ids
assert mid in ids and new in ids, ids
print("runs_max_list_ok", ids)
PYRMLIST
set +e
OLD_CODE="$(curl -s -o data/runs-max-old.json -w '%{http_code}' "http://127.0.0.1:$RUNSMAX_PORT/v1/runs/$RM1")"
set -e
echo "runs_max_oldest_status=$OLD_CODE body=$(cat data/runs-max-old.json)"
test "$OLD_CODE" = "404"
curl -sf "http://127.0.0.1:$RUNSMAX_PORT/v1/runs/$RM3" >/dev/null
# queue must still accept a run (not hung)
QOK="$(curl -s -o data/runs-max-queue.json -w '%{http_code}' -X POST "http://127.0.0.1:$RUNSMAX_PORT/v1/runs" \
  -H 'content-type: application/json' \
  -H 'Authorization: Bearer demo' \
  -d '{"suite":"fixtures/demo"}')"
echo "runs_max_queue_post_status=$QOK"
test "$QOK" = "202"
if [ -n "${RUNSMAX_PID:-}" ]; then
  kill "$RUNSMAX_PID" 2>/dev/null || true
  wait "$RUNSMAX_PID" 2>/dev/null || true
  RUNSMAX_PID=""
fi
echo "==> [runs-max] list 2 / oldest 404 / queue still 202 OK (isolated); main serve default 1000 unchanged"

cleanup_serve
trap - EXIT

echo "c-agent-ci local-mvp OK (queue+cors+request-id+openapi+metrics+webhook+hmac+watch+shutdown+access-log+junit+tap+md+html+gha+rate-limit+runs-max+run-diff+run-cases+promptfoo)"
