#!/usr/bin/env python3
"""Bilingual one-screen weather scene for agents.
Outputs: live/<city>/en and live/<city>/zh
Layout: headline + 2h rain curve (6min buckets) + current radar map + legend.
Radar art fetched ONCE per city, shared across languages.
Data source: caiyunapp.com. Token via env CAIYUN_TOKEN."""
import json, math, os, sys, time, urllib.request, tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from runemap.render import ascii_radar, ascii_radar_centered

# One window for every asker, switched by env so the tree is safe to deploy.
# RUNEMAP_SPAN_KM=0 (default, production today) keeps the upstream station's
# box: the asker lands wherever they land and a cell is 5.0 km in Bangkok but
# 12.4 km in Tokyo.  Setting it to a positive number crops a span x span square
# centred on the asker instead, so "+" is always dead centre and one cell is the
# same distance in every city.  The flag exists because that is a visible
# product change and the shareholder has not seen it yet.
_ascii_radar_box = ascii_radar


import threading as _th
_SPAN_TL = _th.local()


def set_span(v):
    """Per-request override of RUNEMAP_SPAN_KM.  dev knob: ?span=400

    The env var is process-global, so it cannot answer "what does 8 km/char
    look like" without a restart that changes the window for every asker at
    once.  Rendering happens on the request's own thread and is never shared
    between requests (only the fetched PNG is), so a thread-local is the
    narrowest place this can live.  None => fall back to the env default.
    """
    _SPAN_TL.span = v


def ascii_radar(png_path, bbox, lng, lat, **kw):
    span = getattr(_SPAN_TL, "span", None)
    if span is None:
        try:
            span = float(os.environ.get("RUNEMAP_SPAN_KM", "0") or 0)
        except ValueError:
            span = 0.0
    if span > 0:
        return ascii_radar_centered(png_path, bbox, lng, lat, span_km=span, **kw)
    return _ascii_radar_box(png_path, bbox, lng, lat, **kw)

import threading

import os as _o, sys as _s
_s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__)))
from cities import CITIES
try:
    _MOTION = json.load(open("live/_motion.json"))
except Exception:
    _MOTION = {}
import os as _nb_os, sys as _nb_sys
_nb_sys.path.insert(0, _nb_os.path.dirname(_nb_os.path.abspath(__file__)))
import net_budget
try:
    import happy_eyeballs
    happy_eyeballs.install()   # concurrent dial (first answer wins) under net_budget's deadline
except Exception as _he:
    import sys as _hs; _hs.stderr.write('happy_eyeballs not installed: %r\n' % (_he,))

SKY_ZH = {"CLEAR_DAY":"\u6674","CLEAR_NIGHT":"\u6674","PARTLY_CLOUDY_DAY":"\u591a\u4e91","PARTLY_CLOUDY_NIGHT":"\u591a\u4e91",
"CLOUDY":"\u9634","LIGHT_HAZE":"\u8f7b\u96fe\u973e","MODERATE_HAZE":"\u4e2d\u96fe\u973e","HEAVY_HAZE":"\u91cd\u96fe\u973e",
"LIGHT_RAIN":"\u5c0f\u96e8","MODERATE_RAIN":"\u4e2d\u96e8","HEAVY_RAIN":"\u5927\u96e8","STORM_RAIN":"\u66b4\u96e8",
"FOG":"\u96fe","LIGHT_SNOW":"\u5c0f\u96ea","MODERATE_SNOW":"\u4e2d\u96ea","HEAVY_SNOW":"\u5927\u96ea","STORM_SNOW":"\u66b4\u96ea",
"DUST":"\u6d6e\u5c18","SAND":"\u6c99\u5c18","WIND":"\u5927\u98ce"}
BARS = "\u2581\u2582\u2583\u2584\u2585\u2586\u2587\u2588"
AXIS = '├────┼────┼────┼────┤\n0   30   60   90 120min'

def _get(url, timeout=15):
    # `timeout` is now a TOTAL wall-clock budget for dial + TTFB + body, not the
    # per-recv gap that urlopen gives you. See scripts/net_budget.py.
    _t0 = time.time()
    b = net_budget.get_hedged(url, budget=timeout, headers={"User-Agent": "runemap/0.1"})
    _el = time.time() - _t0
    if _el > 1.0:
        sys.stderr.write("SLOW-GET total=%.2f bytes=%d %s\n" % (_el, len(b), url[-46:]))
    return b

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

# A failure is not a conclusion, and must not be kept like one.
#
# 8/7 11:46 bob sent a screen full of echo under "could not be fetched". I
# measured the same sky two minutes later: all 20 observation frames answered
# 200. He was not looking at a live failure, he was looking at the corpse of one
# that happened ten minutes earlier -- the finally clause below writes every
# outcome into the cache, and both read sites honoured the same 600s.
#
# Upstream fails in bursts (the radar CDN rotates the hostname onto a /24 that
# is unroutable from here; measured 8/7 11:37, eight addresses, none answering).
# A burst lasts seconds. Caching its verdict for ten minutes turns a blink into
# an outage for everyone who asks about that sky, and the reader cannot tell the
# difference -- which is the same lie this file already fixed one layer down.
#
# So: an answer keeps its full life, a failure keeps one refresh cycle.
_MO_FAIL_TTL = 60


def _mo_fresh(hit):
    """True if this cache entry may still be served."""
    if not hit:
        return False
    age = time.time() - hit[0]
    undecided = (hit[1] or {}).get("kind") in (None, "undetermined")
    return age < (_MO_FAIL_TTL if undecided else _MO_TTL)
# _MO_BUDGET is gone with ede4d59. It was 3.0s of join on the request thread
# that never consulted the deadline, and 1.2 + 3.0 walked through a 3s wall.
# The constant and its two joins are deleted rather than left unused: a shape
# that could once breach the wall, sitting in the file with no callers, is an
# invitation for the next reader to wire it back in exactly as it was.

_MO_BUSY = set()

def _motion_compute(key, imgs):
    mo = {"kind": None}
    try:
        frames = [(f[0], float(f[1]), f[2]) for f in imgs if len(f) >= 3 and f[2]]
        import echo_motion as EM
        EM._get = _get          # picks up the cached getter
        mo = EM.echo_motion(frames) or {"kind": None}
    except Exception:
        mo = {"kind": None, "why": "error"}
    finally:
        # 8/1 13:36: both lines used to sit OUTSIDE the try. Exception is caught,
        # but a BaseException (interpreter shutdown) or a failure in the cache
        # write itself left key in _MO_BUSY forever -- and both start sites gate
        # on `key not in _MO_BUSY`, so that one coordinate would never compute
        # motion again for the life of the process. Permanent, silent, and only
        # for the unlucky sky. finally is the whole fix.
        if mo.get("kind") is None:
            mo = {"kind": "undetermined", "why": mo.get("why") or "corr"}
        # A failure must not evict an answer that is still allowed to be served.
        #
        # Upstream goes unroutable in bursts: on 8/7 the radar CDN rotated the
        # hostname onto 45.253.17.x at 11:54 and 103.239.45.x at 11:55, and all
        # eight addresses of each timed out on a bare TCP connect. Without this
        # branch, one such burst throws away a motion vector computed four
        # minutes earlier and hands the reader "undetermined" instead --
        # strictly less than what we already knew, and indistinguishable from a
        # sky we never managed to read at all.
        #
        # The bound does not move: the surviving entry keeps its ORIGINAL
        # timestamp, so it still expires at _MO_TTL and can never be served any
        # older than an answer on the happy path. This buys freshness for
        # nobody -- it only refuses to trade knowledge for ignorance.
        keep_prev = False
        if mo.get("kind") == "undetermined":
            prev = _MO_CACHE.get(key)
            keep_prev = bool(prev
                             and (prev[1] or {}).get("kind") in ("moving", "stationary")
                             and time.time() - prev[0] < _MO_TTL)
        if not keep_prev:
            _MO_CACHE[key] = (time.time(), mo)
        _MO_BUSY.discard(key)

_MO_UNDET = {
    # "no echo over the radar" is not "the instrument could not decide": telling a
    # reader the frames failed to correlate when the sky is simply empty is the
    # same class of lie as promising a retry that can never change anything.
    "noecho": {"en": "= echo motion: n/a (no echo to track)",
               "zh": "= 回波移动: 无(视野内无回波可追踪)",
               "ja": "= エコー移動: なし(追跡できるエコーなし)"},
    "frames": {"en": "= echo motion: n/a (too few usable frames)",
               "zh": "= 回波移动: 无(可用观测帧不足)",
               "ja": "= エコー移動: なし(有効フレーム不足)"},
    "error":  {"en": "= echo motion: n/a (computation failed)",
               "zh": "= 回波移动: 无(计算失败)",
               "ja": "= エコー移動: なし(計算失敗)"},
    "sparse": {"en": "= echo motion: undetermined (echo too sparse to track)",
               "zh": "= 回波移动: 未能测定(回波过于稀疏, 不足以追踪)",
               "ja": "= エコー移動: 判定不能(エコーが疎すぎて追跡不可)"},
    "fetch":  {"en": "= echo motion: undetermined (frames could not be fetched)",
               "zh": "= 回波移动: 未能测定(观测帧下载失败)",
               "ja": "= エコー移動: 判定不能(観測フレーム取得失敗)"},
    "corr":   {"en": "= echo motion: undetermined (frames not correlated)",
               "zh": "= 回波移动: 未能测定(帧间相关性不足)",
               "ja": "= エコー移動: 判定不能(フレーム間の相関不足)"},
}

def _mo_undet(why, lang):
    d = _MO_UNDET.get(why) or _MO_UNDET["corr"]
    return d.get(lang) or d["zh"] if lang != "en" else d["en"]

def _motion_start(imgs, lng, lat):
    """Kick the motion thread as soon as imgs is known (it only needs the frame
    list), so its extra PNG download overlaps ours instead of following it."""
    key = (round(float(lat), 1), round(float(lng), 1))
    hit = _MO_CACHE.get(key)
    if _mo_fresh(hit):
        return (key, None)
    if key not in _MO_BUSY:
        _MO_BUSY.add(key)
        t = threading.Thread(target=_motion_compute, args=(key, imgs), daemon=True)
        t.start()
        return (key, t)
    return (key, None)

# Batch path only (render_scene main() writing live/), never a request. It may
# block: nobody is waiting on the other end of a socket for it. Named apart
# from anything on the request path so the two can never be confused again --
# that confusion is precisely what put a 3.0s join behind a 3s wall.
_MO_BATCH_BUDGET = 3.0


def _motion_join(handle):
    key, t = handle
    if t is not None:
        t.join(_MO_BATCH_BUDGET)
    hit = _MO_CACHE.get(key)
    return (hit[1] if hit else {"kind": None})

def _motion_peek(imgs, lng, lat):
    """Motion if it is already in hand; otherwise start it and answer without it.

    _motion_now waits t.join(_MO_BUDGET) = 3.0s, and that join never consulted
    net_budget's request deadline -- the radar wait right below does. Two budgets
    that each look reasonable on their own, 1.2s for frames and 3.0s for motion,
    add up to 4.2s and walk straight through a 3s wall. Luoshu measured 3.05s and
    called it an anomaly; it was not, it was the maximum this file approves of.
    Rendering was never the cost: ascii_radar measures 43ms per frame, 81ms worst,
    over the real cached PNGs.

    So the request thread no longer waits for motion at all. Motion is a suffix on
    one headline. A map without it is still a map; a map that arrives after the
    reader gave up is nothing.
    """
    key = (round(float(lat), 1), round(float(lng), 1))
    hit = _MO_CACHE.get(key)
    if _mo_fresh(hit):
        return hit[1]
    if key not in _MO_BUSY:
        _MO_BUSY.add(key)
        t = threading.Thread(target=_motion_compute, args=(key, imgs), daemon=True)
        t.start()
    return {"kind": None}


# ---------------------------------------------------------------- radar states
#
# Three states, and the whole point is that 2 and 3 are different answers:
#   ok       - frames are in hand, map rendered
#   fetching - not here yet; come back in ~60s. A background thread is on it.
#   none     - this location has no radar coverage. Coming back will not help.
#
# Before this, both of the latter collapsed -- and in the worst direction.
# radar_art() returned None both when the frame list came back empty (real
# no-coverage) and when fetching that list raised (a stall). serve.py only set
# radar_err when radar_art *raised*, so a transient upstream hiccup rendered as
# "no coverage here": we told the user "never" when the truth was "not yet".
# Hence the rule below, which is the only load-bearing line in this section:
#
#   state 3 is proven by a successful list fetch that contains no images.
#   It is NEVER inferred from a failure. Failures are state 2, always.
#
STATE_OK, STATE_FETCHING = "ok", "fetching"

# A frame older than this may draw the echo a full cell (~10km) away from
# where it now is: 10km/char over an observed 20-40km/h echo is 15-30 min.
# Derived from the picture, not picked to make the logs look good.
RADAR_STALE_MIN = 20

_RA_LOCK = threading.Lock()
_RA_INFLIGHT = {}                 # key -> Event, one warm per sky at a time
_RA_FAIL = {}                     # key -> ts of the last refusal (throttle only)
_RA_FAIL_COOLDOWN = 30.0          # do not re-warm a known-failing sky faster
_RA_BG_BUDGET = 45.0              # the background warm may outlive the response
                                  # but not the heat death of the universe
import wall as _wall
_RA_WAIT = _wall.RADAR_WAIT_UNKNOWN


def _peek(url):
    """Cache-only read. Overwritten by scene_at with the disk-pool reader, the
    same way _get is. The bare CLI keeps this stub, so every lookup misses and
    everything reports state 2 -- correct, just less useful."""
    return None


# Which upstream list every radar path reads. One constant, because the list
# kind decides two things at once -- the url AND which frame is the observation
# -- and letting those two disagree is exactly how a frame starts lying about
# its own age.
RADAR_LIST_KIND = "forecast_images"   # DEFAULT only -- see _kind_for below

# ...except coverage is not global either. Measured 8/2 at the upstream
# boundary: mumbai and sydney answer images=200 / forecast_images=404 --
# observation coverage with no forecast coverage. Asking only the forecast
# endpoint turned those two skies into PERMANENT "fetching": a city that used
# to print a map went blank, and blank is the state nobody reports. So the
# kind is a per-sky fact that upstream tells us with a 404, memoised so we
# ask once rather than per request. It still decides url AND which frame is
# the observation AND what the motion line claims its basis is -- so it is
# read through ONE helper everywhere, never from two places.
_RA_KIND = {}


def _sky_key(lng, lat):
    return (round(float(lat), 1), round(float(lng), 1))




def _kind_for(lng, lat):
    with _RA_LOCK:
        return _RA_KIND.get(_sky_key(lng, lat), RADAR_LIST_KIND)

# The motion vector is computed from whatever RADAR_LIST_KIND selects. Fed
# forecast frames it is no longer "we watched it move" but "upstream expects
# it to move" -- measured 2026-08-02, the two sources disagreed on direction
# at 2 of 2 stations, so this is a change of meaning, not of wording. Derive
# the word from the constant: the label can never drift from the data again.
_MO_OBS = RADAR_LIST_KIND == "images"
_MO_BASIS_EN = "1h obs" if _MO_OBS else "upstream forecast"
_MO_BASIS_ZH = "\u8fd11h\u5b9e\u6d4b" if _MO_OBS else "\u4e0a\u6e38\u9884\u62a5"
_MO_BASIS_JA = "直近1h実測" if _MO_OBS else "\u4e0a\u6d41\u4e88\u5831"


def _radar_list_url(token, lng, lat, kind=None):
    return ("https://api.caiyunapp.com/v1/radar/%s?token=%s&lon=%s&lat=%s"
            % (kind or _kind_for(lng, lat), token, lng, lat))


def _radar_list_bytes(token, lng, lat):
    """Fetch the frame list, learning from a 404 which endpoint this sky has.

    A 404 here is not a failure, it is upstream answering a different
    question: "this sky has no forecast product". Falling back to the
    observation list gives that reader a map instead of a permanent
    "ask again in ~60s" -- which is the one promise we must not break.
    Only 404 flips the kind; a timeout or a 5xx says nothing about coverage.
    """
    kind = _kind_for(lng, lat)
    try:
        return _get(_radar_list_url(token, lng, lat, kind))
    except Exception as e:
        if kind != "forecast_images" or "HTTP 404" not in str(e):
            raise
        with _RA_LOCK:
            _RA_KIND[_sky_key(lng, lat)] = "images"
        sys.stderr.write("RADAR-KIND-FALLBACK %r -> images\n" % (_sky_key(lng, lat),))
        return _get(_radar_list_url(token, lng, lat, "images"))


def _pick_frames(imgs, kind=None):
    """-> (candidates nearest-to-now first, ts of the last real observation).

    An observation list is all past: the frame to draw and the last look at the
    sky are the same frame, the newest one. A forecast list runs from that same
    observation out to +4h, so its newest frame shows a sky nobody has seen.
    Draw the frame nearest to now; age it from the observation it was
    extrapolated from -- measured 8/2: forecast_images[0] and images[-1] carry
    the identical timestamp, to the second, at two stations.

    Returning the base ts here, rather than letting the caller compute an age
    from whatever frame it happened to draw, is the whole point: there is one
    answer to "how long since we saw this sky", and one place that knows it.
    """
    fr = sorted((f for f in imgs if f and len(f) >= 2), key=lambda f: float(f[1]))
    if not fr:
        return [], None
    if (kind or RADAR_LIST_KIND) == "forecast_images":
        base_ts = float(fr[0][1])         # the observation the run started from
    else:
        base_ts = float(fr[-1][1])        # every frame is a look at the sky
    now = time.time()
    cands = sorted(fr, key=lambda f: abs(float(f[1]) - now))
    return cands, base_ts


def _radar_warm(key, lng, lat, token):
    """Fetch list + newest frame into the disk pool, off the response path.

    Runs with its own budget, not the request's: it is meant to outlive the
    response. That is the difference between "ask again in ~60s" being a
    promise and being a lie -- today nothing keeps fetching after we say it,
    so the next caller pays the same stall from scratch."""
    try:
        with net_budget.request_budget(_RA_BG_BUDGET):
            d = json.loads(_radar_list_bytes(token, lng, lat))
            imgs = d.get("images") or []
            if not imgs:
                # Measured against the real upstream, not assumed: a covered
                # city answers {"status":"ok"} with 20 frames; open ocean, the
                # Sahara and the pole all answer {"status":"failed"}, 24 bytes,
                # no images. So "failed" IS the no-coverage signal -- except
                # scene_at._usable already records, from an incident, that a
                # COVERED city can get "failed" transiently, which is why that
                # body is never cached.
                #
                # bob 8/3 14:35: "no radar means you did not get the radar.
                # Nobody is going to believe there is no radar just because
                # you say so." That sentence deletes the verdict. The whole
                # confirmation machinery existed to earn the right to say
                # "this sky has no coverage" -- a claim about the world,
                # backed only by "I asked three times and got nothing",
                # which is a claim about me. Deleted: the counter, the memo,
                # the .seen history, and with them the observer effect my
                # own probe produced on 8/3 12:4x (a missing capability
                # outranks a guard: no probe can manufacture a verdict that
                # does not exist).
                #
                # What SURVIVES is the throttle. It looked like part of the
                # verdict, but its job is to stop re-asking a sky that just
                # refused -- otherwise the skies that never answer are
                # exactly the ones we spend upstream quota on.
                with _RA_LOCK:
                    _RA_FAIL[key] = time.time()
                return
            with _RA_LOCK:
                _RA_FAIL.pop(key, None)      # it answered; stop throttling
            # imgs[-1] used to be "the newest frame", which is true of an
            # observation list and FALSE of a forecast list: there the last
            # element is the FARTHEST FUTURE (+227min, measured 8/2). The warm
            # was fetching two frames nobody will ever draw, so every sky stayed
            # in state 2 forever while the cache filled with useless pngs.
            # Warm what the renderer will actually draw -- one helper decides
            # which frame matters, here and there.
            _cands, _base = _pick_frames(imgs, _kind_for(lng, lat))
            for cand in (_cands[:2] or [None]):
                if cand is None:
                    continue
                try:
                    _get(cand[0], timeout=20)
                    break
                except Exception as e:
                    sys.stderr.write("RADAR-WARM-FRAME %r\n" % (e,))
            _motion_start(imgs, lng, lat)
    except Exception as e:
        # Leave the cache cold: the next request is state 2 again and will
        # start another warm. Never memo no-coverage from a failure.
        sys.stderr.write("RADAR-WARM-FAILED %r\n" % (e,))
    finally:
        # try/finally, not "at the end of the happy path": a key left marked
        # in-flight is a sky that silently never leaves state 2 again, and
        # nothing in the output would ever say so.
        with _RA_LOCK:
            ev = _RA_INFLIGHT.pop(key, None)
        if ev is not None:
            ev.set()


def _radar_start(key, lng, lat, token):
    """Single-flight. Returns the Event for whoever is already fetching.

    The claim happens under the lock; only the thread start is outside it.
    The old motion code did `if key not in busy: busy.add(key)` unlocked, so
    N concurrent requests for one cold sky each spawned a fetch -- which is
    exactly the 60-requests-must-not-mean-60-fetches case."""
    with _RA_LOCK:
        ev = _RA_INFLIGHT.get(key)
        if ev is not None:
            return ev
        ev = threading.Event()
        _RA_INFLIGHT[key] = ev
    threading.Thread(target=_radar_warm, args=(key, lng, lat, token),
                     daemon=True).start()
    return ev


def _radar_render(code, lng, lat, imgs, small):
    """Render from cached bytes only. Returns None if the frames are not local.

    Art depends on the marker and the size, which vary per request, so what is
    shared between requests is the fetched PNG, not the rendered map."""
    cands, base_ts = _pick_frames(imgs, _kind_for(lng, lat))
    for cand in cands[:2]:
        png = _peek(cand[0])
        if png is None:
            continue
        url, ts, bbox = cand[0], float(cand[1]), cand[2]
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(png); p = f.name
        try:
            art, kmcol = ascii_radar(p, bbox, lng, lat,
                                     cols=(24 if small else 48),
                                     rows=(12 if small else 24), marker=code)
        finally:
            os.unlink(p)
        return art, kmcol, ts, _motion_peek(imgs, lng, lat), base_ts
    return None


def radar_resolve(code, lng, lat, token, small=False, wait=None):
    """(state, payload) -- this thread opens no socket and joins no thread.

    Everything read here comes from the disk pool. Anything missing is handed to
    a background thread and reported as state 2.

    The old wording of this docstring said "no upstream call on this thread,
    ever", and it was false for weeks: the last line of _radar_render joined a
    motion thread for up to 3s, which is a socket wait wearing a different hat.
    A comment that promises what the code stopped doing is worse than no comment,
    because the next reader (me) quotes it instead of measuring."""
    code = _mark(code)
    key = (round(float(lat), 1), round(float(lng), 1))
    _wait_override = wait

    now = time.time()
    with _RA_LOCK:
        fail = _RA_FAIL.get(key)
    if fail is not None and now - fail < _RA_FAIL_COOLDOWN:
        # A sky that just refused us: still state 2 (we are not sure it is
        # "never"), but do not hammer the upstream once per request while we
        # make up our mind.
        return STATE_FETCHING, None

    def _from_cache():
        raw = _peek(_radar_list_url(token, lng, lat))
        if raw is None:
            return None                      # unknown: not proof of anything
        try:
            imgs = (json.loads(raw).get("images") or [])
        except Exception:
            return None
        if not imgs:
            # Unknown, not proven: an empty list out of a cached body says
            # nothing about the sky, and there is no verdict left to promote
            # it to. Ask again.
            return None
        got = _radar_render(code, lng, lat, imgs, small)
        return (STATE_OK, got) if got else None

    hit = _from_cache()
    if hit is not None:
        return hit

    ev = _radar_start(key, lng, lat, token)
    # How long is worth waiting depends on what waiting can buy.
    #
    # Nothing renderable is in the pool (we would have returned above), so this
    # reader sees a map only if the background warm lands while they are here:
    # one list fetch, ~1s, plus one frame, 1-3s. Under the old 3s wall that
    # could not finish, so the answer was always "fetching" -- the wall was not
    # costing latency, it was costing content. That is the complaint the larger
    # wall was bought to fix, and this is where it gets spent.
    #
    # Except for a sky that just refused us: the fail counter is in cooldown,
    # and spending the reader's whole budget on a peer that said no 30 seconds
    # ago is paying full price for a coin flip we just lost.
    _dl = net_budget.current_deadline()
    wait = _wall.radar_wait(cooling=fail is not None,
                            left=(_dl.left() if _dl is not None else None))
    if _wait_override is not None:      # explicit caller (tests) still wins,
        wait = _wait_override           # but the deadline clamp below does not
        if _dl is not None:             # get to be optional for them either
            wait = max(0.0, min(wait, _dl.left() - _wall.RESERVE))
    if wait > 0:
        ev.wait(wait)
    hit = _from_cache()
    return hit if hit is not None else (STATE_FETCHING, None)


_WX_LOCK = threading.Lock()
_WX_INFLIGHT = {}


def _weather_warm(key, lng, lat, token, lang):
    try:
        with net_budget.request_budget(_RA_BG_BUDGET):
            weather(lng, lat, token, lang)
    except Exception as e:
        sys.stderr.write("WEATHER-WARM-FAILED %r\n" % (e,))
    finally:
        with _WX_LOCK:
            ev = _WX_INFLIGHT.pop(key, None)
        if ev is not None:
            ev.set()


def weather_start(lng, lat, token, lang):
    """Single-flight background warm for weather, same discipline as radar.

    Without it, "ask again in ~60s" on a weather miss is the same empty promise
    the radar path used to make: nothing keeps fetching after the response, so
    the next caller pays the identical stall from scratch."""
    key = (round(float(lat), 1), round(float(lng), 1), lang)
    with _WX_LOCK:
        ev = _WX_INFLIGHT.get(key)
        if ev is not None:
            return ev
        ev = threading.Event()
        _WX_INFLIGHT[key] = ev
    threading.Thread(target=_weather_warm,
                     args=(key, lng, lat, token, lang), daemon=True).start()
    return ev


def build_fetching(lang, name):
    """A 200 that says "not yet", for when even the weather is not in hand.

    The alternative is a 502 inside 3s, which satisfies the clock and fails the
    person: they asked for the sky and got a stack trace. The disk pool already
    serves stale-but-good up to 6x TTL, so reaching here means this coordinate
    has genuinely never been fetched -- new, not broken. Say that, and keep
    fetching in the background so the next ask lands."""
    if lang == "ja":
        return ("# %s 天気一覧\n"
                "weather: fetching -- まだ取得できていません、約60秒後に再度\n"
                "radar: fetching -- この空を探しています、まだフレームがありません\n"
                "\n"
                "data: 彩雲天気 caiyunapp.com | runemap で描画 "
                "(github.com/eirik-rune/runemap)\n") % name
    if lang == "en":
        return ("# %s weather scene\n"
                "weather: fetching -- not ready yet, ask again in ~60s\n"
                "radar: fetching -- looking for this sky; no frame yet\n"
                "\n"
                "data: Caiyun Weather caiyunapp.com | rendered by runemap "
                "(github.com/eirik-rune/runemap)\n") % name
    return ("# %s \u5929\u6c14\u5b9e\u51b5\n"
            "weather: fetching -- \u8fd8\u6ca1\u53d6\u5230, \u7ea6 60 \u79d2\u540e\u518d\u95ee\n"
            "radar: fetching -- \u6b63\u5728\u627e\u8fd9\u7247\u5929, \u8fd8\u6ca1\u6709\u5e27\n"
            "\n"
            "\u6570\u636e: \u5f69\u4e91\u5929\u6c14 caiyunapp.com | runemap \u6e32\u67d3 "
            "(github.com/eirik-rune/runemap)\n") % name


def drain_warms(timeout=60.0):
    """Block until outstanding background warms finish. For short-lived
    processes only.

    The warm threads are daemons, so they die with the interpreter. A CLI that
    exits the moment it prints "fetching" therefore warms nothing, and its own
    promise -- ask again in ~60s -- is false in exactly the way the service's
    used to be. The service never calls this: there the process outlives the
    request, which is the entire point of the design."""
    with _RA_LOCK:
        evs = list(_RA_INFLIGHT.values())
    end = time.time() + timeout
    for ev in evs:
        ev.wait(max(0.0, end - time.time()))


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


# ---------------------------------------------------------------- ghost cell
GHOST = "+"
GHOST_MIN = 60          # minutes ahead. The number in the legend IS this number.

def _ghost(art, mo, kmcol, code):
    """Mark the cell of sky that will be over the reader in GHOST_MIN minutes.

    Not "where the rain goes" -- that would mean redrawing the whole field. The
    reader's question is "does it reach me", so displace the READER backwards
    along the motion vector and mark the cell that arrives here. One glyph, and
    the answer is the shade underneath it.

    No arrow: the position of GHOST relative to the marker already carries the
    direction, continuously. Arrows are East_Asian_Width=Ambiguous and would
    shear the grid for CJK terminals (see _mark), and an 8-way glyph would throw
    away resolution the vector still has.

    Returns (art, drawn). Every early return below is a way this could lie:
      - motion not resolved           -> nothing to say
      - displacement under one cell   -> rounding up would invent motion
      - target off the grid           -> clamping to the edge changes the claim
                                         from "arrives from there" to "arrives
                                         from the edge"
      - target has no radar behind it -> "?" means nobody looked; a confident
                                         "+" on top claims knowledge we lack
    """
    if not art or not mo or mo.get("kind") != "moving":
        return art, False
    vx, vy = mo.get("vx"), mo.get("vy")
    if vx is None or vy is None or not kmcol:
        return art, False
    rows = [list(r) for r in art.split("\n")]
    if not rows:
        return art, False
    mk = _mark(code)
    my = mx = None
    for j, r in enumerate(rows):
        i = "".join(r).find(mk)
        if i >= 0:
            my, mx = j, i
            break
    if my is None:
        return art, False
    t = GHOST_MIN / 60.0
    # Where the reader sits in the echo's frame, i.e. me - v*t. vy is
    # south-positive, so the northward component is -vy; a row index grows
    # southward, hence the second minus. km per ROW is twice km per COLUMN: a
    # terminal cell is about twice as tall as wide, so the grid is 1:2
    # geographically (see ascii_radar_centered). Dividing by kmcol here would
    # put the mark twice as far north/south as it belongs.
    fcol = -vx * t / kmcol
    frow = -vy * t / (2.0 * kmcol)
    # The refusal has to be tested BEFORE rounding, not after. Testing
    # `dcol == 0 and drow == 0` tests whether the ROUNDED result vanished, which
    # lets every component in [0.5, 1.0) through -- rounded up into a full cell
    # of motion that did not happen. Eirik swept kmcol in {5,12} x 24 bearings x
    # 5-40 km/h: 169 of 1680 samples drew a ghost for a true displacement under
    # one cell, worst 0.53 cells shown as 1.00 -- and that cell actually arrives
    # in 103 minutes while the legend says 60.
    # hypot, not the two components separately: 0.57 and 0.56 are each under half
    # a cell and together are 0.80. The diagonal is where this leaks.
    if math.hypot(fcol, frow) < 1.0:
        return art, False
    dcol, drow = int(round(fcol)), int(round(frow))
    gy, gx = my + drow, mx + dcol
    if not (0 <= gy < len(rows) and 0 <= gx < len(rows[gy])):
        return art, False
    if gy == my and mx <= gx < mx + len(mk):
        return art, False
    if rows[gy][gx] == "?":
        return art, False
    rows[gy][gx] = GHOST
    return "\n".join("".join(r) for r in rows), True


_GHOST_NOTE = {
    "en": "%s = the sky that reaches you in ~%dmin (straight-line extrapolation)",
    "zh": "%s = \u7ea6%d\u5206\u949f\u540e\u98d8\u5230\u4f60\u5934\u4e0a\u7684\u90a3\u5757\u5929(\u76f4\u7ebf\u5916\u63a8)",
    "ja": "%s = \u7d04%d\u5206\u5f8c\u306b\u3053\u3053\u306b\u6765\u308b\u7a7a(\u76f4\u7dda\u5916\u633f)",
}


def radar_art(code, lng, lat, token, small=False):
    code = _mark(code)
    try:
        d = json.loads(_radar_list_bytes(token, lng, lat))
    except Exception:
        return None
    imgs = d.get("images") or []
    if not imgs:
        return None
    _mh = _motion_start(imgs, lng, lat)   # overlap motion's PNG with ours
    # JP2375 stalls recur (7/30 19:17, 21:07-21:13): when the newest frame's
    # CDN object stalls, fall back to the previous frame (~6min older, its
    # own timestamp shown honestly) instead of degrading to no radar at all.
    png = None
    _err = None
    _cands, base_ts = _pick_frames(imgs, _kind_for(lng, lat))
    for _cand in _cands[:2]:
        try:
            png = _get(_cand[0], timeout=20)
            url, ts, bbox = _cand[0], float(_cand[1]), _cand[2]
            break
        except Exception as _e:
            _err = _e
            sys.stderr.write("RADAR-FRAME-FALLBACK %r\n" % (_e,))
    if png is None:
        raise _err
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(png); p = f.name
    try:
        art, kmcol = ascii_radar(p, bbox, lng, lat, cols=(24 if small else 48), rows=(12 if small else 24), marker=code)
        _t = time.time()
        mo = _motion_join(_mh)
        _t_mo = time.time() - _t
        if _t_mo > 1.5:
            sys.stderr.write("SLOW-RADAR motion=%.2f\n" % (_t_mo,))
        return art, kmcol, ts, mo, base_ts
    finally:
        os.unlink(p)

SKY_JA = {"CLEAR_DAY":"晴れ","CLEAR_NIGHT":"晴れ","PARTLY_CLOUDY_DAY":"晴れ時々曇り",
"PARTLY_CLOUDY_NIGHT":"晴れ時々曇り","CLOUDY":"曇り","LIGHT_HAZE":"弱い煙霧",
"MODERATE_HAZE":"煙霧","HEAVY_HAZE":"濃い煙霧","LIGHT_RAIN":"小雨","MODERATE_RAIN":"雨",
"HEAVY_RAIN":"大雨","STORM_RAIN":"豪雨","FOG":"霧","LIGHT_SNOW":"小雪","MODERATE_SNOW":"雪",
"HEAVY_SNOW":"大雪","STORM_SNOW":"暴風雪","DUST":"塵","SAND":"黄砂","WIND":"強風"}


def _tz_label(tzh):
    """UTC+7 / UTC+5:30 -- an offset the reader can act on.

    The header used to end the timestamp with the words for a clock local to a
    place you had to already know. chaosconst opened runemap#14 for exactly
    this: the line names a city, but an agent parsing it still cannot put that
    timestamp on a shared axis. Half-hour zones (IST, NPT) are why not int().
    """
    sign = "+" if tzh >= 0 else "-"
    a = abs(float(tzh))
    h = int(a)
    m = int(round((a - h) * 60))
    return "UTC%s%d" % (sign, h) if m == 0 else "UTC%s%d:%02d" % (sign, h, m)


def build(lang, name, code, zh, lng, lat, tzh, wx, rb, radar_err=None,
          radar_state=None):
    code = _mark(code)   # legend and grid must show the same glyph
    rt = wx["realtime"]
    kp = (wx.get("forecast_keypoint") or wx.get("minutely", {}).get("description", "")).strip()
    p2h = wx.get("minutely", {}).get("precipitation_2h", [])[:120]
    stamp = time.strftime("%Y-%m-%d %H:%M", time.gmtime(time.time() + tzh * 3600))
    L = []
    if lang == "en":
        L.append("# %s weather scene  updated %s %s  (lon %s, lat %s)" % (name, stamp, _tz_label(tzh), lng, lat))
        L.append("now: %s  %.0fC  humidity %.0f%%  wind %.0fkm/h  precip %.2fmm/h" % (
            rt["skycon"], rt["temperature"], rt["humidity"]*100, rt["wind"]["speed"],
            rt["precipitation"]["local"]["intensity"]))
    elif lang == "ja":
        sky = SKY_JA.get(rt["skycon"], rt["skycon"])
        L.append("# %s 天気一覧  更新 %s %s  (経度 %s, 緯度 %s)" % (name, stamp, _tz_label(tzh), lng, lat))
        L.append("現在: %s  %.0fC  湿度 %.0f%%  風速 %.0fkm/h  降水 %.2fmm/h" % (
            sky, rt["temperature"], rt["humidity"]*100, rt["wind"]["speed"],
            rt["precipitation"]["local"]["intensity"]))
    else:
        sky = SKY_ZH.get(rt["skycon"], rt["skycon"])
        L.append("# %s \u5929\u6c14\u4e00\u5c4f  \u66f4\u65b0\u4e8e %s %s  (\u7ecf\u5ea6 %s, \u7eac\u5ea6 %s)" % (zh, stamp, _tz_label(tzh), lng, lat))
        L.append("\u5f53\u524d: %s  %.0fC  \u6e7f\u5ea6 %.0f%%  \u98ce\u901f %.0fkm/h  \u96e8\u5f3a %.2fmm/h" % (
            sky, rt["temperature"], rt["humidity"]*100, rt["wind"]["speed"],
            rt["precipitation"]["local"]["intensity"]))
    if kp:
        L.append(kp)
    # Shadow the module-level basis labels with this sky's kind. A sky on the
    # observation fallback really did have its motion measured, and saying
    # "upstream forecast" about it would be the exact drift the comment above
    # RADAR_LIST_KIND warns against: the label parting company with the data.
    _MO_OBS = _kind_for(lng, lat) == "images"
    _MO_BASIS_EN = "1h obs" if _MO_OBS else "upstream forecast"
    _MO_BASIS_ZH = "\u8fd11h\u5b9e\u6d4b" if _MO_OBS else "\u4e0a\u6e38\u9884\u62a5"
    _MO_BASIS_JA = "\u76f4\u8fd11h\u5b9f\u6e2c" if _MO_OBS else "\u4e0a\u6d41\u4e88\u5831"
    mo = (rb[3] if rb and len(rb) > 3 else None) or _MOTION.get(name) or {}
    if mo.get("kind") == "moving":
        mo_sfx = (("  |  echo motion(%s): %s %s ~%.0f km/h" % (_MO_BASIS_EN, mo["arrow"], mo["dir_en"], mo["kmh"]))
                  if lang == "en" else
                  ("  |  \u56de\u6ce2\u79fb\u52a8(%s): %s %s ~%.0f km/h" % (_MO_BASIS_ZH, mo["arrow"], mo["dir_cn"], mo["kmh"])))
    elif mo.get("kind") == "stationary":
        mo_sfx = (("  |  echo quasi-stationary(<5km/h, %s)" % _MO_BASIS_EN) if lang == "en"
                  else ("  |  \u56de\u6ce2\u51c6\u9759\u6b62(<5km/h, %s)" % _MO_BASIS_ZH))
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
        mo_line = ("%s %s ~%.0f km/h   echo motion, %s"
                   % (mo["arrow"], mo["dir_en"], mo["kmh"], _MO_BASIS_EN) if lang == "en" else
                   "%s %s ~%.0f km/h   回波移动, %s"
                   % (mo["arrow"], mo["dir_cn"], mo["kmh"], _MO_BASIS_ZH))
    elif mo.get("kind") == "stationary":
        mo_line = (("= echo quasi-stationary (<5km/h, %s)" % _MO_BASIS_EN) if lang == "en"
                   else ("= 回波准静止 (<5km/h, %s)" % _MO_BASIS_ZH))
    else:
        mo_line = _mo_undet(mo.get("why"), lang) if mo.get("kind") == "undetermined" else (
                   "~ echo motion: fetching (retry in ~60s)" if lang == "en"
                   else "~ 回波移动: 获取中(约60s后重试)")
    if lang == "ja":
        if mo.get("kind") == "moving":
            mo_line = "%s %s ~%.0f km/h   エコー移動, %s" % (mo["arrow"], mo["dir_en"], mo["kmh"], _MO_BASIS_JA)
        elif mo.get("kind") == "stationary":
            mo_line = "= エコーほぼ停滞 (<5km/h, %s)" % _MO_BASIS_JA
        elif mo.get("kind") == "undetermined":
            mo_line = _mo_undet(mo.get("why"), "ja")
        else:
            mo_line = "~ エコー移動: 取得中(約60s後に再試行)"
    # The reading lives on one line only: the one under the map, where the eye
    # already is. On the legend line it competed with the marker key for the same
    # glance and pushed that row to 100+ columns, which wraps in a narrow terminal.
    mo_sfx = ""
    L.append("")
    if p2h and max(p2h) > 0:
        buckets = [round(max(p2h[i*6:(i+1)*6]), 2) for i in range(20)]
        L.append("rain curve (next 2h, 6min/bucket):" if lang == "en" else "雨量曲線(今後2h, 6min/枠):" if lang == "ja" else "\u96e8\u91cf\u66f2\u7ebf(\u672a\u67652h, 6min/\u683c):")
        L.append(spark(buckets))
        L.append(AXIS)
    else:
        L.append("rain curve (next 2h): no precipitation expected" if lang == "en"
                 else "雨量曲線(今後2h): 降水なし" if lang == "ja"
                 else "\u96e8\u91cf\u66f2\u7ebf(\u672a\u67652h): \u65e0\u964d\u6c34")
    L.append("")
    if rb:
        art, kmcol, ts = rb[0], rb[1], rb[2]
        art, _ghost_on = _ghost(art, mo, kmcol, code)
        # Two different quantities, deliberately not the same variable: ts is
        # the frame drawn on screen, base_ts is the last time anyone actually
        # looked at this sky. They coincide for an observation frame and differ
        # for an extrapolated one -- which is the entire reason (4) exists.
        base_ts = rb[4] if len(rb) > 4 and rb[4] else ts
        t = time.strftime("%H:%M", time.gmtime(ts + tzh * 3600))
        # One greppable line per state, same token in every language: most
        # readers here are agents, and a state you must translate before you
        # can grep it is not a state. Prose after the token stays localised.
        obs_age = int(max(0.0, time.time() - base_ts) // 60)
        # One age for both modes: how long since we last actually saw the
        # sky. A second age variable is where this line starts lying again.
        # TWO tokens, because these are two orthogonal axes and one slot cannot
        # carry both (bob, 8/2 10:57). Axis 1 answers "what is drawn": an
        # observed frame, or an extrapolated one. Axis 2 answers "how long
        # since anyone saw this sky". They are independent: the worst cell --
        # an extrapolation on top of a 47-minute-old observation -- printed as
        # plain "radar: predict" under the collapsed scheme, which looked
        # HEALTHIER than "stale". A warning had been demoted to a description.
        # Precedence is gone with the collapse: nothing outranks anything now,
        # both words are always printed.
        _extrapolated = ts > base_ts + 1.0
        _age_tok = "ok" if obs_age < RADAR_STALE_MIN else "stale"
        _axis1 = ("predict %s" % time.strftime("%H:%M", time.gmtime(ts + tzh * 3600))
                  if _extrapolated else "obs")
        # Contract for parsers (bob, 8/2 11:05): key on the TOKEN, never on the
        # field count. "fetching" and "none" carry no age at all -- there is no
        # frame, so there is no observation to be old. We deliberately do not
        # print a placeholder: a dash is a value-shaped nothing, which a machine
        # will try to parse and a human will ask about. Same rule that made us
        # delete the word "now" this morning -- one fewer true statement beats
        # one more ambiguous symbol. A fourth state added later must not break
        # a reader that expects "age:" to be optional.
        L.append("radar: %-14s obs age: %dmin %s" % (_axis1, obs_age, _age_tok))
        if lang == "ja":
            L.append("1文字≈%.0fkm, [%s]=%s" % (kmcol, code, name) + mo_sfx)
            L.append(art)
            if _ghost_on:
                L.append(_GHOST_NOTE["ja"] % (GHOST, GHOST_MIN))
            if mo_line:
                L.append(mo_line)
            L.append("凡例: · 霧雨  ░ 小雨  ▒ 中雨  ▓ 大雨  █ 豪雨")
        elif lang == "en":
            L.append("~%.0fkm/char, [%s]=%s" % (kmcol, code, name) + mo_sfx)
            L.append(art)
            if _ghost_on:
                L.append(_GHOST_NOTE["en"] % (GHOST, GHOST_MIN))
            if mo_line:
                L.append(mo_line)
            L.append("legend: \u00b7 drizzle  \u2591 light  \u2592 moderate  \u2593 heavy  \u2588 storm")
        else:
            L.append("每字符≈%.0fkm, [%s]=%s" % (kmcol, code, zh) + mo_sfx)
            L.append(art)
            if _ghost_on:
                L.append(_GHOST_NOTE["zh"] % (GHOST, GHOST_MIN))
            if mo_line:
                L.append(mo_line)
            L.append("\u56fe\u4f8b: \u00b7 \u6bdb\u6bdb\u96e8  \u2591 \u5c0f\u96e8  \u2592 \u4e2d\u96e8  \u2593 \u5927\u96e8  \u2588 \u66b4\u96e8")
    else:
        # bob 7/30 19:26: a transient tile stall must degrade, not 502. And bob
        # 8/3 14:35: "no radar means you did not get the radar. Nobody is going
        # to believe there is no radar just because you say so." So there is one
        # not-drawn state left and its sentence is about US: we have no frames.
        # It cannot be wrong about the world, which is why radar_err no longer
        # changes it and why nothing has to be earned before we may say it.
        st = radar_state or STATE_FETCHING
        L.append("radar: fetching -- no radar frames for this sky yet; weather above is live"
                 if lang == "en" else
                 "radar: fetching -- この空のレーダーはまだ取得できていません; 上の天気は実況です"
                 if lang == "ja" else
                 "radar: fetching -- 还没拿到这片天的雷达数据; 以上天气为实时")
    L.append("")
    L.append("data: Caiyun Weather caiyunapp.com | rendered by runemap (github.com/eirik-rune/runemap)" if lang == "en"
             else "データ: 彩雲天気 caiyunapp.com | runemap で描画 (github.com/eirik-rune/runemap)" if lang == "ja"
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
