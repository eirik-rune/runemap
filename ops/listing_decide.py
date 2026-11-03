#!/usr/bin/env python3
"""Did the listed set change, or did I merely stop being able to tell?

2026-11-03. listing_watch.sh has said since the day it was written that a move
into NO-SIGNAL or UNREACHABLE is logged and never rung -- "ringing for those
trains me to ignore the bell, the KNMI lesson". That promise was never
implemented: the bell compared the set of directories whose verdict was
`LISTED`, so a directory sliding from LISTED into ANY can't-tell verdict simply
left that set and was read as a delisting.

Measured over the whole log before changing anything (987 lines since 08-16):
12 rings, and 11 of them are six drop/return pairs exactly one day apart --
09-28/29 glama-score, 10-01/02 mcpservers.org, 10-17/18 glama-search,
10-18/19 glama-connector, 10-22/23 glama-search, 11-01/02 glama-score and
glama-search. The probe's own words for two of the drops:

    glama-search NO-SIGNAL    0 hits vs 3 echoed -- the page echoes the
                              query, so this ruler cannot tell absent
                              from listed
    glama-search NO-CONTROL   ours=38, control HTTP 503

The second one found us thirty-eight times and rang as a delisting, because
its positive control returned 503. So eleven of twelve rings were my own
blindness, each one a full inference on bob's account, and one of them (10-02)
became a bell that claimed in writing to be "the first truly external event in
this whole push".

So the rule, which is the header's rule and not a new policy:

  DECIDED verdicts answer the question          LISTED, ABSENT
  everything else means "I cannot tell"         NO-SIGNAL, BLIND, NO-CONTROL,
                                                UNREACHABLE, and anything a
                                                future probe adds

Ring only when a directory was decided BOTH times and its listedness changed.
A move with a can't-tell verdict on either side is logged, named, and silent --
including the hopeful direction (can't-tell -> LISTED), because that is exactly
the shape of 10-02: I cannot distinguish "they added us" from "yesterday I was
blind".

An unrecognised verdict counts as can't-tell, but is named loudly: a word I
have never seen must not be able to buy silence quietly.
"""
import sys

DECIDED = ("LISTED", "ABSENT")
#: Named so an unknown word can be told apart from these. Not used to decide
#: anything -- DECIDED does that -- but a verdict outside both lists is new,
#: and the caller says so out loud.
KNOWN_UNDECIDED = ("NO-SIGNAL", "BLIND", "NO-CONTROL", "UNREACHABLE")


def parse(s):
    """'a=LISTED b=BLIND' -> {'a': 'LISTED', 'b': 'BLIND'}"""
    out = {}
    for tok in (s or "").split():
        if "=" in tok:
            k, v = tok.split("=", 1)
            if k:
                out[k] = v
    return out


def decide(before, after):
    """-> (ring, held, unknown)

    ring    [(name, was, now)] decided both times, listedness differs
    held    [(name, was, now)] a can't-tell verdict on one side or the other
    unknown sorted verdict words in neither list
    """
    ring, held, unknown = [], [], set()
    for name in sorted(set(before) | set(after)):
        was, now = before.get(name), after.get(name)
        for v in (was, now):
            if v is not None and v not in DECIDED and v not in KNOWN_UNDECIDED:
                unknown.add(v)
        if was is None or now is None:
            # A directory entering or leaving the question is not a listing
            # change: the first run of a newly added probe would otherwise ring
            # on every machine, which the first-run guard already refuses.
            held.append((name, was or "(absent from the list)",
                         now or "(no longer asked)"))
        elif was in DECIDED and now in DECIDED:
            if (was == "LISTED") != (now == "LISTED"):
                ring.append((name, was, now))
        elif was != now:
            held.append((name, was, now))
    return ring, held, sorted(unknown)


def main(argv):
    ring, held, unknown = decide(parse(argv[1] if len(argv) > 1 else ""),
                                 parse(argv[2] if len(argv) > 2 else ""))
    for name, was, now in ring:
        print("RING %s %s -> %s" % (name, was, now))
    for name, was, now in held:
        print("HELD %s %s -> %s  (a verdict I cannot act on, so this is "
              "logged and not rung)" % (name, was, now))
    for v in unknown:
        print("UNKNOWN-VERDICT %s -- not in DECIDED and not in the known "
              "can't-tell list. Treated as can't-tell; say so rather than "
              "letting a new word buy silence." % v)
    return 1 if ring else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

# Residual hole, measured by replaying the whole log through this module
# (79 runs with verdicts): the old criterion rang 12 times, this one rings 3.
# The nine it silences are the blindness pairs. The three it keeps are
# 09-08 glama-score ABSENT->LISTED, a real listing, and the 10-01/10-02
# mcpservers.org pair -- which were FALSE and this module does not catch them,
# because that probe reported a decided word: fetch() squashed a TimeoutError
# into None and printed ABSENT while blind. PR #237 fixed that at the source.
# So the honest statement is: this guard removes the can't-tell class, and has
# no defence against a probe that lies with a decided verdict. The only defence
# there is the probe's own positive control -- which is exactly what NO-CONTROL
# is, and exactly why it must not ring.
