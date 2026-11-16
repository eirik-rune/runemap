"""Raw radar grid for a lon/lat box: numbers instead of glyphs (issue #259).

    GET /radar.json?bbox=<lon0>,<lat0>,<lon1>,<lat1>[&res=<km>][&frames=<n>][&since=<t>]

Asked for by Qianlu: a user wanted a radar mosaic of Gansu (~1,600 km), one
text view covers 280 km, and stitching 13 text maps back into numbers was
lossy, fragile, heavy on this box and had no history.

What upstream gives, measured 2026-11-14 -- the shape below follows from it:

* Caiyun radar is per station, not a mosaic.  ``v1/radar/images?lon&lat``
  answers with ONE station, the one serving that point: 20-26 transparent
  PNG frames 5-10 min apart (about two hours), Web Mercator, a box of about
  4.1 x 5.1 degrees around the station.  A point no station serves answers
  ``{"status": "failed"}`` (Dunhuang, Qaidam: measured).
* Stations are dense in the east: near Lanzhou two centres are 0.3-0.5 deg
  apart.  So "find every station" is not needed and not affordable; probing a
  lattice and taking each point's station is.
* A station's reach is the circle inscribed in its box, not the box.  Of
  818,352 pixels with echo in 80 cached China frames, 37 fell outside that
  circle (one station, at most 1.08 radii); the station that rained widest
  stopped at 0.992.  So the corners of a station picture are "this radar
  cannot see here" and are null below, not 0.  Measured on China stations
  (ids "AZ..."); for any other station we do not know the shape, so its whole
  box counts as seen and the station is listed with reach "box".
* Colour is the only intensity there is: the 14 colours of CAIYUN_RAMP, no
  thresholds published.  They look like the common 5-dBZ reflectivity palette,
  but its 2nd and 3rd colours are almost never drawn (1,542 and 0 of 18.1M
  visible pixels) while the 1st and 4th carry a third each -- not how a dBZ
  field spreads.  So no dBZ or mm/h is printed: a value is the step on the
  scale, 1 (weakest) .. 14, and the legend gives each step's colour.
* "Is there echo" uses the same test as the text map (alpha > 50), so the
  two products cannot disagree about where it rains.  Visible pixels are
  alpha 90 (99.8%) or 255; 0.1% are off every ramp colour and take the
  nearest step.

Mosaic:

* Probe a 1-degree lattice over the box (plus one degree around it, because a
  station outside the box can see into it): even points first, then only the
  points no station found so far reaches.  Which station a point gets is kept
  a day -- stations do not move.  A "failed" answer is kept 3 h only, because
  upstream also says "failed" transiently at covered places (scene_at._usable
  records an incident), and a day of that would blank a province.
* Frame lists and PNGs go through the same cache as the text map (list 5 min,
  frames 30 min), so asking twice costs upstream nothing.
* Per cell: the highest step over every station that reaches it; 0 when some
  station reaches it and draws nothing; null when none of the stations we
  found reaches it.
* ``since=<t>`` (a frame's own ``t``, or epoch seconds) keeps only frames newer
  than t, compared to the minute, so passing back the newest t you have
  returns nothing twice.  Asked for by the first consumer: a poller re-fetching
  3 MB to learn one new frame.  ``newest`` is always given.
* Frames step back 6 min from the latest time at least 90% of the stations
  have a frame for (see align()); a station uses its frame nearest each target within 5 min
  (half of the slowest cadence seen, 10 min), otherwise it sits that frame out
  and is named in that frame's "gaps".
"""
import calendar
import io
import json
import math
import re
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from PIL import Image

MAX_SIDE_KM = 2000.0
MIN_RES_KM = 4.0
MAX_RES_KM = 50.0
DEFAULT_RES_KM = 5.0
MAX_FRAMES = 20                 # upstream keeps 20-26; leave a margin
MAX_VALUES = 2_500_000          # cells x frames; keeps one answer under ~10 MB raw
STEP_S = 360                    # target spacing between returned frames
MATCH_S = 300                   # half of the slowest cadence seen (10 min)
AGREE = 0.9                     # share of stations the newest frame waits for; see align()
LATTICE = 1.0                   # degrees between probe points
PROBE_OK_TTL = 86400            # stations do not move
PROBE_FAIL_TTL = 3 * 3600       # "failed" is also a transient upstream answer
MAX_NEW_PROBES = 150            # per request; the rest is said, not hidden
WORKERS = 6
VISIBLE_ALPHA = 50              # same test as runemap.render.classify
KM_PER_DEG = 111.32

_BUILD = threading.Semaphore(1)  # one mosaic at a time on a 1 GB box
_FILE_LOCK = threading.Lock()


class BadRequest(ValueError):
    """The question cannot be answered as asked; the message says why."""


# --- geometry ---------------------------------------------------------------

def merc_y(lat):
    lat = np.clip(np.asarray(lat, float), -85.0, 85.0)
    return np.degrees(np.log(np.tan(np.pi / 4 + np.radians(lat) / 2)))


def inv_merc_y(y):
    return np.degrees(2 * np.arctan(np.exp(np.radians(np.asarray(y, float)))) - np.pi / 2)


class Grid:
    """A plain lon/lat grid. Cell [0][0] is the north-west cell; row 0 is north.
    lon0/lat0 name the CENTRE of that cell; dlat is negative (rows go south)."""

    def __init__(self, west, south, east, north, res_km):
        self.west, self.south, self.east, self.north = west, south, east, north
        mid = math.radians((south + north) / 2.0)
        self.dlat = res_km / KM_PER_DEG
        self.dlon = res_km / (KM_PER_DEG * max(math.cos(mid), 0.05))
        self.nx = max(1, int(math.ceil((east - west) / self.dlon - 1e-9)))
        self.ny = max(1, int(math.ceil((north - south) / self.dlat - 1e-9)))

    def header(self):
        return {"lon0": round(self.west + self.dlon / 2, 6),
                "lat0": round(self.north - self.dlat / 2, 6),
                "dlon": round(self.dlon, 6), "dlat": round(-self.dlat, 6),
                "nx": self.nx, "ny": self.ny, "cell": "lon0/lat0 is the centre of values[0][0]; row 0 is north"}


def parse(qs):
    """qs: parse_qs dict -> (west, south, east, north, res_km, frames, since). Raises BadRequest."""
    raw = (qs.get("bbox") or [""])[0]
    try:
        w, s, e, n = (float(v) for v in raw.split(","))
    except ValueError:
        raise BadRequest("bbox must be four numbers: bbox=<lon0>,<lat0>,<lon1>,<lat1> "
                         "(west,south,east,north), e.g. bbox=92.3,32.5,108.7,42.8")
    if not all(math.isfinite(v) for v in (w, s, e, n)):
        raise BadRequest("bbox values must be finite numbers")
    if not (-180 <= w < e <= 180):
        raise BadRequest("bbox lon0 must be west of lon1, both within -180..180 (got %s, %s)" % (w, e))
    if not (-85 <= s < n <= 85):
        raise BadRequest("bbox lat0 must be south of lat1, both within -85..85 (got %s, %s)" % (s, n))
    ns_km = (n - s) * KM_PER_DEG
    # the widest east-west extent is at the latitude closest to the equator
    lat_w = 0.0 if s <= 0 <= n else min(abs(s), abs(n))
    ew_km = (e - w) * KM_PER_DEG * math.cos(math.radians(lat_w))
    if max(ns_km, ew_km) > MAX_SIDE_KM:
        raise BadRequest("bbox is %.0f x %.0f km; the cap is %.0f km a side"
                         % (ew_km, ns_km, MAX_SIDE_KM))
    try:
        res = float((qs.get("res") or [DEFAULT_RES_KM])[0])
    except ValueError:
        raise BadRequest("res is a number of km per cell, %g..%g" % (MIN_RES_KM, MAX_RES_KM))
    if not (MIN_RES_KM <= res <= MAX_RES_KM):
        raise BadRequest("res=%s km is outside %g..%g" % (res, MIN_RES_KM, MAX_RES_KM))
    since = None
    if qs.get("since"):
        since = parse_since(qs["since"][0])
    g = Grid(w, s, e, n, res)
    if qs.get("frames"):
        try:
            frames = int(qs["frames"][0])
        except ValueError:
            raise BadRequest("frames is a whole number, 1..%d" % MAX_FRAMES)
        if not (1 <= frames <= MAX_FRAMES):
            raise BadRequest("frames=%s is outside 1..%d" % (frames, MAX_FRAMES))
    elif since is not None:
        # a poller wants every new frame, not one: as many as the value cap allows
        frames = max(1, min(MAX_FRAMES, MAX_VALUES // (g.nx * g.ny)))
    else:
        frames = 1
    if g.nx * g.ny * frames > MAX_VALUES:
        fit = max(1, MAX_VALUES // (g.nx * g.ny))
        raise BadRequest("%d x %d cells x %d frames = %d values; the cap is %d. "
                         "Ask for frames<=%d, or a coarser res."
                         % (g.nx, g.ny, frames, g.nx * g.ny * frames, MAX_VALUES, fit))
    return w, s, e, n, res, frames, since


def parse_since(raw):
    raw = raw.strip()
    if re.fullmatch(r"\d{9,11}", raw):
        return float(raw)
    for fmt in ("%Y-%m-%dT%H:%MZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return float(calendar.timegm(time.strptime(raw, fmt)))
        except ValueError:
            pass
    raise BadRequest("since is a frame time as this endpoint writes it in t, "
                     "e.g. since=2026-11-14T16:17Z, or epoch seconds")


# --- colour scale -------------------------------------------------------------

def _ramp():
    from runemap.radar_image import CAIYUN_RAMP
    return np.array(CAIYUN_RAMP, dtype=np.int32)


def levels(rgba, ramp):
    """HxWx4 uint8 -> HxW int8: 0 where nothing is drawn, else 1 + nearest ramp step."""
    a = rgba[..., 3]
    vis = a > VISIBLE_ALPHA
    lv = np.zeros(a.shape, dtype=np.int8)
    if vis.any():
        # Distances on the distinct colours only: a frame draws a few dozen, and
        # pixels x 14 x 3 int32 for a frame full of rain is ~50 MB on a 1 GB box.
        px = rgba[vis][:, :3].astype(np.int32)
        packed = (px[:, 0] << 16) | (px[:, 1] << 8) | px[:, 2]
        uniq, inv = np.unique(packed, return_inverse=True)
        u = np.stack([(uniq >> 16) & 255, (uniq >> 8) & 255, uniq & 255], axis=1)
        d = ((u[:, None, :] - ramp[None, :, :]) ** 2).sum(axis=2)
        lv[vis] = (d.argmin(axis=1) + 1).astype(np.int8)[inv.reshape(-1)]
    return lv, vis


# --- probes -------------------------------------------------------------------

def _pkey(lon, lat):
    return "%.1f,%.1f" % (lon, lat)


class ProbeBook:
    """Which station serves a lattice point. One small JSON file in the cache dir;
    two service instances share it, and a lost write only means a re-probe."""

    def __init__(self, path, now=time.time):
        self.path, self.now = path, now
        self.d = self._load()

    def _load(self):
        try:
            with open(self.path) as f:
                d = json.load(f)
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def get(self, key):
        e = self.d.get(key)
        if not isinstance(e, dict):
            return None
        ttl = PROBE_OK_TTL if e.get("s") else PROBE_FAIL_TTL
        if self.now() - float(e.get("at", 0)) > ttl:
            return None
        return e

    def put(self, key, entry):
        self.d[key] = entry

    def rename(self, old, new, bbox):
        """Upstream gave a station a new id: move the points the book had on it.
        Their "at" stays, so a renamed entry still ages out on its own day."""
        for k, e in list(self.d.items()):
            if isinstance(e, dict) and e.get("s") == old:
                self.d[k] = dict(e, s=new, bbox=list(bbox))

    def save(self):
        with _FILE_LOCK:
            disk = self._load()
            disk.update(self.d)
            now = self.now()
            disk = {k: v for k, v in disk.items() if isinstance(v, dict)
                    and now - float(v.get("at", 0)) <= PROBE_OK_TTL}
            tmp = "%s.%d.%d.part" % (self.path, os.getpid(), threading.get_ident())
            with open(tmp, "w") as f:
                json.dump(disk, f, separators=(",", ":"))
            os.replace(tmp, self.path)


def _reaches(st, lon, lat):
    """Does station st (dict with bbox [lat0, lon0, lat1, lon1], reach) see this point?"""
    la0, lo0, la1, lo1 = st["bbox"]
    if not (lo0 <= lon <= lo1 and la0 <= lat <= la1):
        return False
    if st["reach"] == "box":
        return True
    cx, hx = (lo0 + lo1) / 2.0, (lo1 - lo0) / 2.0
    my0, my1, my = merc_y(la0), merc_y(la1), merc_y(lat)
    cy, hy = (my0 + my1) / 2.0, (my1 - my0) / 2.0
    return ((lon - cx) / hx) ** 2 + ((my - cy) / hy) ** 2 <= 1.0


def _reach_kind(station_id):
    return "circle" if isinstance(station_id, str) and station_id.startswith("AZ") else "box"


def _lattice(w, s, e, n):
    pts = []
    lo = math.floor(w - LATTICE)
    while lo <= e + LATTICE + 1e-9:
        la = math.floor(s - LATTICE)
        while la <= n + LATTICE + 1e-9:
            if -85 <= la <= 85 and -180 <= lo <= 180:
                pts.append((float(lo), float(la)))
            la += LATTICE
        lo += LATTICE
    return pts


# --- the build ----------------------------------------------------------------

class Builder:
    """fetch(url, timeout) -> bytes is the cached getter (scene_at's in the service);
    list_url(lon, lat) builds the observation-list url for a point."""

    def __init__(self, fetch, list_url, book, deadline=None, now=time.time):
        self.fetch, self.list_url, self.book = fetch, list_url, book
        self.deadline, self.now = deadline, now
        self.new_probes = 0
        self.newest = None
        self.unprobed = 0
        self.lists = {}            # probe key -> parsed list payload (this request only)
        self.restationed = []      # "old->new" ids re-registered from a frame list
        self._lock = threading.Lock()
        self.ramp = _ramp()

    def _left(self):
        return self.deadline.left() if self.deadline is not None else 30.0

    def _get(self, url, timeout):
        import net_budget
        if self.deadline is not None:
            with net_budget.adopt(self.deadline):
                return self.fetch(url, timeout)
        return self.fetch(url, timeout)

    def _probe(self, pt):
        key = _pkey(*pt)
        e = self.book.get(key)
        if e is not None:
            return e
        with self._lock:
            if self.new_probes >= MAX_NEW_PROBES or self._left() < 2.0:
                self.unprobed += 1
                return None
            self.new_probes += 1
        try:
            b = self._get(self.list_url(*pt), min(8.0, self._left()))
            d = json.loads(b)
        except Exception:
            with self._lock:
                self.unprobed += 1
            return None
        imgs = d.get("images") or []
        if d.get("status") == "ok" and imgs and len(imgs[0]) > 2 and imgs[0][2]:
            e = {"s": d.get("station") or "?", "bbox": [float(v) for v in imgs[0][2]],
                 "at": self.now()}
            with self._lock:
                self.lists[key] = d
        else:
            e = {"s": None, "at": self.now()}
        with self._lock:
            self.book.put(key, e)
        return e

    def stations(self, w, s, e, n):
        pts = _lattice(w, s, e, n)
        found = {}                 # station id -> {"bbox", "reach", "probe"}
        probed = {}

        def run(batch):
            with ThreadPoolExecutor(max_workers=WORKERS) as ex:
                for pt, r in zip(batch, ex.map(self._probe, batch)):
                    probed[pt] = r
                    if r and r.get("s"):
                        sid = r["s"]
                        if sid not in found:
                            found[sid] = {"id": sid, "bbox": r["bbox"],
                                          "reach": _reach_kind(sid), "probe": pt}

        first = [p for p in pts if int(round(p[0])) % 2 == 0 and int(round(p[1])) % 2 == 0]
        run(first)
        rest = [p for p in pts if p not in probed
                and not any(_reaches(st, p[0], p[1]) for st in found.values())]
        run(rest)
        lattice_skipped = len(pts) - len(probed)
        boxed = [st for st in found.values()
                 if st["bbox"][1] < e and st["bbox"][3] > w and st["bbox"][0] < n and st["bbox"][2] > s]
        return boxed, len(pts), lattice_skipped

    def frame_list(self, st):
        key = _pkey(*st["probe"])
        d = self.lists.get(key)
        if d is None:
            try:
                d = json.loads(self._get(self.list_url(*st["probe"]), min(8.0, self._left())))
            except Exception:
                return []
        if d.get("status") != "ok":
            return []
        out = []
        for it in d.get("images") or []:
            if isinstance(it, (list, tuple)) and len(it) >= 3 and it[2]:
                out.append((it[0], float(it[1]), [float(v) for v in it[2]]))
        out.sort(key=lambda f: f[1])
        sid = d.get("station") or "?"
        if sid != st["id"] and out:
            # The point is now served under another id (2026-11-15: 110E24N
            # answered AZ9774 where the book said AZ9772; four more like it).
            # Dropping the list put all of that station's frames in "gaps",
            # and a gap says the station published nothing -- untrue.  Take
            # the station the list names; frames carry their own bbox.
            with self._lock:
                st_old = st["id"]
                self.restationed.append("%s->%s" % (st_old, sid))
                st["id"], st["bbox"], st["reach"] = sid, out[-1][2], _reach_kind(sid)
                # every point the book had on the old id: same radar, new id
                self.book.rename(st_old, sid, out[-1][2])
                self.book.put(key, {"s": sid, "bbox": out[-1][2], "at": self.now()})
        return out

    def build(self, w, s, e, n, res, nframes, since=None):
        g = Grid(w, s, e, n, res)
        stations, n_lattice, skipped = self.stations(w, s, e, n)
        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            lists = list(ex.map(self.frame_list, stations))
        # two probe points re-registered onto one station: keep it once
        seen, keep = set(), []
        for st, fl in zip(stations, lists):
            if st["id"] not in seen:
                seen.add(st["id"])
                keep.append((st, fl))
        stations, lists = [k[0] for k in keep], [k[1] for k in keep]
        frames_out = []
        t0 = align(lists)
        if t0 is not None:
            self.newest = t0
            targets = [t0 - k * STEP_S for k in range(nframes)][::-1]
            if since is not None:
                # to the minute: t is printed to the minute, and a poller passes it back
                targets = [t for t in targets if int(t // 60) > int(since // 60)]
            plan = []          # per target: [(station, frame or None)]
            urls = set()
            for t in targets:
                row = []
                for st, fl in zip(stations, lists):
                    best = min(fl, key=lambda f: abs(f[1] - t)) if fl else None
                    if best is not None and abs(best[1] - t) > MATCH_S:
                        best = None
                    row.append((st, best))
                    if best is not None:
                        urls.add(best[0])
                plan.append((t, row))
            pngs = {}
            urls = sorted(urls)
            with ThreadPoolExecutor(max_workers=WORKERS) as ex:
                for u, b in zip(urls, ex.map(self._png, urls)):
                    pngs[u] = b
            maps = {}
            for t, row in plan:
                out = np.full(g.nx * g.ny, -1, dtype=np.int8)
                gaps, unfetched, used = [], [], []
                for st, fr in row:
                    if fr is None:
                        gaps.append(st["id"])
                        continue
                    if pngs.get(fr[0]) is None:
                        # upstream has this frame; we did not get it in time.
                        # Not a gap: a gap says the station published nothing then.
                        unfetched.append(st["id"])
                        continue
                    self._paint(out, g, st, fr, pngs[fr[0]], maps)
                    used.append(fr[1])
                frames_out.append({
                    "t": _tstr(t),
                    "kind": "obs",
                    "spread_s": int(max((abs(u_ - t) for u_ in used), default=0)),
                    "gaps": sorted(gaps),
                    "unfetched": sorted(unfetched),
                    "values": out.reshape(g.ny, g.nx)})
        complete = self.unprobed == 0
        return g, stations, frames_out, {
            "lattice_points": n_lattice, "probed_now": self.new_probes,
            "unprobed": self.unprobed, "skipped_as_covered": skipped, "complete": complete,
            "restationed": sorted(self.restationed)}

    def _png(self, url):
        # Never start a fetch that cannot finish: 2026-11-14 17:49Z a slow CDN
        # held this past nginx's 25 s and the reader got an HTML 504 instead
        # of a JSON answer that says which frames are missing.
        if self._left() < 1.0:
            return None
        try:
            return self._get(url, min(8.0, self._left()))
        except Exception:
            return None

    def _paint(self, out, g, st, fr, png, maps):
        try:
            rgba = np.asarray(Image.open(io.BytesIO(png)).convert("RGBA"))
        except Exception:
            return
        h, wd = rgba.shape[:2]
        mkey = (tuple(fr[2]), wd, h, st["reach"])
        if mkey not in maps:
            maps[mkey] = _pixel_cells(fr[2], wd, h, g, st["reach"])
        cell, valid, inreach = maps[mkey]
        lv, vis = levels(rgba, self.ramp)
        cov = valid & (inreach | vis)
        if not cov.any():
            return
        idx = cell[cov]
        val = lv[cov]
        out[idx] = np.maximum(out[idx], 0)
        for L in np.unique(val):
            if L <= 0:
                continue
            j = idx[val == L]
            # duplicates in j read the same value and write the same value
            out[j] = np.maximum(out[j], L)


def align(lists):
    """-> the newest frame time, or None if no station has frames.

    Not simply the newest frame anywhere: measured 2026-11-14 16:15Z over Gansu,
    that put the newest frame where one station had published and seven had not
    yet, so a quarter of the province went null in it -- null that meant "not
    published yet", which is not what null says here.

    Nor the time at which the MOST stations have a frame: measured 18:33Z the
    same day over 101-119E 31-40N, 51 stations whose newest frames were 2..29
    min old (median 7), and waiting for all of them put "newest" 25 min back
    -- one late station held back the whole picture (Qianlu saw it from the
    outside). So: the latest time at which at least AGREE of the stations have
    a frame, or the best coverage there is when no time reaches that. The late
    ones are named in that frame's gaps."""
    newest = [fl[-1][1] for fl in lists if fl]
    if not newest:
        return None
    lo = max(newest) - 1800
    cands = sorted({f[1] for fl in lists for f in fl if f[1] >= lo})

    def n_cov(t):
        return sum(1 for fl in lists if fl and min(abs(f[1] - t) for f in fl) <= MATCH_S)

    scored = [(n_cov(t), t) for t in cands]
    best = max(n for n, _ in scored)
    need = max(1, min(best, math.ceil(AGREE * len(newest))))
    return max(t for n, t in scored if n >= need)


def _pixel_cells(sbbox, wd, h, g, reach):
    la0, lo0, la1, lo1 = sbbox
    lons = lo0 + (np.arange(wd) + 0.5) / wd * (lo1 - lo0)
    my0, my1 = float(merc_y(la0)), float(merc_y(la1))
    lats = inv_merc_y(my1 - (np.arange(h) + 0.5) / h * (my1 - my0))
    ix = np.floor((lons - g.west) / g.dlon).astype(np.int64)
    iy = np.floor((g.north - lats) / g.dlat).astype(np.int64)
    okx = (ix >= 0) & (ix < g.nx)
    oky = (iy >= 0) & (iy < g.ny)
    cell = iy[:, None] * g.nx + ix[None, :]
    valid = oky[:, None] & okx[None, :]
    if reach == "box":
        inreach = np.ones((h, wd), dtype=bool)
    else:
        xx = (np.arange(wd) + 0.5 - wd / 2.0) / (wd / 2.0)
        yy = (np.arange(h) + 0.5 - h / 2.0) / (h / 2.0)
        inreach = (yy[:, None] ** 2 + xx[None, :] ** 2) <= 1.0
    return cell, valid, inreach


# --- the answer ---------------------------------------------------------------

_TOK = ["null"] + [str(i) for i in range(15)]      # index = value + 1


def _rows(arr):
    return "[" + ",".join("[" + ",".join(_TOK[v + 1] for v in r.tolist()) + "]" for r in arr) + "]"


def _tstr(t):
    return time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime(t))


def to_json(asked, g, stations, frames, coverage, newest=None, since=None):
    from runemap.radar_image import CAIYUN_RAMP
    head = {
        "source": "caiyunapp.com",
        "drawn_by": "echorune.net, resampled from caiyun's per-station radar images; "
                    "lossy, and not caiyun's own product",
        "values": "step on caiyun's colour scale: 1 weakest .. 14 strongest; "
                  "0 = a radar sees this cell and draws no echo; "
                  "null = none of the radars we found reaches this cell",
        "scale": "caiyun publishes no thresholds for these colours, so no dBZ or mm/h is given",
        "legend": [{"step": i + 1, "rgb": list(c)} for i, c in enumerate(CAIYUN_RAMP)],
        "bbox": list(asked),
        "grid": g.header(),
        "frames_order": "oldest first, %d min apart; each frame uses every station's "
                        "frame nearest its t (within %d min); stations with none are in gaps, "
                        "stations whose frame did not arrive in time are in unfetched"
                        % (STEP_S // 60, MATCH_S // 60),
        "newest": _tstr(newest) if newest is not None else None,
        "coverage": coverage,
        "stations": [{"id": st["id"], "bbox": st["bbox"], "reach": st["reach"]} for st in stations],
    }
    if not coverage["complete"]:
        head["note"] = ("%d probe points were not asked yet (per-request limit or time); "
                        "cells only they would have found are null. Ask again in a minute."
                        % coverage["unprobed"])
    missed = sum(len(f.get("unfetched", ())) for f in frames)
    if missed:
        head["note"] = ("%d station frames did not arrive from upstream in time (see unfetched); "
                        "their cells are null in those frames. Ask again in a minute." % missed)
    if not frames:
        # "none found" is only "none reaches" when every probe point was asked
        if since is not None and newest is not None and int(newest // 60) <= int(since // 60):
            head["note"] = "nothing newer than since=%s; the newest frame is %s" % (_tstr(since), _tstr(newest))
        elif stations:
            head["note"] = "no frames could be fetched for the stations found; ask again in a minute"
        elif coverage["complete"]:
            head["note"] = "no radar station reaches this box"
        else:
            head["note"] = ("no station found yet, and %d probe points were not asked; "
                            "this is not 'no radar here'. Ask again in a minute." % coverage["unprobed"])
    body = json.dumps(head, ensure_ascii=False, separators=(",", ":"))
    parts = []
    for fr in frames:
        meta = {k: v for k, v in fr.items() if k != "values"}
        m = json.dumps(meta, ensure_ascii=False, separators=(",", ":"))
        parts.append(m[:-1] + ',"values":' + _rows(fr["values"]) + "}")
    return body[:-1] + ',"frames":[' + ",".join(parts) + "]}\n"


def answer(qs, fetch, list_url, cache_dir, deadline=None, now=time.time, wait=4.0):
    """-> (http status, body str). The service calls this; tests call it with fakes."""
    try:
        w, s, e, n, res, nframes, since = parse(qs)
    except BadRequest as ex:
        return 400, json.dumps({"error": str(ex), "usage": USAGE}, ensure_ascii=False) + "\n"
    if not _BUILD.acquire(timeout=wait):
        return 503, json.dumps({"error": "another radar grid is being built; ask again in a minute"}) + "\n"
    try:
        book = ProbeBook(os.path.join(cache_dir, "radar_grid_probes.json"), now=now)
        b = Builder(fetch, list_url, book, deadline=deadline, now=now)
        g, stations, frames, coverage = b.build(w, s, e, n, res, nframes, since)
        try:
            book.save()
        except OSError:
            pass        # a lost probe book costs re-probing, not the answer
        return 200, to_json((w, s, e, n), g, stations, frames, coverage, b.newest, since)
    finally:
        _BUILD.release()


USAGE = ("GET /radar.json?bbox=<lon0>,<lat0>,<lon1>,<lat1>[&res=<km>][&frames=<n>][&since=<t>]  "
         "bbox is west,south,east,north in degrees, at most %d km a side; "
         "res %g..%g km per cell (default %g); frames 1..%d (default 1, or as many as fit when since is given); "
         "since=<a frame's t> returns only newer frames"
         % (MAX_SIDE_KM, MIN_RES_KM, MAX_RES_KM, DEFAULT_RES_KM, MAX_FRAMES))
