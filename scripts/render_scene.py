#!/usr/bin/env python3
"""Bilingual one-screen weather scene for agents.
Outputs: live/<city>/en and live/<city>/zh
Layout: headline + 2h rain curve (6min buckets) + current radar map + legend.
Radar art fetched ONCE per city, shared across languages.
Data source: caiyunapp.com. Token via env CAIYUN_TOKEN."""
import json, os, sys, time, urllib.request, tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from runemap.render import ascii_radar

CITIES = [
    ("beijing",   "BJ", "\u5317\u4eac",   116.4074, 39.9042, 8),
    ("shanghai",  "SH", "\u4e0a\u6d77",   121.4737, 31.2304, 8),
    ("guangzhou", "GZ", "\u5e7f\u5dde",   113.2644, 23.1291, 8),
    ("london",    "LD", "\u4f26\u6566",    -0.1276, 51.5072, 0),
    ("newyork",   "NY", "\u7ebd\u7ea6",   -74.0060, 40.7128, -4),
    ("singapore", "SG", "\u65b0\u52a0\u5761", 103.8198, 1.3521, 8),
    ("chiangmai", "CM", "\u6e05\u8fc8",    98.9853, 18.7883, 7),
    ("bangkok",   "BK", "\u66fc\u8c37",   100.5018, 13.7563, 7),
]
SKY_ZH = {"CLEAR_DAY":"\u6674","CLEAR_NIGHT":"\u6674","PARTLY_CLOUDY_DAY":"\u591a\u4e91","PARTLY_CLOUDY_NIGHT":"\u591a\u4e91",
"CLOUDY":"\u9634","LIGHT_HAZE":"\u8f7b\u96fe\u973e","MODERATE_HAZE":"\u4e2d\u96fe\u973e","HEAVY_HAZE":"\u91cd\u96fe\u973e",
"LIGHT_RAIN":"\u5c0f\u96e8","MODERATE_RAIN":"\u4e2d\u96e8","HEAVY_RAIN":"\u5927\u96e8","STORM_RAIN":"\u66b4\u96e8",
"FOG":"\u96fe","LIGHT_SNOW":"\u5c0f\u96ea","MODERATE_SNOW":"\u4e2d\u96ea","HEAVY_SNOW":"\u5927\u96ea","STORM_SNOW":"\u66b4\u96ea",
"DUST":"\u6d6e\u5c18","SAND":"\u6c99\u5c18","WIND":"\u5927\u98ce"}
BARS = "\u2581\u2582\u2583\u2584\u2585\u2586\u2587\u2588"
AXIS = "now       +30min    +60min    +90min   +120min"

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

def radar_art(code, lng, lat, token):
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
        return art, kmcol, ts
    finally:
        os.unlink(p)

def build(lang, name, code, zh, lng, lat, tzh, wx, rb):
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
    L.append("")
    if p2h and max(p2h) > 0:
        buckets = [round(max(p2h[i*6:(i+1)*6]), 2) for i in range(20)]
        L.append("rain curve (next 2h, 6min/bucket):" if lang == "en" else "\u96e8\u91cf\u66f2\u7ebf(\u672a\u67652h, 6min/\u683c):")
        L.append(spark(buckets))
        L.append(AXIS)
        L.append(("bucket max (mm/h): " if lang == "en" else "\u5404\u683c\u5cf0\u503c(mm/h): ") + str(buckets))
    else:
        L.append("rain curve (next 2h): no precipitation expected" if lang == "en"
                 else "\u96e8\u91cf\u66f2\u7ebf(\u672a\u67652h): \u65e0\u964d\u6c34")
    L.append("")
    if rb:
        art, kmcol, ts = rb
        t = time.strftime("%H:%M", time.gmtime(ts + tzh * 3600))
        if lang == "en":
            L.append("radar now (%s local), ~%.0fkm/char, [%s]=%s" % (t, kmcol, code, name))
            L.append(art)
            L.append("legend: \u00b7 drizzle  \u2591 light  \u2592 moderate  \u2593 heavy  \u2588 storm")
        else:
            L.append("\u96f7\u8fbe\u5b9e\u51b5 (\u5f53\u5730 %s), \u6bcf\u5b57\u7b26\u2248%.0fkm, [%s]=%s" % (t, kmcol, code, zh))
            L.append(art)
            L.append("\u56fe\u4f8b: \u00b7 \u6bdb\u6bdb\u96e8  \u2591 \u5c0f\u96e8  \u2592 \u4e2d\u96e8  \u2593 \u5927\u96e8  \u2588 \u66b4\u96e8")
    else:
        L.append("radar: no coverage here (text brief: live/%s.txt)" % name if lang == "en"
                 else "\u96f7\u8fbe: \u8be5\u4f4d\u7f6e\u65e0\u96f7\u8fbe\u8986\u76d6 (\u6587\u672c\u7b80\u62a5: live/%s.txt)" % name)
    L.append("")
    L.append("data: caiyunapp.com | rendered by runemap (github.com/eirik-rune/runemap)" if lang == "en"
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
