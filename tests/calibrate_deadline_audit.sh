#!/bin/sh
# Prove the ruler can read a known-bad value before trusting it on unknowns.
#
# The acceptance criterion for tests/test_deadline_audit.py is not "it passes".
# It is:
#
#     ede4d59^  (motion still joins on the request thread)  -> MUST FAIL
#     ede4d59   (motion left the request path)              -> MUST PASS
#
# The commit is named, not described as "the current code". Current is a moving
# target: the audit was written against a tree that had already been fixed for
# three hours without my knowing, so "run it on the unfixed code" had by then
# stopped pointing at anything.
#
# This script is also the honest record of how the ruler got here. It was green
# against ede4d59^ three times before it was right:
#   1. fixture gave echo_motion 2 frames; it returns instantly under 4, so the
#      thread finished before the join could block. No wait, no violation.
#   2. rule read "blocked past the deadline"; the join asked 3.0s with 3.0s
#      left and returned at exactly the wall.
#   3. rule read "asked for more than was left"; asking for precisely all of it
#      is not more.
# What is actually wrong with that join is that it leaves nothing for rendering
# and writing, so the rule now says that.
#
# Usage:  sh tests/calibrate_deadline_audit.sh [python]
set -eu
PY=${1:-python3}
cd "$(dirname "$0")/.."
HERE=$(pwd)
SICK=$(git rev-parse ede4d59^)
WELL=$(git rev-parse ede4d59)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
cp tests/test_deadline_audit.py "$TMP/ruler.py"
# The ruler reads the wall from scripts/wall.py rather than carrying a literal,
# so the module travels with it. Neither historical commit has that file, and
# without this the calibration failed on the FIXED commit -- the ruler crying
# wolf over its own missing import, which would have read as "the fix is bad".
cp scripts/wall.py "$TMP/wall.py"

# The era's wall, not today's. ede4d59^ is sick *relative to a 3s wall*: the
# same 3.0s motion join fits comfortably inside the 10s wall that replaced it,
# so calibrating under today's config would show the defect as fixed by a
# config change it predates. A ruler must judge a commit by the promise that
# commit was making.
ERA_WALL=${ERA_WALL:-3}

run_at() {   # commit, expected: FAIL|PASS
    W="$TMP/w$2"
    git worktree add -q --detach "$W" "$1"
    cp "$TMP/ruler.py" "$W/tests/test_deadline_audit.py"
    cp "$TMP/wall.py" "$W/scripts/wall.py"
    set +e
    ( cd "$W" && RUNEMAP_SCENE_BUDGET="$ERA_WALL" "$PY" tests/test_deadline_audit.py >"$TMP/out.$2" 2>&1 )
    rc=$?
    set -e
    git worktree remove --force "$W" >/dev/null 2>&1 || true
    echo "$rc"
}

rc_sick=$(run_at "$SICK" sick)
rc_well=$(run_at "$WELL" well)

echo "wall in force for this calibration: ${ERA_WALL}s"
echo "ede4d59^ ($SICK) -> exit $rc_sick   (must be non-zero)"
sed -n 's/^  VIOLATION/  VIOLATION/p' "$TMP/out.sick" || true
echo "ede4d59  ($WELL) -> exit $rc_well   (must be zero)"

fail=0
[ "$rc_sick" -ne 0 ] || { echo "CALIBRATION FAILED: the ruler is green on the sick commit -- it is a decoration"; fail=1; }
[ "$rc_well" -eq 0 ] || { echo "CALIBRATION FAILED: the ruler is red on the fixed commit -- it is crying wolf"; fail=1; }
[ "$fail" -eq 0 ] && echo "CALIBRATED: red on the known defect, green on its fix."
exit "$fail"
