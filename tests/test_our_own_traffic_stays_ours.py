"""Our own machines must never land in the bucket that feeds the headline.

`ASKED-FOR-WEATHER` is the only bucket that could ever become evidence that a
stranger needs this service, so anything of ours that leaks into it moves the
acceptance number without anyone needing us. That is the same failure as the
installer which quietly pushed a public install counter: an instrument is what
I judge other things with, so I do not think to judge it.

Both address shapes are pinned on purpose. nginx here anonymises the client
address to its /24 before writing it, so live log lines look like
`3.114.3.0` -- measured, not assumed: 6486 lines of access.log.3.gz, zero
addresses not ending in `.0`. The classifier must not *depend* on that, because
it is a property of an nginx config sitting upstream of this program: if the
anonymiser is ever switched off, `3.114.3.152` starts appearing, and under an
exact-string match our own traffic would re-enter the headline bucket silently
and in our favour.

The neighbouring-network cases are the other half. A guard that calls too much
"ours" shrinks the only number that matters, and it would do it quietly.
"""
import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "ops"))

import who_is_using as W  # noqa: E402

_UA = "curl/8.5.0"


class OurOwnMachinesAreNeverCandidates(unittest.TestCase):
    def test_the_anonymised_form_that_actually_appears_in_the_logs(self):
        for ip in ("139.162.58.0", "3.114.3.0", "127.0.0.0"):
            self.assertEqual(W.classify(ip, _UA, "/tokyo", "200"), "OURS", ip)

    def test_a_full_address_inside_an_insider_network_is_also_ours(self):
        """The case that only appears if the anonymiser is turned off. It
        cannot be exercised against today's logs, which is exactly why it is
        pinned here rather than trusted to stay true."""
        for ip in ("139.162.58.7", "3.114.3.152", "127.0.0.1"):
            self.assertEqual(W.classify(ip, _UA, "/tokyo", "200"), "OURS", ip)

    def test_a_neighbouring_network_is_not_ours(self):
        """Positive control for the direction that loses users. Without it,
        'our traffic is excluded' would be indistinguishable from 'everything
        is excluded', which is a guard with one verdict and no jurisdiction."""
        for ip in ("3.114.4.152", "139.162.59.7", "8.8.8.8"):
            self.assertEqual(W.classify(ip, _UA, "/tokyo", "200"),
                             "ASKED-FOR-WEATHER", ip)

    def test_an_address_we_cannot_parse_is_not_quietly_called_ours(self):
        """IPv6 and malformed lines: the safe direction is to leave them in the
        candidate bucket, where they are visible and labelled as an upper
        bound, rather than to disappear them into OURS."""
        self.assertIsNone(W.insider("2001:db8::1"))
        self.assertIsNone(W.insider("not-an-address"))
        self.assertIsNone(W.insider(""))

    def test_the_insider_list_is_not_empty(self):
        """If the list is ever emptied, every test above still passes except
        this one -- they would all be asserting about strangers."""
        self.assertTrue(W.INSIDER_NETS)
        for net in W.INSIDER_NETS:
            self.assertTrue(net.endswith(".0"),
                            "keys are networks, and insider() derives a /24 "
                            "key ending in .0 to look them up: %r" % net)


if __name__ == "__main__":
    unittest.main()
