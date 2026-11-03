"""The weather for one place as one long, phone-width picture.

bob 2026-11-03: "open one png and it is the whole weather, now". Then, from
his phone: a square leaves half the screen black; and, twice, the long
picture's text is too small to read.

The size was a judgement I had made by eye ("~34-42 px at 1080 should read
like app text") and it was wrong by a whole step. So the layout is written in
phone points, not image pixels, on the type scale phone weather apps already
use (iOS: large title 34, body 17, secondary 15, caption 13, on a 390 pt wide
screen), and drawn at K = 1080 / 390 px per point. The sizes come from
something that already works on a phone, not from my eye.

Top to bottom is near to far: now -> the next two hours (one sentence, the
radar, the curve at your point) -> 24 hours -> air quality -> the coming
days. Every block says when its data is from, in local time.

Everything comes from the same Caiyun weather response the text map uses and
the same radar frame and motion vector -- one request upstream, two renderings.
"""
import io
import math
import os
import threading
from datetime import datetime, timezone

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from . import radar_image as RI

PT_W = 390.0                 # design width, phone points
W = 1080                     # output width, pixels
K = W / PT_W                 # pixels per point
M = 16                       # page margin, pt
P = 16                       # card padding, pt
RADAR_UI = K                 # map labels at the same point sizes as the page

INK = (24, 28, 36); DIM = (84, 90, 102); FAINT = (222, 226, 232)
BG = (240, 242, 245); CARD = (255, 255, 255); TINT = (226, 238, 252)
TEMP = (214, 96, 52); RAIN = (36, 104, 184); RAIN_L = (186, 212, 240)

# China AQI bands (HJ 633-2012); the index Caiyun gives as "chn".
AQI_BANDS = ((50, "excellent", (0, 190, 80)), (100, "good", (240, 200, 0)),
             (150, "lightly polluted", (255, 126, 0)), (200, "moderately polluted", (230, 30, 30)),
             (300, "heavily polluted", (153, 0, 76)), (10 ** 9, "severely polluted", (126, 0, 35)))


def aqi_band(v):
    for hi, name, col in AQI_BANDS:
        if v <= hi:
            return name, col


def font(pt, bold=False):
    return RI.font(max(8, round(pt * K)), bold)


SKY = {"CLEAR_DAY": "clear", "CLEAR_NIGHT": "clear", "PARTLY_CLOUDY_DAY": "partly cloudy",
       "PARTLY_CLOUDY_NIGHT": "partly cloudy", "CLOUDY": "cloudy", "LIGHT_HAZE": "light haze",
       "MODERATE_HAZE": "haze", "HEAVY_HAZE": "heavy haze", "LIGHT_RAIN": "light rain",
       "MODERATE_RAIN": "rain", "HEAVY_RAIN": "heavy rain", "STORM_RAIN": "storm",
       "FOG": "fog", "LIGHT_SNOW": "light snow", "MODERATE_SNOW": "snow",
       "HEAVY_SNOW": "heavy snow", "STORM_SNOW": "snowstorm", "DUST": "dust",
       "SAND": "sand", "WIND": "windy"}
COMPASS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]


class _Measure:
    """A drawing surface that draws nothing. The layout runs once against it
    to learn its own height, then once for real: one code path decides both,
    so the canvas cannot be planned for one height and drawn at another."""
    def __getattr__(self, name):
        return lambda *a, **k: None


class _Page:
    """Drawing in points on top of PIL (or on the measuring stub)."""
    def __init__(self, im, d):
        self.im, self.d = im, d

    def text(self, x, y, s, pt, fill=INK, bold=False, anchor="la"):
        self.d.text((x * K, y * K), s, font=font(pt, bold), fill=fill, anchor=anchor)

    def width(self, s, pt, bold=False):
        return font(pt, bold).getlength(s) / K

    def rrect(self, x0, y0, x1, y1, r, fill=None, outline=None, w=1):
        self.d.rounded_rectangle((x0 * K, y0 * K, x1 * K, y1 * K), radius=r * K,
                                 fill=fill, outline=outline, width=max(1, round(w * K)))

    def line(self, pts, fill, w):
        self.d.line([(x * K, y * K) for x, y in pts], fill=fill, width=max(1, round(w * K)))

    def poly(self, pts, fill):
        self.d.polygon([(x * K, y * K) for x, y in pts], fill=fill)

    def dot(self, x, y, r, fill):
        self.d.ellipse(((x - r) * K, (y - r) * K, (x + r) * K, (y + r) * K), fill=fill)

    def icon(self, x, y, s, sky):
        if self.im is not None:
            icon(self.d, x * K, y * K, s * K, sky)


def icon(d, x, y, s, sky):
    """A small drawn glyph (no emoji font on this box). (x, y) centre, s size, px."""
    sky = sky or ""
    sun = "CLEAR" in sky or "PARTLY" in sky
    cloud = sky not in ("CLEAR_DAY", "CLEAR_NIGHT")
    rain, snow, night = "RAIN" in sky, "SNOW" in sky, "NIGHT" in sky
    lw = max(2, round(s / 22))
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
        col = (140, 148, 162) if (rain or snow or sky == "CLOUDY") else (186, 192, 204)
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


def _local(ts, tz):
    return datetime.fromtimestamp(float(ts) + tz, timezone.utc)


# One picture at a time per process: a render peaks ~100 MB above the
# process's resting size, on a ~1 GB box with other people's traffic on it.
_RENDER_LOCK = threading.Lock()


def render(wx_full, radar, label, motion=None, basis=None, span_km=200.0, radar_note=None):
    """-> PNG bytes.

    wx_full  the whole Caiyun weather response (result + server_time + tzshift)
    radar    None, or dict(png, bbox, ts, obs_ts, lon, lat, key) -- the frame
             the text map draws
    """
    with _RENDER_LOCK:
        args = (wx_full, radar, label, motion, basis, span_km, radar_note)
        h = _layout(_Page(None, _Measure()), *args)
        im = Image.new("RGB", (W, round(h * K)), BG)
        drawn = _layout(_Page(im, ImageDraw.Draw(im)), *args)
        render.last = (h, drawn)
        buf = io.BytesIO()
        quantize_pinned(im).save(buf, "PNG", compress_level=6)
        return buf.getvalue()


render.last = None


def _card(pg, y, h, title=None, note=None, sub=None, fill=CARD):
    """A card; -> y of its first content line (pt).

    Titles are 20 pt sentence case, notes and subtitles 15 pt: the first
    long picture used 13 pt grey capitals here, and next to a phone-app
    reference at the same scale those were the hardest text on the page."""
    pg.rrect(M, y, PT_W - M, y + h, 16, fill=fill)
    yy = y + 16
    if title:
        pg.text(M + P, yy, title, 20, INK, bold=True)
        if note:
            pg.text(PT_W - M - P, yy + 4, note, 15, DIM, anchor="ra")
        yy += 28
    for ln in sub or ():
        pg.text(M + P, yy, ln, 15, DIM)
        yy += 20
    return yy + (6 if (title or sub) else 0)


def _card_h(pg, body, title=True, sub=()):
    """Height of a card whose body is `body` pt tall."""
    return 16 + (28 if title else 0) + 20 * len(sub) + (6 if (title or sub) else 0) + body + 16


def _pill(pg, x, y, v, pt=15, right=False):
    """An AQI value on its band colour; -> its far edge."""
    _, col = aqi_band(v)
    s = str(v)
    w = pg.width(s, pt, True) + 14
    x0 = x - w if right else x
    pg.rrect(x0, y, x0 + w, y + pt + 9, (pt + 9) / 2, fill=col)
    pg.text(x0 + w / 2, y + (pt + 9) / 2, s, pt, (255, 255, 255) if v > 100 else INK, bold=True, anchor="mm")
    return x0 if right else x0 + w


def _layout(pg, wx_full, radar, label, motion, basis, span_km, radar_note):
    """Lay the page out in points; -> the height used (pt)."""
    r = wx_full["result"]; tz = int(wx_full.get("tzshift") or 0)
    rt, mi, hr, dy = r["realtime"], r["minutely"], r["hourly"], r["daily"]
    wx_at = _local(wx_full["server_time"], tz)
    X0, X1 = M + P, PT_W - M - P            # content edges inside a card
    GAP = 14

    # --- place --------------------------------------------------------------
    y = 18
    pg.text(M + 4, y, label.split(",")[0].strip(), 34, INK, bold=True)
    y += 44
    pg.text(M + 4, y, "%s · as of %s" % (wx_at.strftime("%a %d %b"), wx_at.strftime("%H:%M")), 15, DIM)
    y += 32

    # --- now ----------------------------------------------------------------
    days = dy.get("temperature") or []
    astro = (dy.get("astro") or [None])[0]
    hh = 306
    _card(pg, y, hh)
    temp = "%.0f°" % rt["temperature"]
    pg.text(X0 - 4, y + 6, temp, 88, INK)
    pg.icon(X1 - 40, y + 58, 76, rt.get("skycon"))
    pg.text(X0, y + 112, SKY.get(rt.get("skycon"), ""), 22, INK, bold=True)
    feel = "feels %.0f°" % rt["apparent_temperature"]
    if days:
        feel = "H %.0f° · L %.0f° · %s" % (days[0]["max"], days[0]["min"], feel)
    pg.text(X0, y + 142, feel, 17, DIM)
    wind = rt.get("wind") or {}
    wdir = COMPASS[int((float(wind.get("direction", 0)) + 22.5) // 45) % 8]
    cw = (X1 - X0) / 2
    cells = [("humidity", "%d%%" % round(rt["humidity"] * 100)),
             ("wind", "%s %.0f km/h" % (wdir, float(wind.get("speed", 0))))]
    aqi = ((rt.get("air_quality") or {}).get("aqi") or {}).get("chn")
    cells.append(("air quality", int(aqi) if aqi is not None else None))
    if astro:
        cells.append(("sunrise – sunset", "%s–%s" % (astro["sunrise"]["time"], astro["sunset"]["time"])))
    for i, (k, v) in enumerate(cells):
        cx, cy = X0 + (i % 2) * cw, y + 180 + (i // 2) * 54
        pg.text(cx, cy, k, 15, DIM)
        if isinstance(v, int):
            e = _pill(pg, cx, cy + 20, v, 20)
            pg.text(e + 8, cy + 34, aqi_band(v)[0], 15, INK, anchor="lm")
        elif v is not None:
            pg.text(cx, cy + 20, v, 24, INK, bold=True)
    y += hh + GAP

    # --- the one sentence ---------------------------------------------------
    desc = (mi.get("description") or r.get("forecast_keypoint") or "").strip()
    if desc:
        lines = _wrap(pg, desc, 20, X1 - X0)
        hh = 32 + 26 * len(lines)
        _card(pg, y, hh, fill=TINT)
        for i, ln in enumerate(lines):
            pg.text(X0, y + 16 + 26 * i, ln, 20, INK, bold=True)
        y += hh + GAP

    # --- radar --------------------------------------------------------------
    if radar:
        side = PT_W - 2 * M - 16             # map inset 8 pt inside the card
        obs = radar.get("obs_ts") or radar["ts"]
        seen = "seen %s" % _local(obs, tz).strftime("%H:%M")
        if abs(float(radar["ts"]) - float(obs)) >= 60:
            seen += ", moved on to %s" % _local(radar["ts"], tz).strftime("%H:%M")
        sub = ["%d km around you" % round(span_km), seen]
        kind = (motion or {}).get("kind")
        mlines = []
        if kind == "moving":
            mlines = _wrap(pg, "motion from %s · rain on the arrow reaches you at the time marked" % (basis or "radar"),
                           15, X1 - X0, bold=False)
        body = side + 12 + (26 if kind in ("moving", "stationary", "undetermined") else 0) \
            + 20 * len(mlines) + 8 + 54
        hh = _card_h(pg, body, True, sub)
        top = _card(pg, y, hh, "Radar", sub=sub)
        if pg.im is not None:
            mp, _ = RI.render(radar["png"], radar["bbox"], radar["lon"], radar["lat"], label,
                              radar["ts"], radar.get("obs_ts"), span_km, size=round(side * K),
                              motion=motion, ui=RADAR_UI, bare=True, as_image=True,
                              frame_key=radar.get("key"))
            mask = Image.new("L", mp.size, 0)
            ImageDraw.Draw(mask).rounded_rectangle((0, 0, mp.size[0] - 1, mp.size[1] - 1),
                                                   radius=round(10 * K), fill=255)
            pg.im.paste(mp, (round((M + 8) * K), round(top * K)), mask)
        yy = top + side + 12
        if kind == "moving":
            pg.text(X0, yy, "rain moving %s ~%.0f km/h" % (motion.get("dir_en", "?"), float(motion["kmh"])), 17, INK, bold=True)
        elif kind == "stationary":
            pg.text(X0, yy, "rain barely moving (under 5 km/h)", 17, INK, bold=True)
        elif kind == "undetermined":
            pg.text(X0, yy, "rain motion undetermined", 17, INK, bold=True)
        if kind in ("moving", "stationary", "undetermined"):
            yy += 26
        for ln in mlines:
            pg.text(X0, yy, ln, 15, DIM)
            yy += 20
        ly = yy + 8
        cols = []
        if pg.im is not None:
            cols = RI.legend_colours(Image.open(io.BytesIO(radar["png"])).convert("RGBA"), radar.get("key"))
        bw = 22
        for i, col in enumerate(cols):
            pg.rrect(X0 + i * bw, ly, X0 + (i + 1) * bw - 3, ly + 16, 3, fill=col)
        if cols:
            pg.text(X0 + len(cols) * bw + 6, ly + 8, "weak → strong", 15, DIM, anchor="lm")
        elif pg.im is not None:
            pg.text(X0, ly + 8, "no rain on this frame", 15, DIM, anchor="lm")
        ly += 30
        if pg.im is not None:
            s = round(26 * K)
            sample = RI._hatch(s, step=round(5 * K), width=max(2, round(K))).crop((0, 0, s, round(16 * K)))
            pg.im.paste(sample.convert("RGB"), (round(X0 * K), round(ly * K)), sample)
        pg.text(X0 + 32, ly + 8, "no radar here", 15, DIM, anchor="lm")
        y += hh + GAP
    elif radar_note:
        # a picture that silently lacks its radar reads as "no rain"
        lines = _wrap(pg, radar_note, 17, X1 - X0, bold=False)
        hh = _card_h(pg, 24 * len(lines))
        top = _card(pg, y, hh, "Radar")
        for i, ln in enumerate(lines):
            pg.text(X0, top + 24 * i, ln, 17, INK)
        y += hh + GAP

    # --- rain at your point, next 2 hours -----------------------------------
    p = mi.get("precipitation_2h") or []
    if p:
        sub = ["mm/h, minute by minute, next 2 hours"]
        hh = _card_h(pg, 214, True, sub)
        t0 = _card(pg, y, hh, "Rain at your point", sub=sub)
        gx0, gx1, gy0, gy1 = X0 + 34, X1, t0 + 10, t0 + 110
        Xm = lambda m: gx0 + (gx1 - gx0) * m / 120.0
        top = max(1.0, max(p) * 1.25)
        for frac in (0, .5, 1):
            yy = gy1 - (gy1 - gy0) * frac
            pg.line([(gx0, yy), (gx1, yy)], FAINT, 1)
            pg.text(gx0 - 6, yy, "%.1f" % (top * frac), 15, DIM, anchor="rm")
        pts = [(Xm(120.0 * i / (len(p) - 1)), gy1 - (gy1 - gy0) * min(v, top) / top) for i, v in enumerate(p)]
        pg.poly(pts + [(gx1, gy1), (gx0, gy1)], RAIN_L)
        pg.line(pts, RAIN, 2)
        for m, lab in ((0, "now"), (30, "+30 min"), (60, "+1 h"), (90, "+90 min"), (120, "+2 h")):
            pg.line([(Xm(m), gy1), (Xm(m), gy1 + 4)], DIM, 1)
            anc = "la" if m == 0 else ("ra" if m == 120 else "ma")
            pg.text(Xm(m), gy1 + 7, lab, 15, DIM, anchor=anc)
        # chance of rain, one cell per half hour, under the half hour it is
        # about (the first mock laid four equal boxes across the card and they
        # did not line up with the curve's axis -- bob 11-03)
        cy = gy1 + 38
        for k, pr in enumerate(mi.get("probability") or []):
            x0, x1 = Xm(30 * k) + 2, Xm(30 * k + 30) - 2
            pg.rrect(x0, cy, x1, cy + 36, 8,
                     fill=tuple(int(255 - (255 - c) * pr) for c in RAIN_L), outline=FAINT)
            pg.text((x0 + x1) / 2, cy + 18, "%d%%" % round(pr * 100), 20, INK, bold=True, anchor="mm")
        pg.text(X0, cy + 46, "chance of rain in each half hour", 15, DIM)
        y += hh + GAP

    # --- next 24 hours ------------------------------------------------------
    T = [h["value"] for h in hr.get("temperature") or []]
    if T:
        Pm = [h["value"] for h in hr["precipitation"]]
        PR = [h.get("probability") or 0 for h in hr["precipitation"]]
        n = len(T)
        hh = _card_h(pg, 206)
        t0 = _card(pg, y, hh, "Next %d hours" % n, "bars: rain")
        hx0, hx1 = X0 + 16, X1 - 16
        Xh = lambda i: hx0 + (hx1 - hx0) * i / max(1, n - 1)
        ty0, ty1 = t0 + 26, t0 + 66
        tlo, thi = min(T) - 1, max(T) + 1
        tp = [(Xh(i), ty1 - (ty1 - ty0) * (t - tlo) / (thi - tlo)) for i, t in enumerate(T)]
        by1 = t0 + 180; ptop = max(1.0, max(Pm))
        for i, v in enumerate(Pm):
            if v > 0.02:
                pg.rrect(Xh(i) - 5, by1 - 28 * min(v, ptop) / ptop - 1, Xh(i) + 5, by1, 2, fill=RAIN_L)
        pg.line(tp, TEMP, 2)
        for i in range(0, n, 4):
            x, yy = tp[i]
            pg.dot(x, yy, 3, TEMP)
            pg.text(x, yy - 8, "%.0f°" % T[i], 17, INK, bold=True, anchor="md")
            pg.icon(x, t0 + 96, 30, hr["skycon"][i]["value"])
            if PR[i] >= 10:
                pg.text(x, t0 + 122, "%d%%" % PR[i], 15, RAIN, bold=True, anchor="ma")
            pg.text(x, by1 + 8, hr["temperature"][i]["datetime"][11:16], 15, DIM, anchor="ma")
        y += hh + GAP

    # --- air quality, next 24 hours -----------------------------------------
    aq = (hr.get("air_quality") or {}).get("aqi") or []
    if aq:
        vals = [int(a["value"]["chn"]) for a in aq]
        n = len(vals)
        lo_v, hi_v = min(vals), max(vals)
        b_lo, b_hi = aqi_band(lo_v)[0], aqi_band(hi_v)[0]
        said = ("%d to %d over the next %d hours, %s" % (lo_v, hi_v, n, b_lo if b_lo == b_hi else "%s to %s" % (b_lo, b_hi)))
        lines = _wrap(pg, said, 17, X1 - X0)
        hh = _card_h(pg, 24 * len(lines) + 12 + 76 + 28)
        t0 = _card(pg, y, hh, "Air quality", "China AQI")
        for i, ln in enumerate(lines):
            pg.text(X0, t0 + 24 * i, ln, 17, INK, bold=True)
        bx0, bx1 = X0 + 34, X1
        by0 = t0 + 24 * len(lines) + 12 + 16; by1 = by0 + 60
        top = max(100, max(vals) * 1.15)
        bw = (bx1 - bx0) / n
        # the band edges, so the space above low bars says "well under 100"
        # instead of being empty
        for edge in (0, 50, 100, 150, 200, 300):
            if edge <= top:
                ye = by1 - (by1 - by0) * edge / top
                pg.line([(bx0, ye), (bx1, ye)], FAINT, 1)
                pg.text(bx0 - 6, ye, str(edge), 15, DIM, anchor="rm")
        for i, v in enumerate(vals):
            h = max(2, (by1 - by0) * v / top)
            pg.rrect(bx0 + i * bw + 1, by1 - h, bx0 + (i + 1) * bw - 1, by1, 2, fill=aqi_band(v)[1])
        for i in range(0, n, 4):
            x = bx0 + (i + .5) * bw
            pg.text(x, by1 + 8, aq[i]["datetime"][11:16], 15, DIM, anchor="ma")
        y += hh + GAP

    # --- the coming days ----------------------------------------------------
    if days:
        nd = len(days)
        rowh = 66
        daq = (dy.get("air_quality") or {}).get("aqi") or []
        hh = _card_h(pg, nd * rowh - 14)
        t0 = _card(pg, y, hh, "Next %d days" % nd, "AQI: day's highest" if daq else None)
        lo = min(t["min"] for t in days); hi = max(t["max"] for t in days)
        sx0, sx1 = X0 + 190, X1 - 34
        SX = lambda t: sx0 + (sx1 - sx0) * (t - lo) / max(1e-6, hi - lo)
        for k in range(nd):
            yy = t0 + k * rowh
            if k:
                pg.line([(X0, yy - 12), (X1, yy - 12)], FAINT, 1)
            date = datetime.strptime(days[k]["date"][:10], "%Y-%m-%d")
            pg.text(X0, yy, "Today" if k == 0 else date.strftime("%a"), 17, INK, bold=True)
            sk = dy["skycon"][k]["value"]
            pg.icon(X0 + 76, yy + 10, 30, sk)
            pp = (dy["precipitation"][k].get("probability") or 0) if k < len(dy.get("precipitation") or []) else 0
            if pp >= 10:
                pg.text(X0 + 100, yy + 2, "%d%%" % pp, 15, RAIN, bold=True)
            pg.text(X0, yy + 28, SKY.get(sk, ""), 15, DIM)
            t = days[k]
            pg.text(sx0 - 6, yy + 10, "%.0f°" % t["min"], 17, DIM, anchor="rm")
            pg.rrect(sx0, yy + 7, sx1, yy + 13, 3, fill=FAINT)
            pg.rrect(SX(t["min"]), yy + 5, max(SX(t["max"]), SX(t["min"]) + 10), yy + 15, 5, fill=TEMP)
            pg.text(sx1 + 6, yy + 10, "%.0f°" % t["max"], 17, INK, bold=True, anchor="lm")
            if k < len(daq):
                v = int(daq[k]["max"]["chn"])
                nm = aqi_band(v)[0]
                e = X1 - pg.width(nm, 15) - 6
                pg.text(X1, yy + 39, nm, 15, INK, anchor="rm")
                _pill(pg, e, yy + 27, v, 15, right=True)
        y += hh + GAP

    pg.text(M + 4, y + 4, "weather, radar & air: caiyunapp.com", 14, DIM)
    pg.text(M + 4, y + 24, "basemap: Natural Earth · echorune.net", 14, DIM)
    return y + 52


def _wrap(pg, s, pt, width, bold=True):
    out, cur = [], ""
    for w in s.split():
        t = (cur + " " + w).strip()
        if cur and pg.width(t, pt, bold) > width:
            out.append(cur); cur = w
        else:
            cur = t
    if cur:
        out.append(cur)
    return out or [""]


# The UI's own colours, held exact through the palette.
UI = (BG, CARD, TINT, INK, DIM, FAINT, TEMP, RAIN, RAIN_L)
FIXED = UI + tuple(c for _, _, c in AQI_BANDS)


def quantize_pinned(img):
    """256-colour PNG with the UI colours kept exact.

    Plain FASTOCTREE merged the page grey with card white on the first live
    render, and every card vanished into the page -- the side-by-side check
    had looked only at the radar block. PIL's palette mapping is approximate
    too (it put pure white on a near-white entry), so the pinning is done
    here: any pixel that IS a UI colour points at that colour's own entry."""
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
