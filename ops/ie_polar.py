"""Polar volume -> Cartesian cells, for Ireland's two radars.

Every other source in this fleet hands us somebody else's Cartesian composite
and the risk is indexing it wrongly. Met Eireann hand us **polar volumes**, so
here we *build* the grid. That moves the risk: an error is ours, and in
particular **the blind mask is ours to author**, because it does not arrive in
the data at all.

Measured on the 2026-08-14 07:10Z frames, both sites:

    nodata 0.0%          -- nothing says "not seen"
    undetect 83-99%      -- "seen, no echo"

Beyond maximum range there is simply no cell. So "seen but dry" and "never
looked at" are ours to keep apart, and Norway is the record of what conflating
them costs: fill read as not-seen turned a clear sky over Oslo into 74% blind
and refused the whole country. Here the same mistake runs the other way and is
worse -- an unseen cell defaulting to "dry" paints fair weather over places no
beam reached, which is the silent direction.

So this module never returns one array. It returns **two**, and `seen` is not
derivable from `dbz`:

    dbz[i]   float, NaN where the cell is dry OR unseen
    seen[i]  bool,  False only where no radar looked

There is no value of `dbz` that means "unseen". That is deliberate: a single
array would make the two states share a representation, which is the shape this
repo has now met in seven different disguises.

**No h5py here.** Reading the files is the adapter's job; this is pure numpy so
it runs in CI, where h5py is deliberately absent. The geometry is the part that
can be wrong in ways nobody sees, so the geometry is the part that must be
testable everywhere.

## Three things read from the file rather than restated

* **`rscale` and `nbins` are per sweep, not per country.** Shannon: 497 bins at
  500 m. Dublin: 250 bins at 1000 m. Same ~250 km reach, half the resolution.
  Reading either one once and reusing it puts the other site's echoes at twice
  or half their true range -- and still draws a plausible Ireland.

* **Azimuth comes from `how/startazA`, not from the ray index.** It happens to
  be true in these files that ray *i* starts near azimuth *i*, but that is an
  observation about today's files, not a guarantee, and `searchsorted` over the
  published array costs nothing.

* **`a1gate` is NOT a rotation.** It is the ray that was acquired first in time;
  storage still begins at azimuth 0, as `startazA[0] ~ 0` confirms in both
  files. It reads like an offset, and applying it would rotate Shannon by 95
  degrees and Dublin by 142 -- *different amounts per site*, which is the only
  reason such a bug would ever be noticed. It is named here precisely so the
  next reader does not have to rediscover that it is a trap.
"""
import math

import numpy as np

#: Earth radius used for ground range. The 4/3 effective-radius refraction model
#: belongs in the beam-height calculation, not here; ground range at <=250 km is
#: dominated by the spherical term and this is the same constant the rest of the
#: fleet uses for distances.
EARTH_R_M = 6371008.8


def ground_range_and_azimuth(site_lat, site_lon, lat, lng):
    """-> (range_m, azimuth_deg) from a site to each cell, as arrays.

    Great-circle, not equirectangular: at 250 km the flat-earth error in
    azimuth is small but it is largest at the edge of coverage, which is
    exactly where the range mask decides seen-vs-unseen.
    """
    la1 = math.radians(float(site_lat))
    lo1 = math.radians(float(site_lon))
    la2 = np.radians(np.asarray(lat, dtype=float))
    lo2 = np.radians(np.asarray(lng, dtype=float))
    dlo = lo2 - lo1

    sin_la1, cos_la1 = math.sin(la1), math.cos(la1)
    sin_la2, cos_la2 = np.sin(la2), np.cos(la2)

    central = np.arccos(
        np.clip(sin_la1 * sin_la2 + cos_la1 * cos_la2 * np.cos(dlo), -1.0, 1.0))
    rng = central * EARTH_R_M

    az = np.degrees(np.arctan2(
        np.sin(dlo) * cos_la2,
        cos_la1 * sin_la2 - sin_la1 * cos_la2 * np.cos(dlo)))
    return rng, np.mod(az, 360.0)


def ray_of_azimuth(startaz, az_deg):
    """-> ray index for each azimuth, using the sweep's published start angles.

    `startaz` is `how/startazA`: the azimuth at which each stored ray begins.
    It is very nearly 0,1,2,... in Met Eireann's files, and this does not
    assume that.
    """
    startaz = np.mod(np.asarray(startaz, dtype=float), 360.0)
    n = startaz.shape[0]
    az = np.mod(np.asarray(az_deg, dtype=float), 360.0)

    # A rotated sweep -- one whose ray 0 starts at, say, 10 degrees -- has a
    # startazA that ascends and then wraps, so it is NOT sorted. Handing that
    # to searchsorted directly returns wrong rays and returns them quietly,
    # which is the failure mode this whole module is built to avoid. Sorting
    # and mapping back through the permutation costs one argsort and is correct
    # for both cases. Met Eireann's current files start at 0 and would work
    # either way; that is a fact about today's files, not a guarantee.
    order = np.argsort(startaz, kind="stable")
    idx = np.searchsorted(startaz[order], az, side="right") - 1
    return order[np.mod(idx, n)]


def sample_sweep(data, startaz, rscale, nbins, rstart_m,
                 gain, offset, nodata, undetect,
                 site_lat, site_lon, lat, lng):
    """-> (dbz, seen) for one sweep of one radar.

    `dbz` is NaN wherever there is no echo, including where `seen` is False.
    `seen` is False only where this radar did not look: beyond the last bin, or
    where the stored value is `nodata`.
    """
    data = np.asarray(data)
    rng, az = ground_range_and_azimuth(site_lat, site_lon, lat, lng)

    # Range mask. This is the authored half -- nothing in the file states it.
    b = np.floor((rng - float(rstart_m)) / float(rscale)).astype(np.int64)
    in_range = (b >= 0) & (b < int(nbins))
    bi = np.where(in_range, b, 0)

    ri = ray_of_azimuth(startaz, az)
    raw = data[ri, bi].astype(float)

    is_nodata = raw == float(nodata)
    is_undetect = raw == float(undetect)

    seen = in_range & ~is_nodata
    dbz = np.full(raw.shape, np.nan, dtype=float)
    echo = seen & ~is_undetect
    dbz[echo] = raw[echo] * float(gain) + float(offset)
    return dbz, seen


def composite(sweeps, floor_dbz=7.0):
    """Combine per-site (dbz, seen) pairs into one pair.

    * `seen` is the union: one radar looking is enough.
    * `dbz` is the maximum over sites that had echo -- the standard choice, and
      the safe one, since taking a mean would let a site that saw nothing dilute
      a site that saw a storm.
    * echoes below `floor_dbz` are dropped to NaN but the cell stays **seen**.

    The floor is not cosmetic and not inherited from another source. Measured on
    2026-08-14: Shannon's echo median is -1.0 dBZ and only 16.4% of its echo
    reaches 7 dBZ. Drawing everything above `undetect` -- the bug that had three
    countries painting clear-air clutter as light rain -- would put the west of
    Ireland under drizzle on a frame that is mostly insects and ground. 7 dBZ is
    DWD's own published floor, which is where the rest of the fleet took it from.
    """
    if not sweeps:
        raise ValueError("composite of no sweeps: the caller must decline "
                         "out loud rather than hand back an empty grid")
    seen = np.zeros_like(sweeps[0][1], dtype=bool)
    best = np.full(sweeps[0][0].shape, np.nan, dtype=float)
    for dbz, s in sweeps:
        seen |= np.asarray(s, dtype=bool)
        best = np.fmax(best, np.asarray(dbz, dtype=float))
    if floor_dbz is not None:
        best = np.where(best >= float(floor_dbz), best, np.nan)
    return best, seen
