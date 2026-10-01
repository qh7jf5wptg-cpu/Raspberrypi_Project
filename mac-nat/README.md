# Pi internet sharing (Mac helper)

The Pi is connected **directly to the Mac with an Ethernet cable** — there is no
router anywhere in that link:

```
   Wi-Fi router                             MacBook
      192.168.3.1  <- - - - - - - - - ->   en0 192.168.3.3
                                            |
                                            |  en8 192.168.50.1
                                            |  Ethernet cable
                                            |
                                         Pi eth0 192.168.50.2
```

The Mac is the Pi's only way out to the internet. That means the Mac has to
forward the Pi's packets and hide them behind its own Wi-Fi address. macOS
forgets both of these on every reboot or Wi-Fi change, and the symptom is
confusing:

- `ping 192.168.50.2` still works (local link is fine)
- `ssh pi@192.168.50.2` still works
- but the Pi has **no internet**, so it disappears from
  [connect.raspberrypi.com](https://connect.raspberrypi.com)

This folder fixes that permanently.

## Install (once)

```sh
cd ~/Documents/ChatGPT/Raspberrypi_Project/mac-nat
sudo sh install.sh
```

It installs a small script at `/usr/local/libexec/pi-nat.sh` and a launch
daemon at `/Library/LaunchDaemons/com.kjde.pi-nat.plist`, then applies the
settings immediately — the Pi gets its internet back without a reboot.

## If the Pi ever goes offline again

```sh
sudo /usr/local/libexec/pi-nat.sh
```

The script is safe to run repeatedly: it only changes something when it is
actually wrong, and it looks up the Mac's internet interface by itself, so it
keeps working when you join a different Wi-Fi network.

## Check it

```sh
sysctl net.inet.ip.forwarding     # should print: 1
cat /etc/pf-pi-nat.conf           # should show:  nat on en0 from 192.168.50.0/24 ...
tail -20 /var/log/pi-nat.log      # what the helper did last
```

Then on the Pi:

```sh
ping -c 2 1.1.1.1
rpi-connect status
```

## Removing it

```sh
sudo launchctl bootout system /Library/LaunchDaemons/com.kjde.pi-nat.plist
sudo rm /Library/LaunchDaemons/com.kjde.pi-nat.plist /usr/local/libexec/pi-nat.sh
sudo sysctl -w net.inet.ip.forwarding=0
sudo pfctl -d -f /etc/pf.conf
```
