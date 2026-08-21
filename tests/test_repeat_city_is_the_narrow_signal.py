"""The narrowest demand signal we have must not widen quietly.

Everything else in who_is_using answers "was there traffic". `--repeat-city`
asks the one thing in the logs that could mean somebody wanted an answer: the
same caller asking for the same named place on two separate days. Returning
costs an indexer nothing; coming back for one particular place is what a person
does who has a reason to care about that place.

The whole value of this number is that it is small and hard to satisfy, so the
tests here are mostly about what must NOT count: a caller that came twice on one
day, a caller that asked for two different places, our own machines, and anything
that says in its own user agent that it checks or indexes.

Offline: a log file is written into a temp dir and read back.
"""
import io
import os
import sys
import contextlib
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "ops"))

import who_is_using as W  # noqa: E402

_BROWSER = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"


def line(ip, day, path, ua=_BROWSER, status="200"):
    return ('%s - [%s:04:05:06 +0000] "GET %s HTTP/1.1" %s 1800 "%s"\n'
            % (ip, day, path, status, ua))


def run(lines):
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "access.log")
        with open(p, "w", encoding="utf-8") as f:
            f.writelines(lines)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = W.repeat_city([p])
        return rc, out.getvalue()


class OnlyARealReturnCounts(unittest.TestCase):
    def test_same_caller_same_place_on_two_days_counts(self):
        rc, out = run([line("9.9.9.0", "01/Aug/2026", "/tokyo"),
                       line("9.9.9.0", "03/Aug/2026", "/tokyo")])
        self.assertEqual(rc, 0, out)
        self.assertIn("1 of them came back", out)
        self.assertIn("tokyo", out)

    def test_twice_in_one_day_is_not_a_return(self):
        """The point is a separate decision to come back, not two requests."""
        rc, out = run([line("9.9.9.0", "01/Aug/2026", "/tokyo"),
                       line("9.9.9.0", "01/Aug/2026", "/tokyo")])
        self.assertIn("0 of them came back", out)

    def test_two_different_places_is_not_a_return(self):
        """Browsing is not needing. A caller sampling our cities looks exactly
        like this, and it was the shape of two of the five rows on the first
        real run."""
        rc, out = run([line("9.9.9.0", "01/Aug/2026", "/tokyo"),
                       line("9.9.9.0", "03/Aug/2026", "/osaka")])
        self.assertIn("0 of them came back", out)

    def test_our_own_machines_never_count(self):
        rc, out = run([line("3.114.3.0", "01/Aug/2026", "/tokyo"),
                       line("3.114.3.0", "03/Aug/2026", "/tokyo")])
        self.assertIn("0 of them came back", out)

    def test_self_declared_machines_never_count(self):
        for ua in ("mcpbeat/0.1 (+https://mcpbeat.com/bot/; liveness check)",
                   "MJ12bot/v2.0.5", "SomethingNew/1.0 (+https://example.com)"):
            rc, out = run([line("9.9.9.0", "01/Aug/2026", "/tokyo", ua),
                           line("9.9.9.0", "03/Aug/2026", "/tokyo", ua)])
            self.assertIn("0 of them came back", out, ua)

    def test_an_agent_runtime_still_counts(self):
        """Positive control in the direction that loses users: `node` and `Bun`
        are what the reader we are looking for sends, and no rule here may
        quietly exclude them."""
        for ua in ("node", "Bun/1.1.45", "curl/8.5.0"):
            rc, out = run([line("9.9.9.0", "01/Aug/2026", "/tokyo", ua),
                           line("9.9.9.0", "03/Aug/2026", "/tokyo", ua)])
            self.assertIn("1 of them came back", out, ua)

    def test_our_own_endpoints_are_not_places(self):
        rc, out = run([line("9.9.9.0", "01/Aug/2026", "/mcp"),
                       line("9.9.9.0", "03/Aug/2026", "/mcp"),
                       line("9.9.9.0", "01/Aug/2026", "/status"),
                       line("9.9.9.0", "03/Aug/2026", "/status")])
        self.assertEqual(rc, 2, out)
        self.assertIn("NO-PLACES", out)

    def test_an_empty_log_says_it_could_not_tell(self):
        """'I could not ask' and 'nobody wanted one' must not print the same
        page -- the true answer here is small enough that a broken run looks
        exactly like a true one."""
        rc, out = run([])
        self.assertEqual(rc, 2, out)
        self.assertIn("NO-PLACES", out)
        self.assertNotIn("0 of them came back", out)

    def test_a_percent_encoded_place_is_the_same_place(self):
        """`/清迈` arrives URL-encoded and matched English `/chiangmai` almost
        one for one in the traffic. If the two spellings of one request did not
        fold together, a returning reader would be split into two strangers."""
        rc, out = run([line("9.9.9.0", "01/Aug/2026", "/%E6%B8%85%E8%BF%88"),
                       line("9.9.9.0", "03/Aug/2026", "/清迈")])
        self.assertIn("1 of them came back", out)


if __name__ == "__main__":
    unittest.main()
