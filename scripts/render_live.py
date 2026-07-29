#!/usr/bin/env python3
"""Render LLM-readable weather briefs for a set of cities.
Runs in GitHub Actions on a schedule; output = plain text an agent can curl.
Data source: caiyunapp.com (attribution required). Token via env CAIYUN_TOKEN."""
import json, os, sys, time, urllib.request

CITIES = [
    # name, lng, lat, tz_offset_hours
    ("beijing",    116.4074,  39.9042, 8),
    ("shanghai",   121.4737,  31.2304, 8),
    ("guangzhou",  113.2644,  23.1291, 8),
    ("london",      -0.1276,  51.5072, 0),
    ("newyork",    -74.0060,  40.7128, -4),
    ("singapore",  103.8198,   1.3521, 8),
    ("chiangmai",   98.9853,  18.7883, 7),
    ("bangkok",    100.5018,  13.7563, 7),
]
BARS = "▁▂▃▄▅▆▇█"

def spark(vals, vmax=None):
    if not vals: return ""
    vmax = vmax or max(vals) or 1.0
    return "".join(BARS[min(int(v / vmax * 7.999), 7)] if v > 0 else " " for v in vals)

def brief(name, lng, lat, tzh, token):
    url = f"https://api.caiyunapp.com/v2.6/{token}/{lng},{lat}/weather?hourlysteps=24&dailysteps=1"
    with urllib.request.urlopen(url, timeout=20) as r:
        d = json.load(r)
    if d.get("status") != "ok":
        raise RuntimeError(f"api status {d.get('status')}")
    res = d["result"]
    rt = res["realtime"]
    hourly = res["hourly"]
    minutely = res.get("minutely", {})
    kp = res.get("forecast_keypoint", "")
    now = time.gmtime(time.time() + tzh * 3600)
    stamp = time.strftime("%Y-%m-%d %H:%M", now)

    p2h = minutely.get("precipitation_2h", [])[:120]
    prob = minutely.get("probability", [])
    hp = [h["value"] for h in hourly.get("precipitation", [])][:24]
    ht = [h["value"] for h in hourly.get("temperature", [])][:24]
    hs = [h["value"] for h in hourly.get("skycon", [])][:24]

    L = []
    L.append(f"# {name}  ({lng},{lat})  local {stamp}  UTC{'+' if tzh>=0 else ''}{tzh}")
    L.append(f"now: {rt['skycon']}  temp {rt['temperature']:.0f}C  humidity {rt['humidity']*100:.0f}%  "
             f"wind {rt['wind']['speed']:.0f}km/h  precip {rt['precipitation']['local']['intensity']:.2f}")
    if p2h:
        mx = max(p2h)
        L.append(f"next 2h rain (per min, max={mx:.2f}): {spark(p2h[::5], vmax=max(mx,0.1))}")
        if prob: L.append(f"rain probability 30min bins: {' '.join(f'{p*100:.0f}%' for p in prob)}")
    if hp:
        L.append(f"next 24h precip (mm/h): {spark(hp, vmax=max(max(hp),0.5))}  peak {max(hp):.1f}")
        L.append(f"next 24h temp {min(ht):.0f}..{max(ht):.0f}C: {spark([t-min(ht) for t in ht], vmax=max(max(ht)-min(ht),1))}")
        # compact skycon transitions
        trans, cur = [], None
        for i, s in enumerate(hs):
            if s != cur: trans.append(f"+{i}h:{s}"); cur = s
        L.append("sky: " + " ".join(trans[:6]))
    if kp: L.append(f"keypoint: {kp}")
    L.append("data: caiyunapp.com | rendered by runemap (github.com/eirik-rune/runemap)")
    return "\n".join(L) + "\n"

def main():
    token = os.environ.get("CAIYUN_TOKEN", "")
    if not token:
        sys.exit("CAIYUN_TOKEN missing")
    os.makedirs("live", exist_ok=True)
    index = [f"# runemap live — text weather for agents  (updated {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())})", ""]
    ok = fail = 0
    for name, lng, lat, tzh in CITIES:
        try:
            txt = brief(name, lng, lat, tzh, token)
            open(f"live/{name}.txt", "w").write(txt)
            first = txt.splitlines()[1]
            index.append(f"{name:<10} {first}")
            ok += 1
        except Exception as e:
            index.append(f"{name:<10} ERROR {e}")
            fail += 1
        time.sleep(0.3)
    index.append("")
    index.append("per-city: live/<city>/en live/<city>/zh (one-screen scene) | live/<city>.txt (brief) | live/<city>_radar.txt (radar)")
    index.append("cities: " + ", ".join(c[0] for c in CITIES))
    open("live/index.txt", "w").write("\n".join(index) + "\n")
    print(f"rendered ok={ok} fail={fail}")
    if ok == 0: sys.exit(1)

if __name__ == "__main__":
    main()
