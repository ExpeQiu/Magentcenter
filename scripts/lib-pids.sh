# shellcheck shell=bash
# PID 约定：数据目录下 core.pid / node-agent.pid；兼容 sidecar.pid、agentcenter.pid。
# 由 start.sh / stop.sh / Tauri 共用。

_ac_data_dir() {
  local app_support="${HOME}/Library/Application Support/AgentCenter"
  echo "${AGENTCENTER_DATA_DIR:-$app_support/data}"
}

_ac_write_pid() {
  local name="$1" pid="$2"
  local dir
  dir="$(_ac_data_dir)"
  mkdir -p "$dir"
  echo "$pid" >"$dir/${name}.pid"
  # 兼容旧脚本
  if [[ "$name" == "core" ]]; then
    echo "$pid" >"$dir/agentcenter.pid"
    echo "$pid" >"$dir/sidecar.pid"
  fi
}

_ac_clear_pid() {
  local name="$1"
  local dir
  dir="$(_ac_data_dir)"
  rm -f "$dir/${name}.pid"
  if [[ "$name" == "core" ]]; then
    rm -f "$dir/agentcenter.pid" "$dir/sidecar.pid"
  fi
}

_ac_stop_pidfile() {
  local path="$1"
  local label="${2:-process}"
  if [[ ! -f "$path" ]]; then
    return 0
  fi
  local pid
  pid="$(tr -d '[:space:]' <"$path" || true)"
  if [[ -z "$pid" ]]; then
    rm -f "$path"
    return 0
  fi
  if kill -0 "$pid" 2>/dev/null; then
    echo "[stop] 停止 $label PID=$pid"
    kill "$pid" 2>/dev/null || true
    sleep 1
    if kill -0 "$pid" 2>/dev/null; then
      kill -9 "$pid" 2>/dev/null || true
    fi
  else
    echo "[stop] $label 进程不存在 PID=$pid"
  fi
  rm -f "$path"
}

_ac_stop_all_local() {
  local dir root_legacy
  dir="$(_ac_data_dir)"
  root_legacy="${1:-}"
  _ac_stop_pidfile "$dir/node-agent.pid" "Node Agent"
  _ac_stop_pidfile "$dir/core.pid" "Core"
  _ac_stop_pidfile "$dir/sidecar.pid" "sidecar(兼容)"
  _ac_stop_pidfile "$dir/agentcenter.pid" "agentcenter(兼容)"
  if [[ -n "$root_legacy" && -f "$root_legacy/logs/agentcenter.pid" ]]; then
    _ac_stop_pidfile "$root_legacy/logs/agentcenter.pid" "legacy logs pid"
  fi
}
