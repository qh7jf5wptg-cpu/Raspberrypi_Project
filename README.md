# Raspberry Pi Project

Two connected projects that form a bidirectional digital twin of a Raspberry Pi:

- **RaspberrypiLED** — a Qt 6 Quick (QML + C++) application that reads the Pi's
  CPU temperature and drives its onboard LED. It publishes its state and
  receives commands over MQTT using `libmosquitto`.
- **digital-twin** — a Blender scene plus Python scripts that mirror the Pi's
  live state over MQTT (temperature text, heat bar, spinning rotor, LED color)
  and send control commands back to it.

See each folder's README for setup and usage.
