#!/usr/bin/env python3
"""Which countries does this fleet actually serve? Ask the code, not me.

    python3 ops/coverage_report.py

Written 2026-08-13 because I got this wrong out loud. bob asked whether the US
was wired. I listed the `radar_*.py` filenames from memory, found no
`radar_nexrad.py`, and told him no. The US has been configured and probed for
days -- `us-nexrad` simply lives inside `radar_wms.py` together with Canada,
Finland and Germany, because all four speak WMS. I had counted modules and
reported them as countries, and the fleet undercounts by three that way.

That mistake had already happened once, in `ops/source_health.py`, where a
probe labelled "wms-toronto" was answered by NEXRAD and Environment Canada
consequently had no probe at all while the table still printed 7 of 7. The
table could at least be fired at. **The second time it happened in a sentence I
said to a person, and speech has no code in it, so grepping the repo could
never have found it.** This file is the code that surface was missing.

Three rules it has to keep, all of them bought elsewhere in this repo:

* **Resolve names the way production resolves them.** The chain comes from
  `RUNEMAP_SECOND_SOURCE` and the name->module mapping from
  `render_scene.SECOND_MODULES` -- the same dict the fetcher uses. A private
  copy here would be this bug with an extra step.
* **"Serves" is not "covers".** `COVERAGE` says what a mosaic can SEE; any box
  holding all of Norway also holds Stockholm. Only an explicit `SERVES` says
  who a source was added FOR, so that is what gets counted.
* **Not knowing needs its own word.** A source that declares no `SERVES` prints
  NO-DECLARATION and makes the run fail. Dropping it silently would let the
  country list shrink without anyone noticing -- the failure mode this whole
  file exists to prevent.
"""
import os
import subprocess
import sys

_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
for _p in (os.path.join(_ROOT, "scripts"), _ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def chain_from_env():
    """-> (chain, where) or (None, why).

    Production keeps the chain in the unit's Environment, so a run that cannot
    see it must say NO-CONFIG rather than fall back to a plausible default. A
    default here would be a second opinion about production wearing
    production's clothes.
    """
    raw = os.environ.get("RUNEMAP_SECOND_SOURCE", "").strip()
    if raw:
        return raw, "environment"
    try:
        out = subprocess.run(
            ["systemctl", "show", "runemap", "-p", "Environment"],
            capture_output=True, text=True, timeout=10).stdout
    except Exception:
        return None, "systemctl unavailable"
    for tok in out.replace("Environment=", "").split():
        if tok.startswith("RUNEMAP_SECOND_SOURCE="):
            return tok.split("=", 1)[1].strip(), "systemctl show runemap"
    return None, "not set in environment and not in the unit"


def survey(chain):
    """-> [(name, module, serves_or_None, error_or_None)] in chain order."""
    import render_scene as R
    rows = []
    for name in [w.strip() for w in chain.split(",") if w.strip()]:
        modname = R.SECOND_MODULES.get(name)
        if modname is None:
            rows.append((name, None, None, "not a known source name"))
            continue
        try:
            mod = __import__(modname)
        except Exception as exc:
            rows.append((name, modname, None, "import failed: %r" % (exc,)))
            continue
        # No default that could pass for an answer: absence is the finding.
        rows.append((name, modname, getattr(mod, "SERVES", None), None))
    return rows


def main():
    chain, where = chain_from_env()
    if not chain:
        print("NO-CONFIG  no second-source chain found (%s)" % where)
        print("           This is not 'no sources'. It is 'I could not ask'.")
        return 2
    print("chain from %s:\n  %s\n" % (where, chain))
    rows = survey(chain)
    print("%-12s %-16s %s" % ("chain name", "module", "serves"))
    print("%-12s %-16s %s" % ("-" * 12, "-" * 16, "-" * 30))
    countries, bad = set(), 0
    for name, modname, serves, err in rows:
        if err:
            print("%-12s %-16s ERROR  %s" % (name, modname or "-", err))
            bad += 1
        elif serves is None:
            print("%-12s %-16s NO-DECLARATION  (covers() is not an answer)"
                  % (name, modname))
            bad += 1
        else:
            countries.update(serves)
            print("%-12s %-16s %s" % (name, modname, ", ".join(sorted(serves))))
    print("\n%d %s served by a national source: %s"
          % (len(countries), "country" if len(countries) == 1 else "countries",
             " ".join(sorted(countries))))
    print("%d sources in the chain, in %d modules -- the two numbers differ on "
          "purpose." % (len(rows), len({r[1] for r in rows if r[1]})))
    if bad:
        print("\n%d source(s) could not state what they serve. The count above "
              "is a floor, not a total." % bad)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
