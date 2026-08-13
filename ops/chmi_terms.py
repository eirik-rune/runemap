"""Re-ask the Czech open-data catalogue what the radar composite's terms are.

We ship Czechia because its licence is CC BY 4.0. Denmark sits unshipped three
directories away from a working download, for no other reason than that its
terms could not be read -- so the licence is not paperwork here, it is the
thing that decided the country.

A licence read once and then remembered is a constant copied out of a file, and
this repo has been bitten by those all week. The difference is that this one is
published as RDF in the national catalogue (data.gov.cz), so it can be asked
again rather than recalled:

    autorské-dílo                CC BY 4.0
    databáze-jako-autorské-dílo  CC BY 4.0
    databáze-chráněná-...        not protected by the database maker's right
    osobní-údaje                 contains no personal data

If any of those move, this exits non-zero and the answer is to stop serving the
source, not to edit the expectation.

    python3 ops/chmi_terms.py

Note what this does NOT prove: that the catalogue entry describes the files we
actually fetch. The link between them is the dataset title (MAX_Z composite for
the territory of Czechia) and the publisher IČO 00020699, both printed below so
a human can check the join rather than take it from me.
"""
import json
import sys
import urllib.parse
import urllib.request

SPARQL = "https://data.gov.cz/sparql"
UA = "runemap/1.0 (+https://echorune.net)"

# The MAX_Z composite distribution's terms node, reached from the dataset by
# dcat:distribution -> dct:license. Recorded rather than re-derived so that a
# catalogue reshuffle shows up as a failure here instead of silently selecting
# some other dataset's terms.
TERMS = ("https://data.gov.cz/zdroj/datové-sady/00020699/"
         "0e0772b43b70e0eaf19d03a99fb94714/distribuce/"
         "5455299e0a8b4b979a6698970801d31e/podmínky-užití")

CC_BY_4 = "https://creativecommons.org/licenses/by/4.0/"
EXPECT = {
    "autorské-dílo": CC_BY_4,
    "databáze-jako-autorské-dílo": CC_BY_4,
    "databáze-chráněná-zvláštními-právy":
        "https://data.gov.cz/podmínky-užití/"
        "není-chráněna-zvláštním-právem-pořizovatele-databáze/",
    "osobní-údaje":
        "https://data.gov.cz/podmínky-užití/neobsahuje-osobní-údaje/",
}


def ask(node, timeout=60):
    q = "SELECT ?p ?o WHERE { <%s> ?p ?o }" % node
    url = SPARQL + "?" + urllib.parse.urlencode(
        {"query": q, "format": "application/sparql-results+json"})
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    raw = urllib.request.urlopen(req, timeout=timeout).read()
    out = {}
    for b in json.loads(raw)["results"]["bindings"]:
        out[b["p"]["value"].rsplit("/", 1)[-1]] = b["o"]["value"]
    return out


def compare(got, expect=None):
    """-> (ok, lines). An empty answer is a failure, not a pass.

    A catalogue that has been moved, renamed, or taken down answers with zero
    bindings, and zero bindings satisfies every "nothing disagrees" test that
    could be written lazily here. So the count is checked first.
    """
    expect = EXPECT if expect is None else expect
    lines, ok = [], True
    if not got:
        return False, ["no bindings at all: the terms node is gone or renamed,"
                       " which is not the same as unchanged"]
    for k, want in sorted(expect.items()):
        have = got.get(k)
        if have == want:
            lines.append("ok      %s = %s" % (k, have))
        else:
            ok = False
            lines.append("CHANGED %s\n          was %s\n          now %s"
                         % (k, want, have))
    return ok, lines


def main():
    try:
        got = ask(TERMS)
    except Exception as e:
        sys.exit("could not reach the catalogue: %r" % (e,))
    ok, lines = compare(got)
    print("publisher: %s" % got.get("autor", "?"))
    for ln in lines:
        print(ln)
    print("OK" if ok else "TERMS MOVED -- stop serving CHMI until this is read")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
