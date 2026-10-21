#!/usr/bin/env python3
"""Browse, read and write the PickLine OPC UA address space.

This is a dependency-light alternative to UaExpert for macOS and Raspberry Pi
(which have no UaExpert build). It uses only `asyncua`, which the bridge
already requires.

Usage:
    python3 opcua/opcua_browse.py                       # dump full tree + values
    python3 opcua/opcua_browse.py --read Status/state
    python3 opcua/opcua_browse.py --write Settings/gap 2.5
    python3 opcua/opcua_browse.py --write-bool Commands/take_a true

    OPCUA_ENDPOINT=opc.tcp://192.168.50.2:4840 python3 opcua/opcua_browse.py
"""
import argparse
import asyncio
import os

from asyncua import Client, ua

ENDPOINT = os.environ.get("OPCUA_ENDPOINT", "opc.tcp://localhost:4840")


async def find_by_path(root, path):
    """Resolve a '/'-separated browse-name path under the PickLine root."""
    node = root
    for part in [p for p in path.split("/") if p]:
        match = None
        for child in await node.get_children():
            bn = await child.read_browse_name()
            if bn.Name == part:
                match = child
                break
        if match is None:
            raise KeyError("node not found: %r" % part)
        node = match
    return node


async def dump(node, indent=0):
    for child in await node.get_children():
        bn = await child.read_browse_name()
        cls = await child.read_node_class()
        line = "  " * indent + "- " + bn.Name
        if cls == ua.NodeClass.Variable:
            try:
                line += " = %r" % (await child.read_value(),)
            except Exception as exc:  # noqa: BLE001
                line += " (unreadable: %s)" % exc
        print(line)
        if cls == ua.NodeClass.Object:
            await dump(child, indent + 1)


def _coerce(text):
    for cast in (int, float):
        try:
            return cast(text)
        except ValueError:
            continue
    lowered = text.lower()
    if lowered in ("true", "false"):
        return lowered == "true"
    return text


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--read", metavar="PATH")
    parser.add_argument("--write", nargs=2, metavar=("PATH", "VALUE"))
    parser.add_argument("--write-bool", nargs=2, metavar=("PATH", "TRUE|FALSE"))
    args = parser.parse_args()

    client = Client(url=ENDPOINT)
    await client.connect()
    try:
        root = await client.get_objects_node().get_child(["2:PickLine"])
        if args.read:
            node = await find_by_path(root, args.read)
            print("%s = %r" % (args.read, await node.read_value()))
        elif args.write:
            node = await find_by_path(root, args.write[0])
            await node.write_value(_coerce(args.write[1]))
            print("%s -> %r (read back %r)" % (
                args.write[0], _coerce(args.write[1]), await node.read_value()))
        elif args.write_bool:
            node = await find_by_path(root, args.write_bool[0])
            value = args.write_bool[1].lower() in ("true", "1")
            await node.write_value(value)
            print("%s -> %r (read back %r)" % (
                args.write_bool[0], value, await node.read_value()))
        else:
            print("PickLine OPC UA tree (browse names):")
            await dump(root)
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
