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
        mo = {"kind": None}
    _MO_CACHE[key] = (time.time(), mo)
    _MO_BUSY.discard(key)

def _motion_start(imgs, lng, lat):
    """Kick the motion thread as soon as imgs is known (it only needs the frame
    list), so its extra PNG download overlaps ours instead of following it."""
    key = (round(float(lat), 1), round(float(lng), 1))
    hit = _MO_CACHE.get(key)
    if hit and time.time() - hit[0] < _MO_TTL:
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
    if hit and time.time() - hit[0] < _MO_TTL:
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
STATE_OK, STATE_FETCHING, STATE_NONE = "ok", "fetching", "none"

_RA_LOCK = threading.Lock()
_RA_INFLIGHT = {}                 # key -> Event, one warm per sky at a time
_RA_NONE = {}                     # key -> ts, memo of confirmed no-coverage
_RA_NONE_TTL = 3600.0             # coverage does not change minute to minute
_RA_FAIL = {}                     # key -> [count, first_ts, last_ts]
_RA_NONE_CONFIRM = 3              # how many failures before we dare say "never"
_RA_NONE_SPAN = 120.0             # ...and spread over at least this long
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


def _radar_list_url(token, lng, lat):
    return "https://api.caiyunapp.com/v1/radar/images?token=%s&lon=%s&lat=%s" % (token, lng, lat)


def _radar_warm(key, lng, lat, token):
    """Fetch list + newest frame into the disk pool, off the response path.

    Runs with its own budget, not the request's: it is meant to outlive the
    response. That is the difference between "ask again in ~60s" being a
    promise and being a lie -- today nothing keeps fetching after we say it,
    so the next caller pays the same stall from scratch."""
    try:
        with net_budget.request_budget(_RA_BG_BUDGET):
            d = json.loads(_get(_radar_list_url(token, lng, lat)))
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
                # One ambiguous signal, two meanings, and guessing wrong in the
                # "none" direction is the exact lie this job exists to remove:
                # telling someone "never come back" about a sky that has rain.
                # So a single failure is only ever state 2. "Never" has to be
                # earned: several failures, spread over time.
                now = time.time()
                with _RA_LOCK:
                    rec = _RA_FAIL.get(key)
                    if rec is None:
                        _RA_FAIL[key] = [1, now, now]
                    else:
                        rec[0] += 1
                        rec[2] = now
                        if (rec[0] >= _RA_NONE_CONFIRM
                                and now - rec[1] >= _RA_NONE_SPAN):
                            _RA_NONE[key] = now
                            _RA_FAIL.pop(key, None)
                return
            with _RA_LOCK:
                _RA_FAIL.pop(key, None)      # it answered; forget the doubt
            for cand in (imgs[-1], imgs[-2] if len(imgs) > 1 else None):
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
    for cand in (imgs[-1], imgs[-2] if len(imgs) > 1 else None):
        if cand is None:
            continue
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
        return art, kmcol, ts, _motion_peek(imgs, lng, lat)
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
        seen = _RA_NONE.get(key)
        fail = _RA_FAIL.get(key)
    if seen is not None and now - seen < _RA_NONE_TTL:
        # Two instances serve this site behind one upstream pool. They share the
        # frame pool on disk but each keeps its own _RA_NONE, so on 8/1 the same
        # London request answered "ok" on :8788 and "no coverage here" on :8789 --
        # a coin flip deciding whether a stranger is told to come back or told
        # never to. "Never" is the one state they cannot argue with, so it may
        # not rest on private memory when shared evidence contradicts it: if a
        # peer has frames for this sky, my memo is simply wrong. Drop it.
        raw = _peek(_radar_list_url(token, lng, lat))
        imgs = []
        if raw is not None:
            try:
                imgs = (json.loads(raw).get("images") or [])
            except Exception:
                imgs = []
        if not imgs:
            return STATE_NONE, None
        with _RA_LOCK:
            _RA_NONE.pop(key, None)
            _RA_FAIL.pop(key, None)
        got = _radar_render(code, lng, lat, imgs, small)
        if got:
            return STATE_OK, got
    if fail is not None and now - fail[2] < _RA_FAIL_COOLDOWN:
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
            # Unknown, not proven. "Never" is decided in one place only -- the
            # failure counter in _radar_warm -- because a single empty answer
            # is the ambiguous signal this whole design turns on. Promoting to
            # STATE_NONE here would let the cache path walk straight around the
            # confirmation rule, which is exactly what the tests caught.
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
                "radar: fetching -- まだ取得できていません、約60秒後に再度\n"
                "\n"
                "data: 彩雲天気 caiyunapp.com | runemap で描画 "
                "(github.com/eirik-rune/runemap)\n") % name
    if lang == "en":
        return ("# %s weather scene\n"
                "weather: fetching -- not ready yet, ask again in ~60s\n"
                "radar: fetching -- not ready yet, ask again in ~60s\n"
                "\n"
                "data: Caiyun Weather caiyunapp.com | rendered by runemap "
                "(github.com/eirik-rune/runemap)\n") % name
    return ("# %s \u5929\u6c14\u5b9e\u51b5\n"
            "weather: fetching -- \u8fd8\u6ca1\u53d6\u5230, \u7ea6 60 \u79d2\u540e\u518d\u95ee\n"
            "radar: fetching -- \u8fd8\u6ca1\u53d6\u5230, \u7ea6 60 \u79d2\u540e\u518d\u95ee\n"
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


def radar_art(code, lng, lat, token, small=False):
    code = _mark(code)
    try:
        d = json.loads(_get("https://api.caiyunapp.com/v1/radar/images?token=%s&lon=%s&lat=%s" % (token, lng, lat)))
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
    for _cand in (imgs[-1], imgs[-2] if len(imgs) > 1 else None):
        if _cand is None:
            continue
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
        return art, kmcol, ts, mo
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
        mo_line = ("%s %s ~%.0f km/h   echo motion, 1h obs"
                   % (mo["arrow"], mo["dir_en"], mo["kmh"]) if lang == "en" else
                   "%s %s ~%.0f km/h   回波移动, 近1h实测"
                   % (mo["arrow"], mo["dir_cn"], mo["kmh"]))
    elif mo.get("kind") == "stationary":
        mo_line = ("= echo quasi-stationary (<5km/h, 1h obs)" if lang == "en"
                   else "= 回波准静止 (<5km/h, 近1h实测)")
    else:
        mo_line = ""
    if lang == "ja":
        if mo.get("kind") == "moving":
            mo_line = "%s %s ~%.0f km/h   エコー移動, 直近1h実測" % (mo["arrow"], mo["dir_en"], mo["kmh"])
        elif mo.get("kind") == "stationary":
            mo_line = "= エコーほぼ停滞 (<5km/h, 直近1h実測)"
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
        t = time.strftime("%H:%M", time.gmtime(ts + tzh * 3600))
        # One greppable line per state, same token in every language: most
        # readers here are agents, and a state you must translate before you
        # can grep it is not a state. Prose after the token stays localised.
        L.append("radar: ok")
        if lang == "ja":
            L.append("レーダー実況 (現地 %s), 1文字≈%.0fkm, [%s]=%s" % (t, kmcol, code, name) + mo_sfx)
            L.append(art)
            if mo_line:
                L.append(mo_line)
            L.append("凡例: · 霧雨  ░ 小雨  ▒ 中雨  ▓ 大雨  █ 豪雨")
        elif lang == "en":
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
        # bob 7/30 19:26: a transient tile stall must degrade, not 502. What was
        # still missing is that a stall and genuine no-coverage produced the same
        # answer: radar_art() returned None for both, and serve.py only set
        # radar_err when it *raised*, so an upstream hiccup printed "no coverage
        # here" -- "never come back" said to a caller whose truth was "not yet".
        # State 3 is proven by an empty image list now, never inferred from a
        # failure; every failure is state 2.
        st = radar_state or (STATE_FETCHING if radar_err else STATE_NONE)
        if st == STATE_NONE:
            L.append("radar: none -- no coverage at this location (text brief: live/%s.txt)" % name
                     if lang == "en" else
                     "radar: none -- この地点はレーダー圏外 (テキスト概況: live/%s.txt)" % name
                     if lang == "ja" else
                     "radar: none -- \u8be5\u4f4d\u7f6e\u65e0\u96f7\u8fbe\u8986\u76d6 (\u6587\u672c\u7b80\u62a5: live/%s.txt)" % name)
        else:
            L.append("radar: fetching -- not ready yet, ask again in ~60s; weather above is live"
                     if lang == "en" else
                     "radar: fetching -- まだ取得できていません、約60秒後に再度; 上の天気は実況です"
                     if lang == "ja" else
                     "radar: fetching -- \u8fd8\u6ca1\u53d6\u5230, \u7ea6 60 \u79d2\u540e\u518d\u95ee; \u4ee5\u4e0a\u5929\u6c14\u4e3a\u5b9e\u65f6")
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
