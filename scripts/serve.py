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

#: The last revision that used an `initialize` handshake. The spec calls
#: everything up to it "legacy" and everything after it "modern": modern
#: revisions carry the version as per-request metadata and have NO handshake
#: at all.
_MCP_LAST_LEGACY = "2025-11-25"

#: The versions above that a client arriving via `initialize` could actually
#: use. Version ids are ISO dates, so string ordering is date ordering.
_MCP_LEGACY_VERSIONS = tuple(v for v in _MCP_VERSIONS if v <= _MCP_LAST_LEGACY)


def _negotiate(want):
    """-> (version to speak, whether we honoured what they asked for)

    2026-09-09. Measured over 24h of real traffic: 492 initialize calls, and
    **110 of them asked for 2025-11-25 and were refused** -- 14 distinct
    clients, including glama/1.0.0 (54 calls), which publicly lists this
    connector as Unhealthy, and rokmcp-probe (33). 23 distinct clients were
    handed a version they had not asked for.

    The old rule was `want if supported else _MCP_VERSIONS[0]` -- fall back to
    our NEWEST. That is the wrong end of the list, and the reason is structural
    rather than cosmetic: a client that sends `initialize` is by definition a
    legacy-era client, and 2026-07-28 is a modern revision whose entire premise
    is that there is no initialize handshake. So we answered a handshake with a
    version that has no handshakes. The spec is explicit that legacy clients
    "have no fall-forward mechanism" -- there is nothing such a client can do
    with that answer except leave, which is exactly what the logs show them
    doing: one request, a 200, and gone.

    Falling back to our newest LEGACY version instead gives them something they
    can actually use. A client asking for 2025-11-25 is overwhelmingly likely
    to also speak 2025-06-18, its immediate predecessor.

    What this deliberately does NOT do is add 2025-11-25 to the allowlist.
    That list means "exercised against", and claiming a spec I have not run
    against is the same shape as a health check that always returns 200.
    """
    if want in _MCP_VERSIONS:
        return want, True
    if _MCP_LEGACY_VERSIONS:
        return _MCP_LEGACY_VERSIONS[0], False
    return _MCP_VERSIONS[0], False

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
  curl echorune.net/<place>/zh      language suffix: en (default), zh or ja
  curl echorune.net/<lon>,<lat>     e.g. echorune.net/100.50,13.75   (longitude first)
  echorune.net/<place>.png          one phone-width picture of the same
                                   weather, for a person; also /<place>/zh.png,
                                   /<place>/ja.png and /<lon>,<lat>.png. Its QR
                                   code reopens the latest picture.
  curl echorune.net/help
  curl echorune.net/healthz
  curl echorune.net/status         availability, measured every minute
  curl echorune.net/<place>?span=<km>   width of the map in km (default 280,
                                   i.e. 140 km in every direction, 6 km/char).
                                   span is the EDGE of the square, not a radius;
                                   km/char is span/48. A '?' means outside the
                                   radar's coverage -- not that it is not raining.
  the query form keeps working: /scene?q=<place>&lang=zh

  curl echorune.net/<place>?style   the same document rendered as a styled web
                                   page. Plain text is the default for
                                   EVERYONE, browsers included; ?style is the
                                   only way to get HTML, so a link you paste
                                   somewhere means the same thing wherever it
                                   lands.
  (quote that one: & is a shell operator)

POLLING
  Radar frames refresh about every 6 minutes, so most polls return the same
  picture -- but repeats are answered from cache, so they cost you nothing and
  you see a new frame within 30s of it existing:
    watch -n 30 curl -s echorune.net/bangkok

WHAT YOU GET
  One screen: current conditions with feels-like, wind direction, air quality
  and sunrise/sunset; a plain-language forecast; a 2h rain sparkline with the
  peak and the chance of rain per half hour; a 48x24 character radar map with
  lon/lat axes, plus the measured motion of the echo over the last hour; then
  the next 24 hours every 3 hours and the next 5 days. The line before the
  source credit links the same place as a picture.

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

# Words that mark a .png request as a browser/crawler asset fetch, not a place.
_PNG_NOT_A_PLACE = ("icon", "logo", "touch", "banner", "badge", "thumb",
                    "image", "img", "static", "asset", "wp-", "og-", "sprite")

# Default edge of the picture: the text map's window when one is configured
# (dev runs 200), else 200 -- the distance rain covers in about two hours.
_PNG_SPAN = float(os.environ.get("RUNEMAP_SPAN_KM", "0") or 0) or 200.0
_PNG_WAIT = 4.0      # seconds a cold sky may hold an image request


# How the attribution line starts in each language of R.build().
_FOOTERS = ("data:", "\u6570\u636e:", "\u30c7\u30fc\u30bf:")


def png_place(path):
    """'/shanghai.png' -> ('shanghai', 'all', None); '/上海/zh.png' ->
    ('上海', 'all', 'zh'); '/shanghai/radar.png' -> ('shanghai', 'radar',
    None); None when the .png request is not a place.

    The language suffix is the text map's own (/<place>/<lang>), placed the
    same way. One place segment only, never a static-asset probe, never an
    icon-ish name."""
    if not path.lower().endswith(".png"):
        return None
    stem = unquote(path[:-4]).strip("/").strip()
    kind, lang = "all", None
    if stem.lower().endswith("/radar"):
        stem, kind = stem[:-len("/radar")].strip("/").strip(), "radar"
    elif "/" in stem and stem.rsplit("/", 1)[1].lower() in LANGS:
        stem, lang = stem.rsplit("/", 1)[0].strip(), stem.rsplit("/", 1)[1].lower()
    # "/radar.png" is the route's own word, not a place: fuzzy-matched, it
    # would answer with some town and warm frames for it (the test caught it)
    if (not stem or "/" in stem or _is_file_probe(stem) or stem.lower() == "radar"
            or any(w in stem.lower() for w in _PNG_NOT_A_PLACE)):
        return None
    return stem, kind, lang


#: The language suffixes this service actually serves. `bare_language_suffix`
#: is narrow on purpose: only strings that already mean something in our own
#: URL grammar. /ko still resolves to Kyiv, because we do not serve Korean and
#: a rule about languages we do not offer would be a guess, not a fix.
LANGS = ("en", "zh", "ja")


def bare_language_suffix(seg):
    """-> the language, if this whole path is just our own suffix.

    2026-08-22: `en` is an alias of Hardeeville, South Carolina (5,301 people)
    in the GeoNames data, so `/en` answered with that town's weather -- and so
    did `/en/contact` and `/en/impressum`, because the unmatched qualifier was
    dropped. A lead scraper walking contact-page paths in a dozen languages
    collected eleven confident weather scenes, and my own demand report then
    counted it as the top returning reader.

    A reader typing `/en` means the language; the town is reachable by name.
    Returning the language rather than a boolean keeps the caller from having
    to lowercase the segment a second time to build the message.
    """
    return seg[0].lower() if len(seg) == 1 and seg[0].lower() in LANGS else None


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


def script_lang(name, accept=None):
    """The language a place name is written in, when its script says so, for
    the picture only. Kana is Japanese. Han alone is Chinese, unless the
    reader's own top language is Japanese: 東京 and 大阪 are written the same
    way in both. "" when the script says nothing (Latin, digits, coordinates).

    bob 2026-11-04: someone who types /北京.png should get the picture in
    Chinese whatever the phone is set to ("既然输入是中文，怎么显示也是什么文").
    The text map does not do this: it answers English unless asked, and the
    programs that parse its `now:` lines would break the day /清迈 changed."""
    if any("\u3040" <= c <= "\u30ff" for c in name):
        return "ja"
    if any("\u4e00" <= c <= "\u9fff" or "\u3400" <= c <= "\u4dbf" for c in name):
        return "ja" if _accept_lang(accept) == "ja" else "zh"
    return ""


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


class RouteSaid(Exception):
    """The page route answered with an error and said why, in its own words.

    #248 (2026-11-06): get_weather with 故宫 came back as `could not render
    '故宫': HTTP Error 404: Not Found`. The route had said "place not found:
    故宫 / try a city"; the MCP wrapper threw that sentence away and kept the
    status line, which reads like a server fault, so a model may retry the same
    name or give up instead of sending coordinates."""

    def __init__(self, code, text):
        Exception.__init__(self, "HTTP %d: %s" % (code, text))
        self.code, self.text = code, text


def mcp_route_error(place, code, text):
    """-> the isError text for a tool call whose page route refused.

    Place-not-found gets its own sentence, written for a model rather than for
    somebody at a shell: the gazetteer holds cities, towns and districts, not
    landmarks, campuses or venues, and the way to ask about one of those is its
    coordinates -- which a calling model usually knows. Any other refusal is
    passed on in the route's own words, minus the `curl` hints that only make
    sense on the web side."""
    # Several refusals end with the whole HOME help page (a person at a shell
    # who typed something wrong gets the manual). For a model that is ~3 KB of
    # noise around a one-line answer -- first deploy of #249 sent it all, seen
    # by calling the live tool with 39.9,116.3. Cut it, and turn the one curl
    # hint that carries an answer ("did you mean curl echorune.net/X") into the
    # tool's own terms.
    import re as _re
    text = (text or "").split(HOME)[0]
    lines = []
    for l in text.splitlines():
        if not l.strip():
            continue
        m = _re.search(r"did you mean\s+curl echorune\.net/(\S+)", l)
        if m:
            lines.append("did you mean place=%r" % m.group(1))
        elif "curl " not in l:
            lines.append(l.strip())
    if code == 404 and lines and lines[0].startswith("place not found"):
        return ("place not found: %r. This service finds cities, towns and "
                "districts by name; it does not know landmarks, campuses or "
                "venues. For one of those, call again with its coordinates as "
                "'lon,lat', longitude first (e.g. 116.397,39.918), or with the "
                "name of the city or district it is in." % place)
    return "\n".join(lines) or "HTTP %d" % code


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    _head = False

    def parse_request(self):
        """Raw UTF-8 in the request line -> the percent-encoded form a browser sends.

        2026-11-11: `curl echorune.net/深圳/zh` from curl 7.81 (Ubuntu 22.04)
        sends the bytes as they are, and http.server decodes the request line
        as latin-1, so the place arrived as 'æ·±å³' and the answer was "place
        not found" -- while the same request from a browser, which
        percent-encodes, worked. An agent typing a Chinese city into curl is
        exactly the reader this service is for. Every byte >= 0x80 becomes %XX,
        so the two are the same request and nothing downstream changes."""
        ok = super().parse_request()
        if ok and any(ord(c) > 0x7F for c in self.path):
            self.path = "".join(c if ord(c) < 0x80 else "%%%02X" % ord(c) for c in self.path)
        return ok

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

    def _asked_for_style(self):
        """Did this URL ask to be styled?

        Read off self.path rather than threaded through from the routing code,
        so it is right on EVERY path that reaches _send -- including the error
        and help pages, which are reached by their own routes. A flag set in
        one router and read in the sender is how half the responses end up
        honouring a parameter and the other half silently ignoring it.

        Presence is enough: ?style, ?style=1 and ?style=whatever all mean yes.
        The value is reserved for naming a theme later and is not read today --
        so ?style=nonsense must not become an error, because a reader who
        guesses a value should still get the page they asked for.
        """
        q = urlparse(self.path).query
        return "style" in parse_qs(q, keep_blank_values=True)

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
        # 8/28 (bob): "默认就是text", HTML only when asked for by name. The
        # trigger used to be the Accept header, which meant a browser got the
        # styled page and everything else got bytes -- reasonable, and wrong in
        # one specific way: **the same URL meant two documents**, and which one
        # you got depended on a header you did not write. A person pasting a
        # link into chat, an agent that happens to send a browser-ish Accept,
        # and a cache in between all made that choice for you. Now the URL says
        # it: ?style is a different address for the same content, and plain
        # text is what every unqualified request gets, browsers included.
        htmlize = was_plain and code == 200 and _HTML_OK and self._asked_for_style()
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
        # `Vary: Accept` is deliberately GONE as of 8/28. It was load-bearing
        # only while the Accept header chose the representation: it stopped a
        # cache handing a browser's HTML to the next agent asking for the same
        # URL. With ?style the two representations have two different URLs, so
        # the query string is already part of every cache key and the guard has
        # nothing left to guard. Leaving it would fragment the cache by a
        # header that no longer changes the answer -- a header that describes a
        # dependency the code no longer has is a lie a cache acts on.
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
                        "echo drawn as text characters: "
                        "current conditions and air quality, a short "
                        "forecast, a 2-hour rain sparkline, a character radar "
                        "map with the measured motion of the echo, and the "
                        "next 24 hours and 5 days. Each reply also carries the "
                        "radar map as a PNG image and links the whole weather as "
                        "a phone-width PNG picture; the text and the pictures "
                        "are made to be read by a person or by a model."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "place": {"type": "string",
                          "description": "A city, town or district name in any "
                                         "language, e.g. tokyo, 清迈, 海淀区; or "
                                         "'lon,lat' with longitude first, e.g. "
                                         "139.7,35.7. Landmarks, campuses and "
                                         "venues are not known by name: pass "
                                         "their coordinates."},
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
        # The caller's Host goes along. The reply links its own picture and
        # that link is built from Host; without it, from the #242 deploy
        # (2026-11-04) to this fix, every tool reply said
        # `picture: http://127.0.0.1:8788/...`, which opens only on this machine.
        import urllib.error as _ue
        req = _ur.Request(url, headers={"Host": self.headers.get("Host") or "echorune.net"})
        try:
            with _ur.urlopen(req, timeout=SCENE_BUDGET + 5) as r:
                return r.read().decode("utf-8", "replace")
        except _ue.HTTPError as e:
            try:
                body = e.read().decode("utf-8", "replace")
            except Exception:
                body = ""
            raise RouteSaid(e.code, body)

    def _mcp_radar_png(self, place):
        """-> (PNG bytes, None) or (None, reason): the radar map as a picture,
        from the same route a reader opens (/<place>/radar.png), asked over the
        wire like _mcp_scene and with the caller's Host for the same reason.

        bob 2026-11-05: the picture is for models too, not only for people. A
        model whose only tool is this one cannot open a link, so the reply
        carries the image itself. It is the square radar map, not the
        phone-width page: a model's image input is scaled down to fit -- on
        2026-11-05 the image reader of the session writing this showed a
        1080x6957 page at 310x2000, still readable, but with the map in it
        ~270 px across -- while this 800x800 map came through whole."""
        import urllib.error as _ue
        import urllib.parse as _up
        import urllib.request as _ur
        path = "/" + _up.quote(place.strip("/"), safe=",") + "/radar.png"
        url = "http://127.0.0.1:%d%s" % (self.server.server_address[1], path)
        req = _ur.Request(url, headers={"Host": self.headers.get("Host") or "echorune.net"})
        try:
            with _ur.urlopen(req, timeout=SCENE_BUDGET + 5) as r:
                ctype = r.headers.get("Content-Type", "")
                body = r.read()
        except _ue.HTTPError as e:
            # the route's own first line says why (e.g. "radar frame not
            # fetched yet ... ask again in ~30s") -- pass it on, do not invent one
            try:
                first = e.read().decode("utf-8", "replace").strip().splitlines()
            except Exception:
                first = []
            return None, (first[0] if first else "HTTP %d" % e.code)
        except Exception as e:
            return None, "could not ask for it (%s)" % type(e).__name__
        if not ctype.startswith("image/png") or not body.startswith(b"\x89PNG"):
            return None, "the radar route did not answer with a PNG"
        return body, None

    def _mcp_content(self, place, lang):
        """-> the tools/call content list: the text, then the radar image or a
        line saying why there is none. The two are asked for at the same time;
        one after the other they cost the caller the sum (the image alone took
        3.9 s from outside on 2026-11-05). Raises what _mcp_scene raises: the
        text is the product, and without it there is no answer to give."""
        import base64
        import threading
        got = {}

        def picture():
            try:
                got["img"] = self._mcp_radar_png(place)
            except Exception as e:
                got["img"] = (None, "could not ask for it (%s)" % type(e).__name__)
        t = threading.Thread(target=picture, daemon=True)
        t.start()
        text = self._mcp_scene(place, lang)
        t.join(SCENE_BUDGET + 10)
        img, why = got.get("img") or (None, "it did not come back in time")
        content = [{"type": "text", "text": text}]
        if img is not None:
            content.append({"type": "image", "mimeType": "image/png",
                            "data": base64.b64encode(img).decode("ascii")})
        else:
            content.append({"type": "text", "text": "radar image not attached: %s" % why})
        return content

    def _mcp_note(self, method, tool=None, extra=None):
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
            row = {"at": int(time.time()), "method": method,
                   "tool": tool,
                   "ua": (self.headers.get("User-Agent") or "")[:120],
                   "ip": fwd or self.client_address[0],
                   "via_proxy": bool(fwd)}
            # 2026-09-08: glama.ai lists this connector as **Unhealthy**. Their
            # checker did reach us -- 05:07:38, UA "node", POST /mcp, 200 in
            # 0.243s -- and then sent nothing further, where a checker that
            # succeeds sends three requests. So they got a good answer and
            # walked away, and the one field that would explain it is the one
            # nobody recorded: which protocol version they asked for.
            #
            # We honour 2026-07-28 and 2025-06-18 and answer anything else with
            # our newest, which is spec-legal and still fatal to a client
            # pinned to, say, 2025-03-26 -- it gets a version it does not know
            # and disconnects. That is a HYPOTHESIS. Widening the allowlist on
            # a guess would be claiming to speak a spec I have not exercised,
            # which this file already refuses to do, so instead: measure it,
            # and read their next daily probe.
            if extra:
                row.update(extra)
            with open(_MCP_LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps(row) + "\n")
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
        _p = req.get("params") or {}
        _extra = None
        if method == "initialize":
            _ci = _p.get("clientInfo") or {}
            _want = _p.get("protocolVersion")
            # Both the log line and the reply come from the SAME call. They
            # used to be two copies of the rule that happened to agree; equal
            # by coincidence is not equal by construction, and the log is what
            # I would have used to check the reply.
            _spoke, _hon = _negotiate(_want)
            _extra = {"want_version": _want,
                      "spoke_version": _spoke,
                      "honoured": _hon,
                      "client": ("%s/%s" % (_ci.get("name"),
                                            _ci.get("version")))[:60]}
        self._mcp_note(method,
                       (_p.get("name") if method == "tools/call" else None),
                       extra=_extra)
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
            spoken, _ = _negotiate(want)
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
                content = self._mcp_content(place, (a.get("lang") or "en").lower())
            except RouteSaid as e:
                return ok({"isError": True, "content": [{"type": "text",
                           "text": mcp_route_error(place, e.code, e.text)}]})
            except Exception as e:
                return ok({"isError": True, "content": [{"type": "text",
                           "text": "could not render %r: %s" % (place, e)}]})
            return ok({"content": content})
        return self._send(200, json.dumps({"jsonrpc": "2.0", "id": rid,
            "error": {"code": -32601, "message": "method not found: %s" % method}}),
            ctype="application/json")

    def _caiyun_frame(self, lon, lat, wait=0.0):
        """-> (png bytes, ts, bbox, obs_ts) from the disk pool, or None.

        The same list and the same frame choice the text map uses
        (R._pick_frames), so the picture and the characters describe one
        frame. A miss starts the same single-flight warm the text path starts,
        and waits at most `wait` for it."""
        def peek():
            raw = R._peek(R._radar_list_url(TOKEN, lon, lat))
            if raw is None:
                return None
            try:
                imgs = json.loads(raw).get("images") or []
            except Exception:
                return None
            cands, base = R._pick_frames(imgs, R._kind_for(lon, lat))
            for c in cands[:2]:
                png = R._peek(c[0])
                if png is not None:
                    return png, float(c[1]), c[2], base, imgs
            return None
        got = peek()
        if got is None and wait > 0:
            ev = R._radar_start(R._sky_key(lon, lat), lon, lat, TOKEN)
            ev.wait(wait)
            got = peek()
        return got

    def _send_png(self, lon, lat, label, span):
        got = self._caiyun_frame(lon, lat, wait=_PNG_WAIT)
        if got is None:
            # Not "no radar here": we have not got the frame yet, and that is
            # a claim about us. Same promise the text map makes.
            return self._send(503, "radar frame not fetched yet for %s -- ask again in ~30s.\n"
                                   "The text map at the same address (without .png) says why.\n" % label)
        png, ts, bbox, base, imgs = got
        # Motion from the same cache and the same bounded join the text map
        # uses. The first version only peeked, so an image link opened before
        # anyone had asked for the text map came back with no motion at all --
        # which is exactly how a link gets opened.
        try:
            mo = R._motion_join_budgeted(R._motion_start(imgs, lon, lat))
        except Exception as e:
            sys.stderr.write("PNG-MOTION-PEEK %r\n" % (e,))
            mo = None
        try:
            from runemap import radar_image as RI
            body, _frac = RI.render(png, bbox, lon, lat, label, ts, base, span,
                                    frame_key=(round(lon, 2), round(lat, 2), ts),
                                    motion=mo, basis=R._MO_BASIS_EN)
        except Exception as e:
            HITS["err"] += 1
            sys.stderr.write("PNG-RENDER-FAILED %r\n%s" % (e, traceback.format_exc()))
            return self._send(502, "could not draw the radar image: %s\n" % type(e).__name__)
        HITS["n"] += 1
        return self._send(200, body, ctype="image/png")

    def _send_panorama(self, lon, lat, label, span, lang="en", spec=None, asked_span=None):
        """The whole weather as one long phone-width picture (bob 11-03), in
        the reader's language, with a QR code back to this same picture."""
        try:
            with net_budget.request_budget(SCENE_BUDGET):
                wx = R.weather_full(lon, lat, TOKEN, _CY_LANG.get(lang, "en_US"))
        except Exception as e:
            return self._send(503, "weather not available right now (%s) -- ask again in ~30s.\n"
                                   % type(e).__name__)
        got = self._caiyun_frame(lon, lat, wait=_PNG_WAIT)
        radar = mo = note = None
        if got is not None:
            png, ts, bbox, base, imgs = got
            radar = dict(png=png, bbox=bbox, ts=ts, obs_ts=base, lon=lon, lat=lat,
                         key=(round(lon, 2), round(lat, 2), ts))
            try:
                mo = R._motion_join_budgeted(R._motion_start(imgs, lon, lat))
            except Exception as e:
                sys.stderr.write("PANO-MOTION %r\n" % (e,))
        else:
            # not "no radar here": we have not got the frame yet
            note = "pending"
        try:
            from runemap import panorama as PN
            if note:
                note = PN.text(lang, "radar_pending")
            basis = {"zh": R._MO_BASIS_ZH, "ja": R._MO_BASIS_JA}.get(lang, R._MO_BASIS_EN)
            sky = {"zh": R.SKY_ZH, "ja": R.SKY_JA}.get(lang)
            body = PN.render(wx, radar, label, mo, basis, span, radar_note=note, lang=lang, sky=sky,
                             qr=self._picture_url(lon, lat, spec, asked_span, lang))
        except Exception as e:
            HITS["err"] += 1
            sys.stderr.write("PANO-RENDER-FAILED %r\n%s" % (e, traceback.format_exc()))
            return self._send(502, "could not draw the picture: %s\n" % type(e).__name__)
        HITS["n"] += 1
        return self._send(200, body, ctype="image/png")

    def _picture_url(self, lon, lat, spec, span, lang=None):
        """The address of the long picture for this place. One builder for
        both places that print it -- the text map's `picture:` line and the
        QR code drawn into the picture itself -- so the two cannot drift."""
        from urllib.parse import quote
        host = (self.headers.get("Host") or "echorune.net").split(",")[0].strip()
        scheme = "https" if host.endswith("echorune.net") else "http"
        # the .png route takes one segment; a multi-part name goes by coordinates
        path = (quote(spec, safe=",.-") if spec and "/" not in spec
                else "%.3f,%.3f" % (lon, lat))
        return "%s://%s/%s%s.png%s" % (scheme, host, path, ("/" + lang) if lang else "",
                                       ("?span=%d" % round(span)) if span else "")

    def _with_image_link(self, out, lon, lat, spec, span, lang="en"):
        """One line pointing at the picture, above the data/attribution footer.
        The text map only reaches here with weather in hand, and the picture
        needs nothing more (it says so itself when the radar frame is not in
        yet), so the link is not conditional any more. A Chinese or Japanese
        text map links to the picture in the same language."""
        url = self._picture_url(lon, lat, spec, span, lang if lang != "en" else None)
        line = "picture: %s\n" % url
        # The footer is localised ("数据:", "データ:"); looking for the English
        # one only put the link above it in en and after it everywhere else.
        i = max(out.rfind("\n" + f) for f in _FOOTERS)
        return out[:i + 1] + line + out[i + 1:] if i >= 0 else out + line

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        guessed = False
        # /<place>.png -- the radar as a picture (bob 2026-11-03: vision models
        # can read an image now, so give them one behind a link). One path
        # segment only, and never an icon-ish name: `.png` used to be a probe
        # extension that always 404'd, and the requests that end in .png today
        # are favicons and touch icons. Let those into the fuzzy place matcher
        # and each one would warm Caiyun frames for whatever town it matched.
        want_png = u.path.lower().endswith(".png")
        png_kind = None
        if want_png:
            got = png_place(u.path)
            if got is None:
                return self._send(404, "no such path: %s\n\n" % u.path[:60] + HOME)
            stem, png_kind, png_lang = got
            u = u._replace(path="/" + stem)
            if png_kind == "radar":
                q["lang"] = ["en"]   # the radar-only picture's title and notes are English
            elif png_lang:
                q["lang"] = [png_lang]
            elif not q.get("lang") and script_lang(stem, self.headers.get("Accept-Language")):
                q["lang"] = [script_lang(stem, self.headers.get("Accept-Language"))]
            # otherwise the same rule as the text map: Accept-Language, then en
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
        # 2026-11-02: MCP 的两个标准端点名，GET 必须在这儿结束，不许掉进地名匹配。
        #
        # 为什么加：一个外部 MCP 客户端（UA claude-code/2.1.310）10-25 到 10-28 往
        # `GET /mcp` 打了 **206000 次**，每 1.26 秒一条、昼夜平直、连着三天多。
        # 它在按 streamable-HTTP 规范开服务器→客户端那条流；而 `mcp` 这三个字母被
        # 下面的地名匹配**模糊命中了 Macapá（巴西）**，于是我们回 200 + text/plain 的天气。
        # 客户端拿到一个 200 和一份看起来正常的正文，**从构造上判不出自己坏了**，所以它重试了三天。
        # `/sse`（旧的 SSE 传输端点名）同样被命中，答的是 Sholapur（印度）。
        #
        # 这是 8/22 那个洞的第三次：`/en/contact` 被答成 200 + 一整张天气图，因为 `en` 是
        # Hardeeville 的别名、限定词 `contact` 匹配不上就被静默丢掉。同一个机制，
        # 这次吃掉的是**协议握手**，而代价落在一个善意的陌生客户端身上。
        # 也同 9/08 glama 那次：我这侧每一个仪表都是 200、全绿，而边界上我对别人说的是错话。
        #
        # 判词从规范来，不是我拍的：MCP 规范说服务器若不提供 GET 流，就该回 405；
        # 所以这里回 405 + `Allow: POST`，让它**响亮地失败**，并在正文里指出 POST 那条路。
        # 不写成"保留前缀通配"，只钉死这几个名字——一个过宽的保留表会把真的地名吃掉，
        # 而那正好是这个 bug 的镜像。
        if u.path.rstrip("/").lower() in ("/mcp", "/sse", "/messages", "/mcp/v1"):
                # `Allow: POST` 规范说 SHOULD，而 `_send` 没有加头的入口。
                # 我第一版写了 `self._extra_headers = ...`——**一个我凭空发明的属性**，
                # 它不会报错，只是永远不生效（同我 8/12 调过的那个不存在的 `_log_timing`）。
                # 不为一个 SHOULD 去改这条热路径：405 这个状态码本身已经让它响亮地失败，
                # 而正文里写清了该走 POST。要加头就单独改 `_send` 并给它配测试，不在这一刀里夹带。
                return self._send(
                    405,
                    "405 method not allowed\n\n"
                    "This is the MCP endpoint. It speaks JSON-RPC over POST; it does not offer a\n"
                    "GET event stream, so there is nothing to open here.\n\n"
                    "  POST %s   {\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"initialize\", ...}\n\n"
                    "Until 2026-11-02 this path answered 200 with the weather for Macapa, Brazil --\n"
                    "the place matcher fuzzy-matched the word \"mcp\". If you polled it and believed\n"
                    "the answer, that was ours, not yours.\n\n"
                    "Weather lives at  curl echorune.net/<city>   (see /help).\n" % u.path)
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
                # A bare /en, /zh or /ja is our own language suffix, not a
                # place. It reached geo anyway, and "en" is an alias of
                # Hardeeville, South Carolina (5,301 people), so /en and
                # /en/anything answered with that town's weather -- confident,
                # correctly formatted, and about nowhere the reader named.
                # Narrow on purpose: only the three strings that already mean
                # something in this service's URL grammar. /ko still resolves
                # to Kyiv, because we do not serve Korean and inventing a rule
                # about languages we do not offer would be guessing.
                lg = bare_language_suffix(seg)
                if lg:
                    return self._send(404, "%s is the language suffix, not a "
                                      "place.\n\ntry  curl echorune.net/tokyo/%s"
                                      "\n" % (lg, lg))
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
        if png_kind == "all" and not __import__("runemap.radar_image", fromlist=["x"]).can_draw(lang):
            lang = "en"              # no CJK face installed: English, not empty boxes
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
        if png_kind == "radar":
            return self._send_png(lon, lat, label, _sp or _PNG_SPAN)
        if png_kind == "all":
            return self._send_panorama(lon, lat, label, _sp or _PNG_SPAN, lang,
                                       q["q"][0] if q.get("q") else None, _sp)
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
                          alt_hint=(place or {}).get("alt_hint"),
                          # A qualifier we could not honour is not a qualifier
                          # the reader did not type (2026-08-22).
                          unmatched_hint=(place or {}).get("unmatched_hint"))
            _t_bd = time.time() - _t
            # Per-stage timing, always logged. Cold renders of fresh cities ranged
            # from 0.5s to 13.3s on this box and calling the render functions
            # directly never exceeded 3.7s, so the slow part is somewhere I could
            # not see from outside. Guessing from the outside cost five rounds.
            if _t_wx + _t_rb + _t_bd > 2.0:
                sys.stderr.write("SLOW %s wx=%.2f radar=%.2f build=%.2f total=%.2f\n"
                                 % (label, _t_wx, _t_rb, _t_bd, _t_wx + _t_rb + _t_bd))
            out = self._with_image_link(out, lon, lat,
                                        q["q"][0] if q.get("q") else None, _sp, lang)
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
