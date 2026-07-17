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
    status=$?
    if [ "$status" -ne 0 ]; then
        for log in "$tmp/stderr.log" "$tmp/software.stderr.log"; do
            [ ! -s "$log" ] || { echo "--- $log" >&2; cat "$log" >&2; }
        done
    fi
    [ -z "$app_pid" ] || kill "$app_pid" 2>/dev/null || true
    kill "$xvfb_pid" 2>/dev/null || true
    wait "$xvfb_pid" 2>/dev/null || true
    rm -rf "$tmp"
    return "$status"
}
trap cleanup EXIT INT TERM

sleep 0.2
DISPLAY="$display" ./files/bin/msys-settings-lvgl \
    --snapshot tests/lvgl_snapshot.txt --run-ms 1200 \
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
printf '%s\n' "$identity" | grep -q 'org.msys.settings:main'

kill -0 "$app_pid"

wait "$app_pid"
app_pid=

DISPLAY="$display" ./files/bin/msys-settings-lvgl \
    --mode software-center --ui files/share/ui/software-center.xml \
    --snapshot tests/lvgl_software_snapshot.txt --run-ms 1200 \
    >"$tmp/software.stdout.log" 2>"$tmp/software.stderr.log" &
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
[ -n "$window" ] || { echo "settings-lvgl-probe: software center window missing" >&2; exit 1; }
identity=$(DISPLAY="$display" xprop -id "$window" \
    _MSYS_APP_ID _MSYS_COMPONENT_ID _MSYS_WINDOW_ROLE)
printf '%s\n' "$identity" | grep -q 'org.msys.software-center'
printf '%s\n' "$identity" | grep -q 'org.msys.settings:software-center'
grep -q 'software-page=apps' "$tmp/software.stderr.log"
kill -0 "$app_pid"
wait "$app_pid"
app_pid=
echo "settings-lvgl-probe: ok"
