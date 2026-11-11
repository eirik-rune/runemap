"""Do not print "overcast" when the source's own sunlight says the sun is out.

2026-11-11. A reader in Caiyun's user group posted a photo of a cloudless
Shenzhen with the app saying 阴 (overcast); we printed `now: CLOUDY` for the
same point. Qianlu (the Tokyo being) took it apart: Caiyun's realtime said
skycon CLOUDY, cloudrate 0.97, and dswrf 790.7 W/m2 -- about what a clear sky
gives at that hour. METARs CAVOK, the Hong Kong Observatory said fine and dry,
Himawari showed nothing over Guangdong. Her reading of the hourly cloudrate is
that it follows the model's total cloud (all high cloud that day), uncorrected.
Her analysis and prototype are in /srv/notes/skyfix/ on the Singapore box.

So the source contradicts itself: one field says the sky is shut, another says
the sunlight is not being stopped. This module takes only the narrow rule from
her prototype that needs nothing but those two fields:

    skycon == CLOUDY  and  dswrf / clear_sky(that moment) >= KT_MIN
        -> PARTLY_CLOUDY_DAY, and say so

Why only that one. "Sunlight is unobstructed" rules out thick cloud, not
cloud: on her 39 airports Zhengzhou and Hefei had kt 0.95 under a thin real
layer. Saying "clear" needs an observation (her satellite rules), which we do
not have a licensed source for. Downgrading "overcast" to "partly cloudy" is the
claim the source's own radiation can carry.

Where KT_MIN comes from: of her 15 stations reported CLOUDY at 2026-11-11
04:30Z, the 9 this rule changes had kt >= 0.82 (all dark or thin on the
satellite), the 6 it leaves had kt <= 0.54 (all thick on the satellite). 0.65
sits in that gap. One moment, 15 points: it is a gap, not a calibration.

**The time each dswrf refers to is the top of its hour, not now.** Measured the
same day: realtime dswrf 790.7 equals hourly[12:00] 790.7344 exactly (read at
12:37 and 12:55), and Haurwitz against hourly 12..16h gives 1.01/1.02/1.02/
1.01/1.00 at the hour mark but drifts 1.03->0.76 or 1.01->1.50 half an hour off.
Judging the hour-mark value against the current minute's clear sky inflates kt
in the afternoon: a real overcast 0.45 at 15:00 reads 0.645 at 15:50 (cos z
0.386, past the low-sun gate), 0.50 reads 0.72 and would be changed wrongly. So
nothing here reads the clock: realtime is judged at hourly[0]'s datetime, and
only when its dswrf IS hourly[0]'s value. If that ever stops being true we do not
know which moment realtime's dswrf describes, and the rule stays out.

Not done here, deliberately:
  * daily skycon (a whole-day summary; the rule was never checked on it);
  * night and low sun (cos z < COSZ_MIN): no sunlight to testify;
  * anything but CLOUDY: the rule only ever weakens an "overcast" claim.
If the upstream cloud field is fixed, this stops firing on its own.

Haurwitz is a sea-level model; on high ground clear-sky sunlight is stronger,
so kt reads high there. Under real thick cloud the gap to KT_MIN is wide enough
that this was judged acceptable, not measured.
"""
import math
import sys
from datetime import datetime, timezone

KT_MIN = 0.65
COSZ_MIN = 0.30
_AT = 0.5          # W/m2: realtime dswrf "is" hourly[0]'s value within this
NEW = "PARTLY_CLOUDY_DAY"


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


def kt_if_contradicted(skycon, dswrf, lon, lat, t_utc):
    """kt when an overcast claim is contradicted by its own sunlight, else None."""
    if skycon != "CLOUDY" or not isinstance(dswrf, (int, float)):
        return None
    c = cos_zenith(lon, lat, t_utc)
    if c < COSZ_MIN:
        return None
    kt = dswrf / clear_sky(c)
    return kt if kt >= KT_MIN else None


def _utc(iso):
    t = datetime.fromisoformat(iso)
    return t.astimezone(timezone.utc) if t.tzinfo else None


def apply(result, lon, lat):
    """Correct `result` (a /weather "result") in place; return it.

    A corrected realtime keeps the source's word in `skycon_upstream` and the
    ratio in `skycon_kt`; a corrected hourly item gets `upstream` and `kt`.
    Renderers print those -- a reader must be able to tell our correction from
    the source's own word. Applying twice changes nothing the second time."""
    lon, lat = float(lon), float(lat)
    hr = result.get("hourly") or {}
    sun = {}
    for x in hr.get("dswrf") or []:
        try:
            sun[x["datetime"]] = float(x["value"])
        except (KeyError, TypeError, ValueError):
            pass
    for it in hr.get("skycon") or []:
        at, v = it.get("datetime"), sun.get(it.get("datetime"))
        t = _utc(at) if isinstance(at, str) else None
        if t is None or v is None:
            continue
        kt = kt_if_contradicted(it.get("value"), v, lon, lat, t)
        if kt is not None:
            it["upstream"], it["value"], it["kt"] = it["value"], NEW, kt

    rt = result.get("realtime") or {}
    if rt.get("skycon") != "CLOUDY":
        return result
    first = (hr.get("dswrf") or [None])[0] or {}
    at = first.get("datetime")
    t = _utc(at) if isinstance(at, str) else None
    d, fv = rt.get("dswrf"), first.get("value")
    num = lambda x: isinstance(x, (int, float)) and not isinstance(x, bool)
    if t is None or not num(d) or not num(fv) or abs(d - fv) > _AT:
        # we cannot say which moment this dswrf describes: leave the word alone
        if num(d):
            sys.stderr.write("SKYFIX-UNTIMED realtime dswrf=%.1f hourly0=%r\n" % (d, fv))
        return result
    kt = kt_if_contradicted("CLOUDY", d, lon, lat, t)
    if kt is not None:
        rt["skycon_upstream"], rt["skycon"], rt["skycon_kt"] = "CLOUDY", NEW, kt
    return result
