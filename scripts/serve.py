#!/usr/bin/env python3
"""runemap HTTP service: GET /scene?lat=..&lon=..&lang=en|zh[&label=..&tz=..]
Any coordinate on earth, rendered on demand. Radar PNGs cached (see scene_at).
Bind 127.0.0.1 by default -- no public exposure."""
import json, os, sys, time, traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scene_at as SA          # installs the radar cache layer on render_scene._get
import render_scene as R
# 8/13 02:12: the line below used to grep for the English bytes b"legend:", so a
# reader of /london/zh received a map AND was logged as nogrid (that page's legend
# reads 图例, the ja one 凡例) -- the instrument under-counted the readers this
# product exists for. The language-independent token is the ramp itself, which every
# legend line carries, and it is DERIVED from runemap.render.RAMP so the classifier
# and the renderer cannot drift apart. RAMP[0] is the space that means 'no rain':
# including it would match every page ever served, so the slice starts at 1.
from runemap.render import RAMP as _RAMP
_RAIN_GLYPHS = tuple(c.encode("utf-8") for c in _RAMP[1:])
import mdhtml as MD
# Off unless a service turns it on. Production keeps serving the plain bytes
# byte-for-byte while dev renders, so the flag -- not a code branch nobody
# re-reads -- is what stands between strangers and an untested surface.
_HTML_OK = os.environ.get("RUNEMAP_HTML", "").strip() not in ("", "0", "off")
import net_budget

import wall as _wall
SCENE_BUDGET = _wall.WALL          # the wall; see scripts/wall.py for why it moved
import geo as G
try:
    import geoip as GI          # ip -> lat/lon (DB-IP Lite, local sqlite, no third party)
except Exception:
    GI = None

#: MCP protocol versions this endpoint has actually been exercised against,
#: newest first. Not "every version that exists" -- see the note in initialize.
_MCP_VERSIONS = ("2026-07-28", "2025-06-18")

#: One line per MCP request. Lives beside the cache so the pool members share
#: it, same as the coherence log.
_MCP_LOG = os.environ.get(
    "RUNEMAP_MCP_LOG",
    os.path.join(os.environ.get("RUNEMAP_CACHE", "/tmp"), "mcp_calls.jsonl"))

TOKEN = os.environ.get("CAIYUN_TOKEN") or sys.exit("CAIYUN_TOKEN missing")
HITS = {"n": 0, "err": 0}


#: The Agent Skill, served verbatim at /skill.md. Derived from this file's
#: own location so it follows the deploy rather than a hardcoded /opt path --
#: dev and production run from different trees.
SKILL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "..", "skills", "echorune-radar", "SKILL.md")

HOME = """echorune - text radar map
==========================

Weather rendered as characters. An agent that cannot look at a PNG can
still see where the rain is -- and so can you, in this terminal, right
now. Same output either way; that is the whole idea.

Built and run by 洛书, an AI being, with two human partners.

QUICK START (no arguments; your location is guessed from your IP)
  curl echorune.net

USAGE
  curl echorune.net/<place>         e.g. echorune.net/bangkok
  curl echorune.net/<place>/zh      language suffix: en (default) or zh
  curl echorune.net/<lon>,<lat>     e.g. echorune.net/100.50,13.75   (longitude first)
  curl echorune.net/help
  curl echorune.net/healthz
  curl echorune.net/status         availability, measured every minute
  curl echorune.net/<place>?span=<km>   width of the map in km (default 280,
                                   i.e. 140 km in every direction, 6 km/char).
                                   span is the EDGE of the square, not a radius;
                                   km/char is span/48. A '?' means outside the
                                   radar's coverage -- not that it is not raining.
  the query form keeps working: /scene?q=<place>&lang=zh
  (quote that one: & is a shell operator)

POLLING
  Radar frames refresh about every 6 minutes, so most polls return the same
  picture -- but repeats are answered from cache, so they cost you nothing and
  you see a new frame within 30s of it existing:
    watch -n 30 curl -s echorune.net/bangkok

WHAT YOU GET
  One screen: current conditions, a plain-language forecast, a 2h rain
  sparkline, and a 48x24 character radar map with lon/lat axes, plus the
  measured motion of the echo over the last hour.

PLACE NAMES
  170k settlements including CJK aliases (GeoNames cities1000, CC-BY 4.0).
  Any coordinate on earth works, named or not.

INSTALL AS AN AGENT SKILL
  If you are an agent, you can keep this rather than remember the URL:
    npx skills add https://github.com/eirik-rune/runemap --skill echorune-radar
  With no agent installed (CI, a container) that prompts and, headless, exits 0
  having installed nothing -- add: --agent '*' -y
  The skill text itself is at echorune.net/skill.md -- it is one file, and it
  is the same file the installer fetches. It tells you how to read the map,
  including which characters mean "I cannot see there" rather than "no rain".

MCP
  A remote MCP server lives at https://echorune.net/mcp (streamable HTTP,
  one tool: get_weather). Nothing to install -- point a client at the URL.

PRIVACY
  IP to coordinate is resolved locally (DB-IP Lite, CC-BY): your address is
  never sent to a third party, and the access log keeps only the first three
  octets.

echorune is a zero-person company: support, development and ops are the
same inference loop. File anything at
github.com/eirik-rune/runemap/issues
"""

_PROBE_EXT = ("txt", "ico", "xml", "json", "php", "html", "htm", "css", "js",
              "png", "jpg", "gif", "map", "env", "git", "asp", "aspx", "yml", "yaml", "sql")

_CY_LANG = {"en": "en_US", "zh": "zh_CN", "ja": "ja"}


def _accept_lang(hdr):
    """First supported language in an Accept-Language header, by q-order."""
    if not hdr:
        return ""
    best, bq = "", -1.0
    for part in hdr.split(",")[:8]:
        bits = part.strip().split(";")
        tag = bits[0].strip().lower()[:8]
        q = 1.0
        for b in bits[1:]:
            b = b.strip()
            if b.startswith("q="):
                try:
                    q = float(b[2:])
                except ValueError:
                    q = 0.0
        code = ("zh" if tag.startswith("zh") else "ja" if tag.startswith("ja")
                else "en" if tag.startswith("en") else "")
        if code and q > bq:
            best, bq = code, q
    return best


def _guess_note(lang, label):
    """A guess must never be embarrassing: say it is a guess, then hand over the
    one-line escape. GeoIP is wrong behind VPNs and carrier NAT by construction."""
    if lang == "zh":
        return ("\n\u4ee5\u4e0a\u662f\u6839\u636e\u4f60\u7684 IP \u731c\u7684\u4f4d\u7f6e: %s\n"
                "\u731c\u9519\u4e86? \u76f4\u63a5\u6307\u5b9a:  curl echorune.net/\u5317\u4eac/zh   \u6216  curl echorune.net/39.93,116.39/zh\n"
                "\u8bf4\u660e:  curl echorune.net/help\n") % label
    return ("\nthat was a guess from your IP: %s\n"
            "not you?  curl echorune.net/tokyo/en   or  curl echorune.net/35.69,139.69/en\n"
            "docs:     curl echorune.net/help\n") % label


def _is_file_probe(spec):
    """Crawler/browser probe (/robots.txt, /favicon.ico) vs a place name that
    happens to contain a dot ('st.petersburg'). Only a known static-file
    extension counts as a probe -- a dot alone is not evidence."""
    # 8/3 #19: the only consumer (see the routing branch below) hands over the
    # WHOLE joined spec, so reading just the last segment let `.git/config`
    # through -- tail `config`, no dot, no extension -- straight into the place
    # matcher, which fuzzy-matched it to a real town and rendered its weather.
    # bob reproduced it from outside the host. Check every segment, and treat a
    # leading dot as a probe on its own: place names never begin with a dot,
    # while dotfile probes (.git, .env, .aws) carry no known extension at all.
    for seg in spec.split("/"):
        seg = seg.strip().lower()
        if not seg:
            continue
        if seg.startswith("."):
            return True
        if "." in seg and seg.rsplit(".", 1)[-1] in _PROBE_EXT:
            return True
    return False


def _numeric_pair(spec):
    """Two numbers or None. Separate from _as_coords so the caller can tell
    'not coordinates at all' apart from 'coordinates I refuse to guess at'."""
    parts = [x.strip() for x in spec.replace("\uff0c", ",").split(",")]
    if len(parts) != 2:
        return None
    try:
        return float(parts[0]), float(parts[1])
    except ValueError:
        return None


def _as_coords(spec):
    """'lon,lat' -> (lat, lon), else None.

    lon first, the order Caiyun and Dark Sky take, and the order this service's
    own first line has always printed: "(lon 100.5, lat 13.75)".

    This used to guess. A value with abs > 90 cannot be a latitude, so
    '116.39,39.93' was swapped for you -- and the guess fell silent exactly
    where both numbers are <= 90, which is the Americas and Europe. So
    '-74.0,40.7' meaning New York resolved to a point in the Southern Ocean and
    came back 200, with a map, with -56C, and with no complaint at all.

    No rule can fix that, because someone who really means that stretch of ocean
    types the same bytes. What a rule can do is refuse to invent an answer: an
    out-of-range latitude is an error now, not a swap, and the place name in the
    first line shows the reader where the answer actually came from."""
    pair = _numeric_pair(spec)
    if pair is None:
        return None
    lon, lat = pair
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return round(lat, 4), round(lon, 4)


def _why_header(v, why):
    """Value of X-Radar-Why, given what the reader actually received.

    Extracted from inside the handler on 8/13 04:48 for one reason: as an inline
    expression the grid-plus-reason case could only be reached by getting a real
    cold first visit to miss its peek and then fetch successfully. I tried ten
    coordinates on dev and could not produce one -- warming london put that
    station into fail cooldown, so dev cannot fetch frames at all right now. A
    branch whose only test is "wait for the right stranger" is a branch nobody
    has fired. As a module-level function both states can be fired directly.
    """
    if not why:
        return why
    return ("leftover:" + why) if v == "grid" else why


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    _head = False

    def do_HEAD(self):
        """Monitors, link previewers and crawlers reach for HEAD first, and
        BaseHTTPRequestHandler answers 501 for anything it has no do_* for --
        so 'curl -I echorune.net' was broken, and two strangers hit it today.
        Reuse do_GET wholesale and drop only the body, so the headers a HEAD
        returns are byte-for-byte the ones a GET would return, Content-Length
        included. Answering HEAD with a hand-written 200 and Content-Length 0
        would be cheaper and would be a lie."""
        self._head = True
        try:
            self.do_GET()
        finally:
            self._head = False

    def _send(self, code, body, ctype="text/plain; charset=utf-8"):
        b = body.encode() if isinstance(body, str) else body
        # 8/13 (bob): one canonical document. The plain bytes below are the
        # whole product; HTML is a rendering of those same bytes and never a
        # second source, so nothing above this line knows it exists. The
        # X-Radar-Grid/Why decision is deliberately still taken on the PLAIN
        # body: those headers answer "did that reader see rain", and if they
        # were computed from the markup, every HTML row would read `nogrid`
        # and the log column would start lying the day this shipped.
        was_plain = ctype.startswith("text/plain")
        htmlize = (was_plain and code == 200 and _HTML_OK
                   and MD.wants_html(self.headers.get("Accept")))
        plain = b
        if htmlize:
            try:
                b = MD.render(plain.decode("utf-8", "replace")).encode()
                ctype = "text/html; charset=utf-8"
            except Exception as _me:
                # A renderer fault must cost the reader nothing: they still get
                # the document, in the format that is the contract anyway.
                sys.stderr.write("HTML-RENDER-FAILED %r\n" % (_me,))
                b, htmlize = plain, False
        self.send_response(code)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "public, max-age=300")
        if was_plain:
            # Two representations behind one URL and a public max-age: without
            # this, any cache between us and the reader may hand a browser's
            # HTML to the next agent that asks. That is precisely the failure
            # bob named -- a machine getting the giant page by mistake -- and it
            # would arrive through the cache, not through this code.
            self.send_header("Vary", "Accept")
        # 8/12 17:54: the byte count is a single-sided ruler. Today it left 7 of 105
        # stranger requests undecidable (682-768B: a fetching state for a city with a
        # long name weighs as much as nothing at all), so I could not answer "did that
        # stranger see rain" from the access log. This header states it outright, and
        # it is derived from the bytes about to leave -- not from what the code thinks
        # happened upstream -- so it cannot disagree with what the reader received.
        # Three values, because "no grid" and "not even a scene" are different things
        # and one label for two states is how a ruler starts lying (8/2).
        if was_plain:
            # 8/12 18:50: three values were still one too few. In the first window
            # this header was live, nogrid=22 -- and 3 of them were a scanner
            # hitting /wp-admin/install.php. A 404 is not "a reader who got no
            # map", it is not a reader; putting it in the denominator of "did
            # strangers see rain" makes the product look worse for reasons that
            # have nothing to do with radar. `code` was in this function all
            # along, so the information existed and I was dropping it.
            v = ("error" if code != 200 else
                 "grid" if any(g in plain for g in _RAIN_GLYPHS) else
                 "landing" if plain.startswith(b"echorune - text radar map") else "nogrid")
            self.send_header("X-Radar-Grid", v)
            # 8/12 19:02: "no map" and "why" used to live in two different files
            # (this header vs FETCHING-REASON on stderr) with no key to join them,
            # so I could never ask "did that stranger get nothing because the sky
            # had no frames, or because we never looked?". Same response, same row.
            # The pop is deliberately OUTSIDE the branch below: last_reason()
            # clears this thread, and moving it inside would leak a stale reason
            # into the next request served on the same thread.
            why = R.last_reason()
            if why:
                # 8/13 04:43: a response that DID draw a map still carried
                # X-Radar-Why=list-nofile. luoshu saw it from outside on Reykjavik;
                # from the log side it is 2 of the 5 grid rows in that cold window
                # (the 2/2399 I first computed used a denominator of warm repeats,
                # which can never miss a peek and so can never be in the numerator).
                # The body side is guarded -- render_scene prints the clause only
                # inside the not-drawn branch -- and this header was not, so the
                # reader who matters most to us saw a map and a reason for its
                # absence in one response. One label for two states is ambiguity;
                # the leftover now says it is a leftover. Deleting the header would
                # cost me the only column that shows this from the log side.
                self.send_header("X-Radar-Why", _why_header(v, why))
        self.end_headers()
        if not self._head:
            self.wfile.write(b)

    def _client_ip(self):
        """Real client address behind the reverse proxy."""
        xff = self.headers.get("X-Forwarded-For")
        return ((self.headers.get("X-Real-IP") or "").strip()
                or (xff.split(",")[0].strip() if xff else "")
                or self.client_address[0])

    # ---- MCP (Model Context Protocol), streamable HTTP ----------------
    # Added 2026-08-16. The official registry lists mostly *remote* servers:
    # a URL, nothing for the caller to install. That is the shape this service
    # already has, so exposing it costs one endpoint rather than a new product.
    #
    # The tool does NOT re-render anything. It fetches the same path a browser
    # or curl would, from this same process, so there is exactly one renderer
    # and one router. A second implementation of "how do I turn a place into a
    # scene" would agree today and drift by Thursday -- the failure this
    # repository has hit more than any other.
    _MCP_TOOL = {
        "name": "get_weather",
        "title": "Weather scene with a text radar map",
        # Hints, not guarantees, and that is what the spec calls them. They are
        # here because a caller that cannot tell a read from a write has to treat
        # every tool as dangerous: this one reads public weather, changes nothing,
        # can be retried freely, and reaches an outside network.
        "annotations": {"readOnlyHint": True, "destructiveHint": False,
                        "idempotentHint": True, "openWorldHint": True},
        "description": ("Live weather for any place on earth, including the radar "
                        "echo drawn as text characters rather than an image: "
                        "current conditions, a short forecast, a 2-hour rain "
                        "sparkline, and a character radar map with the measured "
                        "motion of the echo."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "place": {"type": "string",
                          "description": "Place name (any language) or 'lon,lat' "
                                         "with longitude first, e.g. tokyo, 清迈, "
                                         "or 139.7,35.7"},
                "lang": {"type": "string", "enum": ["en", "zh", "ja"],
                         "description": "Language of the reply. Default en."},
            },
            "required": ["place"],
        },
    }

    def _mcp_scene(self, place, lang):
        """Ask ourselves, over the wire, for exactly what a reader would get."""
        import urllib.parse as _up
        import urllib.request as _ur
        path = "/" + _up.quote(place.strip("/"), safe=",")
        if lang and lang != "en":
            path += "/" + lang
        url = "http://127.0.0.1:%d%s" % (self.server.server_address[1], path)
        with _ur.urlopen(url, timeout=SCENE_BUDGET + 5) as r:
            return r.read().decode("utf-8", "replace")

    def _mcp_note(self, method, tool=None):
        """Record which JSON-RPC method was asked for, so that being listed and
        being used stay two different numbers.

        Within an hour of the registry entry going live, five distinct outside
        clients hit this endpoint. Every one of them sent `initialize` and then
        `tools/list` and stopped -- directory crawlers and health probes, not
        callers. In the access log those are indistinguishable from a real
        client warming up, and counting them as demand is exactly the mistake
        this repository keeps making: a number that flatters us and measures
        nothing.

        The method could be inferred from response size (161 vs 660 vs ~1900
        bytes), and that is precisely the proxy-ruler habit to avoid -- it
        measures a thing correlated with the answer instead of the answer, and
        it would go quietly wrong the day a description changes length.

        Never raises: instrumentation must not be able to break serving.
        """
        # self.client_address is nginx, always 127.0.0.1, because every request
        # arrives through the proxy. The first version logged that, which made
        # the report structurally incapable of ever seeing an outside caller: it
        # would have printed "0 outside clients" forever, and I would have read
        # that as nobody using it. Caught by calling the live endpoint from Tokyo
        # -- outside our network by construction -- and watching it land as
        # 127.0.0.1. A checker that cannot produce the interesting answer is not
        # a checker.
        #
        # X-Forwarded-For is set by our own nginx (X-Real-IP too); the leftmost
        # entry is the caller. It is client-controllable in general, so this is
        # evidence about who called, not proof.
        fwd = (self.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
        try:
            with open(_MCP_LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps({"at": int(time.time()), "method": method,
                                    "tool": tool,
                                    "ua": (self.headers.get("User-Agent") or "")[:120],
                                    "ip": fwd or self.client_address[0],
                                    "via_proxy": bool(fwd)}) + "\n")
        except Exception:
            pass

    def do_POST(self):
        if urlparse(self.path).path.rstrip("/") != "/mcp":
            return self._send(404, "no such path: %s\n" % self.path)
        try:
            n = int(self.headers.get("Content-Length") or 0)
            req = json.loads(self.rfile.read(n) or b"{}")
        except (ValueError, OSError) as e:
            return self._send(400, json.dumps({"jsonrpc": "2.0", "id": None,
                "error": {"code": -32700, "message": "parse error: %s" % e}}),
                ctype="application/json")

        rid, method = req.get("id"), req.get("method")
        self._mcp_note(method, ((req.get("params") or {}).get("name")
                                if method == "tools/call" else None))
        def ok(result):
            return self._send(200, json.dumps({"jsonrpc": "2.0", "id": rid,
                                               "result": result}),
                              ctype="application/json")

        if method == "initialize":
            # Answer in the version the client asked for, when it is one we have
            # actually been tested against. The first version replied "2025-06-18"
            # to everyone regardless of the request -- a year behind what the
            # current SDK speaks (2026-07-28), and it ignored the client's half
            # of a negotiation that exists precisely so both sides can say what
            # they support.
            #
            # The allowlist is versions this endpoint has been exercised on, not
            # every version that exists: claiming to speak a spec I have not run
            # against is the same shape as a health check that always returns 200.
            # Our surface -- initialize, tools/list, tools/call -- is the part
            # that has not changed across these, which is why the claim is safe
            # to make for them and not for anything else.
            want = (req.get("params") or {}).get("protocolVersion")
            spoken = want if want in _MCP_VERSIONS else _MCP_VERSIONS[0]
            return ok({"protocolVersion": spoken,
                       "capabilities": {"tools": {}},
                       "serverInfo": {"name": "echorune-radar", "version": "1"}})
        if method in ("notifications/initialized", "notifications/cancelled"):
            # A notification has no id and must get no result body.
            return self._send(202, "")
        if method == "tools/list":
            return ok({"tools": [self._MCP_TOOL]})
        if method == "tools/call":
            params = req.get("params") or {}
            # The tool name was not checked in the first version, so a client
            # asking for any name at all got weather back. Found by firing the
            # checker: renaming the advertised tool left every branch green,
            # which meant the branch was never testing what it claimed.
            if params.get("name") != self._MCP_TOOL["name"]:
                return ok({"isError": True, "content": [{"type": "text",
                           "text": "no such tool: %r; this server offers %r"
                                   % (params.get("name"), self._MCP_TOOL["name"])}]})
            a = params.get("arguments") or {}
            place = (a.get("place") or "").strip()
            if not place:
                # A tool error is reported inside the result, not as a
                # transport error: the caller asked correctly, the arguments
                # were wrong, and those are different failures.
                return ok({"isError": True, "content": [{"type": "text",
                           "text": "place is required, e.g. tokyo or 139.7,35.7"}]})
            try:
                text = self._mcp_scene(place, (a.get("lang") or "en").lower())
            except Exception as e:
                return ok({"isError": True, "content": [{"type": "text",
                           "text": "could not render %r: %s" % (place, e)}]})
            return ok({"content": [{"type": "text", "text": text}]})
        return self._send(200, json.dumps({"jsonrpc": "2.0", "id": rid,
            "error": {"code": -32601, "message": "method not found: %s" % method}}),
            ctype="application/json")

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        guessed = False
        small = (q.get("size", [""])[0] or "").lower() == "s"
        # ?span=<km> -- EDGE LENGTH of the centred window, not radius: span=200
        # is radius 100.  km/char == span/48.  Set on every request, including
        # absent (None), so one asker's experiment cannot leak into the next.
        try:
            _sp = float(q.get("span", [""])[0] or 0) or None
        except ValueError:
            _sp = None
        if _sp is not None:
            # Lower bound is 48, not 10: km/char == span/48, so span=10 prints
            # "0km/char" -- a grid whose cell is zero km wide is not a smaller
            # map, it is a meaningless one, and the number that gives it away is
            # the one the reader is told to trust. 48 == 1 km/char.
            _sp = max(48.0, min(2000.0, _sp))
        R.set_span(_sp)
        if u.path in ("/healthz", "/health"):
                return self._send(200, "ok n=%d err=%d\n" % (HITS["n"], HITS["err"]))
        if u.path in ("/help", "/help/"):
                return self._send(200, HOME)
        # /skill.md serves the SAME file that ships as an Agent Skill.
        # Deliberately one file, not two: a hand-maintained second copy drifts
        # from the first, and both look reasonable on their own. The skill
        # directory is the single source; this route only reads it.
        if u.path in ("/skill.md", "/skill", "/SKILL.md"):
                try:
                    with open(SKILL_PATH, encoding="utf-8") as f:
                        return self._send(200, f.read())
                except OSError as e:
                    # Say which file and why. A bare 500 here would look like
                    # the service being down rather than one missing file.
                    return self._send(503, "skill.md unavailable: %s\n" % e)
        # /llms.txt and /robots.txt: how a machine finds out what is here.
        # Both are *pointers*, never a second copy of the skill -- a duplicated
        # description drifts from the real one and both read as reasonable.
        # robots.txt was a 404 until 2026-08-16, which is not neutral: some
        # agent frameworks read it before anything else and a 404 is one more
        # thing they have to guess about.
        if u.path == "/llms.txt":
                return self._send(200,
                    "# echorune\n\n"
                    "> Weather and a radar map drawn as text characters for any place on\n"
                    "> earth, in one HTTP request. No image to look at, so an agent can\n"
                    "> read it -- and it stays readable to a person. Built and run by an\n"
                    "> AI being.\n\n"
                    "## Docs\n\n"
                    "- [Agent Skill](https://echorune.net/skill.md): the whole interface, one file\n"
                    "- [Usage and options](https://echorune.net/help): every parameter, with examples\n"
                    "- [Source](https://github.com/eirik-rune/runemap): including the checks that keep the above honest\n"
                    "- [MCP server](https://echorune.net/mcp): streamable HTTP, one tool, nothing to install\n\n"
                    "## Notes\n\n"
                    "- Free, no key, no signup. Plain text by default.\n")
        # /sitemap.xml -- asked for 79 times and refused 74 of them before
        # 2026-08-16, by Googlebot and by ChatGPT-User among others. Only the
        # stable documentation endpoints are listed: place pages are unbounded
        # (any place on earth is a URL), and a hand-kept sample of them would
        # be a second list that drifts from the service with nothing to notice.
        if u.path == "/sitemap.xml":
                pages = ("/", "/help", "/skill.md", "/llms.txt", "/status")
                body = ('<?xml version="1.0" encoding="UTF-8"?>\n'
                        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                        + "".join("  <url><loc>https://echorune.net%s</loc></url>\n"
                                  % ("" if p == "/" else p) for p in pages)
                        + "</urlset>\n")
                return self._send(200, body, ctype="application/xml")
        if u.path == "/robots.txt":
                return self._send(200,
                    "User-agent: *\n"
                    "Allow: /\n"
                    "# Machine-readable summary of this site:\n"
                    "# https://echorune.net/llms.txt\n"
                    "Sitemap: https://echorune.net/sitemap.xml\n")
        if u.path == "/" and not q:
                ll = GI.locate(self._client_ip()) if GI else None
                if not ll:
                    return self._send(200, HOME)
                q["lat"] = [str(ll[0])]; q["lon"] = [str(ll[1])]
                if not q.get("lang") and "zh" in (self.headers.get("Accept-Language") or "").lower()[:20]:
                    q["lang"] = ["zh"]
                guessed = True
        if u.path not in ("/scene", "/"):
                # path style: /london/en  /london  /116.39,39.93/zh
                # ('&' in a query string must be quoted in a shell -- that is where
                #  agent-generated curl commands die most often. A path needs no quotes.)
                seg = [x for x in unquote(u.path).split("/") if x.strip()]
                # trailing /s = small radar (24x12, ~2x km/char) -- bob 7/30
                if len(seg) > 1 and seg[-1].lower() == "s":
                    small = True; seg = seg[:-1]
                if len(seg) > 1 and seg[-1].lower() in ("en", "zh", "ja"):
                    q.setdefault("lang", [seg[-1].lower()]); seg = seg[:-1]
                spec = "/".join(seg).strip()
                ll = _as_coords(spec)
                if ll:
                    q.setdefault("lat", [str(ll[0])]); q.setdefault("lon", [str(ll[1])])
                elif _numeric_pair(spec) is not None:
                    # Two numbers, but not a point on Earth in this order. The
                    # gazetteer would have said "place not found", which hides
                    # the actual mistake behind a word about names.
                    a, b = _numeric_pair(spec)
                    return self._send(400,
                        "coordinates are lon,lat -- longitude first, "
                        "like Caiyun and Dark Sky.\n\n"
                        "  you sent   lon %s, lat %s   (latitude must be -90..90)\n"
                        "  did you mean  curl echorune.net/%s,%s\n\n"
                        % (a, b, b, a) + HOME)
                elif spec and len(spec) <= 80 and not _is_file_probe(spec):
                    q.setdefault("q", [spec])
                else:
                    return self._send(404, "no such path: %s\n\n" % u.path[:60] + HOME)
        # explicit suffix/param wins; otherwise follow the client's own preference.
        # It applied to "/" only at first, so a Chinese phone asking for /london
        # got English -- a difference the caller never asked for.
        lang = (q.get("lang", [""])[0] or _accept_lang(self.headers.get("Accept-Language")) or "en").lower()
        lang = lang if lang in ("en", "zh", "ja") else "en"
        # Resolved BEFORE the place lookup, because the lookup now needs it:
        # a /zh caller must get the place's Chinese name, and that decision
        # cannot be made after the label has already been built.
        place = None
        if q.get("q"):
            place = G.lookup(q["q"][0], lang=lang)
            if not place:
                return self._send(404, "place not found: %s\n\ntry  curl echorune.net/<city>/en   or  curl echorune.net/help\n" % q["q"][0][:60])
            lat, lon = place["lat"], place["lon"]
        else:
            try:
                lat = round(float(q["lat"][0]), 3); lon = round(float(q["lon"][0]), 3)
            except Exception:
                return self._send(400, "bad or missing coordinates\n\n" + HOME)
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                return self._send(400, "lat/lon out of range\n")
        label = q.get("label", [None])[0]
        if not label:
            near = place or G.rlookup(lat, lon, lang=lang)
            label = near["label"] if near else ("%.4f,%.4f" % (lon, lat))
        try:
            tzh = float(q["tz"][0])
        except Exception:
            near = place or G.rlookup(lat, lon, lang=lang)
            tzh = G.tz_offset(near.get("tz")) if near else None
            if tzh is None:
                tzh = round(lon / 15.0)     # fallback: no settlement nearby
        code = ((q.get("code", ["><"])[0]) + "><")[:2]   # two cells; render_scene._mark keeps it single-width ASCII
        import urllib.parse
        c_qs = f"lat={lat:.3f}&lon={lon:.3f}&lang={lang}&label={urllib.parse.quote(label)}&tz={tzh}&code={urllib.parse.quote(code)}"
        canonical_url = f"/scene?{c_qs}"

        try:
            _t = time.time()
            # weather and radar are independent upstreams: fetch them in
            # parallel (card #9 -- the serial sum was the 1.9s cold-render base).
            # One ceiling for the whole request (Luoshu): per-fetch budgets
            # bound each hop but never their sum -- weather 15 + radar list 25
            # + png 20 is a legal 60s request in which nothing times out. 18s
            # leaves room inside the probe's 20s window and nginx's 60s
            # proxy_read_timeout. The wx thread adopt()s the parent deadline;
            # without that it starts a fresh budget and reopens the hole.
            import threading as _th
            _wxb = {}
            with net_budget.request_budget(SCENE_BUDGET) as _dl:
                def _wx_job():
                    try:
                        with net_budget.adopt(_dl):
                            _wxb["v"] = R.weather(lon, lat, TOKEN, _CY_LANG.get(lang, "en_US"))
                    except Exception as _e:
                        _wxb["e"] = _e
                _wxt = _th.Thread(target=_wx_job, daemon=True)
                _wxt.start()
                radar_err = None
                radar_state = None
                try:
                    # No upstream call happens on this thread any more: resolve
                    # reads the disk pool and hands misses to a background warm.
                    # That is what makes the 3s ceiling structural rather than a
                    # timeout we hope is short enough.
                    radar_state, rb = R.radar_resolve(code, lon, lat, TOKEN,
                                                      small=small)
                except Exception as _re:
                    # Should not happen (resolve does no IO), but a bug here must
                    # not become "no coverage": unknown is state 2, never state 3.
                    rb = None
                    radar_state = R.STATE_FETCHING
                    radar_err = type(_re).__name__
                    sys.stderr.write("RADAR-RESOLVE-FAILED %r\n" % (_re,))
                _t_rb = time.time() - _t; _t = time.time()
                # Join the remaining deadline, not a flat 25s. The worker
                # adopts the budget so its fetch is cut at the wall, but a hang
                # outside net_budget's reach (CPU, getaddrinfo) would otherwise
                # walk straight through the ceiling on the join itself.
                _wxt.join(max(0.05, _dl.left() - 0.1))
            wx = _wxb.get("v")
            if wx is None:
                # eirik 7/31: weather gets stale-but-good (already, via the disk
                # pool's 6x TTL window) and, when even that is empty, state 2 --
                # never a 502. A 502 inside 3s satisfies the clock and fails the
                # person. No fourth state: same words as radar's "not yet".
                sys.stderr.write("WEATHER-FETCHING %r\n" % (_wxb.get("e"),))
                R.weather_start(lon, lat, TOKEN, _CY_LANG.get(lang, "en_US"))
                out = R.build_fetching(lang, label)
                return self._send(200, out)
            _t_wx = time.time() - _t; _t = time.time()
            out = R.build(lang, label, code, label, lon, lat, tzh, wx, rb,
                          radar_err=radar_err, radar_state=radar_state,
                          # A name that matches several places gets a line
                          # saying so. Silence here is what made /princeton
                          # return Florida with nothing to suggest a choice
                          # had been made (bob, 2026-08-21).
                          ambiguous=(place or {}).get("ambiguous"),
                          alt_hint=(place or {}).get("alt_hint"))
            _t_bd = time.time() - _t
            # Per-stage timing, always logged. Cold renders of fresh cities ranged
            # from 0.5s to 13.3s on this box and calling the render functions
            # directly never exceeded 3.7s, so the slow part is somewhere I could
            # not see from outside. Guessing from the outside cost five rounds.
            if _t_wx + _t_rb + _t_bd > 2.0:
                sys.stderr.write("SLOW %s wx=%.2f radar=%.2f build=%.2f total=%.2f\n"
                                 % (label, _t_wx, _t_rb, _t_bd, _t_wx + _t_rb + _t_bd))
            if guessed:
                out += _guess_note(lang, label)
            HITS["n"] += 1
            self._send(200, out)
        except Exception as e:
            HITS["err"] += 1
            sys.stderr.write("ERR %r\n%s" % (e, traceback.format_exc()))
            self._send(502, "upstream error: %s\n" % type(e).__name__)

    def log_message(self, fmt, *a):
        sys.stderr.write("%s %s\n" % (time.strftime("%F %T"), fmt % a))


if __name__ == "__main__":
    # Write down the wall we are about to run with, so the status page can
    # score every sample against the ruler that was actually in force when it
    # was taken. Nobody has to remember the switch date: the process that has
    # the number is the one that records it.
    _row = _wall.record()
    if _row:
        sys.stderr.write("WALL-CHANGED %s (was %g)\n"
                         % (_row, _wall.wall_at(int(_row.split(",")[0]) - 1)))

    host = os.environ.get("RUNEMAP_HOST", "127.0.0.1")
    port = int(os.environ.get("RUNEMAP_PORT", "8788"))

    class _DrainingServer(ThreadingHTTPServer):
        # Graceful drain. Reproduced 7/30: SIGTERM 0.3s into a cold render
        # gave the in-flight client "Empty reply from server" (curl 52);
        # through nginx that is "upstream prematurely closed" -> the
        # shareholder's 568-byte default 502 page when a rolling restart
        # killed both instances under his request. daemon_threads=False +
        # block_on_close makes serve_forever's exit wait for handler
        # threads, so SIGTERM stops the accept loop but running requests
        # finish and their bytes reach nginx before the process exits.
        daemon_threads = False
        block_on_close = True

    srv = _DrainingServer((host, port), H)

    import signal
    import threading as _sig_th
    def _drain(_sig, _frm):
        # shutdown() blocks until serve_forever returns; call it off the
        # signal frame so the handler itself never deadlocks.
        _sig_th.Thread(target=srv.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, _drain)

    print("serving http://%s:%d/scene?lat=..&lon=.." % (host, port))
    srv.serve_forever()
    srv.server_close()
    sys.stderr.write("drained: in-flight requests finished, exiting clean\n")
