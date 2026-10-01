#!/bin/sh
# Install the Pi internet-sharing helper on the Mac.  Run it with sudo:
#
#     cd ~/Documents/ChatGPT/Raspberrypi_Project/mac-nat
#     sudo sh install.sh
#
# It copies two files into place and turns the helper on. It also applies the
# settings right away, so the Pi regains its internet without a reboot.
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
LABEL="/Library/LaunchDaemons/com.kjde.pi-nat.plist"

install -d -m 755 /usr/local/libexec
install -m 755 "$HERE/pi-nat.sh" /usr/local/libexec/pi-nat.sh
install -m 644 -o root -g wheel "$HERE/com.kjde.pi-nat.plist" "$LABEL"

# reload if it was already installed, otherwise start it for the first time
launchctl bootout system "$LABEL" 2>/dev/null || true
launchctl bootstrap system "$LABEL"

# apply immediately and show the result
/usr/local/libexec/pi-nat.sh
echo
echo "Installed. Current state:"
echo -n "  IP forwarding : "; sysctl -n net.inet.ip.forwarding
echo -n "  NAT rule      : "; cat /etc/pf-pi-nat.conf 2>/dev/null || echo "(none)"
