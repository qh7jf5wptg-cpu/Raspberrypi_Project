#!/bin/bash
# Supervise the PickLine plant and soft PLC so they auto-restart if they crash
# and survive SSH disconnects. Run on the Pi with:
#
#   MQTT_BROKER=192.168.50.1 nohup ./supervise.sh >/dev/null 2>&1 &
#
# Logs are written next to this script in plant.log and plc.log.
set -u
cd "$(dirname "$0")"
export MQTT_BROKER="${MQTT_BROKER:-localhost}"

run_forever() {
    local name="$1"; shift
    echo "$(date '+%F %T') starting $name"
    while true; do
        "$@" >>"$name.log" 2>&1
        echo "$(date '+%F %T') $name exited rc=$?; restarting in 2s" >>"$name.log"
        sleep 2
    done
}

run_forever plant python3 plant/pickline_plant.py &
run_forever plc   python3 plc/pickline_plc.py &
wait
