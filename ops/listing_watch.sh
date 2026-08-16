#!/bin/sh
# Ask the directories once a day whether they list us, and ring only for the
# answer that would change what I do.
#
# 2026-08-16. I told bob that this question "now gets asked once a day without
# me remembering to" -- and it did not. ops/listed_where.py had no scheduler of
# any kind. The sentence was false at the moment I said it, and nothing in the
# repository could have contradicted me, because **a claim made out loud has no
# code in it**. That is the third time today a check existed and its schedule
# did not; the difference here is that the gap lived in a report to a person.
#
# What rings, and what does not, is the whole design:
#
#   LISTED  <-> not listed   ring. A directory picking us up is the first
#                            external event in this whole push, and a directory
#                            dropping us is worth knowing the same day.
#   anything <-> NO-SIGNAL   log only. A search page that echoes the query can
#   anything <-> UNREACHABLE only ever shrug, and mcp.so times out on its own
#                            schedule. Ringing for those trains me to ignore the
#                            bell -- the KNMI lesson, which I learned this
#                            morning and would otherwise re-earn here.
#
# So the bell is keyed on the verdict I would act on, not on "something
# changed". Exit 0 quiet, 1 a listing changed, 2 could not ask.
set -u
cd "$(dirname "$0")/.." || exit 2

WAKE=${LISTING_WAKE:-/home/cc/beings/20260730_dev/wake}
LOG=${LISTING_LOG:-/var/log/runemap_listings.log}
PY=${LISTING_PY:-python3}
STATE=${LISTING_STATE:-/var/cache/runemap/listed_where.json}

# The verdicts before this run, so the wrapper can decide what kind of change
# happened. listed_where.py owns the file; this only reads it.
before=$("$PY" - "$STATE" <<'EOF' 2>/dev/null
import json,sys
try: d=json.load(open(sys.argv[1]))
except Exception: d={}
print(" ".join("%s=%s" % kv for kv in sorted(d.items())))
EOF
)

out=$(RUNEMAP_LISTED_STATE="$STATE" "$PY" ops/listed_where.py 2>&1)
rc=$?
printf '%s %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "rc=$rc" >> "$LOG"
printf '%s\n' "$out" >> "$LOG"

after=$("$PY" - "$STATE" <<'EOF' 2>/dev/null
import json,sys
try: d=json.load(open(sys.argv[1]))
except Exception: d={}
print(" ".join("%s=%s" % kv for kv in sorted(d.items())))
EOF
)

# Only a change in who says LISTED is worth a human's attention.
listed_before=$(printf '%s' "$before" | tr ' ' '\n' | grep '=LISTED$' | sort | tr '\n' ',')
listed_after=$(printf '%s' "$after"  | tr ' ' '\n' | grep '=LISTED$' | sort | tr '\n' ',')

if [ -n "$before" ] && [ "$listed_before" != "$listed_after" ]; then
    [ -x "$WAKE" ] && "$WAKE" --from listing \
        "目录收录变了：${listed_before:-（无）} -> ${listed_after:-（无）}。这是这轮宣传里第一类真正来自外部的事件，看 $LOG。" \
        >/dev/null 2>&1
    exit 1
fi
exit 0
