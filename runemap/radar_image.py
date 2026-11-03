"""Radar as a picture: the same window as the text map, for readers that can see.

bob 2026-11-03: vision models are good now, so offer the radar as an image
behind a link -- the text stays the product, the picture is one line in it.

What is drawn, and why each choice:

* The window is the text product's window (``ascii_radar_centered``): a square
  ``span_km`` on a side, centred on the asker, not on the radar station.  Same
  question, same answer, two renderings -- if they disagreed about where the
  rain is, the reader could not tell which one to believe.
* Caiyun's frame is a transparent overlay in Web Mercator (measured: lon span
  4.808 deg vs mercator-lat span 4.810 deg on the Shanghai frame).  Our window
  is Web Mercator too, so station -> window is one affine map, no resampling
  of the projection.
* Where the window runs past the station's image there is no radar at all.
  That area is hatched, the picture's version of the text map's ``?``.  Inside
  the station image, "no rain" and "out of the radar's reach" are both
  transparent upstream; we cannot tell them apart and do not pretend to.
* Basemap is Natural Earth 10m (public domain), cut offline into 10-degree
  tiles (``data/ne/*.npz``) so a request reads only the tiles its window
  touches.  This box has ~1 GB of RAM and other people's traffic on it; the
  full land layer costs 130 MB to parse, one tile costs almost nothing.
* Legend: the colours present in THIS frame, ordered weak -> strong by how deep
  inside an echo they sit, each blended exactly as on the map.  No mm/h labels:
  we do not know Caiyun's thresholds, and a confident number we made up would
  be worse than an honest "weaker / stronger".
* Text is English only: no CJK font is installed, and a label of tofu boxes is
  a label that says nothing.
"""
import io
import math
import os
import threading
import time
from collections import OrderedDict

import numpy as np
from PIL import Image, ImageDraw, ImageFont

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "ne")
TILE = 10            # degrees; must match the offline cutter
SIZE = 800
ALPHA = 0.9

PAL = dict(sea=(214, 223, 231), land=(246, 244, 238), lake=(214, 223, 231),
           coast=(150, 162, 175), border=(120, 128, 140), city=(70, 76, 86),
           text=(40, 44, 52), dim=(90, 96, 106), mark=(200, 30, 30),
           marktext=(160, 20, 20), white=(255, 255, 255))


# --- projection -------------------------------------------------------------

def merc_y(lat):
    lat = np.clip(np.asarray(lat, float), -85.0, 85.0)
    return np.degrees(np.log(np.tan(np.pi / 4 + np.radians(lat) / 2)))


def inv_merc_y(y):
    return math.degrees(2 * math.atan(math.exp(math.radians(y))) - math.pi / 2)


def window(lon, lat, span_km):
    """-> (lat0, lon0, lat1, lon1): a Mercator-square window, span_km across at lat."""
    h = (span_km / 2.0) / (111.32 * math.cos(math.radians(lat)))
    yc = float(merc_y(lat))
    return (inv_merc_y(yc - h), lon - h, inv_merc_y(yc + h), lon + h)


class _Proj:
    def __init__(self, wb, size):
        self.lat0, self.lon0, self.lat1, self.lon1 = wb
        self.x0, self.x1 = self.lon0, self.lon1
        self.y0, self.y1 = float(merc_y(self.lat0)), float(merc_y(self.lat1))
        self.s = size

    def __call__(self, lon, lat):
        x = (np.asarray(lon, float) - self.x0) / (self.x1 - self.x0) * self.s
        y = (self.y1 - merc_y(lat)) / (self.y1 - self.y0) * self.s
        return x, y


# --- Natural Earth tiles ----------------------------------------------------

_NPZ = {}
_NPZ_LOCK = threading.Lock()
_PLACES = None


def _layer(name):
    with _NPZ_LOCK:
        z = _NPZ.get(name)
        if z is None:
            # np.load on an npz is lazy: each key is decompressed on access.
            z = _NPZ[name] = np.load(os.path.join(DATA, name + ".npz"))
        return z


def _tiles(wb):
    lat0, lon0, lat1, lon1 = wb
    for tx in range(int(math.floor(lon0 / TILE)) * TILE, int(math.ceil(lon1 / TILE)) * TILE, TILE):
        for ty in range(int(math.floor(lat0 / TILE)) * TILE, int(math.ceil(lat1 / TILE)) * TILE, TILE):
            yield "%d_%d" % (tx, ty)


def _rings(name, wb):
    """Yield (int32 milli-degree coords Nx2, is_hole) for rings near the window."""
    z = _layer(name)
    keys = set(z.files)
    lat0, lon0, lat1, lon1 = wb
    m = 0.05
    for k in _tiles(wb):
        if k + "_xy" not in keys:
            continue
        xy, ns, hs = z[k + "_xy"], z[k + "_n"], z[k + "_h"]
        off = 0
        for n, h in zip(ns.tolist(), hs.tolist()):
            a = xy[off:off + n]; off += n
            lo, la = a[:, 0] / 1000.0, a[:, 1] / 1000.0
            if lo.max() < lon0 - m or lo.min() > lon1 + m or la.max() < lat0 - m or la.min() > lat1 + m:
                continue
            yield a, h


def _not_tile_edge(a):
    """Mask of segments that are real coastline, not a cut made by the tiler.

    Polygons were clipped to 10-degree squares offline; drawn as-is, every tile
    border would show up as a straight 'coast'.  A cut segment runs exactly
    along x or y == k*TILE (in milli-degrees, an exact integer), both ends."""
    t = TILE * 1000
    x0, y0, x1, y1 = a[:-1, 0], a[:-1, 1], a[1:, 0], a[1:, 1]
    cut = ((x0 == x1) & (x0 % t == 0)) | ((y0 == y1) & (y0 % t == 0))
    return ~cut


def _polys(d, P, name, fill, hole_fill, outline):
    for a, hole in _rings(name, P.wb):
        x, y = P(a[:, 0] / 1000.0, a[:, 1] / 1000.0)
        pts = list(zip(x.tolist(), y.tolist()))
        if len(pts) < 3:
            continue
        d.polygon(pts, fill=hole_fill if hole else fill)
        if outline:
            closed = np.vstack([a, a[:1]])
            keep = _not_tile_edge(closed)
            cx, cy = P(closed[:, 0] / 1000.0, closed[:, 1] / 1000.0)
            for i in np.nonzero(keep)[0].tolist():
                d.line((cx[i], cy[i], cx[i + 1], cy[i + 1]), fill=outline, width=1)


def _lines(d, P, name, color, width):
    for a, _ in _rings(name, P.wb):
        x, y = P(a[:, 0] / 1000.0, a[:, 1] / 1000.0)
        d.line(list(zip(x.tolist(), y.tolist())), fill=color, width=width)


def _places():
    global _PLACES
    if _PLACES is None:
        import json
        with open(os.path.join(DATA, "places.json"), encoding="utf-8") as f:
            _PLACES = json.load(f)       # [lon, lat, name, scalerank]
    return _PLACES


# Liberation Sans (Arial metrics) where the box has it: PIL's built-in face is
# thin, and on a phone the thin strokes are what made "too small" worse.
_FONT_FILES = {False: ("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
                       "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
               True: ("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
                      "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")}
_FONTS = {}


def font(px, bold=False):
    f = _FONTS.get((px, bold))
    if f is None:
        for path in _FONT_FILES[bold]:
            if os.path.exists(path):
                f = ImageFont.truetype(path, px)
                break
        else:
            f = ImageFont.load_default(size=px)
        _FONTS[(px, bold)] = f
    return f


def _font(n):
    return font(n)


_BASE = OrderedDict()
_BASE_LOCK = threading.Lock()
_BASE_MAX = 6          # 800x800 RGB ~ 1.9 MB each


def basemap(lon, lat, span_km, size=SIZE, ui=1.0):
    """Land/lakes/borders/towns for the window. Cached per window: the basemap
    does not change between frames, and drawing it is most of the work."""
    key = (round(lon, 2), round(lat, 2), round(span_km), size, round(ui, 2))
    with _BASE_LOCK:
        im = _BASE.get(key)
        if im is not None:
            _BASE.move_to_end(key)
            return im
    wb = window(lon, lat, span_km)
    P = _Proj(wb, size); P.wb = wb
    im = Image.new("RGB", (size, size), PAL["sea"])
    d = ImageDraw.Draw(im)
    _polys(d, P, "land", PAL["land"], PAL["sea"], PAL["coast"])
    _polys(d, P, "lakes", PAL["lake"], PAL["land"], PAL["coast"])
    _lines(d, P, "admin_0_boundary_lines_land", PAL["border"], max(2, round(2 * ui)))
    # Towns: more of them in a small window, only the big ones in a wide one.
    rank = 6 if span_km <= 300 else 4
    fc = _font(round(15 * ui))
    for clon, clat, name, sr in _places():
        if sr > rank or not (wb[1] < clon < wb[3] and wb[0] < clat < wb[2]):
            continue
        # the asker's own point gets the red marker; a town dot on top of it
        # would hide it
        if abs(clon - lon) < 0.15 and abs(clat - lat) < 0.15:
            continue
        x, y = (float(v) for v in P(clon, clat))
        rr = 3 * ui
        d.ellipse((x - rr, y - rr, x + rr, y + rr), fill=PAL["city"])
        d.text((x + 2 * rr, y - 9 * ui), name, font=fc, fill=PAL["text"],
               stroke_width=max(2, round(2 * ui)), stroke_fill=PAL["white"])
    with _BASE_LOCK:
        _BASE[key] = im
        while len(_BASE) > _BASE_MAX:
            _BASE.popitem(last=False)
    return im


# --- legend -----------------------------------------------------------------

_LEG = OrderedDict()
_LEG_LOCK = threading.Lock()


def legend_colours(st, cache_key=None):
    """Colours present in this frame, weak -> strong by depth inside the echo."""
    if cache_key is not None:
        with _LEG_LOCK:
            if cache_key in _LEG:
                return _LEG[cache_key]
    raw = np.asarray(st).astype(np.int16)
    wet = raw[..., 3] > 50
    depth = np.zeros(wet.shape, np.int16)
    cur = wet.copy(); k = 0
    while cur.any() and k < 60:
        k += 1; depth[cur] = k; n = cur.copy()
        n[1:] &= cur[:-1]; n[:-1] &= cur[1:]; n[:, 1:] &= cur[:, :-1]; n[:, :-1] &= cur[:, 1:]
        cur = n
    q = (raw[..., 0] // 32) * 64 + (raw[..., 1] // 32) * 8 + (raw[..., 2] // 32)
    out = []
    for v in np.unique(q[wet]):
        m = wet & (q == v)
        if m.sum() < 150:
            continue
        rgb = np.median(raw[m][:, :3], axis=0)
        al = float(np.median(raw[m][:, 3])) / 255 * ALPHA
        out.append((float(np.median(depth[m])),
                    tuple(int(c * al + l * (1 - al)) for c, l in zip(rgb, PAL["land"]))))
    out.sort()
    cols = [c for _, c in out]
    if cache_key is not None:
        with _LEG_LOCK:
            _LEG[cache_key] = cols
            while len(_LEG) > 32:
                _LEG.popitem(last=False)
    return cols


# --- the picture ------------------------------------------------------------

def when_text(frame_ts, obs_ts=None):
    """A frame extrapolated from an older observation is not "observed"."""
    hm = lambda t: time.strftime("%Y-%m-%d %H:%MZ", time.gmtime(t))
    if obs_ts is not None and abs(float(frame_ts) - float(obs_ts)) >= 60:
        return "radar predicted for %s from obs %s" % (
            hm(frame_ts), time.strftime("%H:%MZ", time.gmtime(obs_ts)))
    return "radar observed %s" % hm(frame_ts)


# --- motion -----------------------------------------------------------------
#
# What the reader wants from a motion vector is "when does that rain get here",
# so the mark is one dashed arrow coming in from UPWIND and ending on the
# asker, ticked in time: rain lying on the "1 h" tick now reaches the marker
# in about an hour if it keeps moving like this. Same vector the text map prints (vx east+, vy SOUTH+, km/h -- image
# rows), so the two cannot disagree. It assumes the echo translates rigidly;
# the box says where the vector came from, and says no more than the text line.

MOTION_COL = (30, 60, 110)
TICKS = ((0.5, "30 min"), (1, "1 h"), (2, "2 h"), (3, "3 h"))


def draw_motion(d, mo, size, span_km, ui=1.0, inner=None):
    """Draw the upwind ticks and the arrow; -> list of segments drawn, for
    the label placer. Nothing is drawn unless the echo is moving."""
    if not mo or mo.get("kind") != "moving":
        return []
    vx, vy = float(mo["vx"]), float(mo["vy"])
    sp = math.hypot(vx, vy)
    if sp <= 0:
        return []
    ux, uy = vx / sp, vy / sp
    nx, ny = -uy, ux
    c = size / 2.0
    ppk = size / float(span_km)
    # How far upwind the dashes may run: to the inner map area, along THIS
    # direction -- a fixed radius let a southbound line run up into the title
    # bar. Inner box keeps clear of the title (top) and the legend (bottom).
    x0, y0, x1, y1 = inner or (24.0, 60.0, size - 24.0, size - 110.0)
    tx = ((x0 - c) / -ux if ux > 0 else (x1 - c) / -ux) if ux else float("inf")
    ty = ((y0 - c) / -uy if uy > 0 else (y1 - c) / -uy) if uy else float("inf")
    lim = min(tx, ty)
    col = MOTION_COL + (235,)
    segs = []
    shown = [(h, lab) for h, lab in TICKS if h * sp * ppk <= lim]
    L = (shown[-1][0] * sp * ppk) if shown else lim
    # One arrow, pointing AT the asker: it comes in from upwind and its head
    # stops on the marker ring. The first version had the dashes upwind plus
    # a red arrow leaving the marker downwind -- bob: that reads as "going
    # away", while what the picture means is "arriving here".
    head0, head1 = 13.0 * ui, 30.0 * ui       # tip on the ring, base further out
    lw = max(3, round(3 * ui))
    a = head1
    while a < L:
        b = min(a + 10.0 * ui, L)
        d.line((c - ux * a, c - uy * a, c - ux * b, c - uy * b), fill=col, width=lw)
        a += 18.0 * ui
    tip = (c - ux * head0, c - uy * head0)
    base = (c - ux * head1, c - uy * head1)
    hw = 8 * ui
    d.polygon([tip, (base[0] + nx * hw, base[1] + ny * hw),
               (base[0] - nx * hw, base[1] - ny * hw)], fill=col)
    segs.append(((c, c), (c - ux * L, c - uy * L), 14 * ui))
    ft = _font(round(14 * ui))
    for h, lab in shown:
        rr = h * sp * ppk
        x, y = c - ux * rr, c - uy * rr
        d.line((x - nx * hw, y - ny * hw, x + nx * hw, y + ny * hw), fill=col, width=lw)
        # tick label on one fixed side of the line, never on the line itself
        tw = ft.getlength(lab)
        th = 16 * ui
        lx, ly = x + nx * 14 * ui, y + ny * 14 * ui
        lx -= tw / 2 * (1 - nx)               # left-align when the side points right
        ly -= th / 2 * (1 - ny)
        d.text((lx, ly), lab, font=ft, fill=MOTION_COL, stroke_width=max(2, round(2 * ui)),
               stroke_fill=PAL["white"])
        segs.append(((lx, ly), (lx + tw, ly + th), 0))
    return segs


def _hits(box, segs):
    """Does a text box (x0,y0,x1,y1) come within a segment's half-width?"""
    x0, y0, x1, y1 = box
    for s in segs:
        (ax, ay), (bx, by), w = s
        if w == 0:                            # another text box
            if not (bx < x0 or ax > x1 or by < y0 or ay > y1):
                return True
            continue
        for t in np.linspace(0.0, 1.0, 40):
            px, py = ax + (bx - ax) * t, ay + (by - ay) * t
            if x0 - w <= px <= x1 + w and y0 - w <= py <= y1 + w:
                return True
    return False


def place_label(bb, c, r, segs, size):
    """-> (x, y, x1, y1) for the marker's name: first candidate that touches
    no motion mark. Candidates go round the marker; east first because that
    is where it sits when there is nothing to avoid."""
    w, h = bb[2] - bb[0], bb[3] - bb[1]
    g = r + 9
    cands = [(c + g, c - h / 2 - 2),               # E
             (c - w / 2, c - g - h - 4),           # N
             (c - w / 2, c + g),                   # S
             (c - g - w, c - h / 2 - 2),           # W
             (c + g, c - g - h), (c + g, c + g * 0.6),          # NE, SE
             (c - g - w, c - g - h), (c - g - w, c + g * 0.6)]  # NW, SW
    for x, y in cands:
        box = (x, y, x + w, y + h)
        if box[0] >= 4 and box[2] <= size - 4 and not _hits(box, segs):
            return box
    x, y = cands[0]
    return (x, y, x + w, y + h)


def motion_box(d, mo, basis, size):
    """Top-right box, same words as the text map's motion line."""
    kind = (mo or {}).get("kind")
    if kind == "moving":
        head = "echo moving %s ~%.0f km/h" % (mo.get("dir_en", "?"), float(mo["kmh"]))
        sub = ["basis: %s" % basis if basis else None,
               "arrow: rain on it reaches you at the time marked"]
    elif kind == "stationary":
        head, sub = "echo stationary (<5 km/h)", ["basis: %s" % basis if basis else None]
    elif kind == "undetermined":
        why = {"sparse": "echo too sparse to track", "corr": "frames not correlated",
               "fetch": "tracking frames failed", "frames": "too few usable frames",
               "noecho": "no echo to track", "error": "computation failed"}
        head, sub = "echo motion undetermined", [why.get(mo.get("why"), mo.get("why") or "")]
    else:
        return
    sub = [x for x in sub if x]
    fh, fs = _font(16), _font(14)
    w = max([fh.getlength(head)] + [fs.getlength(x) for x in sub]) + 20
    x0, y0 = size - 10 - w, 44
    d.rectangle((x0, y0, size - 10, y0 + 30 + 18 * len(sub)), fill=PAL["white"] + (225,))
    d.text((x0 + 10, y0 + 6), head, font=fh, fill=PAL["text"])
    for i, t in enumerate(sub):
        d.text((x0 + 10, y0 + 28 + 18 * i), t, font=fs, fill=PAL["dim"])


def _hatch(size, step=14, width=2):
    h = Image.new("RGBA", (size, size), (120, 126, 136, 70))
    hd = ImageDraw.Draw(h)
    for k in range(-size, size, step):
        hd.line((k, size, k + size, 0), fill=(110, 116, 126, 150), width=width)
    return h


def _scale_bar(d, size, span_km, fs, ui, bottom=None):
    bar = 50 if span_km <= 400 else 100
    ppk = size / span_km
    byp = size - (bottom if bottom is not None else 30 * ui)
    bxp = size - 30 * ui - bar * ppk
    th = fs.getbbox("0")[3]
    d.rectangle((bxp - 8 * ui, byp - th - 10 * ui, size - 14 * ui, byp + 10 * ui), fill=PAL["white"] + (225,))
    d.line((bxp, byp, bxp + bar * ppk, byp), fill=PAL["text"], width=max(3, round(3 * ui)))
    for xx in (bxp, bxp + bar * ppk):
        d.line((xx, byp - 5 * ui, xx, byp + 5 * ui), fill=PAL["text"], width=max(2, round(2 * ui)))
    d.text((bxp, byp - th - 7 * ui), "%d km" % bar, font=fs, fill=PAL["text"])


def render(png, bbox, lon, lat, label, frame_ts, obs_ts=None, span_km=200.0,
           size=SIZE, frame_key=None, motion=None, basis=None, ui=1.0, bare=False,
           as_image=False):
    """-> (PNG bytes, fraction of the picture with no radar).

    png       Caiyun frame bytes (transparent overlay, Web Mercator)
    bbox      [lat0, lon0, lat1, lon1] of that frame, as upstream gives it
    frame_ts  the time the frame depicts; obs_ts the observation it came from
              (differ when the frame is extrapolated -- then the title says so)
    ui        scale for text, lines and marks, independent of size: a picture
              read on a phone needs its labels ~2x larger RELATIVE to the map,
              which an upscale cannot give (it grows the map with them)
    bare      map only (basemap, radar, hatch, marker, motion arrow, scale bar):
              the caller draws title, legend and motion words itself
    """
    span_km = float(span_km)
    wb = window(lon, lat, span_km)
    img = basemap(lon, lat, span_km, size, ui).convert("RGBA")

    st = Image.open(io.BytesIO(png)).convert("RGBA")
    sw, sh = st.size
    s_lat0, s_lon0, s_lat1, s_lon1 = (float(v) for v in bbox)
    sx0, sx1 = s_lon0, s_lon1
    sy0, sy1 = float(merc_y(s_lat0)), float(merc_y(s_lat1))
    wx0, wx1 = wb[1], wb[3]
    wy0, wy1 = float(merc_y(wb[0])), float(merc_y(wb[2]))
    # output pixel -> station pixel (both Web Mercator: one affine map)
    ax = (wx1 - wx0) / size / (sx1 - sx0) * sw
    bx = (wx0 - sx0) / (sx1 - sx0) * sw
    ay = (wy1 - wy0) / size / (sy1 - sy0) * sh
    by = (sy1 - wy1) / (sy1 - sy0) * sh
    radar = st.transform((size, size), Image.AFFINE, (ax, 0, bx, 0, ay, by),
                         resample=Image.BILINEAR, fillcolor=(0, 0, 0, 0))
    radar.putalpha(radar.getchannel("A").point(lambda v: int(v * ALPHA)))
    img = Image.alpha_composite(img, radar)

    u = np.arange(size) + 0.5
    sxp, syp = ax * u + bx, ay * u + by
    outside = (~((sxp >= 0) & (sxp < sw)))[None, :] | (~((syp >= 0) & (syp < sh)))[:, None]
    n_out = int(outside.sum())
    if n_out:
        # Blend, do not paste: paste() writes the hatch's own alpha (70) into
        # the picture, and the RGB export then shows that layer opaque -- the
        # first version drew "no radar" as a solid grey slab.
        h = _hatch(size, step=round(14 * ui), width=max(2, round(2 * ui)))
        a = np.asarray(h.getchannel("A")).astype(np.uint16) * outside
        h.putalpha(Image.fromarray(a.astype(np.uint8)))
        img = Image.alpha_composite(img, h)

    d = ImageDraw.Draw(img)
    fs = _font(round(14 * ui))
    c0, r = size / 2.0, 10 * ui
    inner = (24.0 * ui, 24.0 * ui, size - 24.0 * ui, size - 80.0 * ui) if bare else None
    segs = draw_motion(d, motion, size, span_km, ui, inner) if motion else []
    d.ellipse((c0 - r, c0 - r, c0 + r, c0 + r), outline=PAL["mark"], width=max(3, round(3 * ui)))
    d.line((c0 - r - 7 * ui, c0, c0 + r + 7 * ui, c0), fill=PAL["mark"], width=max(2, round(2 * ui)))
    d.line((c0, c0 - r - 7 * ui, c0, c0 + r + 7 * ui), fill=PAL["mark"], width=max(2, round(2 * ui)))
    # The marker gets the place's own name ("Shanghai"), not the whole
    # gazetteer label ("Shanghai, Shanghai Municipality, Shanghai, CN"),
    # which ran off the right edge on the first live render. It goes wherever
    # the motion marks are not: the first mock put it to the east, right
    # under an eastbound arrow.
    name = label.split(",")[0].strip()
    fm = _font(round(18 * ui))
    sw_ = max(3, round(3 * ui))
    box = place_label(fm.getbbox(name, stroke_width=sw_), c0, r, segs, size)
    d.text((box[0], box[1]), name, font=fm, fill=PAL["marktext"],
           stroke_width=sw_, stroke_fill=PAL["white"])
    if bare:
        _scale_bar(d, size, span_km, fs, ui)
        if as_image:          # the caller composites it; encoding here is wasted
            return img.convert("RGB"), n_out / float(size * size)
        buf = io.BytesIO()
        img.convert("RGB").save(buf, "PNG", optimize=True)
        return buf.getvalue(), n_out / float(size * size)
    if motion:
        motion_box(d, motion, basis, size)

    when = when_text(frame_ts, obs_ts)
    d.rectangle((0, 0, size, 34), fill=PAL["white"] + (225,))
    ft = _font(18)
    parts = [x.strip() for x in label.split(",") if x.strip()] or [label]
    while True:
        # drop the middle of the label (region names) before the country,
        # until the line fits: "Shanghai, CN" beats a title cut mid-word
        name = ", ".join(parts)
        title = "%s  -  %s  -  %d km square" % (name, when, round(span_km))
        if ft.getlength(title) <= size - 24 or len(parts) <= 1:
            break
        parts = parts[:1] + parts[2:] if len(parts) > 2 else parts[:1]
    d.text((12, 7), title, font=ft, fill=PAL["text"])

    cols = legend_colours(st, frame_key)
    bw = 28; lx, ly = 14, size - 24 - 62
    d.rectangle((lx - 8, ly - 26, lx + max(bw * len(cols), 150) + 130, ly + 30),
                fill=PAL["white"] + (225,))
    if cols:
        d.text((lx, ly - 22), "rain (caiyun colour scale)", font=fs, fill=PAL["text"])
        for i, col in enumerate(cols):
            d.rectangle((lx + i * bw, ly, lx + (i + 1) * bw - 2, ly + 14), fill=col + (255,))
        d.text((lx, ly + 15), "weaker", font=fs, fill=PAL["text"])
        if len(cols) > 3:
            d.text((lx + bw * len(cols) - 56, ly + 15), "stronger", font=fs, fill=PAL["text"])
    else:
        d.text((lx, ly - 22), "no rain on this radar frame", font=fs, fill=PAL["text"])
    hx = lx + max(bw * len(cols), 150) + 18
    sample = Image.new("RGBA", (26, 14), (120, 126, 136, 70))
    sd = ImageDraw.Draw(sample)
    for k in range(-14, 26, 7):
        sd.line((k, 14, k + 14, 0), fill=(110, 116, 126, 170), width=2)
    img.paste(sample, (hx, ly), sample)
    d.text((hx + 32, ly), "no radar", font=fs, fill=PAL["text"])

    _scale_bar(d, size, span_km, fs, 1.0, bottom=46)

    d.rectangle((0, size - 24, size, size), fill=PAL["white"] + (225,))
    d.text((12, size - 20), "radar: caiyunapp.com  |  basemap: Natural Earth (public domain)  |  echorune.net",
           font=fs, fill=PAL["dim"])

    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG", optimize=True)
    return buf.getvalue(), n_out / float(size * size)
