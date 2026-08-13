"""Is the MeteoSwiss payload laid out the way its coordinates claim?

The question this answers is the one the projection check cannot. `somerc.py`
is verified against swisstopo's own worked example, and the frame's four corners
reproduce its declared grid to ~6 m -- but my arithmetic and those corners both
come from the same file, so they agree whatever the data array does. An
upside-down read would still be scale-correct, still freshly stamped, and put
the weather in the wrong half of the country.

**The usual control does not work here.** Denmark's `dmi_orient.py` compares the
blind mask against the radar sites, and for Switzerland that has no power:
MeteoSwiss centre the composite on their own network (radar cluster centre
N 1161002, grid centre N 1160000 -- one kilometre apart), so flipping the mask
maps it almost onto itself. Measured: 140.6 km against 142.0 km. A judgement
whose branches differ by one percent would fire on noise.

**So the control here is a different instrument entirely: rain gauges.**
MeteoSwiss's SMN automatic weather stations publish hourly precipitation
(`rre150h0`) with station coordinates, in different files, from equipment that
is not a radar. If the array is read correctly, gauge totals must correlate
with the radar rate at each station's own cell; if it is upside down, they
correlate with rain that fell somewhere else.

Measured over four independent rainy hours (2026-07-31 to 2026-08-05, n≈27
stations each):

    as read   +0.968  +0.873  +0.914  +0.982      mean +0.934
    flipped   +0.197  -0.127  +0.029  +0.136      mean +0.059

That is a verdict with room to be wrong in, unlike the 1% the mask offered.

This module is the judgement, not the download: callers supply the frame and
the gauge readings, so it can be exercised without a network.
"""
import math

# Correlation the correct orientation must reach, and the margin it must beat
# the flipped read by. Both are needed: a frame where nothing rained can score
# well on neither, and must say INSUFFICIENT rather than pick a winner.
MIN_CORR = 0.5
MIN_MARGIN = 0.3
MIN_STATIONS = 8
MIN_WET = 3
WET_MM = 0.3


def _corr(a, b):
    n = len(a)
    if n < 2:
        return None
    ma, mb = sum(a) / n, sum(b) / n
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((x - mb) ** 2 for x in b)
    if va <= 0 or vb <= 0:
        # No spread on one side: a constant column has no correlation, and
        # returning 0.0 here would read as "measured, and it disagrees".
        return None
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    return cov / math.sqrt(va * vb)


def judge(sample):
    """-> (verdict, note) for [(gauge_mm, radar_as_read, radar_flipped), ...].

    Verdicts: OK, FLIPPED, INSUFFICIENT. "I cannot tell" must not print the
    same word as "they disagree" -- one sends you to the weather, the other to
    the code.
    """
    rows = [(g, a, b) for g, a, b in sample
            if g is not None and a is not None and b is not None
            and g == g and a == a and b == b]
    if len(rows) < MIN_STATIONS:
        return "INSUFFICIENT", ("only %d usable stations, need %d"
                                % (len(rows), MIN_STATIONS))
    wet = [r for r in rows if r[0] >= WET_MM]
    if len(wet) < MIN_WET:
        # The failure that hid this problem all evening: when nothing is
        # raining, the map looks the same however it is drawn.
        return "INSUFFICIENT", ("only %d stations recorded rain, need %d -- a dry "
                                "hour cannot orient anything" % (len(wet), MIN_WET))
    g = [r[0] for r in rows]
    cn = _corr(g, [r[1] for r in rows])
    cf = _corr(g, [r[2] for r in rows])
    if cn is None or cf is None:
        return "INSUFFICIENT", "no spread in gauge or radar values"
    note = "as-read %+.3f, flipped %+.3f, n=%d (%d wet)" % (cn, cf, len(rows), len(wet))
    if cn >= MIN_CORR and cn - cf >= MIN_MARGIN:
        return "OK", note
    if cf >= MIN_CORR and cf - cn >= MIN_MARGIN:
        return "FLIPPED", note
    return "INSUFFICIENT", note + " -- neither orientation wins by the margin"


def sample_from(frame, flipped_frame_lookup, stations, cell_of):
    """-> [(gauge_mm, as_read, flipped)] for stations inside the grid.

    `frame` is indexed [row][col]; `stations` is [(lat, lng, gauge_mm)].
    Kept free of h5py and of the network so the judgement can be tested.
    """
    out = []
    for lat, lng, mm in stations:
        rc = cell_of(lat, lng)
        if rc is None:
            continue
        a = frame[rc[0]][rc[1]]
        b = flipped_frame_lookup(rc)
        out.append((mm, a, b))
    return out
