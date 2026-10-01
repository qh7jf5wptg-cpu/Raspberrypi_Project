#!/bin/sh
# Give the Raspberry Pi its internet connection.
#
# The Pi is plugged straight into the Mac with an Ethernet cable, so there is
# no router in between:
#
#     Mac  en8 = 192.168.50.1   <-- cable -->   Pi  eth0 = 192.168.50.2
#
# The Pi uses the Mac as its default gateway, so the Mac has to (1) forward
# those packets and (2) hide them behind the Mac's own Wi-Fi address with NAT.
# Without this the Pi still pings and still accepts SSH, but has no internet --
# which also drops it off connect.raspberrypi.com.
#
# This script is safe to run over and over: it only changes things when they
# are actually wrong. It is installed as a launch daemon so it re-applies
# itself at boot and whenever the Mac changes Wi-Fi network.
set -u

PI_SUBNET="192.168.50.0/24"
RULES="/etc/pf-pi-nat.conf"
LOG="/var/log/pi-nat.log"

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >> "$LOG"
}

# Which interface is the Mac using for its own internet? (usually en0 = Wi-Fi)
UPLINK=$(route -n get default 2>/dev/null | awk '/interface:/{print $2}')
if [ -z "${UPLINK:-}" ]; then
    # No internet yet (e.g. right after boot, before Wi-Fi is up).
    # Say nothing and let the next run handle it.
    exit 0
fi

# 1. let the Mac forward packets between the cable and the internet
if [ "$(sysctl -n net.inet.ip.forwarding)" != "1" ]; then
    sysctl -w net.inet.ip.forwarding=1 >/dev/null
    log "enabled IP forwarding"
fi

# 2. rewrite the Pi's traffic so it leaves through the Mac's Wi-Fi address
WANT="nat on $UPLINK from $PI_SUBNET to any -> ($UPLINK)"
if [ ! -f "$RULES" ] || ! grep -qF "$WANT" "$RULES"; then
    printf '%s\n' "$WANT" > "$RULES"
    /sbin/pfctl -e -f "$RULES" 2>/dev/null || /sbin/pfctl -f "$RULES"
    log "loaded NAT rule: $WANT"
fi

exit 0
