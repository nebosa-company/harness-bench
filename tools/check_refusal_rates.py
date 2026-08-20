"""The refusal-rate guard fires, and does not fire on noise.

`D4`. The guard reads a round and compares it to a baseline; a guard that can
pass vacuously is worth less than no guard, and this project has already
written one -- the `D2` path matrix asserted over a predicate that was never
true, so both its tests passed on an empty set and neither noticed when
workspace confinement was disabled underneath them. This asserts the opposite
of that: each rule fires on a case built to trip it, and stays quiet on the
case built to look like it.

Run: python tools/check_refusal_rates.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from refusal_rates import FLOOR, THRESHOLD, compare  # noqa: E402

failures: list[str] = []


def check(ok: bool, why: str) -> None:
    if not ok:
        failures.append(why)


def tool(ok: int, refused: int) -> dict:
    attempts = ok + refused
    return {
        "ok": ok,
        "refused": refused,
        "attempts": attempts,
        "rate": round(refused / attempts, 4) if attempts else 0.0,
    }


def round_of(tools: dict, kinds: dict | None = None) -> dict:
    return {"tools": tools, "kinds": kinds if kinds is not None else {"rule": 1}}


BIG = FLOOR * 10

# A round against itself holds. This is the case the first version of the guard
# failed: every tool under the attempt floor counted as a movement, so the
# guard reported MOVED comparing a round to its own baseline.
same = round_of({"read": tool(BIG, 3), "fetch": tool(6, 3), "glob": tool(BIG, 0)})
moved, noted = compare(same, same)
check(moved == [], "a round does not match its own baseline: %s" % moved)
check(any("fetch" in line for line in noted), "the under-floor tool was not even noted")

# A rate that moves past the threshold on samples big enough to mean it.
#
# The baseline refuses a little already, and that is the point rather than
# decoration: the first version of this case had a baseline of zero refusals,
# so the first-refusal rule below claimed it and returned before the threshold
# was ever consulted. The movement rule had no test at all, and raising
# THRESHOLD to 1.10 in a red run left this file green. A guard's test can go
# vacuous the same way a guard can.
was = round_of({"shell": tool(int(BIG * 0.95), int(BIG * 0.05))})
now = round_of({"shell": tool(int(BIG * 0.70), int(BIG * 0.30))})
moved, _ = compare(was, now)
check(any("shell" in line for line in moved), "a 0.05 -> 0.30 swing on %d calls did not fire" % BIG)
check(
    was["tools"]["shell"]["refused"] > 0,
    "the baseline must already refuse, or the first-refusal rule shadows this case",
)

# The same swing, under the floor, is a note and not a verdict. Two calls where
# one was refused is not a 50% refusal rate.
was = round_of({"shell": tool(FLOOR - 1, 0)})
now = round_of({"shell": tool(1, 1)})
moved, noted = compare(was, now)
check(moved == [], "a swing on %d calls fired: %s" % (2, moved))
check(any("shell" in line for line in noted), "and was not noted either")

# A movement smaller than the threshold is jitter. read sits between 0.01 and
# 0.03 across four real rounds and must not fail a round for it.
was = round_of({"read": tool(BIG, 3)})
now = round_of({"read": tool(BIG, 9)})
moved, _ = compare(was, now)
check(moved == [], "jitter under the threshold fired: %s" % moved)

# The first refusal on a tool that has never been refused is the event, even
# though the movement is far under the threshold. write stood at 0 refusals in
# 1,003 calls across four rounds; one is news.
was = round_of({"write": tool(BIG, 0)})
now = round_of({"write": tool(BIG - 1, 1)})
moved, _ = compare(was, now)
check(any("write" in line for line in moved), "a first refusal did not fire")
check(
    abs(now["tools"]["write"]["rate"] - was["tools"]["write"]["rate"]) < THRESHOLD,
    "this case was supposed to be under the threshold, so it tests the other rule",
)

# But not when the round asking is too small for its own number to mean
# anything. One refusal in three calls says nothing about a tool.
was = round_of({"write": tool(BIG, 0)})
now = round_of({"write": tool(2, 1)})
moved, noted = compare(was, now)
check(moved == [], "a first refusal on 3 calls fired: %s" % moved)
check(any("write" in line for line in noted), "and was not noted either")

# A tool absent from the baseline is a tool with no refusals on record, and
# reads through the same rule rather than a separate one.
was = round_of({"read": tool(BIG, 0)})
now = round_of({"read": tool(BIG, 0), "sandbox_run": tool(1, BIG - 1)})
moved, _ = compare(was, now)
check(any("sandbox_run" in line for line in moved), "a new tool refusing almost everything did not fire")

# A refusal kind the baseline never saw. Every refusal in the recorded round is
# `rule`; a round that starts producing `missing-argument` is producing
# malformed calls, which is a different failure from a stricter rule.
was = round_of({"read": tool(BIG, 1)}, {"rule": 1})
now = round_of({"read": tool(BIG, 1)}, {"rule": 1, "missing-argument": 4})
moved, _ = compare(was, now)
check(any("missing-argument" in line for line in moved), "a new refusal kind did not fire")

# Nothing below the floor ever reaches the verdict list. This is the property
# the whole split exists for, asserted directly rather than through a case.
was = round_of({t: tool(FLOOR - 1, 0) for t in ("a", "b", "c")})
now = round_of({t: tool(0, FLOOR - 1) for t in ("a", "b", "c")})
moved, noted = compare(was, now)
check(moved == [], "an under-floor tool reached the verdict: %s" % moved)
check(len(noted) == 3, "the three under-floor tools were not all noted: %s" % noted)

if failures:
    print("FAILED")
    for line in failures:
        print("  -", line)
    raise SystemExit(1)
print("ok: the refusal-rate guard fires on movement and stays quiet on small samples")
