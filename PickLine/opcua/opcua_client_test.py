#!/usr/bin/env python3
"""Quick OPC UA client smoke test for the PickLine bridge.

Connect, browse the PickLine node tree, read a few tags, write a setting and
trigger a command. Run while opcua_server.py (and the plant + PLC) are running.

    pip install asyncua
    python3 opcua/opcua_client_test.py
    OPCUA_ENDPOINT=opc.tcp://192.168.50.2:4840 python3 opcua/opcua_client_test.py
"""
import asyncio
import os

from asyncua import Client

ENDPOINT = os.environ.get("OPCUA_ENDPOINT", "opc.tcp://localhost:4840")


async def main():
    client = Client(url=ENDPOINT)
    await client.connect()

    root = await client.get_objects_node().get_child(["2:PickLine"])
    print("PickLine children:")
    for child in await root.get_children():
        print("  -", (await child.read_browse_name()).Name)

    state = await root.get_child(["2:Status", "2:state"])
    mode = await root.get_child(["2:Status", "2:mode"])
    a_count = await root.get_child(["2:FillA", "2:count"])
    b_count = await root.get_child(["2:FillB", "2:count"])
    print("state=%s mode=%s FillA.count=%s FillB.count=%s" % (
        await state.read_value(), await mode.read_value(),
        await a_count.read_value(), await b_count.read_value()))

    gap = await root.get_child(["2:Settings", "2:gap"])
    await gap.write_value(2.5)
    print("set Settings.gap =", await gap.read_value())

    take_a = await root.get_child(["2:Commands", "2:take_a"])
    await take_a.write_value(True)
    await asyncio.sleep(1.0)
    print("Commands.take_a after trigger =", await take_a.read_value(), "(False = handled)")

    await client.disconnect()
    print("OK")


if __name__ == "__main__":
    asyncio.run(main())
