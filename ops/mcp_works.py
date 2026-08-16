#!/usr/bin/env python3
"""Exercise every branch of the MCP endpoint against a running service.

Written 2026-08-16 with the endpoint itself. The MCP surface has no reader
inside this repository: if it breaks, no page looks wrong and no test goes red
-- an agent's client fails to connect, once, somewhere else, and never comes
back. That is the shape this repo keeps warning about, so the promise is
checked by making the calls rather than by reading the source.

Every branch is exercised, not just the happy one. A checker that only proves
the good path cannot tell "the tool works" from "the tool returns something".

Exit 0 all branches behave, 1 a branch is wrong, 2 could not tell.
"""
import json
import os
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("MCP_BASE", "https://echorune.net")


def rpc(method, params=None, rid=1):
    body = json.dumps({"jsonrpc": "2.0", "id": rid, "method": method,
                       **({"params": params} if params else {})}).encode()
    req = urllib.request.Request(BASE + "/mcp", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=45) as r:
        raw = r.read()
        return r.status, (json.loads(raw) if raw else None)


def main():
    checks, bad = [], []

    def check(name, fn):
        try:
            ok, detail = fn()
        except (urllib.error.URLError, OSError, ValueError) as e:
            print("  ??? %-34s %s" % (name, e))
            bad.append(name)
            return
        print("  %-3s %-34s %s" % ("ok" if ok else "BAD", name, detail))
        checks.append(ok)
        if not ok:
            bad.append(name)

    print("MCP endpoint at %s/mcp\n" % BASE)

    def initialize():
        _, d = rpc("initialize", {})
        r = (d or {}).get("result", {})
        return (bool(r.get("protocolVersion")) and "tools" in r.get("capabilities", {}),
                "protocol %s" % r.get("protocolVersion"))

    def tools_list():
        _, d = rpc("tools/list")
        tools = (d or {}).get("result", {}).get("tools", [])
        names = [t.get("name") for t in tools]
        schema_ok = all("inputSchema" in t and t.get("description") for t in tools)
        return (bool(names) and schema_ok, "tools=%s" % names)

    def call_place():
        _, d = rpc("tools/call", {"name": "get_weather",
                                  "arguments": {"place": "zurich"}})
        r = (d or {}).get("result", {})
        text = (r.get("content") or [{}])[0].get("text", "")
        # A weather scene, not merely a 200 with prose in it. Whether a radar
        # map came with it is reported but NOT failed on: upstream is allowed
        # to have no frames, and a checker that reddens for that would be
        # reporting the weather rather than the endpoint. The distinction is
        # printed because a mapless scene once made this look like a product
        # bug when it was the test instance missing RUNEMAP_SECOND_SOURCE.
        mapped = "legend:" in text or "图例:" in text
        return (not r.get("isError") and "weather scene" in text and len(text) > 400,
                "%d chars, radar map %s" % (len(text), "present" if mapped else "absent"))

    def call_missing_arg():
        """The wrong-argument path must be a tool error, not a transport error,
        and must not look like success."""
        _, d = rpc("tools/call", {"name": "get_weather", "arguments": {}})
        r = (d or {}).get("result", {})
        return (r.get("isError") is True, "isError=%s" % r.get("isError"))

    def unknown_method():
        _, d = rpc("nonexistent/method")
        return ((d or {}).get("error", {}).get("code") == -32601,
                "code=%s" % (d or {}).get("error", {}).get("code"))

    def unknown_tool():
        """Asking for a tool this server does not offer must fail. Without
        this, renaming the advertised tool leaves every other check green --
        which is exactly how the missing name validation was found."""
        _, d = rpc("tools/call", {"name": "definitely_not_a_tool",
                                  "arguments": {"place": "zurich"}})
        r = (d or {}).get("result", {})
        return (r.get("isError") is True, "isError=%s" % r.get("isError"))

    check("initialize", initialize)
    check("tools/list carries a schema", tools_list)
    check("tools/call returns a scene", call_place)
    check("missing argument is a tool error", call_missing_arg)
    check("unknown tool name is refused", unknown_tool)
    check("unknown method is -32601", unknown_method)

    if not checks:
        print("\nNO-CONTACT could not reach the endpoint at all -- this is "
              "'I cannot tell', not 'it is broken'")
        return 2
    if bad:
        print("\nFAILED: %s" % ", ".join(bad))
        return 1
    print("\nOK every branch behaves")
    return 0


if __name__ == "__main__":
    sys.exit(main())
