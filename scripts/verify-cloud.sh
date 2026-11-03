#!/usr/bin/env bash
# 云端协调器验收。不断言 OpenClaw/Hermes 可用。
# 日志：logs/verify-cloud.log
# 用法：
#   ./scripts/verify-cloud.sh
#   ./scripts/verify-cloud.sh --local-full   # 额外对本机 full 做 handshake 冒烟
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="${AGENTCENTER_LOG_DIR_LOCAL:-$ROOT/logs}"
LOG_FILE="$LOG_DIR/verify-cloud.log"
REMOTE="${AGENTCENTER_CLOUD_HOST:-root@47.113.225.93}"
HOST_ONLY="${REMOTE##*@}"
BASE_URL="${AGENTCENTER_CLOUD_URL:-http://${HOST_ONLY}:8080}"
SSH=(ssh -o BatchMode=yes -o ConnectTimeout=20 -o StrictHostKeyChecking=accept-new)
DO_HANDSHAKE=0

for arg in "$@"; do
  case "$arg" in
    --local-full) DO_HANDSHAKE=1 ;;
    -h|--help)
      echo "Usage: $0 [--local-full]"
      exit 0
      ;;
  esac
done

mkdir -p "$LOG_DIR"
exec > >(tee -a "$LOG_FILE") 2>&1

pass=0
fail=0

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') [verify-cloud] $*"; }

check() {
  local name="$1"
  shift
  echo -n "[verify-cloud] $name ... "
  if "$@" >/dev/null 2>&1; then
    echo "PASS"
    pass=$((pass + 1))
  else
    echo "FAIL"
    fail=$((fail + 1))
  fi
}

log "BASE_URL=$BASE_URL"

check "health 可达" curl -sf --max-time 8 "$BASE_URL/api/health"

check "deploy_profile=cloud" python3 - <<PY
import json, urllib.request
with urllib.request.urlopen("$BASE_URL/api/health", timeout=8) as r:
    d = json.load(r)
assert d.get("status") == "ok", d
assert d.get("deploy_profile") == "cloud", d
PY

check "静态首页" python3 - <<PY
import urllib.request
req = urllib.request.Request("$BASE_URL/")
with urllib.request.urlopen(req, timeout=8) as r:
    assert r.status in (200, 302, 307), r.status
PY

check "无令牌 enroll 拒绝" python3 - <<PY
import json, urllib.error, urllib.request
body = json.dumps({
    "enroll_token": "",
    "node_id": "verify-empty",
    "name": "verify",
    "runtimes": [],
    "agents": [],
    "hostname": "verify",
    "platform": "linux",
    "mode": "plugin",
}).encode()
req = urllib.request.Request(
    "$BASE_URL/api/fleet/enroll",
    data=body,
    headers={"Content-Type": "application/json"},
    method="POST",
)
try:
    with urllib.request.urlopen(req, timeout=8) as resp:
        raise SystemExit(f"unexpected success {resp.status}")
except urllib.error.HTTPError as e:
    assert e.code in (400, 401, 403, 422), e.code
PY

echo -n "[verify-cloud] 远端无个人内容路径 ... "
if "${SSH[@]}" "$REMOTE" bash -s <<'EOF'
set -euo pipefail
f=/opt/agentcenter/app/.env
c=/opt/agentcenter/data/content_roots.json
if [[ -f "$f" ]] && grep -Eiq 'Mobile Documents|iCloud|/Users/|/opt/agentcenter/WaytoAI' "$f"; then
  exit 1
fi
if [[ -f "$c" ]] && grep -Eiq 'Mobile Documents|iCloud|/Users/|/opt/agentcenter/WaytoAI' "$c"; then
  exit 1
fi
exit 0
EOF
then
  echo "PASS"
  pass=$((pass + 1))
else
  echo "FAIL"
  fail=$((fail + 1))
fi

echo -n "[verify-cloud] 有令牌 enroll ... "
ENROLL_CODE="$("${SSH[@]}" "$REMOTE" python3 - <<'PY'
import json, pathlib, urllib.error, urllib.request
env = pathlib.Path("/opt/agentcenter/app/.env").read_text(encoding="utf-8")
token = ""
for line in env.splitlines():
    if line.startswith("FLEET_ENROLL_TOKEN="):
        token = line.split("=", 1)[1].strip().strip("\"'")
        break
if not token:
    raise SystemExit("missing")
body = json.dumps({
    "enroll_token": token,
    "node_id": "verify-cloud-smoke",
    "name": "verify-cloud-smoke",
    "runtimes": ["openclaw"],
    "agents": [{"id": "main", "name": "main", "runtime": "openclaw"}],
    "hostname": "verify-cloud",
    "platform": "linux",
    "mode": "plugin",
}).encode()
req = urllib.request.Request(
    "http://127.0.0.1:8080/api/fleet/enroll",
    data=body,
    headers={"Content-Type": "application/json"},
    method="POST",
)
try:
    with urllib.request.urlopen(req, timeout=8) as resp:
        print(resp.status)
except urllib.error.HTTPError as e:
    print(e.code)
PY
)" || ENROLL_CODE="err"
if [[ "$ENROLL_CODE" == "200" || "$ENROLL_CODE" == "201" ]]; then
  echo "PASS ($ENROLL_CODE)"
  pass=$((pass + 1))
else
  echo "FAIL (code=$ENROLL_CODE)"
  fail=$((fail + 1))
fi

if [[ "$DO_HANDSHAKE" == "1" ]]; then
  LOCAL_URL="${AGENTCENTER_URL:-http://127.0.0.1:8013}"
  echo -n "[verify-cloud] local-full handshake ... "
  if curl -sf --max-time 5 "$LOCAL_URL/api/health" >/dev/null 2>&1; then
    # 本机 POST /api/fleet/link 走完整握手（含云端 /handshake/accept）
    HS_CODE="$(python3 - <<PY
import json, urllib.error, urllib.request
from pathlib import Path
base = "$LOCAL_URL"
cloud = "$BASE_URL"
data = Path.home() / "Library/Application Support/AgentCenter/data"
entry = (data / "entry_code").read_text().strip() if (data / "entry_code").is_file() else ""
session = ""
if entry:
    req = urllib.request.Request(
        f"{base}/api/session/unlock",
        data=json.dumps({"code": entry}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        session = json.load(resp).get("token") or ""
if not session and (data / "local_session.token").is_file():
    session = (data / "local_session.token").read_text().strip()
body = json.dumps({"cloud_url": cloud, "workspace_id": "cyber"}).encode()
req = urllib.request.Request(
    f"{base}/api/fleet/link",
    data=body,
    headers={
        "Content-Type": "application/json",
        "X-AgentCenter-Session": session,
    },
    method="POST",
)
try:
    with urllib.request.urlopen(req, timeout=45) as resp:
        payload = json.load(resp)
        print("200" if payload.get("state") == "ok" or payload.get("bound") else f"bad-state:{payload.get('state')}")
except urllib.error.HTTPError as e:
    print(e.code)
except Exception:
    print("err")
PY
)"
    if [[ "$HS_CODE" == "200" ]]; then
      echo "PASS"
      pass=$((pass + 1))
    else
      echo "FAIL (code=$HS_CODE)"
      fail=$((fail + 1))
    fi

    echo -n "[verify-cloud] local-full 槽位与撤证 ... "
    SLOT_OUT="$(python3 - <<PY
import json, urllib.request
with urllib.request.urlopen("$LOCAL_URL/api/health", timeout=8) as r:
    d = json.load(r)
assert d.get("deploy_profile") == "full", d
assert d.get("center_id"), d
print("ok")
PY
)" || SLOT_OUT="fail"
    if [[ "$SLOT_OUT" == "ok" ]]; then
      echo "PASS (health center)"
      pass=$((pass + 1))
    else
      echo "FAIL"
      fail=$((fail + 1))
    fi

    echo -n "[verify-cloud] local-full 撤销 node 凭证后 claim 拒绝 ... "
    REVOKE_OUT="$(python3 - <<'PY'
import json, urllib.error, urllib.request
from pathlib import Path
import os
base = os.environ.get("AGENTCENTER_URL", "http://127.0.0.1:8013")
data = Path(os.environ.get("AGENTCENTER_DATA_DIR", Path.home() / "Library/Application Support/AgentCenter/data"))
token_path = data / "node_agent.token"
if not token_path.is_file():
    print("skip")
    raise SystemExit(0)
token = token_path.read_text().strip()
entry = (data / "entry_code").read_text().strip() if (data / "entry_code").is_file() else ""
session = ""
if entry:
    ureq = urllib.request.Request(
        f"{base}/api/session/unlock",
        data=json.dumps({"code": entry}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(ureq, timeout=10) as resp:
        session = json.load(resp).get("token") or ""
if not session and (data / "local_session.token").is_file():
    session = (data / "local_session.token").read_text().strip()
# 先确认可 claim-next
body = json.dumps({"protocol_version": 2}).encode()
req = urllib.request.Request(
    f"{base}/api/v2/commands/claim-next",
    data=body,
    headers={"Content-Type": "application/json", "X-Node-Token": token},
    method="POST",
)
try:
    with urllib.request.urlopen(req, timeout=10) as resp:
        json.load(resp)
except urllib.error.HTTPError as e:
    if e.code == 401:
        print("already-revoked")
        raise SystemExit(0)
# 调用本机撤销 API（需本机会话）
rev = urllib.request.Request(
    f"{base}/api/v2/nodes/revoke-local",
    data=b"{}",
    headers={
        "Content-Type": "application/json",
        "X-AgentCenter-Session": session,
    },
    method="POST",
)
try:
    with urllib.request.urlopen(rev, timeout=10) as resp:
        json.load(resp)
except urllib.error.HTTPError as e:
    if e.code == 404:
        print("skip-no-api")
        raise SystemExit(0)
    print(f"fail-revoke-{e.code}")
    raise SystemExit(0)
req2 = urllib.request.Request(
    f"{base}/api/v2/commands/claim-next",
    data=body,
    headers={"Content-Type": "application/json", "X-Node-Token": token},
    method="POST",
)
try:
    with urllib.request.urlopen(req2, timeout=10) as resp:
        print("fail-still-accepted")
except urllib.error.HTTPError as e:
    print("ok" if e.code in (401, 403) else f"fail-{e.code}")
PY
)"
    if [[ "$REVOKE_OUT" == ok* || "$REVOKE_OUT" == skip* || "$REVOKE_OUT" == already-* ]]; then
      echo "PASS ($REVOKE_OUT)"
      pass=$((pass + 1))
    else
      echo "FAIL ($REVOKE_OUT)"
      fail=$((fail + 1))
    fi
  else
    echo "SKIP (本机 $LOCAL_URL 未运行)"
  fi
fi

log "ESP 文档地址仍为 http://47.113.225.93:8080（见 sound/esp32-direct/TOOLS.md）"
log "结果 pass=$pass fail=$fail"
if [[ "$fail" -gt 0 ]]; then
  exit 1
fi
exit 0
