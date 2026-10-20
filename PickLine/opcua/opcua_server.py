#!/usr/bin/env python3
"""OPC UA server bridge for the PickLine cell.

Mirrors the MQTT tag space (pickline/#) as an OPC UA address space so that
industrial clients (TwinCAT, CODESYS, UaExpert, SCADA) can monitor and control
the cell through the standard OPC UA interface.

Run (on the Pi, alongside the soft PLC):
    pip install asyncua
    python3 opcua/opcua_server.py
    MQTT_BROKER=192.168.50.1 OPCUA_ENDPOINT=opc.tcp://0.0.0.0:4840 \
        python3 opcua/opcua_server.py

Endpoint: opc.tcp://0.0.0.0:4840
"""
import asyncio
import os

import paho.mqtt.client as mqtt
from asyncua import Server, ua

BROKER = os.environ.get("MQTT_BROKER", "localhost")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
OPCUA_ENDPOINT = os.environ.get("OPCUA_ENDPOINT", "opc.tcp://0.0.0.0:4840")

# Read-only tags: (folder, browse_name, mqtt_topic_suffix, variant_type)
READ_TAGS = [
    ("Status", "state", "state", ua.VariantType.String),
    ("Status", "mode", "mode", ua.VariantType.String),
    ("Status", "side", "side", ua.VariantType.String),
    ("Status", "route_mode", "route_mode", ua.VariantType.String),
    ("Status", "decision", "decision", ua.VariantType.String),
    ("Status", "alarm", "alarm", ua.VariantType.String),
    ("Status", "paused", "paused", ua.VariantType.Boolean),
    ("Status", "estop", "estop", ua.VariantType.Boolean),
    ("Gantry", "x", "x", ua.VariantType.Double),
    ("Gantry", "y", "y", ua.VariantType.Double),
    ("Gantry", "z", "z", ua.VariantType.Double),
    ("Gantry", "grip", "grip", ua.VariantType.Double),
    ("Gantry", "holding", "holding", ua.VariantType.Boolean),
    ("Conveyor", "belt", "belt", ua.VariantType.Double),
    ("Conveyor", "speed", "speed", ua.VariantType.Double),
    ("Conveyor", "diverter", "diverter", ua.VariantType.Double),
    ("Conveyor", "part_x", "part_x", ua.VariantType.Double),
    ("Conveyor", "part_y", "part_y", ua.VariantType.Double),
    ("Conveyor", "part_on_line", "part_on_line", ua.VariantType.Boolean),
    ("Production", "placed", "placed", ua.VariantType.Int64),
    ("Production", "exited", "exited", ua.VariantType.Int64),
    ("Production", "volume", "volume", ua.VariantType.Double),
    ("Production", "fill_total", "fill/total", ua.VariantType.Double),
    ("FillA", "level", "fill/a/level", ua.VariantType.Double),
    ("FillA", "state", "fill/a/state", ua.VariantType.String),
    ("FillA", "count", "fill/a/count", ua.VariantType.Int64),
    ("FillA", "filled", "fill/a/filled", ua.VariantType.Int64),
    ("FillA", "pickups", "fill/a/pickups", ua.VariantType.Int64),
    ("FillB", "level", "fill/b/level", ua.VariantType.Double),
    ("FillB", "state", "fill/b/state", ua.VariantType.String),
    ("FillB", "count", "fill/b/count", ua.VariantType.Int64),
    ("FillB", "filled", "fill/b/filled", ua.VariantType.Int64),
    ("FillB", "pickups", "fill/b/pickups", ua.VariantType.Int64),
]

# Writable settings: (browse_name, mqtt_topic, variant_type)
WRITE_SETTINGS = [
    ("speed", "pickline/target/speed", ua.VariantType.Double),
    ("volume", "pickline/target/volume", ua.VariantType.Double),
    ("gap", "pickline/command/gap", ua.VariantType.Double),
    ("fill_a_pickups", "pickline/target/fill/a/pickups", ua.VariantType.Int64),
    ("fill_b_pickups", "pickline/target/fill/b/pickups", ua.VariantType.Int64),
    ("mode", "pickline/command/mode", ua.VariantType.String),
    ("route", "pickline/command/route", ua.VariantType.String),
    ("side", "pickline/command/side", ua.VariantType.String),
]

# Writable commands (Boolean, reset after handling): (browse_name, mqtt_topic)
WRITE_COMMANDS = [
    ("start", "pickline/command/start"),
    ("stop", "pickline/command/stop"),
    ("reset", "pickline/command/reset"),
    ("pause", "pickline/command/pause"),
    ("resume", "pickline/command/resume"),
    ("estop", "pickline/command/estop"),
    ("clear_belt", "pickline/command/clear_belt"),
    ("take_a", "pickline/fill/a/take"),
    ("take_b", "pickline/fill/b/take"),
]


def default_value(vtype):
    if vtype == ua.VariantType.Boolean:
        return False
    if vtype in (ua.VariantType.Double, ua.VariantType.Float):
        return 0.0
    if vtype in (ua.VariantType.Int64, ua.VariantType.Int32,
                 ua.VariantType.Int16, ua.VariantType.Byte):
        return 0
    return ""


def convert(payload, vtype):
    """Convert an MQTT string payload to the OPC UA variant type."""
    if vtype == ua.VariantType.Boolean:
        return payload.lower() in ("1", "true", "on", "yes")
    if vtype in (ua.VariantType.Int64, ua.VariantType.Int32,
                 ua.VariantType.Int16, ua.VariantType.Byte):
        try:
            return int(float(payload))
        except ValueError:
            return 0
    if vtype in (ua.VariantType.Double, ua.VariantType.Float):
        try:
            return float(payload)
        except ValueError:
            return 0.0
    return payload


def format_setting(value):
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, float):
        return "%.1f" % value
    return str(value)


class MqttBridge:
    """Thread-safe cache of the latest MQTT tag values."""

    def __init__(self, broker, port):
        self.values = {}
        try:
            self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        except AttributeError:
            self.client = mqtt.Client()
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.connect(broker, port, 60)
        self.client.loop_start()

    def _on_connect(self, client, *_args):
        client.subscribe("pickline/#")

    def _on_message(self, _client, _userdata, msg):
        key = msg.topic[9:] if msg.topic.startswith("pickline/") else msg.topic
        payload = msg.payload.decode("utf-8", "replace").strip()
        self.values[key] = payload

    def publish(self, topic, payload):
        self.client.publish(topic, payload)


async def main():
    server = Server()
    await server.init()
    server.set_endpoint(OPCUA_ENDPOINT)
    server.set_server_name("PickLine OPC UA Server")
    idx = await server.register_namespace("http://pickline.local")

    objects = server.nodes.objects
    root = await objects.add_object(idx, "PickLine")

    # Build the read-only address space.
    nodes = {}       # mqtt suffix -> OPC UA node
    last_written = {}
    folders = {}
    for folder, browse_name, suffix, vtype in READ_TAGS:
        if folder not in folders:
            folders[folder] = await root.add_object(idx, folder)
        node = await folders[folder].add_variable(
            idx, browse_name, default_value(vtype), varianttype=vtype)
        nodes[suffix] = node
        last_written[suffix] = None

    # Commands and settings.
    cmd_folder = await root.add_object(idx, "Commands")
    cmd_nodes = {}
    for browse_name, topic in WRITE_COMMANDS:
        node = await cmd_folder.add_variable(idx, browse_name, False,
                                             varianttype=ua.VariantType.Boolean)
        await node.set_writable()
        cmd_nodes[browse_name] = (node, topic)

    settings_folder = await root.add_object(idx, "Settings")
    setting_nodes = {}
    setting_last = {}
    for browse_name, topic, vtype in WRITE_SETTINGS:
        node = await settings_folder.add_variable(
            idx, browse_name, default_value(vtype), varianttype=vtype)
        await node.set_writable()
        setting_nodes[browse_name] = (node, topic)
        setting_last[browse_name] = None

    # MQTT bridge.
    bridge = MqttBridge(BROKER, MQTT_PORT)

    # Map suffix -> variant type for conversion.
    vtype_by_suffix = {suffix: vtype for _f, _n, suffix, vtype in READ_TAGS}

    async def sync_loop():
        while True:
            await asyncio.sleep(0.2)

            # MQTT -> OPC UA.
            for suffix, node in nodes.items():
                payload = bridge.values.get(suffix)
                if payload is None:
                    continue
                value = convert(payload, vtype_by_suffix[suffix])
                if value != last_written[suffix]:
                    try:
                        await node.write_value(value)
                        last_written[suffix] = value
                    except Exception:
                        pass

            # OPC UA commands -> MQTT.
            for browse_name, (node, topic) in cmd_nodes.items():
                try:
                    if await node.read_value():
                        bridge.publish(topic, "1")
                        await node.write_value(False)
                except Exception:
                    pass

            # OPC UA settings -> MQTT.
            for browse_name, (node, topic) in setting_nodes.items():
                try:
                    value = await node.read_value()
                    if value != setting_last[browse_name]:
                        setting_last[browse_name] = value
                        bridge.publish(topic, format_setting(value))
                except Exception:
                    pass

    print("OPC UA server on %s (broker %s:%d)" % (OPCUA_ENDPOINT, BROKER, MQTT_PORT))
    await server.start()
    try:
        await sync_loop()
    finally:
        await server.stop()


if __name__ == "__main__":
    asyncio.run(main())
