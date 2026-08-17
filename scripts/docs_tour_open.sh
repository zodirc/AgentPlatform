#!/usr/bin/env bash
# Open docs/tour in a browser. Serves docs/ over HTTP so ../assets images resolve
# (file:// on UNC / remote paths is flaky).
# Native Linux: xdg-open / firefox on the current graphical session.
# WSL: Windows browser via interop (cmd.exe / chrome.exe).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DOCS="$ROOT/docs"
PORT="${DOCS_TOUR_PORT:-8765}"
URL="http://127.0.0.1:${PORT}/tour/"
PIDFILE="${TMPDIR:-/tmp}/agentplatform-docs-tour.pid"
LOGFILE="${TMPDIR:-/tmp}/agentplatform-docs-tour.log"
SHORTCUT="/mnt/c/Users/Public/Desktop/AgentPlatform-Docs-Tour.url"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 required" >&2
  exit 1
fi

is_wsl() {
  [[ -n "${WSL_DISTRO_NAME:-}" || -n "${WSL_INTEROP:-}" ]] && return 0
  [[ -e /proc/sys/fs/binfmt_misc/WSLInterop ]] && return 0
  grep -qiE 'microsoft|wsl' /proc/version 2>/dev/null && return 0
  return 1
}

# Cursor / SSH often have no DISPLAY even when the same user is on GNOME.
inherit_graphical_session() {
  [[ -n "${DISPLAY:-}" || -n "${WAYLAND_DISPLAY:-}" ]] && return 0
  local uid runtime
  uid="$(id -u)"
  runtime="/run/user/${uid}"
  if [[ -S "${runtime}/wayland-0" ]]; then
    export WAYLAND_DISPLAY=wayland-0
  elif [[ -S "${runtime}/wayland-1" ]]; then
    export WAYLAND_DISPLAY=wayland-1
  fi
  if [[ -S /tmp/.X11-unix/X0 ]]; then
    export DISPLAY=:0
  fi
  if [[ -z "${XDG_RUNTIME_DIR:-}" && -d "$runtime" ]]; then
    export XDG_RUNTIME_DIR="$runtime"
  fi
  if [[ -z "${DBUS_SESSION_BUS_ADDRESS:-}" && -S "${runtime}/bus" ]]; then
    export DBUS_SESSION_BUS_ADDRESS="unix:path=${runtime}/bus"
  fi
}

try_open() {
  local bin="$1"
  shift
  command -v "$bin" >/dev/null 2>&1 || return 1
  if command -v timeout >/dev/null 2>&1; then
    timeout 5 "$bin" "$@" >/dev/null 2>&1
  else
    "$bin" "$@" >/dev/null 2>&1
  fi
}

open_linux_browser() {
  inherit_graphical_session
  if [[ -z "${DISPLAY:-}" && -z "${WAYLAND_DISPLAY:-}" ]]; then
    return 1
  fi
  if [[ -n "${BROWSER:-}" ]]; then
    try_open "$BROWSER" "$URL" && return 0
  fi
  try_open xdg-open "$URL" && return 0
  try_open gio open "$URL" && return 0
  for bin in firefox google-chrome chromium-browser chromium; do
    try_open "$bin" "$URL" && return 0
  done
  return 1
}

can_run_win() {
  local bin="$1"
  [[ -x "$bin" ]] || return 1
  # Broken WSL interop → "cannot execute binary file: Exec format error"
  "$bin" /c "exit 0" >/dev/null 2>&1
}

write_shortcut() {
  mkdir -p "$(dirname "$SHORTCUT")" 2>/dev/null || true
  cat >"$SHORTCUT" <<EOF
[InternetShortcut]
URL=${URL}
EOF
}

open_windows_browser() {
  if command -v wslview >/dev/null 2>&1 && wslview "$URL" >/dev/null 2>&1; then
    return 0
  fi
  if can_run_win /mnt/c/Windows/System32/cmd.exe; then
    /mnt/c/Windows/System32/cmd.exe /c start "" "$URL" >/dev/null 2>&1 && return 0
  fi
  if can_run_win /mnt/c/Windows/system32/cmd.exe; then
    /mnt/c/Windows/system32/cmd.exe /c start "" "$URL" >/dev/null 2>&1 && return 0
  fi
  local browser
  for browser in \
    "/mnt/c/Program Files/Google/Chrome/Application/chrome.exe" \
    "/mnt/c/Program Files/Microsoft/Edge/Application/msedge.exe" \
    "/mnt/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"
  do
    if [[ -x "$browser" ]] && "$browser" "$URL" >/dev/null 2>&1; then
      return 0
    fi
  done
  return 1
}

cd "$DOCS"
if ! curl -fsS --max-time 0.3 "$URL" >/dev/null 2>&1; then
  python3 -m http.server "$PORT" --bind 127.0.0.1 >"$LOGFILE" 2>&1 &
  echo $! >"$PIDFILE"
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    curl -fsS --max-time 0.3 "$URL" >/dev/null 2>&1 && break
    sleep 0.15
  done
fi

echo "[docs-tour] serving  $URL"
if [[ -f "$PIDFILE" ]]; then
  echo "[docs-tour] stop with: kill \$(cat $PIDFILE) 2>/dev/null"
fi

opened=0
if is_wsl; then
  open_windows_browser && opened=1
else
  open_linux_browser && opened=1
fi

if [[ "$opened" -eq 1 ]]; then
  echo "[docs-tour] opened in browser"
  exit 0
fi

echo ""
if is_wsl; then
  write_shortcut 2>/dev/null || true
  echo "[docs-tour] 自动弹窗失败：本机 WSL 缺少 WSLInterop（无法执行 .exe）。"
  echo "[docs-tour] 服务已就绪，任选其一："
  echo ""
  echo "  1) 在 Windows 浏览器地址栏粘贴："
  echo "       $URL"
  if [[ -f "$SHORTCUT" ]]; then
    echo ""
    echo "  2) 双击 Windows 桌面上的快捷方式："
    echo "       AgentPlatform-Docs-Tour.url"
    echo "     （Public Desktop · 所有用户桌面可见）"
  fi
  echo ""
  echo "  3)（可选）修复互操作后再 make docs-tour："
  echo "       sudo sh -c 'echo :WSLInterop:M::MZ::/init:PF > /proc/sys/fs/binfmt_misc/register'"
  echo "       # 若仍无效：在 Windows PowerShell 执行 wsl --shutdown 后重开终端"
else
  echo "[docs-tour] 未能自动打开浏览器（当前终端没有图形会话，或 xdg-open 失败）。"
  echo "[docs-tour] 服务已就绪，在浏览器地址栏打开："
  echo "       $URL"
fi
echo ""
