#!/usr/bin/env bash
# Open docs/tour in a browser (WSL-friendly).
# Serves docs/ over HTTP so ../assets images resolve (file:// on UNC is flaky).
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
echo "[docs-tour] stop with: kill \$(cat $PIDFILE) 2>/dev/null"

opened=0
if command -v wslview >/dev/null 2>&1 && wslview "$URL" >/dev/null 2>&1; then
  opened=1
elif can_run_win /mnt/c/Windows/System32/cmd.exe; then
  /mnt/c/Windows/System32/cmd.exe /c start "" "$URL" >/dev/null 2>&1 && opened=1
elif can_run_win /mnt/c/Windows/system32/cmd.exe; then
  /mnt/c/Windows/system32/cmd.exe /c start "" "$URL" >/dev/null 2>&1 && opened=1
fi

# Direct browser exe also needs the same PE interop; try anyway.
if [[ "$opened" -eq 0 ]]; then
  for browser in \
    "/mnt/c/Program Files/Google/Chrome/Application/chrome.exe" \
    "/mnt/c/Program Files/Microsoft/Edge/Application/msedge.exe" \
    "/mnt/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"
  do
    if [[ -x "$browser" ]] && "$browser" "$URL" >/dev/null 2>&1; then
      opened=1
      break
    fi
  done
fi

if [[ "$opened" -eq 1 ]]; then
  echo "[docs-tour] opened in browser"
  exit 0
fi

write_shortcut 2>/dev/null || true

echo ""
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
echo ""
