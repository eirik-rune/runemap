#!/bin/sh
# Every promise this project makes to a stranger, checked on a clock.
#
# 2026-08-16. The install command printed in the README, in /help, on the INFERO
# hub and in three listing PRs was dead for several hours. The check that would
# have caught it did not exist; the checks that did exist had no scheduler at
# all -- skill_commands_work, sitemap_is_honest and mcp_works ran only when I
# remembered to run them, and I remember about as reliably as anyone.
#
# "A guard that fires only when I remember is not a guard" is written on my
# stone twice. Both times I wrote it about somebody else's code.
#
# Each check here answers a question a stranger would ask by acting:
#   skill_commands_work  do the commands the Skill teaches still work?
#   sitemap_is_honest    does every URL we advertise still answer?
#   mcp_works            do all six MCP branches still behave?
#
# NOT included: ops/skill_installs.py. It downloads an npm package and installs
# it, which is too heavy hourly and belongs where it already runs -- CI, after
# every merge that touches the skill, on a machine with no agents.
#
# On failure it rings the doorbell rather than only writing a log, because a red
# line in a file nobody opens is the same as no check at all. On success it
# stays quiet: a bell that rings to prove it works trains me to ignore bells.
set -u
cd "$(dirname "$0")/.." || exit 2

WAKE=${PROMISES_WAKE:-/home/cc/beings/20260730_dev/wake}
LOG=${PROMISES_LOG:-/var/log/runemap_promises.log}
PY=${PROMISES_PY:-python3}

stamp() { date -u '+%Y-%m-%dT%H:%M:%SZ'; }

failed=""
for check in skill_commands_work sitemap_is_honest mcp_works; do
    out=$("$PY" "ops/$check.py" 2>&1)
    rc=$?
    # rc 2 is "could not determine", which is not a failure of the product and
    # must not ring: reporting an unreachable checker as a broken service is how
    # an hour goes to the wrong system.
    verdict=$(printf '%s\n' "$out" | tail -1 | cut -c1-120)
    printf '%s %-22s rc=%s %s\n' "$(stamp)" "$check" "$rc" "$verdict" >> "$LOG"
    [ "$rc" = "1" ] && failed="$failed $check"
done

if [ -n "$failed" ]; then
    [ -x "$WAKE" ] && "$WAKE" --from promises \
        "对外承诺的检查红了:$failed —— 这些是陌生人照着做的命令（skill 教的 curl / sitemap 上广告的 URL / MCP 分支）。看 $LOG" \
        >/dev/null 2>&1
    exit 1
fi
exit 0
