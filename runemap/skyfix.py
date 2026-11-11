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
  no observation (off the disk, stale, night, low sun):
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

Low sun: the sunlight rule needs cos z >= 0.30 at its hour; the observation is
used while the sun is above ~10 deg at the frame time (cos z >= 0.17). Below
that, and at night, the source's word stands: the mask was only checked at
noon, and twilight is where it is weakest.

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
    Sets realtime["cloudmask_at"] when the observation decided anything, so the
    page can credit it. Applying twice changes nothing the second time."""
    lon, lat = float(lon), float(lat)
    frac, ft = obs if obs else (None, None)
    if frac is not None and (ft is None or cos_zenith(lon, lat, ft) < COSZ_OBS):
        frac = None                         # night or twilight: the mask was not checked there
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
    now = decide(rt.get("skycon"), kt, frac)
    if now != rt.get("skycon"):
        rt["skycon_upstream"] = rt.get("skycon_upstream", rt.get("skycon"))
        rt["skycon"] = now
        sys.stderr.write("SKYFIX %s -> %s frac=%s kt=%s at %.2f,%.2f\n" % (
            rt["skycon_upstream"], now, "-" if frac is None else "%.2f" % frac,
            "-" if kt is None else "%.2f" % kt, lon, lat))
    if frac is not None:
        rt["cloudmask_at"] = ft.strftime("%Y-%m-%dT%H:%MZ")

    # hourly: the current hour shows what realtime shows when observed;
    # every other hour has only its own sunlight
    for i, it in enumerate(hr.get("skycon") or []):
        if not isinstance(it, dict) or it.get("value") not in DRY:
            continue
        if i == 0 and frac is not None and now in DRY:
            _set(it, "value", now)
            continue
        t = _utc(it.get("datetime"))
        if t is None:
            continue
        _set(it, "value", decide(it.get("value"), sunlight(sun.get(it.get("datetime")), lon, lat, t)))

    # today's summary cannot be "overcast" while we observe that it is not
    dy = (result.get("daily") or {}).get("skycon") or []
    if dy and isinstance(dy[0], dict) and frac is not None and dy[0].get("value") == "CLOUDY" \
            and now in ("CLEAR_DAY", "PARTLY_CLOUDY_DAY"):
        _set(dy[0], "value", "PARTLY_CLOUDY_DAY")
    return result
