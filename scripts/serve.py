#!/usr/bin/env python3
"""runemap HTTP service: GET /scene?lat=..&lon=..&lang=en|zh[&label=..&tz=..]
Any coordinate on earth, rendered on demand. Radar PNGs cached (see scene_at).
Bind 127.0.0.1 by default -- no public exposure."""
import os, sys, time, traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scene_at as SA          # installs the radar cache layer on render_scene._get
import render_scene as R
import net_budget

import wall as _wall
SCENE_BUDGET = _wall.WALL          # the wall; see scripts/wall.py for why it moved
import geo as G
try:
    import geoip as GI          # ip -> lat/lon (DB-IP Lite, local sqlite, no third party)
except Exception:
    GI = None

TOKEN = os.environ.get("CAIYUN_TOKEN") or sys.exit("CAIYUN_TOKEN missing")
HITS = {"n": 0, "err": 0}


HOME = """echorune - text radar map for agents
=====================================

Weather rendered as characters, so LLM agents that cannot read images
can still see the rain.

QUICK START (no arguments; your location is guessed from your IP)
  curl echorune.net

USAGE
  curl echorune.net/<place>         e.g. echorune.net/bangkok
  curl echorune.net/<place>/zh      language suffix: en (default) or zh
  curl echorune.net/<lat>,<lon>     e.g. echorune.net/13.75,100.50
  curl echorune.net/help
  curl echorune.net/healthz
  curl echorune.net/status         availability, measured every minute
  the query form keeps working: /scene?q=<place>&lang=zh
  (quote that one: & is a shell operator)

WHAT YOU GET
  One screen: current conditions, a plain-language forecast, a 2h rain
  sparkline, and a 48x24 character radar map with lon/lat axes, plus the
  measured motion of the echo over the last hour.

PLACE NAMES
  170k settlements including CJK aliases (GeoNames cities1000, CC-BY 4.0).
  Any coordinate on earth works, named or not.

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
        code = "zh" if tag.startswith("zh") else ("en" if tag.startswith("en") else "")
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
    tail = spec.split("/")[-1].lower()
    return "." in tail and tail.rsplit(".", 1)[-1] in _PROBE_EXT


def _as_coords(spec):
    """'lat,lon' -> (lat, lon), else None.

    Disambiguation is measured, not conventional: a value with abs > 90 cannot be
    a latitude, so '116.39,39.93' resolves to lon,lat with certainty. Only when
    both values are <= 90 do we fall back to the lat,lon convention."""
    parts = [x.strip() for x in spec.replace("\uff0c", ",").split(",")]
    if len(parts) != 2:
        return None
    try:
        a, b = float(parts[0]), float(parts[1])
    except ValueError:
        return None
    if abs(a) > 90 and abs(b) <= 90:
        a, b = b, a                      # given lon,lat
    if not (-90 <= a <= 90 and -180 <= b <= 180):
        return None
    return round(a, 4), round(b, 4)


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
        self.send_response(code)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "public, max-age=300")
        self.end_headers()
        if not self._head:
            self.wfile.write(b)

    def _client_ip(self):
        """Real client address behind the reverse proxy."""
        xff = self.headers.get("X-Forwarded-For")
        return ((self.headers.get("X-Real-IP") or "").strip()
                or (xff.split(",")[0].strip() if xff else "")
                or self.client_address[0])

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        guessed = False
        small = (q.get("size", [""])[0] or "").lower() == "s"
        if u.path in ("/healthz", "/health"):
                return self._send(200, "ok n=%d err=%d\n" % (HITS["n"], HITS["err"]))
        if u.path in ("/help", "/help/"):
                return self._send(200, HOME)
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
                if len(seg) > 1 and seg[-1].lower() in ("en", "zh"):
                    q.setdefault("lang", [seg[-1].lower()]); seg = seg[:-1]
                spec = "/".join(seg).strip()
                ll = _as_coords(spec)
                if ll:
                    q.setdefault("lat", [str(ll[0])]); q.setdefault("lon", [str(ll[1])])
                elif spec and len(spec) <= 80 and not _is_file_probe(spec):
                    q.setdefault("q", [spec])
                else:
                    return self._send(404, "no such path: %s\n\n" % u.path[:60] + HOME)
        place = None
        if q.get("q"):
            place = G.lookup(q["q"][0])
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
        # explicit suffix/param wins; otherwise follow the client's own preference.
        # It applied to "/" only at first, so a Chinese phone asking for /london
        # got English -- a difference the caller never asked for.
        lang = (q.get("lang", [""])[0] or _accept_lang(self.headers.get("Accept-Language")) or "en").lower()
        lang = lang if lang in ("en", "zh") else "en"
        label = q.get("label", [None])[0]
        if not label:
            near = place or G.rlookup(lat, lon)
            label = near["label"] if near else ("%.4f,%.4f" % (lon, lat))
        try:
            tzh = float(q["tz"][0])
        except Exception:
            near = place or G.rlookup(lat, lon)
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
                            _wxb["v"] = R.weather(lon, lat, TOKEN, "en_US" if lang == "en" else "zh_CN")
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
                R.weather_start(lon, lat, TOKEN,
                                "en_US" if lang == "en" else "zh_CN")
                out = R.build_fetching(lang, label)
                return self._send(200, out)
            _t_wx = time.time() - _t; _t = time.time()
            out = R.build(lang, label, code, label, lon, lat, tzh, wx, rb,
                          radar_err=radar_err, radar_state=radar_state)
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
