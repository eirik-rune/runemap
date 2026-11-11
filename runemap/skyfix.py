"""Say the sky that is there, not the model's cloud field.

2026-11-11. A cloudless Shenzhen (METAR CAVOK, HKO "fine and dry", Himawari
empty) was printed `now: CLOUDY`: Caiyun's realtime had skycon CLOUDY with
cloudrate 0.97 and dswrf 790.7 W/m2 -- clear-sky sunlight for that hour. The
cloud field follows the model's total cloud (all thin high cloud that day),
uncorrected. Analysis and the rules below are Qianlu's (/srv/notes/skyfix/).
bob: fix it so echorune is right -- Shenzhen today is clear, "partly cloudy"
is not fixed -- and print only the answer, not a note about the source.

Two witnesses, both used only for the dry sky words (rain, haze, dust, wind
are never touched):

  observed cloud share around the point (Himawari-9 cloud mask, cloudmask.py)
      < 15%                         -> clear
      15% .. 85%                    -> partly cloudy
      >= 85% and sunlight >= 65%    -> partly cloudy (thin cloud the sun shines through)
      >= 85% otherwise              -> overcast
  sun low or down at the frame (below ~10 deg), observation only takes cloud away:
      < 15%, humidity < 75%, visibility > 10 km   -> clear
      anything else                               -> the source's word
  no observation (off the disk, stale):
      CLOUDY and sunlight >= 65% of clear-sky  -> partly cloudy

"sunlight" is kt = dswrf / Haurwitz clear-sky. The observation decides now:
realtime, the current hour's row, and today's summary when it said overcast.
Future hours have no observation and get only the sunlight rule.

Where the numbers come from, all from one moment (11-11 04:30Z, 39 airports):
15%/85% are Qianlu's cut of the mask share (it matched her reading of the
satellite pictures at all 39, and it tells the thin layer over Zhengzhou and
Hefei that sunlight alone cannot see); kt 0.65 sits in the gap between the 9
overcast-reported stations under clear or thin sky (kt >= 0.82) and the 6 under
thick cloud (kt <= 0.54). Her 24-hour comparison, mornings and evenings
included, is what will say whether they hold.

**dswrf is the value at the top of its hour, not now.** Realtime dswrf equals
hourly[0]'s to 0.1 W/m2, and Haurwitz against hourly 12..16h is flat at the
hour mark (1.01/1.02/1.02/1.01/1.00) but drifts half an hour off (to 0.76 or
1.50). Judged against the current minute, a real 0.45 overcast at 15:00 reads
0.645 at 15:50. So each value is judged at its own hour; realtime only when its
dswrf is hourly[0]'s (otherwise logged SKYFIX-UNTIMED and the sunlight rule
stays out).

Low sun: the sunlight rule needs cos z >= 0.30 at its hour; the full
observation rule is used while the sun is above ~10 deg at the frame time
(cos z >= 0.17).

Below that -- low sun, twilight, night -- only the clear half is open (11-11
evening: Shenzhen CAVOK, share 0.05, printed overcast). The night mask works
in the infrared, where the thin high cloud that fooled the model is cold and
plain to see; what it misses is fog and low stratus, which are as warm as the
ground. So:
  * clear only when the mask sees < 15% AND the ground air is too dry for fog
    (humidity < 0.75, visibility > 10 km). Missing either -> no change: the
    worst case is the old behaviour.
  * never toward overcast: Shanghai that night read 1.00 over a CAVOK sky
    (thin cirrus); without sunlight 1.00 cannot tell cirrus from a deck.
Counted by Qianlu on her 39 airports, 17:05-19:05 Beijing (rule_replay.py):
17 changes, the 11 with a METAR all CAVOK/NSC, 6 without one; the 5 of those
with the sun still above the horizon had 3 METARs, all CAVOK. Not tested:
a fog night -- none of the 39 had fog or a low deck. 0.75 and 10 km are her
physical estimate, not counted; her morning table is the check. Gate held
back a clear sky -> logged SKYFIX-GATED, so we can count it too.
Day or night in the clear word: the source's own suffix; for CLOUDY, whether
the sun was up at the frame.

Haurwitz is a sea-level model; on high ground kt reads somewhat high. Judged
acceptable under thick cloud, not measured.
"""
import math
import sys
from datetime import datetime, timezone

DRY = ("CLEAR_DAY", "CLEAR_NIGHT", "PARTLY_CLOUDY_DAY", "PARTLY_CLOUDY_NIGHT", "CLOUDY")
KT_MIN = 0.65
COSZ_MIN = 0.30          # sunlight rule
COSZ_OBS = 0.17          # observation used while the sun is above ~10 deg
LO, HI = 0.15, 0.85      # cloud share: clear below LO, overcast from HI
HUM_MAX = 0.75           # sun low/down: clear only in air too dry for fog ...
VIS_MIN = 10.0           # ... and with the airport-scale view open, km
_AT = 0.5                # W/m2: realtime dswrf "is" hourly[0]'s value within this


def cos_zenith(lon, lat, t_utc):
    """Cosine of the solar zenith angle (NOAA's Fourier series)."""
    doy = t_utc.timetuple().tm_yday
    g = 2 * math.pi * (doy - 1) / 365
    decl = (0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g)
            - 0.006758 * math.cos(2 * g) + 0.000907 * math.sin(2 * g)
            - 0.002697 * math.cos(3 * g) + 0.00148 * math.sin(3 * g))
    eot = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g)
                    - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g))
    minutes = t_utc.hour * 60 + t_utc.minute + t_utc.second / 60 + 4 * lon + eot
    ha = math.radians(minutes / 4 - 180)
    la = math.radians(lat)
    return math.sin(la) * math.sin(decl) + math.cos(la) * math.cos(decl) * math.cos(ha)


def clear_sky(cosz):
    """Haurwitz clear-sky global horizontal irradiance, W/m2."""
    return 1098 * cosz * math.exp(-0.057 / cosz) if cosz > 0 else 0.0


def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def sunlight(dswrf, lon, lat, t_utc):
    """kt at the moment dswrf describes, or None when the sun is too low."""
    if not _num(dswrf):
        return None
    c = cos_zenith(lon, lat, t_utc)
    return dswrf / clear_sky(c) if c >= COSZ_MIN else None


def decide(sky, kt=None, frac=None, day=True):
    """The word to print. `frac` None means no observation."""
    if sky not in DRY:
        return sky
    if frac is None:
        return "PARTLY_CLOUDY_DAY" if sky == "CLOUDY" and kt is not None and kt >= KT_MIN else sky
    sfx = "_DAY" if day else "_NIGHT"
    if frac < LO:
        return "CLEAR" + sfx
    if frac < HI:
        return "PARTLY_CLOUDY" + sfx
    if kt is not None and kt >= KT_MIN:
        return "PARTLY_CLOUDY_DAY"
    return "CLOUDY"


def dry_air(hum, vis):
    """Too dry for fog or a deck on the ground; unknown is not dry."""
    return _num(hum) and hum < HUM_MAX and _num(vis) and vis > VIS_MIN


def decide_low(sky, frac, hum, vis, up):
    """Sun low or down: the clear word, or None when the source's word stands."""
    if sky not in DRY or frac >= LO or not dry_air(hum, vis):
        return None
    if sky.endswith("_NIGHT") or (sky == "CLOUDY" and not up):
        return "CLEAR_NIGHT"
    return "CLEAR_DAY"


def _utc(iso):
    try:
        t = datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return None
    return t.astimezone(timezone.utc) if t.tzinfo else None


def _set(item, key, new):
    if item.get(key) != new:
        item.setdefault("upstream", item.get(key))
        item[key] = new


def apply(result, lon, lat, obs=(None, None)):
    """Correct a /weather "result" in place and return it.

    obs: (cloud share, frame time) from cloudmask.cloud_fraction, or (None, None).
    Sets realtime["cloudmask_at"] when the observation decided the word (by day
    whenever there is one; with the sun low, only when it made the sky clear),
    so the page can credit it. Applying twice changes nothing the second time."""
    lon, lat = float(lon), float(lat)
    frac, ft = obs if obs else (None, None)
    low = None                              # the share, when the sun was low or down at the frame
    if frac is not None and ft is None:
        frac = None
    elif frac is not None and cos_zenith(lon, lat, ft) < COSZ_OBS:
        low, frac = frac, None              # there only the clear half is open
    hr = result.get("hourly") or {}
    sun = {}
    for x in hr.get("dswrf") or []:
        if isinstance(x, dict) and _num(x.get("value")):
            sun[x.get("datetime")] = x["value"]

    # realtime: its dswrf is hourly[0]'s, judged at hourly[0]'s hour
    rt = result.get("realtime") or {}
    first = (hr.get("dswrf") or [None])[0] or {}
    t0 = _utc(first.get("datetime"))
    d, fv = rt.get("dswrf"), first.get("value")
    kt = None
    if t0 is not None and _num(d) and _num(fv) and abs(d - fv) <= _AT:
        kt = sunlight(d, lon, lat, t0)
    elif _num(d) and rt.get("skycon") == "CLOUDY":
        sys.stderr.write("SKYFIX-UNTIMED realtime dswrf=%.1f hourly0=%r\n" % (d, fv))
    sky0 = rt.get("skycon")
    now = decide(sky0, kt, frac)
    seen = frac is not None                 # the observation decided the word
    if low is not None:
        hum, vis = rt.get("humidity"), rt.get("visibility")
        clr = decide_low(sky0, low, hum, vis, cos_zenith(lon, lat, ft) > 0)
        if clr:
            now, seen = clr, True
        elif sky0 in DRY and not sky0.startswith("CLEAR") and low < LO:
            sys.stderr.write("SKYFIX-GATED %s frac=%.2f hum=%r vis=%r at %.2f,%.2f\n" % (
                sky0, low, hum, vis, lon, lat))
    if now != sky0:
        rt["skycon_upstream"] = rt.get("skycon_upstream", sky0)
        rt["skycon"] = now
        shown = frac if frac is not None else low
        sys.stderr.write("SKYFIX %s -> %s frac=%s kt=%s at %.2f,%.2f\n" % (
            rt["skycon_upstream"], now, "-" if shown is None else "%.2f" % shown,
            "-" if kt is None else "%.2f" % kt, lon, lat))
    if seen:
        rt["cloudmask_at"] = ft.strftime("%Y-%m-%dT%H:%MZ")

    # hourly: the current hour shows what realtime shows when observed;
    # every other hour has only its own sunlight
    for i, it in enumerate(hr.get("skycon") or []):
        if not isinstance(it, dict) or it.get("value") not in DRY:
            continue
        if i == 0 and seen and now in DRY:
            _set(it, "value", now)
            continue
        t = _utc(it.get("datetime"))
        if t is None:
            continue
        _set(it, "value", decide(it.get("value"), sunlight(sun.get(it.get("datetime")), lon, lat, t)))

    # today's summary cannot be "overcast" while we observe that it is not
    dy = (result.get("daily") or {}).get("skycon") or []
    if dy and isinstance(dy[0], dict) and seen and dy[0].get("value") == "CLOUDY" \
            and now in ("CLEAR_DAY", "CLEAR_NIGHT", "PARTLY_CLOUDY_DAY"):
        _set(dy[0], "value", "PARTLY_CLOUDY_DAY")
    return result
