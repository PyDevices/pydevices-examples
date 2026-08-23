#!/bin/bash
# Legacy x11grab recording (desktop capture). Prefer tools/record_win.sh for frame capture.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PKG_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SRC_DIR="$(cd "$PKG_DIR/../.." && pwd)"
REPO_ROOT="$(cd "$SRC_DIR/.." && pwd)"
GAME_SCRIPT="$PKG_DIR/tower_climb.py"
PYTHON="${REPO_ROOT}/.venv/bin/python"

OUT="${TOWER_CLIMB_VIDEO:-/opt/cursor/artifacts/tower-climb-vertical-platformer.mp4}"
TRACE="${TOWER_CLIMB_TRACE:-$PKG_DIR/trace/record.jsonl}"
DURATION="${TOWER_CLIMB_RECORD_SECONDS:-18}"
mkdir -p "$(dirname "$OUT")" "$(dirname "$TRACE")"
rm -f "$TRACE"

find_win() {
  DISPLAY=:1 xwininfo -root -tree 2>/dev/null | rg "tower_climb/tower_climb\.py" | head -1 \
    | sed -E 's/^[[:space:]]*(0x[0-9a-f]+).*/\1/'
}

win_geom() {
  DISPLAY=:1 xwininfo -id "$1" 2>/dev/null \
    | awk '/Absolute upper-left X:|Absolute upper-left Y:|Width:|Height:/ {print $NF}'
}

SESSION="tower-vid"
tmux -f /exec-daemon/tmux.portal.conf kill-session -t "$SESSION" 2>/dev/null || true
tmux -f /exec-daemon/tmux.portal.conf new-session -d -s "$SESSION" -c "$SRC_DIR" -- "${SHELL:-zsh}" -l
tmux -f /exec-daemon/tmux.portal.conf send-keys -t "$SESSION:0.0" \
  "DISPLAY=:1 PYTHONPATH=lib $PYTHON $GAME_SCRIPT --record --trace $TRACE" C-m

WIN=""
for _ in $(seq 1 50); do
  WIN=$(find_win || true)
  [ -n "$WIN" ] && break
  sleep 0.2
done

if [ -z "$WIN" ]; then
  echo "window not found" >&2
  tmux -f /exec-daemon/tmux.portal.conf capture-pane -t "$SESSION:0.0" -p | tail -10 >&2
  exit 1
fi

read -r X Y W H <<<"$(win_geom "$WIN" | tr '\n' ' ')"
echo "WIN=$WIN ${W}x${H} at ${X},${Y}"

sleep 1.0

ffmpeg -y -f x11grab -draw_mouse 0 -framerate 24 \
  -video_size "${W}x${H}" -i ":1+${X},${Y}" \
  -t "$DURATION" -c:v libx264 -pix_fmt yuv420p "$OUT" &
FFPID=$!

wait "$FFPID"
ls -lh "$OUT"

if [ -f "$TRACE" ]; then
  echo "TRACE=$TRACE ($(wc -l < "$TRACE") lines)"
  "$PYTHON" - <<'PY' "$TRACE"
import json, sys
path = sys.argv[1]
ys = []
won = False
for line in open(path, encoding="utf-8"):
    d = json.loads(line)
    if d["kind"] == "frame":
        ys.append(d["player"]["y"])
    if d["kind"] == "win":
        won = True
if ys:
    print(f"trace ymin={min(ys):.1f} ymax={max(ys):.1f} frames={len(ys)} won={won}")
else:
    print("trace has no frame records")
PY
fi

tmux -f /exec-daemon/tmux.portal.conf kill-session -t "$SESSION" 2>/dev/null || true
