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

# The target comes from the environment, not from argv. A positional argument
# used to be accepted and ignored, so `mcp_works.py http://127.0.0.1:8899`
# silently checked PRODUCTION -- which is how a deliberately broken build
# reported "ok" while I was firing it, and I nearly recorded a check as proven
# when it had never been pointed at the thing under test. Refuse instead: the
# wrong target is not a smaller mistake than a wrong answer, it is the same
# mistake with a friendlier face.
if len(sys.argv) > 1:
    raise SystemExit("usage: MCP_BASE=<url> %s  (the target is an env var; a "
                     "positional argument was silently ignored before, which "
                     "pointed firings at production)" % os.path.basename(sys.argv[0]))


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

    def negotiates_version():
        """The version a client asks for comes back, when we speak it.

        Before 2026-08-16 this endpoint answered 2025-06-18 to everyone,
        ignoring the request entirely. Nothing went red, because nothing was
        looking: a promise made to clients that no check reads is a promise
        that quietly expires.

        Two directions, because a server that echoes ANY string a client sends
        would pass a one-sided version of this test while claiming to speak
        specs that do not exist.
        """
        _, d = rpc("initialize", {"protocolVersion": "2026-07-28"})
        got = (d or {}).get("result", {}).get("protocolVersion")
        _, d2 = rpc("initialize", {"protocolVersion": "1999-01-01"})
        bogus = (d2 or {}).get("result", {}).get("protocolVersion")
        return (got == "2026-07-28" and bogus != "1999-01-01",
                "asked 2026-07-28 got %s; asked nonsense got %s" % (got, bogus))

    def tool_says_what_it_does():
        """Annotations tell a caller it may retry without asking permission.

        Hints, per the spec -- but their absence makes a careful caller treat a
        weather lookup like a bank transfer, so losing them silently is a real
        regression in how usable this is.
        """
        _, d = rpc("tools/list")
        tools = (d or {}).get("result", {}).get("tools", [])
        ann = (tools[0].get("annotations") or {}) if tools else {}
        return (ann.get("readOnlyHint") is True
                and ann.get("destructiveHint") is False, "annotations=%s" % ann)

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
    check("negotiates protocol version", negotiates_version)
    check("tool declares read-only/safe", tool_says_what_it_does)
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
