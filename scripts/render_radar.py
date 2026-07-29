#!/usr/bin/env python3
"""Three-frame ascii radar with lon/lat axes: t-1h obs, now, t+1h forecast.
Global radar where caiyun has coverage (probed at runtime; e.g. NYC has none).
Axes: left column = latitude, bottom row = longitude (degrees).
Data source: caiyunapp.com. Token via env CAIYUN_TOKEN."""
import json, os, sys, time, urllib.request, tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from runemap.render import ascii_radar

import os as _o, sys as _s
_s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__)))
from cities import CITIES as _ALL
CITIES = [(n, lng, lat, tz) for (n, _c, _z, lng, lat, tz) in _ALL]

def _get(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": "runemap/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()

def frames_of(payload):
    d = json.loads(payload)
    out = []
    for it in d.get("images") or []:
        if isinstance(it, (list, tuple)) and len(it) >= 2:
            out.append((it[0], float(it[1]), it[2] if len(it) > 2 else None))
    return out

def pick(frames, target_ts):
    return min(frames, key=lambda f: abs(f[1] - target_ts))

def render_frame(url, bbox, lng, lat):
    png = _get(url)
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(png); p = f.name
    try:
        art, kmcol = ascii_radar(p, bbox, lng, lat, cols=48, rows=24, marker="+")
        return art, kmcol
    finally:
        os.unlink(p)

def labeled(art, bbox):
    """add lat labels on the left edge, lon labels along the bottom (ASCII only)."""
    lat0, lon0, lat1, lon1 = bbox
    rows = art.split("\n")
    n = len(rows)
    out = []
    for i, r in enumerate(rows):
        lat = lat1 - (lat1 - lat0) * (i / (n - 1)) if n > 1 else lat1
        pre = ("%6.2f|" % lat) if i in (0, n // 2, n - 1) else "      |"
        out.append(pre + r)
    w = max(len(r) for r in rows)
    out.append("      +" + "-" * w)
    bot = [" "] * (7 + w)
    def put(s, pos):
        for j, ch in enumerate(s):
            k = pos + j
            if 0 <= k < len(bot): bot[k] = ch
    put("%.2f" % lon0, 7)
    mid = "%.2f" % ((lon0 + lon1) / 2)
    put(mid, 7 + w // 2 - len(mid) // 2)
    rgt = "%.2f" % lon1
    put(rgt, 7 + w - len(rgt))
    out.append("".join(bot))
    return "\n".join(out)

def city_radar(name, lng, lat, token, tzh=8):
    now = time.time()
    obs = []
    for _try in range(3):  # global source flaps 200-with-0-frames ~50%: retry
        obs = frames_of(_get(f"https://api.caiyunapp.com/v1/radar/images?token={token}&lon={lng}&lat={lat}"))
        if obs:
            break
        time.sleep(2)
    fc  = frames_of(_get(f"https://api.caiyunapp.com/v1/radar/forecast_images?token={token}&lon={lng}&lat={lat}"))
    if not obs:
        raise RuntimeError("no obs frames")
    tz = tzh * 3600
    def stamp(ts): return time.strftime("%H:%M", time.gmtime(ts + tz))
    picks = [("t-1h obs", pick(obs, now - 3600)), ("now obs", obs[-1])]
    if fc:
        picks.append(("t+1h forecast", pick(fc, now + 3600)))
    blocks, km = [], None
    for lbl, fr in picks:
        art, kmcol = render_frame(fr[0], fr[2], lng, lat)
        km = km or kmcol
        blocks.append((lbl, stamp(fr[1]), labeled(art, fr[2])))
    L = [f"# {name} radar  center=({lng},{lat}) marked '+'  48x24 ascii, ~{km:.1f}km/col",
         f"# local {time.strftime('%Y-%m-%d %H:%M', time.gmtime(now + tz))}  axes: left=lat deg, bottom=lon deg",
         f"# intensity ramp: ' ' none, '.' drizzle, then light->storm as blocks fill", ""]
    for lbl, st, art in blocks:
        L.append(f"## {lbl} ({st})")
        L.append(art)
        L.append("")
    L.append("data: caiyunapp.com | rendered by runemap (github.com/eirik-rune/runemap)")
    return "\n".join(L) + "\n"

def main():
    token = os.environ.get("CAIYUN_TOKEN") or sys.exit("CAIYUN_TOKEN missing")
    os.makedirs("live", exist_ok=True)
    ok = 0
    for name, lng, lat, tzh in CITIES:
        try:
            open(f"live/{name}_radar.txt", "w").write(city_radar(name, lng, lat, token, tzh))
            ok += 1; print(f"{name} ok")
        except Exception as e:
            if "no obs frames" in str(e) or "404" in str(e):
                # transient empty response? keep last good frame instead of clobbering
                path = f"live/{name}_radar.txt"
                prev = ""
                try:
                    prev = open(path).read()
                except Exception:
                    pass
                if prev and "no radar coverage" not in prev:
                    print(f"{name} empty-frames, kept previous good radar")
                else:
                    open(path, "w").write(
                        f"# {name} radar: no radar coverage at this location (data: caiyunapp.com)\n"
                        f"# text brief still available: live/{name}.txt\n")
                    print(f"{name} no-coverage stub")
            else:
                print(f"{name} FAIL {e}")
        time.sleep(0.3)
    if ok == 0: sys.exit(1)

if __name__ == "__main__":
    main()
