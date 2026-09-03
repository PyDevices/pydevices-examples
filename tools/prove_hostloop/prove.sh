#!/usr/bin/env bash
# Prove that appdev.App keeps itself alive with no trailing app.run(),
# on every interpreter PyDevices targets.
cd "$(dirname "$0")"
PD=${PD:-/home/brad/gh/pydevices/pydevices}
BIN=${BIN:-$PD/bin}
export MICROPYPATH=".:$PD/lib:$PD/utils"
export PYTHONPATH=".:$PD/lib:$PD/utils"
# micropython.exe is a Windows binary launched from WSL, so it only sees the
# environment variables named in WSLENV. Without this it never receives
# MICROPYPATH and silently falls back to the installed copy under
# %USERPROFILE%\.micropython\lib -- which is how a stale install masquerades
# as a code failure. The "/l" flag translates the WSL paths for it.
export WSLENV="MICROPYPATH/l"

run() {  # run <label> <cmd...>
    echo
    echo "----- $1"
    shift
    timeout 30 "$@" </dev/null 2>&1 | sed 's/^/    /'
    echo "    [rc=${PIPESTATUS[0]}]"
}

for scenario in noloop async run crash; do
    echo
    echo "=================== $scenario"
    run "CPython / linux"       python3 demo_$scenario.py
    run "MicroPython / linux"   "$BIN/micropython" demo_$scenario.py
    run "MicroPython / windows" "$BIN/micropython.exe" demo_$scenario.py
    run "CircuitPython / unix"  "$BIN/circuitpython" demo_$scenario.py
done

echo
echo "=================== browser (wasm, ambient): host loop outlives the script"
for scenario in noloop async run; do
    run "MicroPython wasm / $scenario" node wasm_host.mjs demo_$scenario.py
done

echo
echo "=================== interactive (-i): REPL owns the loop"
repl_feed() { sleep 0.6; printf 'print("[repl] ticks during REPL:", len(app.ticks))\n'; sleep 0.3; }
echo "----- CPython -i"
repl_feed | timeout 30 python3 -i demo_noloop.py 2>&1 | sed 's/^/    /'
echo "----- MicroPython -i"
repl_feed | timeout 30 "$BIN/micropython" -i demo_noloop.py 2>&1 | sed 's/^/    /'
