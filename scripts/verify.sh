#!/usr/bin/env bash
# AgentCenter 验证脚本
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${PORT:-8013}"
BASE_URL="http://localhost:${PORT}"
MOCK_MODE="${AI_MOCK_MODE:-true}"

pass=0
fail=0

check() {
  local name="$1"
  local cmd="$2"
  echo -n "[verify] $name ... "
  if eval "$cmd" > /dev/null 2>&1; then
    echo "PASS"
    pass=$((pass + 1))
  else
    echo "FAIL"
    fail=$((fail + 1))
  fi
}

echo "=== AgentCenter 验证 ==="
echo "BASE_URL=$BASE_URL MOCK_MODE=$MOCK_MODE"

# 确保服务运行（Mock 模式）
export AI_MOCK_MODE="$MOCK_MODE"
if ! curl -sf "$BASE_URL/api/health" > /dev/null 2>&1; then
  echo "[verify] 服务未运行，尝试启动..."
  AI_MOCK_MODE="$MOCK_MODE" "$ROOT/scripts/start.sh"
  sleep 2
fi

AC="$ROOT/scripts/ac"
export AGENTCENTER_URL="$BASE_URL"

check "健康检查" "'$AC' health | grep -q 'status=ok'"

check "Agent 列表" "'$AC' --json agents list | python3 -c \"import sys,json; d=json.load(sys.stdin); assert len(d)>=1\""

# 创建 Mock 任务
TASK_ID=$("$AC" --json tasks run coder "verify smoke test" --wait --wait-timeout 30 \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['id']); assert d['status']=='completed'")
echo "[verify] 创建任务 task_id=$TASK_ID"

check "任务完成" "'$AC' --json tasks get '$TASK_ID' | python3 -c \"import sys,json; d=json.load(sys.stdin); assert d['status']=='completed'\""

check "任务列表" "'$AC' --json tasks list | python3 -c \"import sys,json; d=json.load(sys.stdin); assert d['total']>=1\""

check "小队列表" "'$AC' --json squads list | python3 -c \"import sys,json; d=json.load(sys.stdin); assert len(d)>=1\""

check "技能目录" "'$AC' --json skills | python3 -c \"import sys,json; json.load(sys.stdin)\""

check "Agent 统计" "'$AC' --json agents stats | python3 -c \"import sys,json; json.load(sys.stdin)\""

check "系统状态" "curl -sf '$BASE_URL/api/system-status' | python3 -c \"import sys,json; d=json.load(sys.stdin); assert 'gateway' in d\""

check "Sessions" "curl -sf '$BASE_URL/api/sessions' | python3 -c \"import sys,json; json.load(sys.stdin)\""

echo ""
echo "=== 结果: $pass 通过, $fail 失败 ==="
if [[ $fail -gt 0 ]]; then
  exit 1
fi
echo "[verify] 全部通过"
