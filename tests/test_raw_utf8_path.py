"""A Chinese place typed into curl must find the same place a browser finds.

2026-11-11: `curl echorune.net/深圳/zh` from curl 7.81 (Ubuntu 22.04) answered
"place not found: æ·±å³". That curl sends the UTF-8 bytes unencoded, and
http.server decodes the request line as latin-1; a browser percent-encodes and
was answered. An agent typing a city into curl is the reader this service is
for, so the two must be the same request. Driven through the handler's own
parse_request on real request bytes: no server, no credentials.
"""
import io
import os
import sys
import unittest
from urllib.parse import unquote

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
# serve.py exits at import time without a token; as in test_coord_order.py
os.environ.setdefault("CAIYUN_TOKEN", "dummy-for-import-only")
import serve  # noqa: E402


def parsed(raw_path):
    h = serve.H.__new__(serve.H)
    h.raw_requestline = b"GET " + raw_path + b" HTTP/1.1\r\n"
    h.rfile = io.BytesIO(b"Host: echorune.net\r\n\r\n")
    h.wfile = io.BytesIO()
    h.client_address = ("127.0.0.1", 0)
    assert h.parse_request(), h.wfile.getvalue()
    return h.path


class RawUtf8IsThePercentEncodedRequest(unittest.TestCase):

    def test_the_reported_case(self):
        self.assertEqual(unquote(parsed("/深圳/zh".encode())), "/深圳/zh")

    def test_raw_bytes_become_exactly_what_a_browser_sends(self):
        for p in ("/深圳/zh", "/广州", "/東京/ja.png", "/?q=深圳&lang=zh"):
            browser = "".join(c if ord(c) < 0x80 else
                              "".join("%%%02X" % b for b in c.encode()) for c in p)
            self.assertEqual(parsed(p.encode()), browser, p)

    def test_ascii_and_already_encoded_paths_are_untouched(self):
        for p in (b"/%E6%B7%B1%E5%9C%B3/zh", b"/shenzhen/zh?style", b"/116.3,39.9"):
            self.assertEqual(parsed(p), p.decode())


if __name__ == "__main__":
    unittest.main()
