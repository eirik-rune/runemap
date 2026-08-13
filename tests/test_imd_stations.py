"""The station table is only useful if it stays honest about what it cannot say.

Hermetic: the GeoJSON is a fixture, shaped exactly like IMD's, including a row
with no position, because that row is the one that decides whether this tool
degrades or lies.
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "ops"))

import imd_stations as S      # noqa: E402


def feat(code, name, lat, lng, status=1):
    return {"type": "Feature",
            "properties": {"code": code, "station": name, "latitude": lat,
                           "longitude": lng, "status": status,
                           "last_updated_date": "13 AUG 2026",
                           "last_updated_time": "08:40:47 UTC"}}


FIXTURE = json.dumps({"features": [
    feat("vrv", "Mumbai - Veravali", 19.7343, 72.8763),
    feat("goa", "Goa", 15.4909, 73.8278),
    feat("slp", "Solapur", 17.6599, 75.9064, status=4),
    {"type": "Feature", "properties": {"code": "xxx", "station": "No Position",
                                       "latitude": None, "longitude": None}},
]}).encode()


class TheTableComesFromThemNotFromMyFingers(unittest.TestCase):

    def rows(self):
        return S.stations(get=lambda u: FIXTURE)

    def test_a_row_with_no_position_is_dropped_not_defaulted(self):
        """Dropping is the honest move; a station at (0,0) would be in the Gulf
        of Guinea and would win 'nearest' for half the planet."""
        self.assertEqual([p["code"] for p in self.rows()], ["vrv", "goa", "slp"])

    def test_mumbai_finds_veravali(self):
        d, p = S.nearest(19.08, 72.88, self.rows())
        self.assertEqual(p["code"], "vrv")
        self.assertLess(d, 100)

    def test_the_distance_is_returned_so_the_caller_can_refuse(self):
        """A station 700 km away is 'nearest' and useless. The number is what
        lets a caller tell those apart, so it is part of the answer."""
        d, _p = S.nearest(28.61, 77.21, self.rows())   # delhi, far from all three
        self.assertGreater(d, 500)

    def test_the_status_flag_is_carried_through_untouched(self):
        by = {p["code"]: p for p in self.rows()}
        self.assertEqual(by["vrv"]["status"], 1)
        self.assertEqual(by["slp"]["status"], 4)   # not normalised to a boolean:
        # 1 and 4 are their vocabulary, and collapsing them would invent a fact.
