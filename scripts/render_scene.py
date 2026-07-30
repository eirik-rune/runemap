#!/usr/bin/env python3
"""Bilingual one-screen weather scene for agents.
Outputs: live/<city>/en and live/<city>/zh
Layout: headline + 2h rain curve (6min buckets) + current radar map + legend.
Radar art fetched ONCE per city, shared across languages.
Data source: caiyunapp.com. Token via env CAIYUN_TOKEN."""
import json, os, sys, time, urllib.request, tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from runemap.render import ascii_radar
import threading

import os as _o, sys as _s
_s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__)))
from cities import CITIES
try:
    _MOTION = json.load(open("live/_motion.json"))
except Exception:
    _MOTION = {}
SKY_ZH = {"CLEAR_DAY":"\u6674","CLEAR_NIGHT":"\u6674","PARTLY_CLOUDY_DAY":"\u591a\u4e91","PARTLY_CLOUDY_NIGHT":"\u591a\u4e91",
"CLOUDY":"\u9634","LIGHT_HAZE":"\u8f7b\u96fe\u973e","MODERATE_HAZE":"\u4e2d\u96fe\u973e","HEAVY_HAZE":"\u91cd\u96fe\u973e",
"LIGHT_RAIN":"\u5c0f\u96e8","MODERATE_RAIN":"\u4e2d\u96e8","HEAVY_RAIN":"\u5927\u96e8","STORM_RAIN":"\u66b4\u96e8",
"FOG":"\u96fe","LIGHT_SNOW":"\u5c0f\u96ea","MODERATE_SNOW":"\u4e2d\u96ea","HEAVY_SNOW":"\u5927\u96ea","STORM_SNOW":"\u66b4\u96ea",
"DUST":"\u6d6e\u5c18","SAND":"\u6c99\u5c18","WIND":"\u5927\u98ce"}
BARS = "\u2581\u2582\u2583\u2584\u2585\u2586\u2587\u2588"
AXIS = '├────┼────┼────┼────┤\n0   30   60   90 120min'

def _get(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": "runemap/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()

def spark(vals, vmax=None):
    vmax = vmax or max(vals) or 1.0
    return "".join(BARS[min(int(v / vmax * 7.999), 7)] if v > 0 else " " for v in vals)

def weather(lng, lat, token, lang):
    d = json.loads(_get("https://api.caiyunapp.com/v2.6/%s/%s,%s/weather?hourlysteps=24&lang=%s" % (token, lng, lat, lang)))
    if d.get("status") != "ok":
        raise RuntimeError("weather api %s" % d.get("status"))
    return d["result"]

_MO_CACHE = {}
_MO_TTL = 600

_MO_BUSY = set()

def _motion_compute(key, imgs):
    mo = {"kind": None}
    try:
        frames = [(f[0], float(f[1]), f[2]) for f in imgs if len(f) >= 3 and f[2]]
        import echo_motion as EM
        EM._get = _get          # picks up the cached getter
        mo = EM.echo_motion(frames) or {"kind": None}
    except Exception:
        mo = {"kind": None}
    _MO_CACHE[key] = (time.time(), mo)
    _MO_BUSY.discard(key)

def _motion_now(imgs, lng, lat):
    """Echo motion, computed OFF the response path.

    It needs ~6 extra radar PNGs plus cross-correlation: measured 5-7s warm and
    >60s for Tokyo (504). Motion is only a suffix on the radar headline, so it
    must never block the map. First request returns without it; a background
    thread fills the cache and every later request inside TTL carries it.
    The old code read a prebuilt live/_motion.json keyed by city name -- a
    relative path the service never had (always {}), and name-keyed so an
    arbitrary coordinate could never be answered at all."""
    key = (round(float(lat), 1), round(float(lng), 1))
    hit = _MO_CACHE.get(key)
    if hit and time.time() - hit[0] < _MO_TTL:
        return hit[1]
    if key not in _MO_BUSY:
        _MO_BUSY.add(key)
        threading.Thread(target=_motion_compute, args=(key, imgs), daemon=True).start()
    return (hit[1] if hit else {"kind": None})

def _mark(code):
    """The in-grid marker must be strictly single-width, so it is ASCII only.
    Emoji (house, pushpin) are East_Asian_Width=Wide: one character, two columns,
    so the row becomes 49 wide and the whole 48-column map shears. Arrows
    (U+2192, U+2198) are Ambiguous: single-width in a Latin terminal, double in a
    CJK one -- a Chinese reader would see a sheared map that I cannot reproduce
    locally. Direction belongs on the legend line, which is prose and does not
    have to align; it already carries the motion arrow.
    Two cells: '><' brackets the spot, and a lone glyph is genuinely hard to find
    in a field of shade characters -- a map you cannot locate yourself on is not a
    map. It does hide ~20km of rain; being findable wins that trade."""
    c = "".join(ch for ch in (code or "") if 32 < ord(ch) < 127)[:2]
    return c or "><"


def radar_art(code, lng, lat, token):
    code = _mark(code)
    try:
        d = json.loads(_get("https://api.caiyunapp.com/v1/radar/images?token=%s&lon=%s&lat=%s" % (token, lng, lat)))
    except Exception:
        return None
    imgs = d.get("images") or []
    if not imgs:
        return None
    url, ts, bbox = imgs[-1][0], float(imgs[-1][1]), imgs[-1][2]
    png = _get(url, timeout=20)
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(png); p = f.name
    try:
        art, kmcol = ascii_radar(p, bbox, lng, lat, cols=48, rows=24, marker=code)
        return art, kmcol, ts, _motion_now(imgs, lng, lat)
    finally:
        os.unlink(p)

def build(lang, name, code, zh, lng, lat, tzh, wx, rb):
    code = _mark(code)   # legend and grid must show the same glyph
    rt = wx["realtime"]
    kp = (wx.get("forecast_keypoint") or wx.get("minutely", {}).get("description", "")).strip()
    p2h = wx.get("minutely", {}).get("precipitation_2h", [])[:120]
    stamp = time.strftime("%Y-%m-%d %H:%M", time.gmtime(time.time() + tzh * 3600))
    L = []
    if lang == "en":
        L.append("# %s weather scene  updated %s local time  (lon %s, lat %s)" % (name, stamp, lng, lat))
        L.append("now: %s  %.0fC  humidity %.0f%%  wind %.0fkm/h  precip %.2fmm/h" % (
            rt["skycon"], rt["temperature"], rt["humidity"]*100, rt["wind"]["speed"],
            rt["precipitation"]["local"]["intensity"]))
    else:
        sky = SKY_ZH.get(rt["skycon"], rt["skycon"])
        L.append("# %s \u5929\u6c14\u4e00\u5c4f  \u66f4\u65b0\u4e8e\u5f53\u5730\u65f6\u95f4 %s  (\u7ecf\u5ea6 %s, \u7eac\u5ea6 %s)" % (zh, stamp, lng, lat))
        L.append("\u5f53\u524d: %s  %.0fC  \u6e7f\u5ea6 %.0f%%  \u98ce\u901f %.0fkm/h  \u96e8\u5f3a %.2fmm/h" % (
            sky, rt["temperature"], rt["humidity"]*100, rt["wind"]["speed"],
            rt["precipitation"]["local"]["intensity"]))
    if kp:
        L.append(kp)
    mo = (rb[3] if rb and len(rb) > 3 else None) or _MOTION.get(name) or {}
    if mo.get("kind") == "moving":
        mo_sfx = (("  |  echo motion(1h obs): %s %s ~%.0f km/h" % (mo["arrow"], mo["dir_en"], mo["kmh"]))
                  if lang == "en" else
                  ("  |  \u56de\u6ce2\u79fb\u52a8(\u8fd11h\u5b9e\u6d4b): %s %s ~%.0f km/h" % (mo["arrow"], mo["dir_cn"], mo["kmh"])))
    elif mo.get("kind") == "stationary":
        mo_sfx = ("  |  echo quasi-stationary(<5km/h, 1h obs)" if lang == "en"
                  else "  |  \u56de\u6ce2\u51c6\u9759\u6b62(<5km/h, \u8fd11h\u5b9e\u6d4b)")
    else:
        mo_sfx = ""
    # The arrow goes on its own line under the map, flush left, where the eye lands
    # after finishing the grid. It stays OUT of the grid on purpose: arrows are
    # East_Asian_Width=Ambiguous, one column in a Latin terminal and two in a CJK
    # one, so putting one in a 48-column row would shear the map for exactly the
    # readers whose terminals I cannot reproduce here.
    # Just the glyph, flush left under the map. The reading already sits on the
    # legend line above, so repeating it here would only bury the one thing this
    # line exists for: a mark the eye cannot miss. It is deliberately below the
    # grid rather than inside it -- arrows are East_Asian_Width=Ambiguous, one
    # column in a Latin terminal and two in a CJK one, so a 48-column row holding
    # one would shear for exactly the readers I cannot reproduce locally.
    if mo.get("kind") == "moving":
        mo_line = mo["arrow"]
    elif mo.get("kind") == "stationary":
        mo_line = "="
    else:
        mo_line = ""
    L.append("")
    if p2h and max(p2h) > 0:
        buckets = [round(max(p2h[i*6:(i+1)*6]), 2) for i in range(20)]
        L.append("rain curve (next 2h, 6min/bucket):" if lang == "en" else "\u96e8\u91cf\u66f2\u7ebf(\u672a\u67652h, 6min/\u683c):")
        L.append(spark(buckets))
        L.append(AXIS)
    else:
        L.append("rain curve (next 2h): no precipitation expected" if lang == "en"
                 else "\u96e8\u91cf\u66f2\u7ebf(\u672a\u67652h): \u65e0\u964d\u6c34")
    L.append("")
    if rb:
        art, kmcol, ts = rb[0], rb[1], rb[2]
        t = time.strftime("%H:%M", time.gmtime(ts + tzh * 3600))
        if lang == "en":
            L.append("radar now (%s local), ~%.0fkm/char, [%s]=%s" % (t, kmcol, code, name) + mo_sfx)
            L.append(art)
            if mo_line:
                L.append(mo_line)
            L.append("legend: \u00b7 drizzle  \u2591 light  \u2592 moderate  \u2593 heavy  \u2588 storm")
        else:
            L.append("\u96f7\u8fbe\u5b9e\u51b5 (\u5f53\u5730 %s), \u6bcf\u5b57\u7b26\u2248%.0fkm, [%s]=%s" % (t, kmcol, code, zh) + mo_sfx)
            L.append(art)
            if mo_line:
                L.append(mo_line)
            L.append("\u56fe\u4f8b: \u00b7 \u6bdb\u6bdb\u96e8  \u2591 \u5c0f\u96e8  \u2592 \u4e2d\u96e8  \u2593 \u5927\u96e8  \u2588 \u66b4\u96e8")
    else:
        L.append("radar: no coverage here (text brief: live/%s.txt)" % name if lang == "en"
                 else "\u96f7\u8fbe: \u8be5\u4f4d\u7f6e\u65e0\u96f7\u8fbe\u8986\u76d6 (\u6587\u672c\u7b80\u62a5: live/%s.txt)" % name)
    L.append("")
    L.append("data: Caiyun Weather caiyunapp.com | rendered by runemap (github.com/eirik-rune/runemap)" if lang == "en"
             else "\u6570\u636e: \u5f69\u4e91\u5929\u6c14 caiyunapp.com | runemap \u6e32\u67d3 (github.com/eirik-rune/runemap)")
    return "\n".join(L) + "\n"

def main():
    token = os.environ.get("CAIYUN_TOKEN") or sys.exit("CAIYUN_TOKEN missing")
    only = sys.argv[1] if len(sys.argv) > 1 else None
    ok = 0
    for name, code, zh, lng, lat, tzh in CITIES:
        if only and name != only:
            continue
        try:
            wx_en = weather(lng, lat, token, "en_US")
            wx_zh = weather(lng, lat, token, "zh_CN")
            rb = radar_art(code, lng, lat, token)
            os.makedirs("live/%s" % name, exist_ok=True)
            open("live/%s/en" % name, "w").write(build("en", name, code, zh, lng, lat, tzh, wx_en, rb))
            open("live/%s/zh" % name, "w").write(build("zh", name, code, zh, lng, lat, tzh, wx_zh, rb))
            ok += 1; print("%s ok" % name)
        except Exception as e:
            print("%s FAIL %r" % (name, e))
        time.sleep(0.2)
    if ok == 0: sys.exit(1)

if __name__ == "__main__":
    main()
