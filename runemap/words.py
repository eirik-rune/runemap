"""Words the text map and the picture must say the same way.

Both renderings print the air quality, the wind direction and the day of the
week; if each kept its own table, the first edit to one would make the two
disagree about the same response -- and the rule that AQI 0 means "no data"
would hold in one of them only. No imports beyond the standard library: the
text map must not need the picture's stack (numpy, PIL, fonts) to say "优".
"""
import datetime as _dt
import math as _math

# China AQI bands (HJ 633-2012); the index Caiyun gives as "chn". The colour
# sits in the same row as the name so the two cannot be re-cut apart.
AQI_BANDS = ((50, "excellent", (0, 190, 80)), (100, "good", (240, 200, 0)),
             (150, "lightly polluted", (255, 126, 0)), (200, "moderately polluted", (230, 30, 30)),
             (300, "heavily polluted", (153, 0, 76)), (10 ** 9, "severely polluted", (126, 0, 35)))

# The same six bands, in the words Chinese and Japanese readers use for them.
AQI_NAMES = {"zh": ("优", "良", "轻度污染", "中度污染", "重度污染", "严重污染"),
             "ja": ("優", "良", "軽度汚染", "中度汚染", "重度汚染", "深刻な汚染")}


def aqi_band(v, lang="en"):
    """-> (band name in `lang`, band colour)."""
    for i, (hi, name, col) in enumerate(AQI_BANDS):
        if v <= hi:
            return (AQI_NAMES[lang][i] if lang in AQI_NAMES else name), col


def aqi_value(x):
    """An AQI the source gave -> int, or None when it gave nothing.

    0 is how the source says "no data": for Tokyo on 2026-11-04 every daily
    MAX from tomorrow on was 0 and 23 of the 24 hours were 0, while the same
    response put the air right now at 11. A day whose worst hour is 0 is not
    air that clean, it is a forecast that is not there -- and drawn as a
    green "0 excellent" it became a reading we made up."""
    try:
        v = int(x)
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


# Where the wind comes FROM, eight points, as each language names them.
COMPASS = {"en": ("N", "NE", "E", "SE", "S", "SW", "W", "NW"),
           "zh": ("北", "东北", "东", "东南", "南", "西南", "西", "西北"),
           "ja": ("北", "北東", "東", "南東", "南", "南西", "西", "北西")}


def compass(deg, lang="en"):
    names = COMPASS.get(lang, COMPASS["en"])
    return names[int((float(deg) + 22.5) // 45) % 8]


WEEK = {"zh": ("周一", "周二", "周三", "周四", "周五", "周六", "周日"),
        "ja": ("月", "火", "水", "木", "金", "土", "日")}


# Polar day and night: (short, for the picture's cell; long, for the text line).
POLAR = {"en": {"day": ("polar day", "polar day: the sun does not set"),
                "night": ("polar night", "polar night: the sun does not rise")},
         "zh": {"day": ("极昼", "极昼: 太阳整天不落"),
                "night": ("极夜", "极夜: 太阳整天不出")},
         "ja": {"day": ("白夜", "白夜: 太陽が沈まない"),
                "night": ("極夜", "極夜: 太陽が昇らない")}}


def polar(lat, day):
    """'day' / 'night' / None: is the sun up all of `day` at `lat`, or down all of it?

    Declination from the usual cosine fit (good to about half a degree); the
    horizon is the sun's centre at -0.833 deg, the refraction-plus-radius
    convention sunrise tables use. Sun up all day: its lowest point (lower
    culmination, |lat + dec| - 90) clears that line. Down all day: its highest
    point (90 - |lat - dec|) stays under it."""
    n = day.timetuple().tm_yday
    dec = -23.44 * _math.cos(_math.radians(360.0 / 365.0 * (n + 10)))
    if abs(lat + dec) - 90.0 > -0.833:
        return "day"
    if 90.0 - abs(lat - dec) < -0.833:
        return "night"
    return None


def polar_of(astro, lat):
    """'day' / 'night' / None for one of Caiyun's daily astro entries.

    Caiyun prints the same time for sunrise and sunset when there is neither
    (McMurdo, 2026-11-12: "16:52" and "16:52" in the middle of polar day), and
    the same pair would be printed in polar night. Which of the two it is
    depends on the season and the hemisphere, so it is computed, not guessed.
    Asked only when the source's two times are equal. At the edges of the
    season this fit lands one to three days off the usual tables (computed
    2026-11-12: Tromso polar night from Nov 26, Murmansk from Nov 30, McMurdo's
    midnight sun from Oct 21); on days where it says neither, the source's own
    times are printed, as they always were."""
    try:
        if lat is None or astro["sunrise"]["time"] != astro["sunset"]["time"]:
            return None
        return polar(float(lat), _dt.date.fromisoformat(str(astro["date"])[:10]))
    except (KeyError, TypeError, ValueError):
        return None


def weekday(dt, lang="en"):
    if lang == "zh":
        return WEEK["zh"][dt.weekday()]
    if lang == "ja":
        return WEEK["ja"][dt.weekday()] + "曜"
    return dt.strftime("%a")
