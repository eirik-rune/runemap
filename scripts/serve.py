#!/usr/bin/env python3
"""runemap HTTP service: GET /scene?lat=..&lon=..&lang=en|zh[&label=..&tz=..]
Any coordinate on earth, rendered on demand. Radar PNGs cached (see scene_at).
Bind 127.0.0.1 by default -- no public exposure."""
import os, sys, time, traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scene_at as SA          # installs the radar cache layer on render_scene._get
import render_scene as R
import geo as G

TOKEN = os.environ.get("CAIYUN_TOKEN") or sys.exit("CAIYUN_TOKEN missing")
HITS = {"n": 0, "err": 0}


HOME = """echorune - text radar map for agents
=====================================

Weather rendered as characters, so LLM agents that cannot read images
can still see the rain.

USAGE
  GET /scene?q=<place>              e.g. /scene?q=Bangkok
  GET /scene?lat=<lat>&lon=<lon>    e.g. /scene?lat=13.75&lon=100.50
  optional  &lang=en|zh             default en
  GET /healthz

EXAMPLES
  curl -L "https://echorune.net/scene?q=Reykjavik&lang=zh"
  curl -L "https://echorune.net/scene?lat=51.51&lon=-0.13"

WHAT YOU GET
  One screen: current conditions, a plain-language forecast, a 2h rain
  sparkline, and a 48x24 character radar map with lon/lat axes.

PLACE NAMES
  170k settlements including CJK aliases (GeoNames cities1000, CC-BY 4.0).
  Any coordinate on earth works, named or not.

SOURCE
  MIT: github.com/eirik-rune/runemap   (self-host with your own API key)
  Weather data: caiyunapp.com

echorune is a zero-person company: support, development and ops are the
same inference loop. File anything at
github.com/eirik-rune/runemap/issues
"""

class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, code, body, ctype="text/plain; charset=utf-8"):
        b = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Type", ctype)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "public, max-age=300")
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path in ("/healthz", "/health"):
                return self._send(200, "ok n=%d err=%d\n" % (HITS["n"], HITS["err"]))
        if u.path == "/" and not q:
                return self._send(200, HOME)
        if u.path not in ("/scene", "/"):
                return self._send(404, "usage: /scene?lat=23.13&lon=113.26&lang=en|zh\n")
        place = None
        if q.get("q"):
            place = G.lookup(q["q"][0])
            if not place:
                return self._send(404, "place not found: %s\n" % q["q"][0][:60])
            lat, lon = place["lat"], place["lon"]
        else:
            try:
                lat = round(float(q["lat"][0]), 3); lon = round(float(q["lon"][0]), 3)
            except Exception:
                return self._send(400, "usage: /scene?q=bangkok  OR  /scene?lat=13.75&lon=100.50 [&lang=en|zh]\n")
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                return self._send(400, "lat/lon out of range\n")
        lang = (q.get("lang", ["en"])[0] or "en").lower()
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
        code = ((q.get("code", ["><"])[0]) + "><")[:2]
        import urllib.parse
        c_qs = f"lat={lat:.3f}&lon={lon:.3f}&lang={lang}&label={urllib.parse.quote(label)}&tz={tzh}&code={urllib.parse.quote(code)}"
        canonical_url = f"/scene?{c_qs}"

        try:
            wx = R.weather(lon, lat, TOKEN, "en_US" if lang == "en" else "zh_CN")
            rb = R.radar_art(code, lon, lat, TOKEN)
            out = R.build(lang, label, code, label, lon, lat, tzh, wx, rb)
            HITS["n"] += 1
            self._send(200, out)
        except Exception as e:
            HITS["err"] += 1
            sys.stderr.write("ERR %r\n%s" % (e, traceback.format_exc()))
            self._send(502, "upstream error: %s\n" % type(e).__name__)

    def log_message(self, fmt, *a):
        sys.stderr.write("%s %s\n" % (time.strftime("%F %T"), fmt % a))


if __name__ == "__main__":
    host = os.environ.get("RUNEMAP_HOST", "127.0.0.1")
    port = int(os.environ.get("RUNEMAP_PORT", "8788"))
    print("serving http://%s:%d/scene?lat=..&lon=.." % (host, port))
    ThreadingHTTPServer((host, port), H).serve_forever()
