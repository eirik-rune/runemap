"""The one reflectivity scale the whole fleet draws with.

Every source that hands us VALUES rather than a picture -- SMHI, CHMI, KNMI --
used to carry its own copy of this table, with a comment in each saying it was
the fleet's table. Four copies that agree are a coincidence, not a
construction: the moment one is edited the maps diverge silently, each
self-consistent, and a reader cannot see that the same character now means two
different things depending on which country they are standing in.

    FLOOR_DBZ   below this, nothing is drawn
    LEVELS      band edges, each one the top of the level below it

**The floor is not a textbook number, it is DWD's.** Their published style for
the WN analysis -- a service already in this fleet, whose pictures we already
classify -- declares its first entry as

    #ffffff   opacity=0   quantity=7      dBz

that is, transparent below 7 dBZ. So a German sky at 3 dBZ draws nothing, and
until this file existed a Dutch or Czech sky at 3 dBZ drew light rain, because
the value sources treated everything above "no echo" as rain. Measured on the
2026-08-13 13:10 frames: **82% of KNMI's echo pixels and 83% of CHMI's are
below 7 dBZ**, and their floors go down to -31 dBZ, which is not weather.

The band edges are DWD's too, coarsened: their 19 / 28 / 37 / 46 boundaries are
the ones the colour classifier already uses, so the value path and the picture
path agree by construction rather than by both being edited to match.
"""

FLOOR_DBZ = 7.0
LEVELS = ((19.0, 1), (28.0, 2), (37.0, 3), (46.0, 4))
TOP = 5


def level_for(dbz):
    """dBZ -> 0-5. Below the floor is 0: seen, and not rain."""
    if dbz < FLOOR_DBZ:
        return 0
    for edge, v in LEVELS:
        if dbz < edge:
            return v
    return TOP
