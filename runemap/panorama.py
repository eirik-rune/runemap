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
from .words import AQI_BANDS, AQI_NAMES, COMPASS, aqi_band, compass, weekday as _weekday, WEEK as _WEEK
from .words import aqi_value as _aqi

PT_W = 390.0                 # design width, phone points
W = 1080                     # output width, pixels
K = W / PT_W                 # pixels per point
M = 16                       # page margin, pt
P = 16                       # card padding, pt
RADAR_UI = K                 # map labels at the same point sizes as the page

INK = (24, 28, 36); DIM = (84, 90, 102); FAINT = (222, 226, 232)
BG = (240, 242, 245); CARD = (255, 255, 255); TINT = (226, 238, 252)
TEMP = (214, 96, 52); RAIN = (36, 104, 184); RAIN_L = (186, 212, 240)

# Everything the picture says in its own voice. Weather words (sky names, the
# two-hour sentence, the motion basis) come from the caller -- the same tables
# and the same upstream text the text map uses -- so there is no second list
# of them here to drift.
T = {
 "en": dict(asof="as of {t}", feel="H {hi}° · L {lo}° · feels {fl}°", feel0="feels {fl}°",
            humidity="humidity", wind="wind", wind_v="{d} {v} km/h", air="air quality",
            sun="sunrise – sunset", radar="Radar", around="{km} km around you",
            seen="seen {a}", moved="seen {a}, moved on to {b}",
            moving="rain moving {d} ~{v} km/h",
            mexpl="motion from {basis} · rain on the arrow reaches you at the time marked",
            stationary="rain barely moving (under 5 km/h)", undetermined="rain motion undetermined",
            weakstrong="weak → strong", norain="no rain on this frame", noradar="no radar here",
            radar_pending="radar frame not fetched yet -- ask again in ~30s",
            rain="Rain at your point", rain_sub="mm/h, minute by minute, next 2 hours",
            axis=("now", "+30 min", "+1 h", "+90 min", "+2 h"),
            chance="chance of rain in each half hour",
            hours="Next {n} hours", bars="bars: rain", aq="Air quality", aq_note="China AQI",
            aq_said="{lo} to {hi} over the next {n} hours, {bands}", aq_range="{a} to {b}",
            aq_none="The source gives no air-quality forecast for this place.",
            days="Next {n} days", days_note="AQI: day's highest", today="Today",
            qr="Latest weather",
            qr_how="Long-press the code (or scan it) to open the latest picture for this place.",
            qr_this="This one is from {t}.",
            foot1="weather, radar & air: caiyunapp.com",
            foot2="basemap: Natural Earth · echorune.net"),
 "zh": dict(asof="{t} 更新", feel="最高 {hi}° · 最低 {lo}° · 体感 {fl}°", feel0="体感 {fl}°",
            humidity="湿度", wind="风", wind_v="{d}风 {v} km/h", air="空气质量",
            sun="日出 – 日落", radar="雷达", around="周围 {km} 公里",
            seen="{a} 观测", moved="{a} 观测，外推到 {b}",
            moving="雨区向{d}移动，约 {v} km/h",
            mexpl="移动依据：{basis} · 箭头上的雨在标注的时间到达这里",
            stationary="雨区几乎不动（低于 5 km/h）", undetermined="雨区移动无法判断",
            weakstrong="弱 → 强", norain="这一帧没有降水回波", noradar="雷达覆盖不到",
            radar_pending="雷达图还没取到，约 30 秒后再试",
            rain="你所在位置的降水", rain_sub="未来 2 小时逐分钟，mm/h",
            axis=("现在", "30分钟", "1小时", "90分钟", "2小时"),
            chance="每半小时的降水概率",
            hours="未来 {n} 小时", bars="柱：降水", aq="空气质量", aq_note="中国 AQI",
            aq_said="未来 {n} 小时 {lo}–{hi}，{bands}", aq_range="{a}到{b}",
            aq_none="数据源没有给出这里的空气质量预报。",
            days="未来 {n} 天", days_note="AQI 为当天最高", today="今天",
            qr="最新天气",
            qr_how="长按识别（或扫一扫）二维码，打开这里最新的天气图。",
            qr_this="这一张是 {t} 的。",
            foot1="天气、雷达、空气质量：彩云天气 caiyunapp.com",
            foot2="底图：Natural Earth · echorune.net"),
 "ja": dict(asof="{t} 時点", feel="最高 {hi}° · 最低 {lo}° · 体感 {fl}°", feel0="体感 {fl}°",
            humidity="湿度", wind="風", wind_v="{d}の風 {v} km/h", air="大気質",
            sun="日の出 – 日の入り", radar="レーダー", around="周辺 {km} km",
            seen="{a} 観測", moved="{a} 観測、{b} まで外挿",
            moving="雨域は{d}へ移動、約 {v} km/h",
            mexpl="移動の根拠：{basis} · 矢印上の雨は表示の時刻にここへ届く",
            stationary="雨域はほぼ停滞（5 km/h 未満）", undetermined="雨域の移動は判定できず",
            weakstrong="弱 → 強", norain="このフレームに降水エコーなし", noradar="レーダー範囲外",
            radar_pending="レーダー画像を取得中、30秒ほどで再度どうぞ",
            rain="現在地の降水", rain_sub="今後2時間・1分ごと、mm/h",
            axis=("今", "30分", "1時間", "90分", "2時間"),
            chance="30分ごとの降水確率",
            hours="今後 {n} 時間", bars="棒：降水", aq="大気質", aq_note="中国AQI",
            aq_said="今後 {n} 時間は {lo}〜{hi}、{bands}", aq_range="{a}〜{b}",
            aq_none="この場所の大気質予報はデータ元から提供されていません。",
            days="今後 {n} 日間", days_note="AQIは日最高値", today="今日",
            qr="最新の天気",
            qr_how="QRコードを長押し（または読み取り）すると、この場所の最新の天気図が開きます。",
            qr_this="この画像は {t} 時点です。",
            foot1="天気・レーダー・大気質：caiyunapp.com",
            foot2="地図：Natural Earth · echorune.net"),
}
LANGS = tuple(T)


def text(lang, key):
    return T.get(lang, T["en"])[key]


def _date_line(dt, lang):
    if lang == "zh":
        return "%d月%d日 %s" % (dt.month, dt.day, _WEEK["zh"][dt.weekday()])
    if lang == "ja":
        return "%d月%d日(%s)" % (dt.month, dt.day, _WEEK["ja"][dt.weekday()])
    return dt.strftime("%a %d %b")


def font(pt, bold=False, lang="en"):
    return RI.font(max(8, round(pt * K)), bold, lang)


SKY = {"CLEAR_DAY": "clear", "CLEAR_NIGHT": "clear", "PARTLY_CLOUDY_DAY": "partly cloudy",
       "PARTLY_CLOUDY_NIGHT": "partly cloudy", "CLOUDY": "cloudy", "LIGHT_HAZE": "light haze",
       "MODERATE_HAZE": "haze", "HEAVY_HAZE": "heavy haze", "LIGHT_RAIN": "light rain",
       "MODERATE_RAIN": "rain", "HEAVY_RAIN": "heavy rain", "STORM_RAIN": "storm",
       "FOG": "fog", "LIGHT_SNOW": "light snow", "MODERATE_SNOW": "snow",
       "HEAVY_SNOW": "heavy snow", "STORM_SNOW": "snowstorm", "DUST": "dust",
       "SAND": "sand", "WIND": "windy"}


class _Measure:
    """A drawing surface that draws nothing. The layout runs once against it
    to learn its own height, then once for real: one code path decides both,
    so the canvas cannot be planned for one height and drawn at another."""
    def __getattr__(self, name):
        return lambda *a, **k: None


class _Page:
    """Drawing in points on top of PIL (or on the measuring stub)."""
    def __init__(self, im, d, lang="en"):
        self.im, self.d, self.lang = im, d, lang

    def text(self, x, y, s, pt, fill=INK, bold=False, anchor="la"):
        f = font(pt, bold, self.lang)
        if anchor[1] == "a" and self.lang != "en":
            # Noto CJK's ascender is ~25% of the em taller than Liberation's,
            # so top-anchored text sat a quarter-line low (the temperature
            # nearly touched the line under it). Shift by the measured
            # difference, so one layout serves every language.
            y -= (f.getmetrics()[0] - font(pt, bold).getmetrics()[0]) / K
        self.d.text((x * K, y * K), s, font=f, fill=fill, anchor=anchor)

    def width(self, s, pt, bold=False):
        return font(pt, bold, self.lang).getlength(s) / K

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


def render(wx_full, radar, label, motion=None, basis=None, span_km=200.0, radar_note=None,
           lang="en", sky=None, qr=None):
    """-> PNG bytes.

    wx_full  the whole Caiyun weather response (result + server_time + tzshift),
             fetched in `lang`
    radar    None, or dict(png, bbox, ts, obs_ts, lon, lat, key) -- the frame
             the text map draws
    lang     en / zh / ja; anything else, or a language this box has no font
             for, is drawn in English rather than as empty boxes
    sky      skycon -> words in `lang` (the text map's own table); English
             default
    qr       the address of this same picture, drawn as a QR code: a picture
             forwarded in a chat stops at the moment it was drawn, and the
             code is its way back to now
    """
    if lang not in T or not RI.can_draw(lang):
        lang, sky = "en", None
    with _RENDER_LOCK:
        args = (wx_full, radar, label, motion, basis, span_km, radar_note, sky or SKY, qr)
        h = _layout(_Page(None, _Measure(), lang), *args)
        im = Image.new("RGB", (W, round(h * K)), BG)
        drawn = _layout(_Page(im, ImageDraw.Draw(im), lang), *args)
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


def _qr_matrix(url):
    import segno            # pure Python; only the picture route needs it
    return segno.make(url, error="m").matrix


def _layout(pg, wx_full, radar, label, motion, basis, span_km, radar_note, sky, qr):
    """Lay the page out in points; -> the height used (pt)."""
    L = T[pg.lang]
    r = wx_full["result"]; tz = int(wx_full.get("tzshift") or 0)
    rt, mi, hr, dy = r["realtime"], r["minutely"], r["hourly"], r["daily"]
    wx_at = _local(wx_full["server_time"], tz)
    X0, X1 = M + P, PT_W - M - P            # content edges inside a card
    GAP = 14
    hm = lambda ts: _local(ts, tz).strftime("%H:%M")

    # --- place --------------------------------------------------------------
    y = 18
    pg.text(M + 4, y, label.split(",")[0].strip(), 34, INK, bold=True)
    y += 44
    pg.text(M + 4, y, "%s · %s" % (_date_line(wx_at, pg.lang), L["asof"].format(t=wx_at.strftime("%H:%M"))), 15, DIM)
    y += 32

    # --- now ----------------------------------------------------------------
    days = dy.get("temperature") or []
    astro = (dy.get("astro") or [None])[0]
    hh = 306
    _card(pg, y, hh)
    temp = "%.0f°" % rt["temperature"]
    pg.text(X0 - 4, y + 6, temp, 88, INK)
    pg.icon(X1 - 40, y + 58, 76, rt.get("skycon"))
    pg.text(X0, y + 112, sky.get(rt.get("skycon"), ""), 22, INK, bold=True)
    fl = "%.0f" % rt["apparent_temperature"]
    feel = (L["feel"].format(hi="%.0f" % days[0]["max"], lo="%.0f" % days[0]["min"], fl=fl) if days
            else L["feel0"].format(fl=fl))
    pg.text(X0, y + 142, feel, 17, DIM)
    wind = rt.get("wind") or {}
    wdir = compass(wind.get("direction", 0), pg.lang)
    cw = (X1 - X0) / 2
    cells = [(L["humidity"], "%d%%" % round(rt["humidity"] * 100)),
             (L["wind"], L["wind_v"].format(d=wdir, v="%.0f" % float(wind.get("speed", 0))))]
    cells.append((L["air"], _aqi(((rt.get("air_quality") or {}).get("aqi") or {}).get("chn"))))
    if astro:
        cells.append((L["sun"], "%s–%s" % (astro["sunrise"]["time"], astro["sunset"]["time"])))
    for i, (k, v) in enumerate(cells):
        cx, cy = X0 + (i % 2) * cw, y + 180 + (i // 2) * 54
        pg.text(cx, cy, k, 15, DIM)
        if isinstance(v, int):
            e = _pill(pg, cx, cy + 20, v, 20)
            pg.text(e + 8, cy + 34, aqi_band(v, pg.lang)[0], 15, INK, anchor="lm")
        elif v is None:
            pg.text(cx, cy + 20, "–", 24, DIM, bold=True)
        else:
            # one column is half the card: "北東の風 9 km/h" ran past its
            # right edge at 24 pt. Step down to fit, never under body size.
            pt = 24
            while pt > 17 and pg.width(v, pt, True) > cw - 8:
                pt -= 1
            pg.text(cx, cy + 20 + (24 - pt) / 2, v, pt, INK, bold=True)
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
        seen = (L["moved"].format(a=hm(obs), b=hm(radar["ts"])) if abs(float(radar["ts"]) - float(obs)) >= 60
                else L["seen"].format(a=hm(obs)))
        sub = [L["around"].format(km=round(span_km)), seen]
        kind = (motion or {}).get("kind")
        mlines = []
        if kind == "moving":
            mlines = _wrap(pg, L["mexpl"].format(basis=basis or "radar"), 15, X1 - X0, bold=False)
        body = side + 12 + (26 if kind in ("moving", "stationary", "undetermined") else 0) \
            + 20 * len(mlines) + 8 + 54
        hh = _card_h(pg, body, True, sub)
        top = _card(pg, y, hh, L["radar"], sub=sub)
        if pg.im is not None:
            mp, _ = RI.render(radar["png"], radar["bbox"], radar["lon"], radar["lat"], label,
                              radar["ts"], radar.get("obs_ts"), span_km, size=round(side * K),
                              motion=motion, ui=RADAR_UI, bare=True, as_image=True,
                              frame_key=radar.get("key"), lang=pg.lang)
            mask = Image.new("L", mp.size, 0)
            ImageDraw.Draw(mask).rounded_rectangle((0, 0, mp.size[0] - 1, mp.size[1] - 1),
                                                   radius=round(10 * K), fill=255)
            pg.im.paste(mp, (round((M + 8) * K), round(top * K)), mask)
        yy = top + side + 12
        if kind == "moving":
            d_en = motion.get("dir_en", "?")
            d = COMPASS[pg.lang][COMPASS["en"].index(d_en)] if d_en in COMPASS["en"] else d_en
            pg.text(X0, yy, L["moving"].format(d=d, v="%.0f" % float(motion["kmh"])), 17, INK, bold=True)
        elif kind in ("stationary", "undetermined"):
            pg.text(X0, yy, L[kind], 17, INK, bold=True)
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
            pg.text(X0 + len(cols) * bw + 6, ly + 8, L["weakstrong"], 15, DIM, anchor="lm")
        elif pg.im is not None:
            pg.text(X0, ly + 8, L["norain"], 15, DIM, anchor="lm")
        ly += 30
        if pg.im is not None:
            s_ = round(26 * K)
            sample = RI._hatch(s_, step=round(5 * K), width=max(2, round(K))).crop((0, 0, s_, round(16 * K)))
            pg.im.paste(sample.convert("RGB"), (round(X0 * K), round(ly * K)), sample)
        pg.text(X0 + 32, ly + 8, L["noradar"], 15, DIM, anchor="lm")
        y += hh + GAP
    elif radar_note:
        # a picture that silently lacks its radar reads as "no rain"
        lines = _wrap(pg, radar_note, 17, X1 - X0, bold=False)
        hh = _card_h(pg, 24 * len(lines))
        top = _card(pg, y, hh, L["radar"])
        for i, ln in enumerate(lines):
            pg.text(X0, top + 24 * i, ln, 17, INK)
        y += hh + GAP

    # --- rain at your point, next 2 hours -----------------------------------
    p = mi.get("precipitation_2h") or []
    if p:
        sub = [L["rain_sub"]]
        hh = _card_h(pg, 214, True, sub)
        t0 = _card(pg, y, hh, L["rain"], sub=sub)
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
        for m, lab in zip((0, 30, 60, 90, 120), L["axis"]):
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
        pg.text(X0, cy + 46, L["chance"], 15, DIM)
        y += hh + GAP

    # --- next 24 hours ------------------------------------------------------
    Tv = [h["value"] for h in hr.get("temperature") or []]
    if Tv:
        Pm = [h["value"] for h in hr["precipitation"]]
        PR = [h.get("probability") or 0 for h in hr["precipitation"]]
        n = len(Tv)
        hh = _card_h(pg, 206)
        t0 = _card(pg, y, hh, L["hours"].format(n=n), L["bars"])
        hx0, hx1 = X0 + 16, X1 - 16
        Xh = lambda i: hx0 + (hx1 - hx0) * i / max(1, n - 1)
        ty0, ty1 = t0 + 26, t0 + 66
        tlo, thi = min(Tv) - 1, max(Tv) + 1
        tp = [(Xh(i), ty1 - (ty1 - ty0) * (t - tlo) / (thi - tlo)) for i, t in enumerate(Tv)]
        by1 = t0 + 180; ptop = max(1.0, max(Pm))
        for i, v in enumerate(Pm):
            if v > 0.02:
                pg.rrect(Xh(i) - 5, by1 - 28 * min(v, ptop) / ptop - 1, Xh(i) + 5, by1, 2, fill=RAIN_L)
        pg.line(tp, TEMP, 2)
        for i in range(0, n, 4):
            x, yy = tp[i]
            pg.dot(x, yy, 3, TEMP)
            pg.text(x, yy - 8, "%.0f°" % Tv[i], 17, INK, bold=True, anchor="md")
            pg.icon(x, t0 + 96, 30, hr["skycon"][i]["value"])
            if PR[i] >= 10:
                pg.text(x, t0 + 122, "%d%%" % PR[i], 15, RAIN, bold=True, anchor="ma")
            pg.text(x, by1 + 8, hr["temperature"][i]["datetime"][11:16], 15, DIM, anchor="ma")
        y += hh + GAP

    # --- air quality, next 24 hours -----------------------------------------
    aq = (hr.get("air_quality") or {}).get("aqi") or []
    vals = [_aqi((a.get("value") or {}).get("chn")) for a in aq]
    have = [v for v in vals if v]
    if aq and len(have) * 2 < len(vals):
        # a series that is mostly holes is not a forecast; say it is missing
        lines = _wrap(pg, L["aq_none"], 17, X1 - X0)
        hh = _card_h(pg, 24 * len(lines) - 4)
        t0 = _card(pg, y, hh, L["aq"], L["aq_note"])
        for i, ln in enumerate(lines):
            pg.text(X0, t0 + 24 * i, ln, 17, DIM)
        y += hh + GAP
    elif aq:
        n = len(vals)
        lo_v, hi_v = min(have), max(have)
        b_lo, b_hi = aqi_band(lo_v, pg.lang)[0], aqi_band(hi_v, pg.lang)[0]
        bands = b_lo if b_lo == b_hi else L["aq_range"].format(a=b_lo, b=b_hi)
        lines = _wrap(pg, L["aq_said"].format(lo=lo_v, hi=hi_v, n=n, bands=bands), 17, X1 - X0)
        hh = _card_h(pg, 24 * len(lines) + 12 + 76 + 28)
        t0 = _card(pg, y, hh, L["aq"], L["aq_note"])
        for i, ln in enumerate(lines):
            pg.text(X0, t0 + 24 * i, ln, 17, INK, bold=True)
        bx0, bx1 = X0 + 34, X1
        by0 = t0 + 24 * len(lines) + 12 + 16; by1 = by0 + 60
        top = max(100, hi_v * 1.15)
        bw = (bx1 - bx0) / n
        # the band edges, so the space above low bars says "well under 100"
        # instead of being empty
        for edge in (0, 50, 100, 150, 200, 300):
            if edge <= top:
                ye = by1 - (by1 - by0) * edge / top
                pg.line([(bx0, ye), (bx1, ye)], FAINT, 1)
                pg.text(bx0 - 6, ye, str(edge), 15, DIM, anchor="rm")
        for i, v in enumerate(vals):
            if not v:
                continue                    # a hole stays a hole
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
        daq = [_aqi((a.get("max") or {}).get("chn")) for a in (dy.get("air_quality") or {}).get("aqi") or []]
        hh = _card_h(pg, nd * rowh - 14)
        t0 = _card(pg, y, hh, L["days"].format(n=nd), L["days_note"] if any(daq) else None)
        lo = min(t["min"] for t in days); hi = max(t["max"] for t in days)
        sx0, sx1 = X0 + 190, X1 - 34
        SX = lambda t: sx0 + (sx1 - sx0) * (t - lo) / max(1e-6, hi - lo)
        for k in range(nd):
            yy = t0 + k * rowh
            if k:
                pg.line([(X0, yy - 12), (X1, yy - 12)], FAINT, 1)
            date = datetime.strptime(days[k]["date"][:10], "%Y-%m-%d")
            pg.text(X0, yy, L["today"] if k == 0 else _weekday(date, pg.lang), 17, INK, bold=True)
            sk = dy["skycon"][k]["value"]
            pg.icon(X0 + 76, yy + 10, 30, sk)
            pp = (dy["precipitation"][k].get("probability") or 0) if k < len(dy.get("precipitation") or []) else 0
            if pp >= 10:
                pg.text(X0 + 100, yy + 2, "%d%%" % pp, 15, RAIN, bold=True)
            pg.text(X0, yy + 28, sky.get(sk, ""), 15, DIM)
            t = days[k]
            pg.text(sx0 - 6, yy + 10, "%.0f°" % t["min"], 17, DIM, anchor="rm")
            pg.rrect(sx0, yy + 7, sx1, yy + 13, 3, fill=FAINT)
            pg.rrect(SX(t["min"]), yy + 5, max(SX(t["max"]), SX(t["min"]) + 10), yy + 15, 5, fill=TEMP)
            pg.text(sx1 + 6, yy + 10, "%.0f°" % t["max"], 17, INK, bold=True, anchor="lm")
            if k < len(daq) and daq[k]:
                v = daq[k]
                nm = aqi_band(v, pg.lang)[0]
                e = X1 - pg.width(nm, 15) - 6
                pg.text(X1, yy + 39, nm, 15, INK, anchor="rm")
                _pill(pg, e, yy + 27, v, 15, right=True)
        y += hh + GAP

    # --- the way back to now ------------------------------------------------
    if qr:
        mx = _qr_matrix(qr)
        n = len(mx)
        mpx = max(4, int(116 * K) // n)            # whole pixels per module: crisp edges
        qs = n * mpx / K
        tx = X0 + qs + 18
        how = _wrap(pg, L["qr_how"], 17, X1 - tx, bold=False)
        this = _wrap(pg, L["qr_this"].format(t=wx_at.strftime("%H:%M")), 15, X1 - tx, bold=False)
        # the code carries the %-escaped address (any reader decodes it);
        # the line under it is for eyes, so it shows 上海 and not %E4%B8%8A
        from urllib.parse import unquote
        url = _wrap_chars(pg, unquote(qr), 14, X1 - X0)
        body = max(qs, 24 * len(how) + 6 + 20 * len(this)) + 12 + 19 * len(url)
        hh = _card_h(pg, body)
        t0 = _card(pg, y, hh, L["qr"])
        if pg.im is not None:
            px0, py0 = round(X0 * K), round(t0 * K)
            render.qr_at = (px0, py0, mpx, n)
            for ri, row in enumerate(mx):
                for ci, v in enumerate(row):
                    if v:
                        pg.d.rectangle((px0 + ci * mpx, py0 + ri * mpx,
                                        px0 + (ci + 1) * mpx - 1, py0 + (ri + 1) * mpx - 1), fill=INK)
        yy = t0 + 2
        for ln in how:
            pg.text(tx, yy, ln, 17, INK)
            yy += 24
        yy += 6
        for ln in this:
            pg.text(tx, yy, ln, 15, DIM)
            yy += 20
        yy = t0 + max(qs, 24 * len(how) + 6 + 20 * len(this)) + 12
        for ln in url:
            pg.text(X0, yy, ln, 14, DIM)
            yy += 19
        y += hh + GAP

    pg.text(M + 4, y + 4, L["foot1"], 14, DIM)
    pg.text(M + 4, y + 24, L["foot2"], 14, DIM)
    return y + 52


def _wrap_chars(pg, s, pt, width):
    """Break a string with no spaces (an address) by width, character by character."""
    out, cur = [], ""
    for ch in s:
        if cur and pg.width(cur + ch, pt) > width:
            out.append(cur); cur = ch
        else:
            cur += ch
    return out + [cur] if cur else out


_NO_LINE_START = set("、。，．,.!?！？：；:;)）」』】〕〉》°%％ーゃゅょっャュョッァィゥェォぁぃぅぇぉ々")


def _wrap(pg, s, pt, width, bold=True):
    if pg.lang != "en":
        # Chinese and Japanese break between characters, not at spaces --
        # except that closing punctuation never starts a line (kinsoku): the
        # first Japanese render left a lone "。" on a line of its own.
        out, cur = [], ""
        for ch in s:
            if cur and ch not in _NO_LINE_START and pg.width(cur + ch, pt, bold) > width:
                out.append(cur.rstrip()); cur = ch.lstrip()
            else:
                cur += ch
        return out + [cur] if cur else (out or [""])
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
