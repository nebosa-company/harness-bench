"""Per-tool refusal rates from a round, and a guard against them moving.

`D4` of the improvement plan. Every other item in section D is a unit test;
this one needs a round to run, because a refusal rate is a property of what
models actually asked for and no fixture reproduces that.

What it measures: for each tool, how often a call was refused rather than run.
perp journals both halves -- `Agent::note_call` writes one `ok: true` record per
successful call and `Refusal::record` writes one `ok: false` record carrying
`refusal` and `tool` -- so the rate is `refused / (ok + refused)` per tool over
every journal in a round.

Two modes:

    python tools/refusal_rates.py --round <name> --record   # write the baseline
    python tools/refusal_rates.py --round <name>            # compare, exit 1 on movement

The baseline names the perp build that produced it. A rate compared across two
different binaries is not a regression signal, and a baseline that does not say
which binary it came from cannot be argued with.

Three ways a comparison reports rather than passes:

  * **Movement** -- a rate that moved by at least `THRESHOLD` in absolute terms,
    on a tool with at least `FLOOR` attempts in both rounds.
  * **A first refusal** -- a tool refused zero times in the baseline that refuses
    at all now. `write` stands at 1 refusal in 1,003 attempts across four
    rounds; waiting for it to reach 10% before saying anything would be waiting
    for a defect to become normal.
  * **Not comparable** -- a tool below the attempt floor in either round is
    named and *not* passed. `sandbox_run` went 0/0 to 2/2 in one round: a rate
    of 1.00 on two calls is not a rate. `D5` is the argument -- the sweep that
    could not measure a thing reported no number rather than reporting zero,
    and that is the only honest option here too.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "tools" / "baseline-refusal-rates.json"

# A tool needs this many attempts in a round before its rate is a rate. Chosen
# against the four rounds on file: at 30 it admits read, glob, write, shell,
# plan, git, grep and patch -- every tool a round actually leans on -- and holds
# back fetch, apply, sandbox_run, symbols and launch, which between them swing
# 0.00 to 1.00 on denominators of 1 to 9.
FLOOR = 30

# Absolute movement that counts. read sits at 0.01-0.03 across four rounds and
# glob/plan/note/write sit at 0.00, so 0.10 clears the jitter; it is also low
# enough to have caught the two real outliers on file -- grep 0.00 -> 0.36 in
# the grok round, shell 0.00 -> 0.19 in opus-high.
THRESHOLD = 0.10


def work_root() -> Path:
    """Where rounds put their sandboxes, from the committed app config."""
    cfg = json.loads((ROOT / "config" / "app.yaml").read_text(encoding="utf-8"))
    return Path(cfg["work_root"])


def sweep(round_dir: Path) -> dict:
    """Count ok and refused calls per tool across every journal in a round.

    `os.walk` rather than `glob`: the journal lives in `.harness/`, and a
    leading dot is not matched by a wildcard. The first version of this used
    `glob(**/journal.jsonl)`, found nothing, and would have reported a round
    with 2,149 tool calls as a round with none.
    """
    ok: dict[str, int] = {}
    refused: dict[str, int] = {}
    kinds: dict[str, int] = {}
    journals = 0
    versions: set[str] = set()

    for dirpath, _dirs, names in os.walk(round_dir):
        if "journal.jsonl" not in names:
            continue
        journals += 1
        path = Path(dirpath) / "journal.jsonl"
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            detail = record.get("detail") or ""
            if detail.startswith("version="):
                versions.add(detail.splitlines()[0][len("version="):])
            tool = record.get("tool")
            if tool is None:
                continue
            if record.get("ok") is True:
                ok[tool] = ok.get(tool, 0) + 1
            elif "refusal" in record:
                refused[tool] = refused.get(tool, 0) + 1
                kind = record["refusal"]
                kinds[kind] = kinds.get(kind, 0) + 1

    tools = {}
    for tool in sorted(set(ok) | set(refused)):
        good, bad = ok.get(tool, 0), refused.get(tool, 0)
        tools[tool] = {
            "ok": good,
            "refused": bad,
            "attempts": good + bad,
            "rate": round(bad / (good + bad), 4),
        }
    return {
        "journals": journals,
        "perp_version": sorted(versions),
        "tools": tools,
        "kinds": dict(sorted(kinds.items())),
    }


def table(measured: dict) -> str:
    lines = ["tool".ljust(14) + "ok".rjust(7) + "refused".rjust(9) + "rate".rjust(8)]
    for tool, row in measured["tools"].items():
        lines.append(
            tool.ljust(14)
            + str(row["ok"]).rjust(7)
            + str(row["refused"]).rjust(9)
            + ("%.3f" % row["rate"]).rjust(8)
        )
    total_ok = sum(r["ok"] for r in measured["tools"].values())
    total_bad = sum(r["refused"] for r in measured["tools"].values())
    attempts = total_ok + total_bad
    overall = total_bad / attempts if attempts else 0.0
    lines.append(
        "ALL".ljust(14)
        + str(total_ok).rjust(7)
        + str(total_bad).rjust(9)
        + ("%.3f" % overall).rjust(8)
    )
    return "\n".join(lines)


def compare(baseline: dict, now: dict) -> tuple[list[str], list[str]]:
    """What moved, and what could not be compared.

    Two lists, because they are two different statements and only the first is
    a verdict. A round compared against its own baseline must pass, and it will
    not if every tool below the attempt floor counts as a movement -- `fetch`,
    `apply` and `sandbox_run` sit under the floor in every round on file, so
    conflating the two would leave the guard failing every time it ran.
    Everything in `noted` is printed and none of it fails.
    """
    moved: list[str] = []
    noted: list[str] = []
    old, new = baseline["tools"], now["tools"]

    for tool in sorted(set(old) | set(new)):
        # A tool absent from the baseline is a tool with no refusals on record,
        # which is what the first-refusal rule below already means.
        was = old.get(tool) or {"ok": 0, "refused": 0, "attempts": 0, "rate": 0.0}
        is_ = new.get(tool)
        if is_ is None:
            noted.append(
                "%s: %d attempts in the baseline, none this round -- nothing to compare"
                % (tool, was["attempts"])
            )
            continue

        # A tool that has never been refused is held to a stricter rule than a
        # tool that sometimes is: the first refusal is the event, at any rate.
        # The new round still has to have asked enough times for its own number
        # to mean something -- one refusal in three calls is not a rate.
        if was["refused"] == 0 and is_["refused"] > 0:
            line = "%s: first refusals -- 0/%d in the baseline, %d/%d now" % (
                tool,
                was["attempts"],
                is_["refused"],
                is_["attempts"],
            )
            (moved if is_["attempts"] >= FLOOR else noted).append(line)
            continue

        if was["attempts"] < FLOOR or is_["attempts"] < FLOOR:
            noted.append(
                "%s: not comparable -- %d then, %d now, floor is %d (rates %.2f -> %.2f)"
                % (tool, was["attempts"], is_["attempts"], FLOOR, was["rate"], is_["rate"])
            )
            continue

        delta = is_["rate"] - was["rate"]
        if abs(delta) >= THRESHOLD:
            moved.append(
                "%s: %.2f -> %.2f (%+.2f), %d/%d refused"
                % (tool, was["rate"], is_["rate"], delta, is_["refused"], is_["attempts"])
            )

    old_kinds, new_kinds = baseline.get("kinds", {}), now.get("kinds", {})
    fresh = sorted(set(new_kinds) - set(old_kinds))
    if fresh:
        moved.append("refusal kinds not seen in the baseline: " + ", ".join(fresh))
    return moved, noted


def main() -> int:
    ap = argparse.ArgumentParser(description="per-tool refusal rates for a round")
    ap.add_argument("--round", required=True, help="the round's sandbox directory name")
    ap.add_argument("--record", action="store_true", help="write this round as the baseline")
    ap.add_argument("--root", default=None, help="override the sandbox root")
    args = ap.parse_args()

    root = Path(args.root) if args.root else work_root()
    round_dir = root / args.round
    if not round_dir.is_dir():
        print("no such round: %s" % round_dir)
        return 2

    now = sweep(round_dir)
    if now["journals"] == 0:
        # Not zero refusals. No journals to read -- say so, because a round
        # whose sandbox has been cleaned looks exactly like a clean round.
        print("FAILED")
        print("  - no journals under %s; a swept-away sandbox is not a clean round" % round_dir)
        return 2

    print(
        "round: %s   journals: %d   perp: %s"
        % (args.round, now["journals"], ", ".join(now["perp_version"]) or "unrecorded")
    )
    print(table(now))

    if args.record:
        now["round"] = args.round
        BASELINE.write_text(json.dumps(now, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print("\nwrote %s" % BASELINE.relative_to(ROOT))
        return 0

    if not BASELINE.exists():
        print("\nno baseline at %s -- run once with --record" % BASELINE.relative_to(ROOT))
        return 2

    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    print(
        "\nbaseline: %s   journals: %s   perp: %s"
        % (
            baseline.get("round"),
            baseline.get("journals"),
            ", ".join(baseline.get("perp_version") or []) or "unrecorded",
        )
    )
    if sorted(baseline.get("perp_version") or []) != sorted(now["perp_version"]):
        print("  note: a different perp build -- a moved rate here may be a change, not a regression")

    moved, noted = compare(baseline, now)
    if noted:
        print("not compared")
        for line in noted:
            print("  .", line)
    if moved:
        print("MOVED")
        for line in moved:
            print("  -", line)
        return 1
    print("ok: no tool's refusal rate moved materially")
    return 0


if __name__ == "__main__":
    sys.exit(main())
