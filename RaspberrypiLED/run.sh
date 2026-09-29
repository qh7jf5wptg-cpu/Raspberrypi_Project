#!/usr/bin/env bash
# Run the RaspberrypiLED app, publishing MQTT to the Mac broker.
# Usage:  ./run.sh            (uses 192.168.50.1)
#         MQTT_BROKER=1.2.3.4 ./run.sh   (override broker)
set -e
cd "$(dirname "$0")"
MQTT_BROKER="${MQTT_BROKER:-192.168.50.1}"
export MQTT_BROKER
exec ./build/appRaspberrypiLED "$@"
