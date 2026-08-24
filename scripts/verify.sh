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

check "双运行时 Agent" "'$AC' --json agents list | python3 -c \"import sys,json; d=json.load(sys.stdin); rts={a.get('runtime') for a in d}; assert 'openclaw' in rts and 'hermes' in rts\""

# 创建 Mock 任务（OpenClaw）
TASK_ID=$("$AC" --json tasks run coder "verify smoke test" --runtime openclaw --wait --wait-timeout 30 \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['id']); assert d['status']=='completed'")
echo "[verify] 创建任务 task_id=$TASK_ID"

check "任务完成" "'$AC' --json tasks get '$TASK_ID' | python3 -c \"import sys,json; d=json.load(sys.stdin); assert d['status']=='completed'\""

# Hermes Mock 任务
HERMES_TASK=$("$AC" --json tasks run default "verify hermes smoke" --runtime hermes --wait --wait-timeout 30 \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['id']); assert d['status']=='completed' and d.get('runtime')=='hermes'")
echo "[verify] Hermes 任务 task_id=$HERMES_TASK"

check "Hermes 任务完成" "'$AC' --json tasks get '$HERMES_TASK' | python3 -c \"import sys,json; d=json.load(sys.stdin); assert d['status']=='completed'\""

check "任务列表" "'$AC' --json tasks list | python3 -c \"import sys,json; d=json.load(sys.stdin); assert d['total']>=1\""

check "小队列表" "'$AC' --json squads list | python3 -c \"import sys,json; d=json.load(sys.stdin); assert len(d)>=1; assert any(s.get('runtime')=='hermes' for s in d)\""

check "Hermes 小队任务" "'$AC' --json squads run hermes_core 'verify hermes squad' --wait --wait-timeout 30 | python3 -c \"import sys,json; d=json.load(sys.stdin); assert d['status']=='completed' and d.get('runtime')=='hermes'\""

check "Autopilot 双栈" "curl -sf '$BASE_URL/api/autopilots?include_hermes=true' | python3 -c \"import sys,json; d=json.load(sys.stdin); assert any((x.get('source')=='hermes' or str(x.get('id','')).startswith('hermes:')) for x in d)\""

check "Hermes Session 详情" "curl -sf '$BASE_URL/api/sessions/hermes-mock-session-1' | python3 -c \"import sys,json; d=json.load(sys.stdin); assert d.get('runtime')=='hermes' and len(d.get('messages') or [])>=1\""

check "技能目录" "'$AC' --json skills | python3 -c \"import sys,json; d=json.load(sys.stdin); assert isinstance(d,list) and len(d)>=1; assert not any((x.get('description') or '').strip()=='---' for x in d)\""

check "Skills 双运行时" "curl -sf '$BASE_URL/api/skills' | python3 -c \"import sys,json; d=json.load(sys.stdin); rts={x.get('runtime') for x in d}; assert 'openclaw' in rts\""

SKILL_META=$("$AC" --json skills | python3 -c "
import sys, json, urllib.parse
d = json.load(sys.stdin)
# 优先 flat openclaw id，避免嵌套路径编码麻烦
item = next((x for x in d if (x.get('runtime') or 'openclaw') == 'openclaw' and '/' not in x.get('id','')), d[0])
print(item.get('id',''))
print(item.get('runtime') or 'openclaw')
")
SKILL_ID=$(echo "$SKILL_META" | sed -n '1p')
SKILL_RT=$(echo "$SKILL_META" | sed -n '2p')
check "技能详情" "curl -sf '$BASE_URL/api/skills/${SKILL_ID}?runtime=${SKILL_RT}' | python3 -c \"import sys,json; d=json.load(sys.stdin); assert d.get('id') and 'body_preview' in d\""

check "Kanban 任务列表" "curl -sf '$BASE_URL/api/kanban/tasks' | python3 -c \"import sys,json; d=json.load(sys.stdin); assert isinstance(d,list) and len(d)>=1\""

check "Kanban 映射执行" "curl -sf -X POST '$BASE_URL/api/kanban/tasks/t_mock1/run' -H 'Content-Type: application/json' -d '{}' | python3 -c \"import sys,json; d=json.load(sys.stdin); assert d.get('runtime')=='hermes' and d.get('id')\""

check "Kanban Swarm" "curl -sf -X POST '$BASE_URL/api/kanban/swarm' -H 'Content-Type: application/json' -d '{\"goal\":\"verify swarm\",\"workers\":[\"default:Research\",\"default:Draft\"],\"verifier\":\"default\",\"synthesizer\":\"default\"}' | python3 -c \"import sys,json; d=json.load(sys.stdin); assert d.get('root_id') and len(d.get('nodes') or [])>=4 and len(d.get('edges') or [])>=3\""

check "Skills Hermes 安装" "curl -sf -X POST '$BASE_URL/api/skills/install' -H 'Content-Type: application/json' -d '{\"url\":\"openai/skills/skill-creator\",\"runtime\":\"hermes\"}' | python3 -c \"import sys,json; d=json.load(sys.stdin); assert d.get('runtime')=='hermes' and d.get('status')=='completed'\""

check "告警接口" "curl -sf '$BASE_URL/api/cron-alerts' | python3 -c \"import sys,json; d=json.load(sys.stdin); assert 'recent_alerts' in d and 'gateway_alerts' in d and d.get('persisted') is True\""

check "告警规则" "curl -sf '$BASE_URL/api/settings/alert' | python3 -c \"import sys,json; d=json.load(sys.stdin); assert 'cron_alert_enabled' in d and 'gateway_alert_enabled' in d and 'disk_alert_threshold' in d\""

check "告警规则更新" "curl -sf -X PATCH '$BASE_URL/api/settings/alert' -H 'Content-Type: application/json' -d '{\"cron_alert_enabled\":true,\"gateway_alert_enabled\":true,\"disk_alert_threshold\":90,\"profile\":\"default\"}' | python3 -c \"import sys,json; d=json.load(sys.stdin); assert d.get('status')=='ok' and d.get('persisted') is True and d.get('settings',{}).get('disk_alert_threshold')==90\""

check "告警规则落盘" "python3 -c \"import json; from pathlib import Path; p=Path('backend/data/alert_profiles.json'); assert p.is_file(), p; d=json.loads(p.read_text()); assert d.get('active'); assert d['profiles'][d['active']]['disk_alert_threshold']==90\""

check "告警多环境" "curl -sf -X POST '$BASE_URL/api/settings/alert/profiles' -H 'Content-Type: application/json' -d '{\"name\":\"verify_env\",\"from_current\":true,\"activate\":false}' >/dev/null && curl -sf -X POST '$BASE_URL/api/settings/alert/profiles/verify_env/activate' | python3 -c \"import sys,json; d=json.load(sys.stdin); assert d.get('active')=='verify_env'\" && curl -sf -X POST '$BASE_URL/api/settings/alert/profiles/default/activate' | python3 -c \"import sys,json; d=json.load(sys.stdin); assert d.get('active')=='default'\""

check "知识库状态" "curl -sf '$BASE_URL/api/knowledge/status' | python3 -c \"import sys,json; d=json.load(sys.stdin); assert d.get('embedding',{}).get('provider')=='hash'; assert 'playbook' in (d.get('kinds') or [])\""

check "知识库蒸馏检索" "curl -sf -X POST '$BASE_URL/api/knowledge/backfill' >/dev/null && curl -sf '$BASE_URL/api/knowledge/search?q=verify&mode=hybrid' | python3 -c \"import sys,json; d=json.load(sys.stdin); assert isinstance(d,list) and any(x.get('kind') in ('playbook','precedent','incident') for x in d)\""

check "知识库注入预览" "curl -sf '$BASE_URL/api/knowledge/inject-preview?q=verify%20smoke' | python3 -c \"import sys,json; d=json.load(sys.stdin); assert 'hits' in d and isinstance(d['hits'],list); assert d.get('block')=='' or '知识库参考' in d.get('block','')\""

check "共享事实写入" "curl -sf -X POST '$BASE_URL/api/knowledge/entries' -H 'Content-Type: application/json' -d '{\"kind\":\"shared_fact\",\"title\":\"verify shared fact\",\"summary\":\"verify archive path convention\",\"tags\":[\"verify\"],\"payload\":{\"body\":\"verify archive path convention\"}}' | python3 -c \"import sys,json; d=json.load(sys.stdin); assert d.get('kind')=='shared_fact' and d.get('id')\""

INJECT_TASK=$("$AC" --json tasks run coder "verify knowledge inject precedent smoke" --runtime openclaw --wait --wait-timeout 30 \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['id'])")
check "任务前注入" "curl -sf '$BASE_URL/api/tasks/$INJECT_TASK' | python3 -c \"import sys,json; d=json.load(sys.stdin); sp=d.get('system_prompt') or ''; assert '知识库参考' in sp, sp[:240]\""

check "Session 消息归档" "curl -sf -X POST '$BASE_URL/api/knowledge/index-session/hermes-mock-session-1' | python3 -c \"import sys,json; d=json.load(sys.stdin); assert d.get('status')=='ok' and d.get('indexed',0)>=1 and d.get('kind')=='archive'\""

check "Archive 向量检索" "curl -sf '$BASE_URL/api/knowledge/search?q=Mock%20Hermes&mode=vector&include_archive=true&kind=archive' | python3 -c \"import sys,json; d=json.load(sys.stdin); assert isinstance(d,list) and any(x.get('source_type')=='session_msg' or x.get('kind')=='archive' for x in d)\""

check "输出物状态" "curl -sf '$BASE_URL/api/outputs/status' | python3 -c \"import sys,json; d=json.load(sys.stdin); assert 'readable' in d and 'status' in d\""

# vault 可读时再测树与路径穿越拒绝
if curl -sf "$BASE_URL/api/outputs/status" | python3 -c "import sys,json; d=json.load(sys.stdin); raise SystemExit(0 if d.get('readable') else 1)"; then
  check "输出物目录" "curl -sf '$BASE_URL/api/outputs/tree' | python3 -c \"import sys,json; d=json.load(sys.stdin); assert isinstance(d,list)\""
  check "输出物路径穿越拒绝" "code=\$(curl -s -o /dev/null -w '%{http_code}' '$BASE_URL/api/outputs/tree?path=../'); [[ \$code == 400 ]]"
else
  echo "[verify] 输出物 vault 不可读，跳过 tree/穿越检查"
fi

# Hermes 技能下线（临时 skill，测完清理；id 勿以 _ 开头，会被当作隐藏目录拒绝）
HERMES_SKILLS_ROOT="${HERMES_SKILLS_DIR:-$HOME/.hermes/skills}"
VERIFY_SKILL_ID="agentcenter-verify/demo"
VERIFY_SKILL_DIR="$HERMES_SKILLS_ROOT/$VERIFY_SKILL_ID"
mkdir -p "$VERIFY_SKILL_DIR"
cat > "$VERIFY_SKILL_DIR/SKILL.md" <<'EOF'
---
name: agentcenter-verify
description: temporary skill for AgentCenter verify
---
# Verify
EOF
check "Hermes 技能下线" "curl -sf -X POST '$BASE_URL/api/skills/${VERIFY_SKILL_ID}/archive?runtime=hermes' | python3 -c \"import sys,json; d=json.load(sys.stdin); assert d.get('archived') is True and d.get('runtime')=='hermes'\""
rm -rf "$HERMES_SKILLS_ROOT/_archive/agentcenter-verify" "$HERMES_SKILLS_ROOT/agentcenter-verify" 2>/dev/null || true
rm -rf "$HOME/.hermes/skills/_archive/_agentcenter_verify" "$HOME/.hermes/skills/_agentcenter_verify" 2>/dev/null || true

check "Agent 统计" "'$AC' --json agents stats | python3 -c \"import sys,json; json.load(sys.stdin)\""

# 桌面端 / 控制台若在跑，确认 CSS 不是 404（打包拷错 distDir 时会无样式）
FE_URL="http://127.0.0.1:${FRONTEND_PORT:-3013}"
if curl -sf -o /dev/null "$FE_URL/cyber/tasks"; then
  CSS_HREF=$(curl -sS "$FE_URL/cyber/tasks" | python3 -c "import sys,re; h=sys.stdin.read(); m=re.search(r'href=\"(/_next/static/css/[^\"]+)\"', h); print(m.group(1) if m else '')")
  if [[ -n "$CSS_HREF" ]]; then
    check "前端 CSS 可加载" "code=\$(curl -s -o /dev/null -w '%{http_code}' '$FE_URL$CSS_HREF'); [[ \$code == 200 ]]"
  else
    echo "[verify] 前端 HTML 未引用 CSS，跳过静态资源检查"
  fi
else
  echo "[verify] 前端 3013 未运行，跳过 CSS 检查"
fi

check "系统状态" "curl -sf '$BASE_URL/api/system-status' | python3 -c \"import sys,json; d=json.load(sys.stdin); assert 'gateway' in d and 'runtimes' in d and len(d['runtimes'])>=2\""

check "Sessions" "curl -sf '$BASE_URL/api/sessions' | python3 -c \"import sys,json; json.load(sys.stdin)\""

# Cron 修复派单（Mock 下有 mock-cron-error-1；Live 取第一条 error）
CRON_ID=$(curl -sf "$BASE_URL/api/system-status?refresh=true" | python3 -c "
import sys, json
d = json.load(sys.stdin)
errs = d.get('cron_errors') or []
print(errs[0]['id'] if errs else '')
")
if [[ -n "$CRON_ID" ]]; then
  check "Cron 修复派单" "curl -sf -X POST '$BASE_URL/api/cron/$CRON_ID/repair' -H 'Content-Type: application/json' -d '{}' | python3 -c \"import sys,json; d=json.load(sys.stdin); assert d.get('id') and d.get('agent_id')\""
else
  check "Cron 修复 404" "code=\$(curl -s -o /dev/null -w '%{http_code}' -X POST '$BASE_URL/api/cron/__missing__/repair' -H 'Content-Type: application/json' -d '{}'); [[ \$code == 404 ]]"
fi

echo ""
echo "=== 结果: $pass 通过, $fail 失败 ==="
if [[ $fail -gt 0 ]]; then
  exit 1
fi
echo "[verify] 全部通过"
