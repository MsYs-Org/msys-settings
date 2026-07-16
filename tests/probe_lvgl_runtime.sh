#!/bin/sh
set -eu

for command in Xvfb xwininfo xprop cc; do
    command -v "$command" >/dev/null 2>&1 || {
        echo "settings-lvgl-probe: missing optional command: $command" >&2
        exit 77
    }
done

display=:96
tmp=${TMPDIR:-/tmp}/msys-settings-lvgl.$$
mkdir -p "$tmp"
Xvfb "$display" -screen 0 320x480x24 -nolisten tcp >"$tmp/xvfb.log" 2>&1 &
xvfb_pid=$!
app_pid=
cleanup() {
    [ -z "$app_pid" ] || kill "$app_pid" 2>/dev/null || true
    kill "$xvfb_pid" 2>/dev/null || true
    wait "$xvfb_pid" 2>/dev/null || true
    rm -rf "$tmp"
}
trap cleanup EXIT INT TERM

sleep 0.2
DISPLAY="$display" ./files/bin/msys-settings-lvgl \
    --snapshot tests/lvgl_snapshot.txt --run-ms 6000 \
    >"$tmp/stdout.log" 2>"$tmp/stderr.log" &
app_pid=$!

window=
attempt=0
while [ "$attempt" -lt 40 ]; do
    window=$(DISPLAY="$display" xwininfo -root -tree 2>/dev/null |
        awk '/MSYS/{print $1; exit}')
    [ -z "$window" ] || break
    attempt=$((attempt + 1))
    sleep 0.05
done
[ -n "$window" ] || { echo "settings-lvgl-probe: window missing" >&2; exit 1; }

identity=$(DISPLAY="$display" xprop -id "$window" \
    _MSYS_APP_ID _MSYS_COMPONENT_ID _MSYS_WINDOW_ROLE)
printf '%s\n' "$identity" | grep -q 'org.msys.settings'
printf '%s\n' "$identity" | grep -q 'org.msys.settings:main-lvgl'

# First two-column card is Wi-Fi. A 60-line Xlib helper sends ordinary core
# pointer XEvents, so the probe does not install or require xdotool/XTest.
cc tests/xsend_touch.c -lX11 -o "$tmp/xsend-touch"
DISPLAY="$display" "$tmp/xsend-touch" "$window"
sleep 0.2
grep -q 'page=wifi' "$tmp/stderr.log"
kill -0 "$app_pid"

wait "$app_pid"
app_pid=
echo "settings-lvgl-probe: ok"
