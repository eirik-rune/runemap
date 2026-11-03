"""The weather for one place as one long, phone-width picture.

bob 2026-11-03: "open one png and it is the whole weather, now". Then, from
his phone: a square leaves half the screen black and its 14 px labels come
out tiny -- make it a long picture.

Sized for a phone, not a monitor. 1080 px wide is shown at roughly 400 css px,
so body text is ~34-42 image px to read like ordinary app text, and the radar
is drawn with its labels scaled up RELATIVE to the map (radar_image ui=),
because an upscale grows the map along with the words.

Top to bottom is near to far: now -> the next two hours (the one sentence,
the radar, the curve at your point) -> 24 hours -> the coming days.

Every block says when its data is from, in local time. Weather and radar are
cached separately and can be minutes apart; one clock at the top would claim
both are as fresh as the fresher one.

Everything comes from the same Caiyun weather response the text map uses and
the same radar frame and motion vector -- one request upstream, two renderings.
"""
import io
import math
import threading
from datetime import datetime, timezone

import numpy as np
from PIL import Image, ImageDraw

from . import radar_image as RI

F = RI._font
INK = (30, 34, 42); DIM = (96, 102, 114); FAINT = (226, 229, 234)
BG = (244, 245, 247); CARD = (255, 255, 255)
TEMP = (214, 96, 52); RAIN = (44, 112, 190); RAIN_L = (186, 212, 240)
W = 1080; PAD = 36; IN = 40
RADAR_UI = 2.2

# One picture at a time per process. A render peaks ~100 MB above the
# process's resting size (measured: canvas 15, radar block, quantize 17), and
# this box has ~1 GB with other people's traffic on it; N links opened at
# once must not mean N times that. Waiting a second is cheaper than swapping.
_RENDER_LOCK = threading.Lock()

SKY = {"CLEAR_DAY": "clear", "CLEAR_NIGHT": "clear", "PARTLY_CLOUDY_DAY": "partly cloudy",
       "PARTLY_CLOUDY_NIGHT": "partly cloudy", "CLOUDY": "cloudy", "LIGHT_HAZE": "light haze",
       "MODERATE_HAZE": "haze", "HEAVY_HAZE": "heavy haze", "LIGHT_RAIN": "light rain",
       "MODERATE_RAIN": "rain", "HEAVY_RAIN": "heavy rain", "STORM_RAIN": "storm",
       "FOG": "fog", "LIGHT_SNOW": "light snow", "MODERATE_SNOW": "snow",
       "HEAVY_SNOW": "heavy snow", "STORM_SNOW": "snowstorm", "DUST": "dust",
       "SAND": "sand", "WIND": "windy"}
COMPASS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]


def icon(d, x, y, s, sky):
    """A small drawn glyph (no emoji font on this box). (x, y) centre, s size."""
    sky = sky or ""
    sun = "CLEAR" in sky or "PARTLY" in sky
    cloud = sky not in ("CLEAR_DAY", "CLEAR_NIGHT")
    rain, snow, night = "RAIN" in sky, "SNOW" in sky, "NIGHT" in sky
    lw = max(2, round(s / 30))
    if sun:
        cx, cy = (x - s * .18, y - s * .18) if cloud else (x, y)
        r = s * (.22 if cloud else .3)
        if night:
            d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(120, 130, 160))
            d.ellipse((cx - r * .5, cy - r * 1.2, cx + r * 1.5, cy + r * .8), fill=CARD)
        else:
            for k in range(8):
                a = k * math.pi / 4
                d.line((cx + math.cos(a) * r * 1.3, cy + math.sin(a) * r * 1.3,
                        cx + math.cos(a) * r * 1.7, cy + math.sin(a) * r * 1.7),
                       fill=(236, 170, 40), width=lw)
            d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(246, 190, 50))
    if cloud:
        col = (150, 158, 172) if (rain or snow or sky == "CLOUDY") else (190, 196, 206)
        cy = y - s * .02
        d.ellipse((x - s * .38, cy - s * .08, x + s * .02, cy + s * .22), fill=col)
        d.ellipse((x - s * .18, cy - s * .26, x + s * .22, cy + s * .14), fill=col)
        d.ellipse((x, cy - s * .1, x + s * .4, cy + s * .22), fill=col)
        d.rectangle((x - s * .24, cy + s * .04, x + s * .26, cy + s * .22), fill=col)
    if rain:
        for k in range(3 if "LIGHT" in sky else 4):
            xx = x - s * .22 + k * s * .16
            d.line((xx, y + s * .28, xx - s * .06, y + s * .42), fill=RAIN, width=lw)
    if snow:
        for k in range(3):
            xx = x - s * .2 + k * s * .2
            d.ellipse((xx - lw, y + s * .3, xx + lw, y + s * .3 + 2 * lw), fill=(120, 160, 210))


def _card(d, y, h, title=None, note=None):
    d.rounded_rectangle((PAD, y, W - PAD, y + h), radius=28, fill=CARD)
    if title:
        d.text((PAD + IN, y + 30), title, font=F(30), fill=DIM)
    if note:
        f = F(26)
        d.text((W - PAD - IN - f.getlength(note), y + 33), note, font=f, fill=DIM)


def _local(ts, tz):
    return datetime.fromtimestamp(float(ts) + tz, timezone.utc)


def _centre(d, x, y, text, font, fill):
    d.text((x - font.getlength(text) / 2, y), text, font=font, fill=fill)


def render(wx_full, radar, label, motion=None, basis=None, span_km=200.0, radar_note=None):
    with _RENDER_LOCK:
        return _render(wx_full, radar, label, motion, basis, span_km, radar_note)


def height(wx_full, radar, radar_note=None):
    """The exact canvas height, so no oversized canvas and no crop copy.
    Must add up the same blocks _render draws; a test holds them together."""
    r = wx_full["result"]; mi, hr, dy = r["minutely"], r["hourly"], r["daily"]
    h = 44 + 146 + 360
    if (mi.get("description") or r.get("forecast_keypoint") or "").strip():
        h += 180
    if radar:
        h += (W - 2 * PAD) + 290 + 30
    elif radar_note:
        h += 180
    if mi.get("precipitation_2h"):
        h += 590
    if hr["temperature"]:
        h += 590
    if dy.get("temperature"):
        h += 130 + len(dy["temperature"]) * 112
    if (dy.get("astro") or [None])[0]:
        h += 70
    return h + 60


def _render(wx_full, radar, label, motion, basis, span_km, radar_note):
    """-> PNG bytes.

    wx_full  the whole Caiyun weather response (result + server_time + tzshift)
    radar    None, or dict(png, bbox, ts, obs_ts, lon, lat) -- the frame the
             text map draws
    """
    r = wx_full["result"]; tz = int(wx_full.get("tzshift") or 0)
    rt, mi, hr, dy = r["realtime"], r["minutely"], r["hourly"], r["daily"]
    H = height(wx_full, radar, radar_note)
    im = Image.new("RGB", (W, H), BG); d = ImageDraw.Draw(im)
    wx_at = _local(wx_full["server_time"], tz)

    # --- place and now ------------------------------------------------------
    y = 44
    d.text((PAD + 8, y), label.split(",")[0].strip(), font=F(60), fill=INK)
    d.text((PAD + 10, y + 80), wx_at.strftime("%a %d %b"), font=F(32), fill=DIM)
    y += 146
    _card(d, y, 330, note="as of %s local" % wx_at.strftime("%H:%M"))
    icon(d, PAD + 140, y + 150, 190, rt.get("skycon"))
    d.text((PAD + 270, y + 46), "%.0f°" % rt["temperature"], font=F(150), fill=INK)
    d.text((PAD + 560, y + 84), SKY.get(rt.get("skycon"), ""), font=F(48), fill=INK)
    d.text((PAD + 560, y + 148), "feels %.0f°" % rt["apparent_temperature"], font=F(36), fill=DIM)
    wind = rt.get("wind") or {}
    wdir = COMPASS[int((float(wind.get("direction", 0)) + 22.5) // 45) % 8]
    aqi = ((rt.get("air_quality") or {}).get("aqi") or {}).get("chn")
    row = ["humidity %d%%" % round(rt["humidity"] * 100),
           "wind %s %.0f km/h" % (wdir, float(wind.get("speed", 0)))]
    if aqi is not None:
        row.append("AQI %s" % aqi)
    d.text((PAD + IN, y + 262), "     ".join(row), font=F(34), fill=DIM)
    y += 360

    # --- the one sentence ---------------------------------------------------
    desc = (mi.get("description") or r.get("forecast_keypoint") or "").strip()
    if desc:
        _card(d, y, 150)
        d.text((PAD + IN, y + 26), "NEXT 2 HOURS", font=F(28), fill=DIM)
        d.text((PAD + IN, y + 70), desc, font=F(42), fill=INK)
        y += 180

    # --- radar --------------------------------------------------------------
    if radar:
        side = W - 2 * PAD
        when = RI.when_text(radar["ts"], radar.get("obs_ts"))
        obs = radar.get("obs_ts") or radar["ts"]
        if abs(float(radar["ts"]) - float(obs)) >= 60:
            cap = "seen %s, moved on to %s" % (_local(obs, tz).strftime("%H:%M"),
                                              _local(radar["ts"], tz).strftime("%H:%M"))
        else:
            cap = "seen %s" % _local(obs, tz).strftime("%H:%M")
        _card(d, y, side + 290, "RADAR  ·  %d km around you" % round(span_km), cap + " local")
        mp, _ = RI.render(radar["png"], radar["bbox"], radar["lon"], radar["lat"], label,
                          radar["ts"], radar.get("obs_ts"), span_km, size=side - 2 * 12,
                          motion=motion, ui=RADAR_UI, bare=True, as_image=True,
                          frame_key=radar.get("key"))
        mask = Image.new("L", mp.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, mp.size[0] - 1, mp.size[1] - 1), radius=18, fill=255)
        im.paste(mp, (PAD + 12, y + 84), mask)
        yy = y + 84 + mp.size[1] + 26
        # motion words, outside the map, at reading size
        kind = (motion or {}).get("kind")
        if kind == "moving":
            mline = "rain moving %s ~%.0f km/h" % (motion.get("dir_en", "?"), float(motion["kmh"]))
            msub = "arrow: rain on it reaches you at the time marked"
        elif kind == "stationary":
            mline, msub = "rain barely moving (<5 km/h)", ""
        elif kind == "undetermined":
            mline, msub = "rain motion undetermined", ""
        else:
            mline, msub = "", ""
        if mline:
            d.text((PAD + IN, yy), mline, font=F(36), fill=INK)
            if msub:
                d.text((PAD + IN, yy + 48), msub + ("  (%s)" % basis if basis else ""), font=F(26), fill=DIM)
        # legend
        cols = RI.legend_colours(Image.open(io.BytesIO(radar["png"])).convert("RGBA"), radar.get("key"))
        ly = yy + 104; bw = 54
        if cols:
            for i, col in enumerate(cols):
                d.rounded_rectangle((PAD + IN + i * bw, ly, PAD + IN + (i + 1) * bw - 6, ly + 30), radius=6, fill=col)
            d.text((PAD + IN, ly + 38), "weaker", font=F(24), fill=DIM)
            sw = F(24).getlength("stronger")
            d.text((PAD + IN + bw * len(cols) - 6 - sw, ly + 38), "stronger", font=F(24), fill=DIM)
        else:
            d.text((PAD + IN, ly), "no rain on this radar frame", font=F(28), fill=DIM)
        hx = W - PAD - IN - 230
        sample = RI._hatch(60, step=12, width=3).crop((0, 0, 60, 30))
        im.paste(sample.convert("RGB"), (hx, ly), sample)
        d.text((hx + 76, ly - 2), "no radar", font=F(28), fill=DIM)
        y += side + 290 + 30
    elif radar_note:
        # say why the map is missing; a picture that silently lacks its radar
        # reads as "no rain"
        _card(d, y, 150, "RADAR")
        d.text((PAD + IN, y + 74), radar_note, font=F(34), fill=INK)
        y += 180

    # --- rain at your point, next 2 hours -----------------------------------
    p = mi.get("precipitation_2h") or []
    if p:
        _card(d, y, 560, "RAIN AT YOUR POINT  ·  mm/h")
        gx0, gx1, gy0, gy1 = PAD + IN + 70, W - PAD - IN, y + 100, y + 360
        X = lambda m: gx0 + (gx1 - gx0) * m / 120.0
        top = max(1.0, max(p) * 1.25)
        for frac in (0, .5, 1):
            yy = gy1 - (gy1 - gy0) * frac
            d.line((gx0, yy, gx1, yy), fill=FAINT, width=2)
            lab = "%.1f" % (top * frac)
            d.text((gx0 - 14 - F(26).getlength(lab), yy - 14), lab, font=F(26), fill=DIM)
        pts = [(X(120.0 * i / (len(p) - 1)), gy1 - (gy1 - gy0) * min(v, top) / top) for i, v in enumerate(p)]
        d.polygon(pts + [(gx1, gy1), (gx0, gy1)], fill=RAIN_L)
        d.line(pts, fill=RAIN, width=5)
        for m in (0, 30, 60, 90, 120):
            d.line((X(m), gy1, X(m), gy1 + 10), fill=DIM, width=2)
        labs = {0: "now", 30: "+30'", 60: "+60'", 90: "+90'", 120: "+120'"}
        for m, lab in labs.items():
            f = F(28); w = f.getlength(lab)
            x = min(max(X(m) - w / 2, PAD + IN), W - PAD - IN - w)
            d.text((x, gy1 + 16), lab, font=f, fill=DIM)
        # chance of rain, one cell per half hour, UNDER the half hour it is
        # about: the first version laid four equal boxes across the card and
        # they did not line up with the curve's axis (bob 11-03)
        for k, pr in enumerate(mi.get("probability") or []):
            x0, x1 = X(30 * k) + 5, X(30 * k + 30) - 5
            d.rounded_rectangle((x0, y + 420, x1, y + 490), radius=14,
                                fill=tuple(int(255 - (255 - c) * pr) for c in RAIN_L), outline=FAINT, width=2)
            _centre(d, (x0 + x1) / 2, y + 434, "%d%%" % round(pr * 100), F(36), INK)
        d.text((PAD + IN, y + 506), "chance of rain in each half hour", font=F(24), fill=DIM)
        y += 590

    # --- next 24 hours ------------------------------------------------------
    T = [h["value"] for h in hr["temperature"]]
    if T:
        P = [h["value"] for h in hr["precipitation"]]
        PR = [h.get("probability") or 0 for h in hr["precipitation"]]
        n = len(T)
        _card(d, y, 560, "NEXT %d HOURS" % n)
        hx0, hx1 = PAD + IN + 30, W - PAD - IN - 30
        X = lambda i: hx0 + (hx1 - hx0) * i / max(1, n - 1)
        ty0, ty1 = y + 140, y + 250
        tlo, thi = min(T) - 1, max(T) + 1
        tp = [(X(i), ty1 - (ty1 - ty0) * (t - tlo) / (thi - tlo)) for i, t in enumerate(T)]
        by1 = y + 450; ptop = max(1.0, max(P))
        for i, v in enumerate(P):
            if v > 0.02:
                d.rounded_rectangle((X(i) - 15, by1 - 70 * min(v, ptop) / ptop - 2, X(i) + 15, by1),
                                    radius=4, fill=RAIN_L)
        d.line(tp, fill=TEMP, width=5)
        for i in range(0, n, 4):
            x, yy = tp[i]
            d.ellipse((x - 7, yy - 7, x + 7, yy + 7), fill=TEMP)
            _centre(d, x, yy - 50, "%.0f°" % T[i], F(34), INK)
            icon(d, x, y + 300, 54, hr["skycon"][i]["value"])
            if PR[i] >= 10:
                _centre(d, x, y + 340, "%d%%" % PR[i], F(26), RAIN)
            _centre(d, x, by1 + 16, hr["temperature"][i]["datetime"][11:16], F(28), DIM)
        y += 590

    # --- the coming days ----------------------------------------------------
    days = dy.get("temperature") or []
    if days:
        nd = len(days)
        _card(d, y, 100 + nd * 112, "NEXT %d DAYS" % nd)
        lo = min(t["min"] for t in days); hi = max(t["max"] for t in days)
        sx0, sx1 = PAD + IN + 470, W - PAD - IN - 80
        SX = lambda t: sx0 + (sx1 - sx0) * (t - lo) / max(1e-6, hi - lo)
        for k in range(nd):
            yy = y + 96 + k * 112
            date = datetime.strptime(days[k]["date"][:10], "%Y-%m-%d")
            d.text((PAD + IN, yy), "Today" if k == 0 else date.strftime("%a"), font=F(36), fill=INK)
            sk = dy["skycon"][k]["value"]
            icon(d, PAD + IN + 160, yy + 22, 60, sk)
            pp = (dy["precipitation"][k].get("probability") or 0) if k < len(dy.get("precipitation", [])) else 0
            if pp >= 10:
                d.text((PAD + IN + 220, yy + 4), "%d%%" % pp, font=F(30), fill=RAIN)
            t = days[k]
            lab = "%.0f°" % t["min"]
            d.text((sx0 - 24 - F(34).getlength(lab), yy), lab, font=F(34), fill=DIM)
            d.rounded_rectangle((sx0, yy + 16, sx1, yy + 30), radius=7, fill=FAINT)
            d.rounded_rectangle((SX(t["min"]), yy + 12, max(SX(t["max"]), SX(t["min"]) + 22), yy + 34),
                                radius=11, fill=TEMP)
            d.text((sx1 + 20, yy), "%.0f°" % t["max"], font=F(34), fill=INK)
            d.text((PAD + IN, yy + 48), SKY.get(sk, ""), font=F(24), fill=DIM)
        y += 130 + nd * 112

    astro = (dy.get("astro") or [None])[0]
    if astro:
        d.text((PAD + 8, y), "sunrise %s   sunset %s" % (astro["sunrise"]["time"], astro["sunset"]["time"]),
               font=F(30), fill=DIM)
        y += 70
    d.text((PAD + 8, y), "weather & radar: caiyunapp.com  ·  basemap: Natural Earth  ·  echorune.net",
           font=F(24), fill=DIM)
    y += 60
    # 256-colour palette (quantize_pinned): flat fills, a third of the bytes
    # of a full-colour PNG, 0.3 s to encode instead of 1.6 s for
    # optimize=True -- which was 80% of the whole render.
    if y != H:            # height() and the drawing disagree: still a picture, but say so
        import sys
        sys.stderr.write("PANORAMA-HEIGHT drew %d, planned %d\n" % (y, H))
        im = im.crop((0, 0, W, min(y, H)))
    buf = io.BytesIO()
    quantize_pinned(im).save(buf, "PNG", compress_level=6)
    _render.last_y = y
    return buf.getvalue()


# The UI's own colours, held exact through the palette.
FIXED = (BG, CARD, INK, DIM, FAINT, TEMP, RAIN, RAIN_L)


def quantize_pinned(img):
    """256-colour PNG with the UI colours kept exact.

    Plain FASTOCTREE merged the page grey (244,245,247) with card white
    (255,255,255) on the first live render, and every card vanished into the
    page -- the side-by-side check had looked only at the radar block. PIL's
    palette mapping is approximate too (it put pure white on a near-white
    entry), so the pinning is done here: any pixel that IS a UI colour points
    at that colour's own palette entry."""
    n = 256 - len(FIXED)
    q = img.quantize(n, method=Image.Quantize.FASTOCTREE)
    pal = (q.getpalette() or [])[: 3 * n]
    pal += [0] * (3 * n - len(pal))
    for c in FIXED:
        pal += list(c)
    idx = np.array(q)
    rgb = np.asarray(img)
    key = (rgb[..., 0].astype(np.uint32) << 16) | (rgb[..., 1].astype(np.uint32) << 8) | rgb[..., 2]
    for k, c in enumerate(FIXED):
        idx[key == ((c[0] << 16) | (c[1] << 8) | c[2])] = n + k
    out = Image.fromarray(idx, "P")
    out.putpalette(pal)
    return out
