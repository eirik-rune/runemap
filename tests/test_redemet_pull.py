"""The publish gate: an empty mirror round must not replace a good index.

2026-08-14. Every radar fetch missed on the Tokyo side, the mirror wrote a
well-formed index with `radars: []` and exited 0, the tar had bytes -- so both
existing guards passed and the empty index went live. Brazil served nothing for
hours while 18 usable frames sat in the destination directory.

The shape is one this repo keeps meeting: a *successful* run that got nothing,
and an empty result overwriting a good one.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "ops"))

import redemet_pull as P      # noqa: E402


class AnEmptyRoundIsRefused(unittest.TestCase):

    def test_the_round_that_blanked_brazil_is_refused(self):
        why = P.why_not_publishable({"listed": 29, "mirrored": 0, "radars": []})
        self.assertIn("REDEMET-MIRROR-EMPTY", why)
        self.assertIn("29", why)

    def test_a_good_round_publishes(self):
        self.assertIsNone(
            P.why_not_publishable({"listed": 29, "mirrored": 18, "radars": [1]}))

    def test_a_partial_round_still_publishes(self):
        """Partial is not empty: 3 of 29 is worse weather cover, not a fault
        this gate should block. Blocking it would freeze the mirror on the
        first bad night."""
        self.assertIsNone(
            P.why_not_publishable({"listed": 29, "mirrored": 3, "radars": [1]}))

    def test_upstream_publishing_no_frames_is_not_our_fetch_failing(self):
        """2026-08-14 07:00Z. All 29 records carried `path: null` -- and the
        hours behind it decayed 18 -> 17 -> 3 -> 0, so REDEMET stopped
        publishing rather than us stopping fetching. Both end as mirrored=0,
        and the old gate called both MIRROR-EMPTY, which points the reader at
        our mirror for a fault that is not there."""
        why = P.why_not_publishable(
            {"listed": 29, "with_path": 0, "mirrored": 0, "radars": []})
        self.assertIn("REDEMET-UPSTREAM-NO-FRAMES", why)
        self.assertNotIn("REDEMET-MIRROR-EMPTY", why)

    def test_frames_published_but_none_fetched_still_blames_the_mirror(self):
        """The other side of the same fork: when they did publish and we got
        nothing, the mirror is exactly where to look."""
        why = P.why_not_publishable(
            {"listed": 29, "with_path": 18, "mirrored": 0, "radars": []})
        self.assertIn("REDEMET-MIRROR-EMPTY", why)
        self.assertNotIn("UPSTREAM-NO-FRAMES", why)

    def test_an_older_index_without_the_field_is_not_read_as_zero(self):
        """`with_path` absent means "written before this field existed", not
        "no frames". Defaulting it to 0 would silently convert every legacy
        fetch failure into an upstream outage."""
        why = P.why_not_publishable({"listed": 29, "mirrored": 0, "radars": []})
        self.assertIn("REDEMET-MIRROR-EMPTY", why)
        self.assertNotIn("UPSTREAM-NO-FRAMES", why)

    def test_the_gate_admits_when_it_is_protecting_nothing(self):
        """It arrived 37 seconds after the empty index went live, so from then
        on "keeping the previous index" meant keeping an empty one. A guard
        must not describe a protection it is not providing."""
        empty_prev = {"listed": 29, "mirrored": 0, "radars": []}
        why = P.why_not_publishable(
            {"listed": 29, "with_path": 0, "mirrored": 0, "radars": []},
            previous=empty_prev)
        self.assertIn("nothing is being protected", why)
        good_prev = {"listed": 29, "mirrored": 18, "radars": [1]}
        why2 = P.why_not_publishable(
            {"listed": 29, "with_path": 0, "mirrored": 0, "radars": []},
            previous=good_prev)
        self.assertNotIn("nothing is being protected", why2)

    def test_upstream_listing_nothing_gets_its_own_words(self):
        """A different fact from our fetches failing, and it must not print the
        same refusal -- one sends you to REDEMET, the other to our mirror."""
        why = P.why_not_publishable({"listed": 0, "mirrored": 0, "radars": []})
        self.assertIn("NOTHING-LISTED", why)
        self.assertNotIn("MIRROR-EMPTY", why)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TheReasonOutlivesTheRound(unittest.TestCase):
    """`index.json` is the switch and may only move on good data -- which is
    precisely why it cannot carry the reason there is none. Through the
    2026-08-14 REDEMET outage the live index stayed frozen at 02:40, from
    before `with_path` existed, so the bell said "none of 0 mirrored radars"
    every 30 minutes: true, and pointing at our mirror rather than at Brazil.
    """

    def setUp(self):
        import tempfile
        self.d = tempfile.mkdtemp()

    def test_a_refused_round_still_records_why(self):
        import json
        idx = {"listed": 29, "with_path": 0, "mirrored": 0, "radars": []}
        P.write_status(idx, "REDEMET-UPSTREAM-NO-FRAMES ...", dest=self.d)
        with open(os.path.join(self.d, "status.json")) as fh:
            st = json.load(fh)
        self.assertEqual(st["with_path"], 0)
        self.assertIn("UPSTREAM-NO-FRAMES", st["refusal"])

    def test_a_published_round_records_that_there_was_no_refusal(self):
        """Absence of a refusal has to be stated, not implied by a missing
        file -- otherwise 'published fine' and 'never ran' are the same."""
        import json
        P.write_status({"listed": 29, "with_path": 18, "mirrored": 18},
                       None, dest=self.d)
        with open(os.path.join(self.d, "status.json")) as fh:
            st = json.load(fh)
        self.assertIsNone(st["refusal"])
        self.assertEqual(st["mirrored"], 18)

    def test_an_unwritable_destination_does_not_stop_the_mirror(self):
        """Bookkeeping must never block frames reaching readers."""
        P.write_status({"listed": 1, "mirrored": 1}, None,
                       dest=os.path.join(self.d, "no", "such", "dir"))


class TheAlarmMustSurviveTheWakeEventTruncation(unittest.TestCase):
    """The doorbell truncates a wake event at 500 characters with no marker at
    the cut, and the mirror note is appended at the END of the alarm line. A
    full-prose note made one bad source 388 characters; two bad sources would
    have lost the reason and the "sudo tail" hint that follows it -- the note
    evaporating precisely when more than one thing is wrong."""

    MAX_NOTE = 90

    def _note(self, refusal):
        import json
        import tempfile
        import time as _t
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "status.json"), "w") as fh:
            json.dump({"at": int(_t.time()), "listed": 29, "with_path": 0,
                       "mirrored": 0, "refusal": refusal}, fh)
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..",
                                        "scripts"))
        import radar_redemet as R
        old, R.DIR = R.DIR, d
        try:
            return R._mirror_status_note()
        finally:
            R.DIR = old

    def test_the_note_is_short_enough_to_survive(self):
        note = self._note(
            "REDEMET-UPSTREAM-NO-FRAMES listed=29 with_path=0 -- REDEMET "
            "published no frame for this hour; not our fetch -- NOTE the "
            "previous index is itself empty, so nothing is being protected; "
            "this is a hold, not a rescue")
        self.assertLessEqual(len(note), self.MAX_NOTE, note)

    def test_it_keeps_the_part_that_says_which_system(self):
        """Short is worthless if it drops the only word that redirects the
        reader from our mirror to Brazil."""
        note = self._note(
            "REDEMET-UPSTREAM-NO-FRAMES listed=29 with_path=0 -- REDEMET "
            "published no frame for this hour; not our fetch")
        self.assertIn("UPSTREAM-NO-FRAMES", note)
        self.assertIn("with_path=0", note)
