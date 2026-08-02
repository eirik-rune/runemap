"""A rainless sky is a valid answer, not a corrupt download.

Measured 8/2 12:16 (bangkok): upstream serves a 268-byte png -- 223x217,
colortype 6, one distinct byte after inflate = fully transparent. The old
usability test was `len(b) > 512`, so that frame was fetched, judged garbage,
never stored; _peek missed for ever and the sky sat in "fetching -- ask again
in ~60s" permanently. Every dry sky, not one city.

Size was standing in for validity, and the emptier the sky the smaller the
file: the test was strictest on exactly the answer it should have accepted.
"""
import os
import sys
import unittest
import zlib
import struct

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import scene_at as SA


def _png(w, h, value):
    """A real png: IHDR + IDAT + IEND, every pixel the same byte."""
    def chunk(typ, body):
        return (struct.pack(">I", len(body)) + typ + body
                + struct.pack(">I", zlib.crc32(typ + body) & 0xffffffff))
    raw = b"".join(b"\x00" + bytes([value]) * (w * 4) for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9))
            + chunk(b"IEND", b""))


class EmptySkyIsCacheable(unittest.TestCase):
    def test_a_transparent_frame_is_usable(self):
        b = _png(223, 217, 0)
        self.assertLess(len(b), 512, "the whole point: an empty sky compresses below the old threshold")
        self.assertTrue(SA._usable("png", b),
                        "a valid png of a dry sky must be cacheable, or that sky never leaves fetching")

    def test_a_rainy_frame_is_still_usable(self):
        self.assertTrue(SA._usable("png", _png(223, 217, 137)))

    def test_truncated_download_is_rejected(self):
        b = _png(223, 217, 0)
        self.assertFalse(SA._usable("png", b[:-6]), "no IEND = the transfer was cut short")

    def test_html_error_page_is_rejected(self):
        self.assertFalse(SA._usable("png", b"<html>502 Bad Gateway</html>" * 40))

    def test_empty_body_is_rejected(self):
        self.assertFalse(SA._usable("png", b""))


if __name__ == "__main__":
    unittest.main()
