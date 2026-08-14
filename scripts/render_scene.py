#!/usr/bin/env python3
"""Bilingual one-screen weather scene for agents.
Outputs: live/<city>/en and live/<city>/zh
Layout: headline + 2h rain curve (6min buckets) + current radar map + legend.
Radar art fetched ONCE per city, shared across languages.
Data source: caiyunapp.com. Token via env CAIYUN_TOKEN."""
import importlib, json, math, os, sys, time, urllib.request, tempfile

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
    # unit=metric:v2 or the number is a lie. Under the DEFAULT `metric`,
    # `precipitation.local.intensity` is Caiyun's radar precipitation INDEX on
    # a 0~1 scale -- their documentation says so in as many words -- and we were
    # printing it verbatim with an "mm/h" label. bob spotted it on the first
    # screen: 0.33 read as a trace of drizzle when 0.33 of full scale is
    # substantial rain. **The error inverted the meaning**, which is the class
    # where the reader forms a false belief and cannot detect it.
    #
    # Verified field-by-field against the same coordinate before switching,
    # because a units flag that quietly changes OTHER fields would trade one
    # silent error for several: of every numeric field under `realtime`, only
    # `precipitation.local.intensity` and `precipitation.nearest.intensity`
    # differ (nearest 0.125 -> 0.6596). Temperature, humidity and wind are
    # identical. Nothing in this repo thresholds on either value -- they are
    # read only by the three display lines below and by render_live.py -- so
    # the change is confined to the number that was wrong.
    d = json.loads(_get("https://api.caiyunapp.com/v2.6/%s/%s,%s/weather?hourlysteps=24&lang=%s&unit=metric:v2" % (token, lng, lat, lang)))
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


# Which lifetime an undecided entry gets is not a question about the word
# "undetermined". It is one question about the world: did we get to look?
#
# noecho / sparse / corr all paid for the same download and ran the same
# correlation that produces a vector. They are answers about the sky -- "there
# is nothing to track", "there is echo but too little of it", "the frames do not
# line up" -- and each is exactly as true five minutes later as a "stationary"
# computed from those same two frames.
#
# fetch / error / frames are the instrument failing to look. Those are the only
# ones a reader can usefully be told to come back for.
#
# 8/7: this file already carried that argument, but only for noecho -- one
# member exempted, the class left behind. Shanghai then printed "fetching
# (retry in ~60s)" on 21 of 22 samples with 20 good frames in hand, because its
# answer was "sparse" and it was being expired at a failure's rate.
_MO_SKY = frozenset(("noecho", "sparse", "corr"))
_MO_BLIND = frozenset(("fetch", "error", "frames"))

def _mo_fresh(hit):
    """True if this cache entry may still be served."""
    if not hit:
        return False
    age = time.time() - hit[0]
    mo = hit[1] or {}
    # "no echo to track" is not an undecided instrument, it is a measurement of
    # the sky. It cost the same download and the same correlation that produced
    # a "stationary", and it is exactly as true five minutes later. Given a
    # failure's lifetime it starved every reader on a 60s rhythm: london printed
    # "fetching (retry in ~60s)" on 38 of 39 samples while the answer was
    # computed and thrown away each cycle. The wording promises that coming back
    # changes something; at that poll rate it never could. See issue #32.
    undecided = mo.get("kind") in (None, "undetermined")
    if undecided and mo.get("why") not in _MO_SKY:
        # unknown codes fall here on purpose: a why nobody classified is
        # treated as a failure, and test_every_why_is_classified fails loudly
        # rather than letting it inherit a lifetime by accident.
        return age < _MO_FAIL_TTL
    return age < _MO_TTL
# _MO_BUDGET is gone with ede4d59. It was 3.0s of join on the request thread
# that never consulted the deadline, and 1.2 + 3.0 walked through a 3s wall.
# The constant and its two joins are deleted rather than left unused: a shape
# that could once breach the wall, sitting in the file with no callers, is an
# invitation for the next reader to wire it back in exactly as it was.

# --- motion answers live on shared disk ------------------------------------
# Measured 8/8, not assumed: the two workers never computed DIFFERENT vectors.
# What differed was WHEN each one's answer expired. 8788 was warmed 06:24:44 and
# fell back to "fetching" at 06:34:57 (613s, i.e. _MO_TTL); 8789 was warmed 330s
# later and flipped at 06:40:21 -- predicted before the data, to the second.
# Two 600s windows permanently offset by however far apart the workers were
# warmed: whichever one is recomputing shows "fetching" while its twin shows a
# vector, and nginx hands consecutive readers to alternating workers. The two
# lines differ in length, which is what bob saw as 1910/1967 bytes alternating.
#
# One entry on disk = one expiry = the alternation cannot happen. The frame list
# already lives here (scene_at.R._get = _cached_get), so this adds no dependency
# and no new failure mode -- only the same directory.
_MO_DIR = os.path.join(
    os.environ.get("RUNEMAP_CACHE", os.path.expanduser("~/.cache/runemap")), "motion")


def _mo_path(key):
    return os.path.join(_MO_DIR, "%.1f_%.1f.json" % (key[0], key[1]))


def _mo_get(key):
    """The disk entry is the authority; memory is a same-process shortcut.

    Returns the (ts, mo) tuple shape every read site already expects, or None.
    A corrupt or half-written file is treated as absent, never as an answer.
    """
    try:
        with open(_mo_path(key), "rb") as f:
            ts, mo = json.loads(f.read().decode("utf-8"))
        return (float(ts), mo)
    except Exception:
        return _MO_CACHE.get(key)


def _mo_put(key, mo, ts=None):
    """Write through: disk first (atomically), memory as a mirror."""
    ent = (time.time() if ts is None else float(ts), mo)
    _MO_CACHE[key] = ent
    try:
        os.makedirs(_MO_DIR, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=_MO_DIR, suffix=".part")
        with os.fdopen(fd, "wb") as f:
            f.write(json.dumps([ent[0], mo]).encode("utf-8"))
        os.replace(tmp, _mo_path(key))
    except Exception as e:
        sys.stderr.write("MO-DISK-WRITE-FAILED %r\n" % (e,))
    return ent

_MO_BUSY = set()
# key -> threading.Event，谁都可以等它。
# 只有 _MO_BUSY 时，"已经有人在算"和"算不出来"对第二个到场的人是同一个答案：
# 不等。而**先到的那个人往往是后台预热，不是读者**——于是读者永远错过。
# 雷达那侧的 _RA_INFLIGHT 早就解决过同一个问题，这里照它的形状来。
_MO_INFLIGHT = {}
_MO_LOCK = threading.Lock()

def _obs_frames(lng, lat):
    """The frames echo_motion has always asked for, that nobody was passing it.

    Motion means displacement that actually happened. This service draws from
    forecast_images: that list begins at the last observation and runs out to
    +4h. echo_motion took whatever list it was handed and called its NEWEST
    frame "now" -- measured 8/7 at chiang mai, that put BOTH correlated frames
    in the future (+40.7min and +100.7min, one hour apart). The arrow described
    two predictions drifting apart from each other, not rain that moved.

    bob, whose company produces the data, caught it by reading one reply.

    The observation list is alive and entirely in the past at the same skies
    (chiang mai images: -135.1min..-25.1min; tokyo: -103.1..-8.1min), so the
    obs frames echo_motion's own docstring names were available the whole time.

    Returns None -- never raises -- so the caller can say "fetch failed" rather
    than "computation failed": a download is not a computation, and the reader
    can tell those apart.
    """
    token = os.environ.get("CAIYUN_TOKEN")
    if not token:
        return None
    try:
        raw = _get(_radar_list_url(token, lng, lat, "images"), timeout=8)
        return json.loads(raw).get("images") or None
    except Exception as e:
        sys.stderr.write("OBS-LIST-FAILED %r\n" % (e,))
        return None


def _motion_compute(key, imgs, lng=None, lat=None):
    mo = {"kind": None}
    try:
        # Motion is measured from the SAME list the map is drawn from. Fetching
        # a second, observation-only list (which is what stood here) made the
        # arrow describe pixels the reader is not looking at -- and cost an
        # extra upstream list request per sky. A forecast pair IS the motion
        # this map predicts; that is the product, not a defect.
        if not imgs:
            mo = {"kind": None, "why": "fetch"}
        else:
            frames = [(f[0], float(f[1]), f[2]) for f in imgs if len(f) >= 3 and f[2]]
            import echo_motion as EM
            EM._get = _get          # picks up the cached getter
            mo = EM.echo_motion(frames) or {"kind": None}
            if mo.get("kind"):
                # Stamp the basis where it is known. Deriving it later from
                # the MAP's list kind is how the label ended up saying
                # "upstream forecast" about a number measured from two
                # observation frames, minutes after that very bug was fixed.
                mo["basis"] = "obs" if _kind_for(lng, lat) != "forecast_images" else "forecast"
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
            prev = _mo_get(key)
            # _mo_fresh, not a hand-rolled comparison: an answer is servable
            # exactly when a read site would still serve it, and there must be
            # one definition of that. tests/test_failure_is_not_a_conclusion
            # greps for this and is right to.
            keep_prev = bool(prev
                             and (prev[1] or {}).get("kind") in ("moving", "stationary")
                             and _mo_fresh(prev))
        if not keep_prev:
            _mo_put(key, mo)
        _MO_BUSY.discard(key)
        with _MO_LOCK:
            _ev = _MO_INFLIGHT.pop(key, None)
        if _ev is not None:
            _ev.set()          # 叫醒所有在等的人，成功失败都叫

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
    "fetch":  {"en": "= echo motion: undetermined (tracking frames failed; map unaffected)",
               "zh": "= 回波移动: 未能测定(追踪帧失败; 不影响上图)",
               "ja": "= エコー移動: 判定不能(追跡フレーム失敗; 上図に影響なし)"},
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
    hit = _mo_get(key)
    if _mo_fresh(hit):
        return (key, None)
    with _MO_LOCK:
        ev = _MO_INFLIGHT.get(key)
        if ev is not None:
            # Someone is already computing this sky -- usually the background
            # warm, which arrives before any reader. Hand back ITS event so the
            # reader can wait on it. Returning None here (what this used to do)
            # is why the request path never waited: by the time a reader had
            # frames, the key was already busy and the answer was "don't wait".
            return (key, ev)
        ev = threading.Event()
        _MO_INFLIGHT[key] = ev
        _MO_BUSY.add(key)
    t = threading.Thread(target=_motion_compute, args=(key, imgs, lng, lat), daemon=True)
    t.start()
    return (key, ev)

# Batch path only (render_scene main() writing live/), never a request. It may
# block: nobody is waiting on the other end of a socket for it. Named apart
# from anything on the request path so the two can never be confused again --
# that confusion is precisely what put a 3.0s join behind a 3s wall.
_MO_BATCH_BUDGET = 3.0


def _motion_join(handle):
    key, t = handle
    if t is not None:
        t.wait(_MO_BATCH_BUDGET)
    hit = _mo_get(key)
    return (hit[1] if hit else {"kind": None})

# 2026-08-12 (bob asked; Luoshu measured). The request thread joined motion for
# ZERO seconds. That was right under the 3s wall: _motion_now's t.join(3.0) never
# consulted the deadline, so 1.2s of frames + 3.0s of motion walked through it.
#
# The wall moved to 10.0 on 7/31 ("The wall was not costing latency, it was
# costing content") and this decision was never revisited. A guard outlives the
# premise it was written for, and its death is silent -- it just starts refusing
# things it no longer needs to refuse.
#
# What it costs to wait, measured rather than assumed:
#   * motion needs ONE new PNG, not two: its pivot IS the frame the renderer
#     draws (`pivot = nearest(time.time())`), and it pairs that with +60min.
#   * echo_motion already fetches concurrently and already adopts the deadline.
#   * _radar_render does no IO at all -- it renders from bytes already on disk.
#   * the request thread is meanwhile waiting on weather: wx=2.13s, measured in
#     production, in a parallel thread.
# So the join is absorbed by a wait that was happening anyway. A cold sky's
# first reader used to be the one person guaranteed NOT to see motion: he paid
# to warm the cache and the next reader within _MO_TTL collected.
#
# Bounded by the request's own deadline, never by a constant of its own -- the
# original bug was a join that did not ask, not the waiting itself.
# Measured on cold skies through the public endpoint, 2026-08-12: motion became
# available 2.4-4.4s after the frames were in hand (one PNG at 1.25-1.53s plus
# the correlation). 2.0 was the first value tried and it missed every time --
# not by much, which is the worst way to be wrong: it looked like the patch did
# nothing at all. The number below is the measurement, not a preference.
# The mechanism's own ceiling: how long the computation itself can plausibly
# need (measured 2.4-4.4s on a cold sky). That answers the PRODUCER's question.
# It is not, and was never, an answer to the consumer's question -- what a
# decorative line is worth to someone who is waiting. Until 8/12 this constant
# was the only ceiling in sight, so it became both (Luoshu found his own number
# doing a job he had not designed it for). The consumer's answer now comes from
# wall.decor_budget(), and this stays as what it always was: an upper bound.
_MO_REQ_CAP = 4.0


def _motion_join_budgeted(handle, cap=_MO_REQ_CAP):
    """Join the motion thread for what the request can still afford.

    Returns {"kind": None} when it does not arrive in time -- the same shape
    the caller already handles, so a slow sky degrades to today's behaviour
    instead of a new one.
    """
    key, t = handle
    if t is not None:
        dl = net_budget.current_deadline()
        if dl is None:
            # No request budget in scope (batch/CLI). The cap is the ceiling
            # then, and that is a different situation, not a failure.
            left = cap
        else:
            # dl.left() -- NOT `dl - time.time()`. The first version of this
            # line assumed a float, raised TypeError, and a bare `except:
            # left = cap` swallowed it: the guard was off and nothing said so.
            # A fallback that cannot tell you it fired is how a guard dies.
            # Ask the reader's budget, not the wall. WALL is an ops knob for how
            # long a request may hold a socket; READER_SLO is a promise about a
            # person. Subtracting one from the other is how a decorative wait
            # came to be governed by a socket timeout.
            # 8/12 09:43: the log below used to re-read dl.elapsed() AFTER the
            # wait and print it under the same name as the decision input, so
            # `elapsed=1.03 budget=2.07` never satisfied the budget formula and
            # a reader checking the arithmetic would conclude the patch was
            # broken. Two moments, one label, is the ambiguity; give each its
            # own name. Bind the decision input once, here.
            _el = dl.elapsed()
            left = _wall.decor_budget(_el, cap=cap, left=dl.left())
        if left > 0:
            _t0 = time.time()
            t.wait(left)
            # Print what happened, not what was hoped for: without this line the
            # only way to know whether the budget was enough is to poll the
            # public endpoint by hand, which is how the 2.0s cap survived a
            # whole deploy looking like "the patch changed nothing".
            # elapsed is in here because without it "how long did this reader
            # wait in total" cannot be answered from the log -- it had to be
            # reverse-engineered from an end-to-end number by hand (Luoshu).
            sys.stderr.write(
                "MOTION-JOIN at_join=%.2f waited=%.2f budget=%.2f total=%.2f got=%s\n" % (
                    (_el if dl is not None else -1.0),
                    time.time() - _t0, left,
                    (dl.elapsed() if dl is not None else -1.0),
                    "yes" if _mo_fresh(_mo_get(key)) else "no"))
    hit = _mo_get(key)
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
    hit = _mo_get(key)
    if _mo_fresh(hit):
        return hit[1]
    if key not in _MO_BUSY:
        _MO_BUSY.add(key)
        t = threading.Thread(target=_motion_compute, args=(key, imgs, lng, lat), daemon=True)
        t.start()
    return {"kind": None}


# ---------------------------------------------------------------- radar states
#
# Two states reach the reader, and a third one used to:
#   ok       - frames are in hand, map rendered
#   fetching - we do not have frames for this sky. A background thread is on it.
#
# The third state ('none - no radar covers this spot, coming back will not help')
# was removed, and this comment kept describing it for weeks. Two reasons it is
# gone, both worth keeping:
#
#   1. bob 8/3 14:35: "no radar means you did not get the radar. Nobody is going
#      to believe there is no radar just because you say so." A sentence about
#      the world can be wrong about the world; a sentence about us cannot.
#   2. The old code inferred 'none' from a failure -- radar_art() returned None
#      both for an empty list and for a stall -- so a transient hiccup told the
#      user "never" when the truth was "not yet".
#
# So _from_cache() treats an empty list as unknown, not as proof, and there is
# no verdict left to promote it to. Measured 8/9: 53.3% of registered urban
# population (PPS n=45, CI 32.9-60.9) lives under a sky upstream has no frames
# for -- for them 'fetching' is a wait that never ends. That is issue #24 and
# the wording is bob's call, not a thing to fix by re-adding state 3 here.
#
STATE_OK, STATE_FETCHING = "ok", "fetching"

# Credit as each source asks to be credited, keyed by the name it reports.
def _second_attrib(name):
    """Whose data drew this map, in the words that source declares for itself.

    This used to be a dict here, restating what every adapter already carries.
    Finland caught it: the row was added, the map drew, and the credit line
    read a bare "FMI" because nobody had remembered to restate it in a second
    place. A duplicated table does not fail when it falls behind -- it just
    quietly starts under-crediting somebody whose data we are using, which is
    the one thing this line exists to prevent. So it is derived, and the only
    fallback is the source's own name.
    """
    try:
        import radar_wms
        for s in radar_wms.SERVICES:
            if s["name"] == name:
                return s["attrib"]
    except Exception:
        pass
    # Derived from SECOND_MODULES, never a second hand-kept list. A source was
    # once added to the chain and not to a tuple exactly like this one, so it
    # served readers for twenty minutes crediting nobody -- and the fallback
    # below returns the bare NAME, which looks like an attribution and is not
    # the licence line CC BY asks for. Silent, and on the licence.
    for mod in SECOND_MODULES.values():
        try:
            m = importlib.import_module(mod)
            if getattr(m, "NAME", None) == name:
                return getattr(m, "ATTRIB", name)
        except Exception:
            continue
    # Reaching here means a source drew a map and no module claims its name.
    sys.stderr.write("SECOND-ATTRIB-UNCLAIMED %r\n" % (name,))
    return name

# A frame older than this may draw the echo a full cell (~10km) away from
# where it now is: 10km/char over an observed 20-40km/h echo is 15-30 min.
# Derived from the picture, not picked to make the logs look good.
RADAR_STALE_MIN = 20

_RA_LOCK = threading.Lock()


_REASON = threading.local()


def note_reason(word):
    """Record, on THIS thread, why we are about to answer `fetching`."""
    _REASON.v = word
    return word


def last_reason():
    """Pop this thread's reason. None means nothing claimed a reason."""
    v = getattr(_REASON, "v", None)
    _REASON.v = None
    return v


def peek_reason():
    """Read this thread's reason WITHOUT clearing it.

    last_reason() pops, and serve.py:233 is the popper -- it runs after the body
    is built, to set X-Radar-Why. If the body popped too, whichever ran first
    would silently blank the other, and a header that goes missing for no stated
    cause is worse than no header. So: the body peeks, the header pops. One
    owner of the clearing, two readers.

    Until now the value only ever reached a response header. A header answers an
    operator; the person who typed `curl echorune.net`, got a screen with no map
    and no reason, reads the body. Measured 8/12: of 105 first-visit product
    requests from strangers, 9 got no map, and all 9 landed on the zero-parameter
    entry -- exactly the reader this service exists for.
    """
    return getattr(_REASON, "v", None)


# Reader-facing clauses for the not-drawn state. Three rules, each bought:
#  1. Every sentence is about US, never about the world. bob 8/3 14:35: "no
#     radar means you did not get the radar. Nobody is going to believe there
#     is no radar just because you say so."
#  2. Silence is the default -- only reasons that change what the reader does
#     next get a clause. bob 8/2 08:56 stopped me hedging every line: "that is
#     not honesty, that is stupid."
#  3. The wording of this state is bob's call (issue #24), so these strings are
#     a proposal. The plumbing is the point: until now the reason existed and
#     only an operator could see it.
_FETCH_CLAUSE = {
    "list-nofile": {
        "en": "not looked at this sky yet; fetching",
        "zh": "\u8fd9\u7247\u5929\u8fd8\u6ca1\u770b\u8fc7, \u521a\u5f00\u59cb\u53d6",
        "ja": "\u3053\u306e\u7a7a\u306f\u672a\u53d6\u5f97; \u53d6\u5f97\u958b\u59cb",
    },
    "list-toostale": {
        "en": "our copy was too old to draw",
        "zh": "\u624b\u4e0a\u8fd9\u4efd\u592a\u65e7, \u6b63\u5728\u91cd\u53d6",
        "ja": "\u624b\u5143\u304c\u53e4\u3059\u304e; \u518d\u53d6\u5f97\u4e2d",
    },
    "list-unreadable": {
        "en": "we could not read our stored copy",
        "zh": "\u5b58\u8fc7, \u4f46\u8bfb\u4e0d\u51fa\u6765",
        "ja": "\u4fdd\u5b58\u5206\u3092\u8aad\u307f\u53d6\u308c\u305a",
    },
    "list-unusable": {
        "en": "what we stored was not a frame",
        "zh": "\u5b58\u7740\u7684\u4e0d\u662f\u4e00\u5e27\u56fe",
        "ja": "\u4fdd\u5b58\u5206\u306f\u30d5\u30ec\u30fc\u30e0\u3067\u306a\u3044",
    },
    "list-unparseable": {
        "en": "upstream's frame list did not parse",
        "zh": "\u4e0a\u6e38\u7684\u5e27\u5217\u8868\u89e3\u4e0d\u5f00",
        "ja": "\u4e0a\u6d41\u306e\u4e00\u89a7\u3092\u89e3\u6790\u3067\u304d\u305a",
    },
    "sky-empty": {
        "en": "upstream listed no radar frames",
        "zh": "\u4e0a\u6e38\u6ca1\u7ed9\u51fa\u8fd9\u7247\u5929\u7684\u5e27",
        "ja": "\u4e0a\u6d41\u304c\u30d5\u30ec\u30fc\u30e0\u3092\u8fd4\u3055\u305a",
    },
    "cooldown": {
        # bob 8/13: "failed is not refused". The only branch that sets _RA_FAIL
        # is `if not imgs` -- upstream answered and the list was empty. Refusal
        # would mean it has frames and withholds them, which we cannot see. So:
        # subject us, predicate verifiable, no motive attributed to anyone.
        # (I reported this fix once before making it. The string is the record.)
        "en": "our last ask got no frames; waiting",
        "zh": "\u4e0a\u6b21\u95ee\u6ca1\u62ff\u5230\u5e27, \u7a0d\u540e\u518d\u95ee",
        "ja": "\u524d\u56de\u306f\u30d5\u30ec\u30fc\u30e0\u3092\u5f97\u3089\u308c\u305a\u5f85\u6a5f\u4e2d",
    },
    "render-failed": {
        "en": "we had frames but could not draw",
        "zh": "\u5e27\u6709, \u4f46\u6ca1\u753b\u51fa\u6765",
        "ja": "\u30d5\u30ec\u30fc\u30e0\u306f\u3042\u308b\u304c\u63cf\u753b\u3067\u304d\u305a",
    },
}

# The three fixed parts the reason slots between. They are not decoration:
# `radar: fetching` is the untranslated token an agent greps (that contract has
# its own test), and the tail tells a human the weather above is real even
# though the radar is not. Keeping BOTH is why the clauses above are terse --
# 24 (reason, lang) pairs, widest 78 of 79 cells.
# The fallback, for a reason we have no sentence for. Module level so a test
# can assert against the shipped string instead of keeping its own copy --
# a hand-copied line in a test is prose that falls behind the code silently.
_BASE_NOT_DRAWN = {
    "en": "radar: fetching -- no radar frames for this sky yet; weather above is live",
    "zh": "radar: fetching -- \u8fd8\u6ca1\u62ff\u5230\u8fd9\u7247\u5929\u7684\u96f7\u8fbe\u6570\u636e; \u4ee5\u4e0a\u5929\u6c14\u4e3a\u5b9e\u65f6",
    "ja": "radar: fetching -- \u3053\u306e\u7a7a\u306e\u30ec\u30fc\u30c0\u30fc\u306f\u307e\u3060\u53d6\u5f97\u3067\u304d\u3066\u3044\u307e\u305b\u3093; \u4e0a\u306e\u5929\u6c17\u306f\u5b9f\u6cc1\u3067\u3059",
}
_FETCH_HEAD = "radar: fetching -- "
_FETCH_TAIL = {
    "en": "; weather above is live",
    "zh": "; \u4ee5\u4e0a\u5929\u6c14\u4e3a\u5b9e\u65f6",
    "ja": "; \u4e0a\u306e\u5929\u6c17\u306f\u5b9f\u6cc1\u3067\u3059",
}


# Deliberately silent, so that "not covered yet" and "we decided to say nothing"
# stop looking alike (issue #41):
#   list-nopeek -- only reachable when the bare _peek stub is installed, i.e. in
#                  tests. A sentence for it could never be read by a person.
#   unknown     -- nobody claimed a reason. Inventing prose for a word that means
#                  "we do not know why" is exactly the failure this file fixes.
_FETCH_SILENT = ("list-nopeek", "unknown")


def fetching_clause(why, lang):
    """Clause for the not-drawn line, or "" when we should stay quiet.

    An unexplained reason returns "" on purpose: a word we have never seen is
    not something we can explain to a stranger, and inventing a sentence for it
    would be this very bug, one layer up.
    """
    return (_FETCH_CLAUSE.get(why) or {}).get(
        lang if lang in ("en", "ja") else "zh", "")
_PEEK = threading.local()


def note_peek_miss(word):
    """Record WHY a cache-only read came back empty, on THIS thread.

    _cached_peek has four ways to return None -- the key was never stored, the
    file aged past the stale window, it could not be read, or the bytes were
    judged not a frame -- and until 8/12 19:25 all four arrived at the reason
    site as one word, list-miss. One label for four states is a ruler with no
    jurisdiction: the information existed and we were the ones dropping it.
    """
    _PEEK.v = word
    return word


def take_peek_miss():
    """Pop this thread's peek reason. None means the stub _peek is in use."""
    v = getattr(_PEEK, "v", None)
    _PEEK.v = None
    return v

_RA_INFLIGHT = {}                 # key -> Event, one warm per sky at a time

def _reason_after_wait(why, refused_at, started_at):
    """Which fact does this reader deserve: the age of our copy, or upstream's answer?

    `refused_at` is _RA_FAIL[key], written only where upstream answered with an
    empty frame list. If that happened DURING this request (>= started_at), it is
    newer than the cached file _from_cache() peeked at, and it is about the sky
    rather than about our housekeeping -- so it wins. A refusal older than this
    request does not win: the throttle already had its say at :903, and re-using
    stale memory here would let one 30-second-old refusal silence a sky that has
    since come back. Anything else returns `why` unchanged, so this can never
    invent a reason where none was observed.
    """
    if refused_at is None or started_at is None:
        return why
    return "sky-empty" if refused_at >= started_at else why
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
        # Start motion only once a frame is known to be LOCAL. The first version
        # of this patch started it above the loop, so every cold sky -- the ones
        # that answer "fetching" and render nothing -- also kicked a motion
        # thread that went to the CDN. On dev that starved the radar warm:
        # RADAR-WARM-FRAME BudgetExceeded ... after 0 bytes, on a CDN that
        # answered a hand-issued curl in 0.2s. Production, unpatched, had zero.
        # Extra load on exactly the requests that had nothing to show for it.
        _mh = _motion_start(imgs, lng, lat)
        url, ts, bbox = cand[0], float(cand[1]), cand[2]
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(png); p = f.name
        try:
            art, kmcol = ascii_radar(p, bbox, lng, lat,
                                     cols=(24 if small else 48),
                                     rows=(12 if small else 24), marker=code)
        finally:
            os.unlink(p)
        # Start it before the render, so its PNG flies while we draw, then
        # collect it with whatever the deadline still allows.
        return art, kmcol, ts, _motion_join_budgeted(_mh), base_ts
    return None


# Off unless switched on, and named rather than boolean: the day there are two
# fallbacks, "which one drew this" must be answerable from the environment and
# from the body, not from reading this file.
SECOND_SOURCE = os.environ.get("RUNEMAP_SECOND_SOURCE", "").strip()

# Chain name -> adapter module. One table, because anything that wants to know
# what this fleet can serve has to resolve the same names production resolves.
#
# This used to be an if/elif ladder inside _second_source, which meant the only
# way to ask "which sources exist" was to read the ladder -- so I answered from
# memory instead, told bob the US was not wired, and was wrong: us-nexrad has
# been configured and probed for days, but it lives inside radar_wms with
# Canada, Finland and Germany, and I had been counting radar_*.py filenames.
# A second copy of this mapping in a reporting tool would be the same bug with
# an extra step; four places agreeing by coincidence is not a guard.
SECOND_MODULES = {
    "rainviewer": "radar_second",
    "redemet": "radar_redemet",
    "wms": "radar_wms",
    "jma": "radar_jma",
    "smhi": "radar_smhi",
    "chmi": "radar_chmi",
    "knmi": "radar_knmi",
    "dmi": "radar_dmi",
    "metno": "radar_metno",
    "meteoswiss": "radar_meteoswiss",
}


def _second_source(code, lng, lat, small, cached_only=False):
    """Never raises into the reader's path: a broken fallback must degrade to
    the sentence we already have, not to a 500."""
    if not SECOND_SOURCE:
        return None
    # A comma-separated chain, tried in order. Order is a judgement about data,
    # not about code: a national radar beats a global composite over the country
    # that owns it, so redemet goes before rainviewer for a Brazilian sky and
    # simply declines everywhere else.
    for which in [w.strip() for w in SECOND_SOURCE.split(",") if w.strip()]:
        try:
            modname = SECOND_MODULES.get(which)
            if modname is None:
                sys.stderr.write("SECOND-UNKNOWN %r\n" % (which,))
                continue
            _m = importlib.import_module(modname)
            try:
                got = _m.draw(code, lng, lat, small, cached_only=cached_only)
            except TypeError:
                # An adapter that predates the flag still works; it just cannot
                # promise to stay off the network, so it is only asked when we
                # are allowed to wait.
                if cached_only:
                    continue
                got = _m.draw(code, lng, lat, small)
            if got is not None:
                return got
        except Exception as e:
            # One broken adapter must not take the rest of the chain with it.
            sys.stderr.write("SECOND-FAILED %s %r\n" % (which, e))
    return None


# What a cold second source costs, measured rather than assumed: 0.7-1.5s for
# a WMS frame, 0.8-1.5s for a JMA mosaic, 3.65s end to end for the worst case
# seen in production (Helsinki, cold). Under this much room left we do not
# start one.
SECOND_FETCH_NEEDS = float(os.environ.get("RUNEMAP_SECOND_NEEDS", "4.0"))

_WARM_LOCK = threading.Lock()
_WARMING = {}
_WARM_EVERY = 120.0
# A diagnostic switch, not a feature. This box is one core: a warm thread doing
# numpy classification is not free while a reader is being served, and the only
# way to test whether that is where today's median went is to run the fleet with
# it off on one instance and on on the other. Default is on, and the day this is
# not being used for an experiment it should go.
WARM_SECOND = os.environ.get("RUNEMAP_WARM_SECOND", "1") != "0"


def _warm_second(code, lng, lat, small):
    """Fetch the second source off this thread, so the NEXT reader gets it.

    One warm per sky per _WARM_EVERY seconds: without that, every reader of a
    stale sky starts their own fetch and we would have replaced one slow
    request with a stampede.
    """
    if not WARM_SECOND:
        sys.stderr.write("SECOND-WARM-OFF %.1f,%.1f\n" % (lat, lng))
        return
    key = (round(float(lat), 1), round(float(lng), 1))
    now = time.time()
    with _WARM_LOCK:
        if now - _WARMING.get(key, 0.0) < _WARM_EVERY:
            sys.stderr.write("SECOND-WARM-SKIP %.1f,%.1f age=%.0fs\n"
                             % (lat, lng, now - _WARMING.get(key, 0.0)))
            return
        _WARMING[key] = now

    def run():
        # An action with no record. Until now the only line this path could
        # ever print was its own failure, so "the warm never ran" and "the warm
        # ran and cost a reader half a second" were the same silence -- and I
        # spent an hour guessing at exactly that. Both ends are written, with
        # the elapsed time, because the question is not whether it happened but
        # what it cost while it did.
        t0 = time.time()
        try:
            got = _second_source(code, lng, lat, small)
            sys.stderr.write("SECOND-WARM %.1f,%.1f %.2fs %s\n"
                             % (lat, lng, time.time() - t0,
                                "drew" if got is not None else "nothing"))
        except Exception as e:
            sys.stderr.write("SECOND-WARM-FAILED %.1f,%.1f %.2fs %r\n"
                             % (lat, lng, time.time() - t0, e))
    t = threading.Thread(target=run, name="second-warm", daemon=True)
    t.start()


def _fresher_of(hit, code, lng, lat, small):
    """Let a national radar win when the primary's frame has gone stale.

    Until now the chain only ran when the primary had NOTHING, and the cost of
    that showed up the hour Germany shipped: Berlin was served a frame 46
    minutes old, correctly labelled stale, while a German radar frame 0 minutes
    old sat one function call away. "Has a frame" and "has a frame worth
    showing" are not the same question, and answering the first was serving the
    reader the older sky on purpose.

    The threshold is RADAR_STALE_MIN, the age at which we already tell the
    reader this picture may be a cell out of date -- so the rule reads: once we
    would warn them, prefer anyone fresher. Below it the primary still wins
    outright and nothing is asked, which keeps this off the fast path.
    """
    try:
        rb = hit[1]
        if not rb or len(rb) < 5 or rb[4] is None:
            # A payload with no observation time is not an error and must not
            # be logged as one: it is simply a shape this comparison cannot
            # judge, so the primary keeps the reader.
            return hit
        base_ts = rb[4]
        age = time.time() - float(base_ts)
        if age <= RADAR_STALE_MIN * 60:
            return hit
        # Cached only: this reader already holds a map, and buying them a
        # fresher one at the price of an upstream round trip is a trade nobody
        # asked for. Measured on production after this shipped without the
        # flag: mean probe latency 0.96s -> 1.66s, p99 6.7s, 9.3% of probes
        # over the 3s product line against 4.1% before. The same file's own
        # docstring says this thread opens no socket.
        alt = _second_source(code, lng, lat, small, cached_only=True)
        if alt is None:
            _warm_second(code, lng, lat, small)   # for whoever asks next
            return hit
        if float(alt[4]) <= float(base_ts):
            return hit
        sys.stderr.write("SECOND-FRESHER %s primary_age=%.0fmin second_age=%.0fmin\n"
                         % (alt[5] if len(alt) > 5 else "?", age / 60.0,
                            (time.time() - float(alt[4])) / 60.0))
        note_reason(None)
        return STATE_OK, alt
    except Exception as e:
        # A comparison that throws must cost the reader nothing: they already
        # have a map in hand.
        sys.stderr.write("SECOND-FRESHER-FAILED %r\n" % (e,))
        return hit


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
    note_reason(None)   # a stale reason from an earlier request is a lie
    take_peek_miss()    # same for the peek sub-reason
    _wait_override = wait

    now = time.time()
    with _RA_LOCK:
        fail = _RA_FAIL.get(key)
    if fail is not None and now - fail < _RA_FAIL_COOLDOWN:
        note_reason("cooldown")
        sys.stderr.write("FETCHING-REASON reason=cooldown key=%.1f,%.1f waited=0.00\n"
                         % (key[0], key[1]))
        # A sky whose last ask got nothing: still state 2 (we are not sure it
        # is "never"), and we will not hammer the upstream once per request
        # while we make up our mind. But the reader is still standing here with
        # no map, so the second source gets asked on THIS path too. Measured in
        # production 07:51: sao paulo spends much of its time in this branch,
        # and wiring the fallback only at the bottom of the function meant it
        # was reached on some requests and not others -- two probes a second
        # apart, one drew and one did not.
        alt = _second_source(code, lng, lat, small)
        if alt is not None:
            note_reason(None)
            return STATE_OK, alt
        return STATE_FETCHING, None

    # Each way out of _from_cache is a DIFFERENT fact about this sky, and they
    # used to meet at one return where the difference was dropped. A dict, not
    # a nonlocal, because this has to keep working on the 3.8 that pyproject
    # still claims and I have not verified the suite on.
    _why = {"v": None}

    def _from_cache():
        raw = _peek(_radar_list_url(token, lng, lat))
        if raw is None:
            # "nopeek" is the absence of a carrier word, NOT a peek that missed: it means
            # nothing on this thread called _cached_peek (a different early exit, or the
            # bare stub). Giving absence its own name is the whole point of splitting.
            _why["v"] = "list-" + (take_peek_miss() or "nopeek")   # not proof of anything
            return None
        try:
            imgs = (json.loads(raw).get("images") or [])
        except Exception:
            _why["v"] = "list-unparseable"
            return None
        if not imgs:
            # Unknown, not proven: an empty list out of a cached body says
            # nothing about the sky, and there is no verdict left to promote
            # it to. Ask again.
            _why["v"] = "sky-empty"
            return None
        got = _radar_render(code, lng, lat, imgs, small)
        if not got:
            _why["v"] = "render-failed"
        return (STATE_OK, got) if got else None

    hit = _from_cache()
    if hit is not None:
        return _fresher_of(hit, code, lng, lat, small)

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
    _t0 = time.time()
    if wait > 0:
        ev.wait(wait)
    hit = _from_cache()
    if hit is not None:
        return hit
    # Order matters and it is not a preference: ask the second source BEFORE
    # computing why there is no map. If it draws, there is no missing map to
    # explain, and _reason_after_wait would be answering a question nobody
    # asked. (Eirik's three lines below arrived in the same place at 05:29;
    # the conflict was ordering, not meaning.)
    # How much of the reader's time is left decides whether we may fetch at
    # all. A cold national radar is 1-4s (measured: Helsinki 3.65s end to end),
    # and spending that when the budget is nearly gone turns "no map, here is
    # why" into "no map, and you waited". So: fetch while there is room, and
    # once there is not, ask only for what is on disk and warm for the next
    # reader. The threshold is not a new number -- it is the same deadline the
    # primary path already spends, minus the reserve rendering needs.
    _dl2 = net_budget.current_deadline()
    _room = None if _dl2 is None else _dl2.left() - _wall.RESERVE
    _cold_ok = _room is None or _room >= SECOND_FETCH_NEEDS
    alt = _second_source(code, lng, lat, small, cached_only=not _cold_ok)
    if alt is None and not _cold_ok:
        sys.stderr.write("SECOND-NO-ROOM left=%.2fs needs=%.2fs\n"
                         % (_room, SECOND_FETCH_NEEDS))
        _warm_second(code, lng, lat, small)
    if alt is not None:
        note_reason(None)               # a reason belongs to a map we did NOT draw
        return STATE_OK, alt

    with _RA_LOCK:
        refused = _RA_FAIL.get(key)
    _why["v"] = _reason_after_wait(_why["v"], refused, _t0)
    note_reason(_why["v"] or "unknown")
    sys.stderr.write("FETCHING-REASON reason=%s key=%.1f,%.1f waited=%.2f budget=%.2f\n"
                     % (_why["v"] or "unknown", key[0], key[1],
                        time.time() - _t0, wait))
    return STATE_FETCHING, None


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
                "data: Caiyun Weather caiyunapp.com | runemap "
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
        L.append("# %s weather scene" % name)
        L.append("# updated %s %s  (lon %s, lat %s)" % (stamp, _tz_label(tzh), lng, lat))
        L.append("now: %s  %.0fC  humidity %.0f%%  wind %.0fkm/h  precip %.2fmm/h" % (
            rt["skycon"], rt["temperature"], rt["humidity"]*100, rt["wind"]["speed"],
            rt["precipitation"]["local"]["intensity"]))
    elif lang == "ja":
        sky = SKY_JA.get(rt["skycon"], rt["skycon"])
        L.append("# %s 天気一覧" % name)
        L.append("# 更新 %s %s  (経度 %s, 緯度 %s)" % (stamp, _tz_label(tzh), lng, lat))
        L.append("現在: %s  %.0fC  湿度 %.0f%%  風速 %.0fkm/h  降水 %.2fmm/h" % (
            sky, rt["temperature"], rt["humidity"]*100, rt["wind"]["speed"],
            rt["precipitation"]["local"]["intensity"]))
    else:
        sky = SKY_ZH.get(rt["skycon"], rt["skycon"])
        L.append("# %s \u5929\u6c14\u4e00\u5c4f" % zh)
        L.append("# \u66f4\u65b0\u4e8e %s %s  (\u7ecf\u5ea6 %s, \u7eac\u5ea6 %s)" % (stamp, _tz_label(tzh), lng, lat))
        L.append("\u5f53\u524d: %s  %.0fC  \u6e7f\u5ea6 %.0f%%  \u98ce\u901f %.0fkm/h  \u96e8\u5f3a %.2fmm/h" % (
            sky, rt["temperature"], rt["humidity"]*100, rt["wind"]["speed"],
            rt["precipitation"]["local"]["intensity"]))
    if kp:
        L.append(kp)
    mo = (rb[3] if rb and len(rb) > 3 else None) or _MOTION.get(name) or {}
    # The basis travels with the datum, it is not re-derived here. Motion is
    # now computed from the observation list even where the MAP is a forecast
    # (see _obs_frames), so deriving the label from the map's kind made chiang
    # mai print "upstream forecast" about a number measured from two observed
    # frames -- minutes after that very bug was fixed. Same family as the bug
    # bob reported: a sentence speaking for a source it does not know.
    _MO_OBS = (mo.get("basis") == "obs") or _kind_for(lng, lat) == "images"
    _MO_BASIS_EN = "1h obs" if _MO_OBS else "upstream forecast"
    _MO_BASIS_ZH = "\u8fd11h\u5b9e\u6d4b" if _MO_OBS else "\u4e0a\u6e38\u9884\u62a5"
    _MO_BASIS_JA = "\u76f4\u8fd11h\u5b9f\u6e2c" if _MO_OBS else "\u4e0a\u6d41\u4e88\u5831"
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
            if mo_line:
                L.append(mo_line)
            L.append("凡例: · 霧雨  ░ 小雨  ▒ 中雨  ▓ 大雨  █ 豪雨")
        elif lang == "en":
            L.append("~%.0fkm/char, [%s]=%s" % (kmcol, code, name) + mo_sfx)
            L.append(art)
            if mo_line:
                L.append(mo_line)
            L.append("legend: \u00b7 drizzle  \u2591 light  \u2592 moderate  \u2593 heavy  \u2588 storm")
        else:
            L.append("每字符≈%.0fkm, [%s]=%s" % (kmcol, code, zh) + mo_sfx)
            L.append(art)
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
        _base = _BASE_NOT_DRAWN[lang if lang in ("en", "ja") else "zh"]
        # peek, not pop: serve.py owns the clearing (see peek_reason).
        # bob 8/13: "why add a line? just replace the sentence." He is right --
        # the generic clause ("no radar frames for this sky yet") is a tautology
        # of the reason, and a second line was me adding rather than replacing,
        # which is the half that carries no risk. So the reason IS the sentence,
        # and the live-weather tail rides along; only an unexplained reason
        # falls back to the generic line. All 24 (reason, lang) pairs measured
        # at <= 79 cells WITH the tail -- the clauses were shortened to fit,
        # because 'weather above is live' disappearing was a real loss, not a
        # width problem.
        _why = fetching_clause(peek_reason(), lang)
        _lg = lang if lang in ("en", "ja") else "zh"
        L.append(_FETCH_HEAD + _why + _FETCH_TAIL[_lg] if _why else _base)
        # Kept for the fallback only: Eirik measured all 9 real (reason, lang)
        # combinations past 80 columns when the clause rode along -- the ja base
        # is already 79 cells, so anything appended must wrap. A wrapped line is
        # not a line an agent can grep, and this text exists for the reader who
        # got no map. Same token in every language for exactly that reason.
    L.append("")
    # Whoever's data drew the radar is named here. When the fallback drew it,
    # the primary did not, and saying "Caiyun" would be taking credit for a map
    # they did not make -- and withholding the credit the other source asks for.
    _src = rb[5] if rb and len(rb) > 5 and rb[5] else None
    L.append("data: Caiyun Weather caiyunapp.com | runemap (github.com/eirik-rune/runemap)" if lang == "en"
             else "データ: 彩雲天気 caiyunapp.com | runemap で描画 (github.com/eirik-rune/runemap)" if lang == "ja"
             else "\u6570\u636e: \u5f69\u4e91\u5929\u6c14 caiyunapp.com | runemap \u6e32\u67d3 (github.com/eirik-rune/runemap)")
    # Its own line, and its own token. Appending it to the data line measured 88
    # cells (Eirik's width guard caught it); and it cannot reuse "radar:", which
    # an agent greps for the state. Present only when the fallback drew the map,
    # so its absence is also information: the primary upstream drew this one.
    if _src:
        L.append("radar-data: " + _second_attrib(_src))
        # Naming the source is not the whole obligation. CC BY 4.0 -- which
        # covers FMI and DWD's open data alike -- asks that changes be
        # indicated, and DWD's own template page says a source note is required
        # even for a change of data format. What we hand a reader is not their
        # picture: it is a 48x24 character grid derived from it. That sentence
        # does not fit on the credit line without pushing the longest
        # attribution past 79 cells, so it gets its own token; a machine keys
        # on the token, and "radar-data-note" cannot be confused with either
        # "radar:" (the state) or "radar-data:" (whose data).
        L.append("radar-data-note: redrawn from the source frames as a text grid")
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
