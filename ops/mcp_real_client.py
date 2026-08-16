#!/usr/bin/env python3
"""Connect with the official MCP SDK, not with our own idea of the protocol.

ops/mcp_works.py builds the JSON-RPC by hand. That proves the endpoint answers
the protocol *as this repository understands it* -- our own ruler measuring our
own work, which is the oldest mistake recorded here. This script uses the
`mcp` package, written by someone else against the specification, so a
disagreement between us and the spec shows up as a failure rather than as
agreement.

Kept separate rather than merged: mcp_works.py needs no dependencies and can
run anywhere, while this one needs the SDK installed. Two instruments, two
reaches, and the cheap one must not silently become the only one.

Exit 0 if a real client can list the tool and get a scene, 1 if it cannot,
2 if the SDK is missing -- which is not the same as the server being broken.
"""
import asyncio
import os
import sys

BASE = os.environ.get("MCP_BASE", "https://echorune.net")

try:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client
except ImportError as e:
    print("NO-SDK the mcp package is not installed (%s). This says nothing "
          "about the server." % e)
    sys.exit(2)


async def run():
    async with streamable_http_client(BASE + "/mcp") as (r, w):
        async with ClientSession(r, w) as s:
            init = await s.initialize()
            print("  server   : %s %s" % (init.server_info.name,
                                          init.server_info.version))
            tools = await s.list_tools()
            names = [t.name for t in tools.tools]
            print("  tools    : %s" % names)
            if "get_weather" not in names:
                print("FAILED the advertised tool is missing")
                return 1
            out = await s.call_tool("get_weather", {"place": "zurich"})
            text = out.content[0].text if out.content else ""
            print("  call     : %d chars, is_error=%s" % (len(text), out.is_error))
            if out.is_error or "weather scene" not in text:
                print("FAILED the tool did not return a scene")
                return 1
            print("\nOK a real MCP client can use this server")
            return 0


def main():
    print("MCP client against %s\n" % BASE)
    try:
        return asyncio.run(run())
    except BaseException as err:
        # An unhandled traceback is not a verdict. Separate the two failures
        # that matter: we could not get there at all (network, wrong host,
        # nothing listening) versus we got there and it did not behave. Only
        # the second is evidence about this server.
        def flat(e):
            subs = getattr(e, "exceptions", None)
            return [x for s in subs for x in flat(s)] if subs else [e]
        msgs = [repr(e) for e in flat(err)]
        reach = any(x in " ".join(msgs).lower()
                    for x in ("connect", "resolve", "timeout", "refused",
                              "name or service", "ssl"))
        if reach:
            print("CANNOT-REACH %s/mcp: %s" % (BASE, msgs[0][:160]))
            return 2          # 'I cannot tell', not 'it is broken'
        print("FAILED reached %s/mcp but it did not behave: %s"
              % (BASE, msgs[0][:160]))
        return 1


if __name__ == "__main__":
    sys.exit(main())
