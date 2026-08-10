"""Run the canary suite, and refuse to judge with it until it has been calibrated.

    python tools/canary.py --calibrate --harness perpetum-mixture
    python tools/canary.py --compare BASE CANDIDATE

`--calibrate` is the A/A run: the same harness twice, so the spread between two
runs of *identical* code can be measured and written into `config/canary.json`.
Until that number exists this script will not declare a winner, because it
cannot: 53 of 106 benchmark tasks moved between two runs of the same binary, and
a gate that has not measured its own noise will promote weather and revert
signal with equal confidence.

`--compare` reads two finished result directories and answers one question —
did the candidate clear the noise band — plus the one that overrides it: did it
break a control task.
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CANARY = ROOT / "config" / "canary.json"


def load_canary() -> dict:
    return json.loads(CANARY.read_text(encoding="utf-8"))


def tasks_of(canary: dict) -> list[str]:
    return [t for cl in canary["classes"].values() for t in cl["tasks"]]


def controls_of(canary: dict) -> set[str]:
    return set(canary["classes"]["control"]["tasks"])


def outcome(result: dict) -> float | None:
    oracle = result.get("oracle_result") or {}
    value = oracle.get("outcome_score", oracle.get("score"))
    return float(value) if value is not None else None


def scores(results_dir: Path, wanted: list[str]) -> dict[str, float]:
    """Per-task outcome, for the canary tasks that have a result."""
    out: dict[str, float] = {}
    for path in results_dir.rglob("*.json"):
        try:
            result = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        task = result.get("task_id")
        if task in wanted:
            value = outcome(result)
            if value is not None:
                out[task] = value
    return out


def run_suite(harness: str, tasks: list[str], label: str) -> int:
    """One canary round. Returns the process exit code."""
    cmd = [
        sys.executable, "-m", "harnessbench.cli", "run-suite",
        "--harness", harness, "--mode", "live",
        "--tasks", ",".join(tasks),
    ]
    print(f"[{label}] {' '.join(cmd)}", flush=True)
    return subprocess.call(cmd, cwd=ROOT)


def calibrate(args, canary: dict) -> int:
    """The A/A run: same code, twice, to find out what noise looks like."""
    tasks = tasks_of(canary)
    runs = canary.get("runs_for_noise_band", 2)
    print(f"A/A calibration: {args.harness}, {len(tasks)} tasks, {runs} times.")
    print("Nothing is being compared. This measures how much the suite moves on its own.\n")

    for n in range(runs):
        code = run_suite(args.harness, tasks, f"run {n + 1} of {runs}")
        if code != 0:
            print(f"run {n + 1} exited {code} — calibration abandoned", file=sys.stderr)
            return code

    print()
    print("Now read the per-task results of the two runs and write the spread into")
    print(f"  {CANARY.relative_to(ROOT)}  ->  \"noise_band\"")
    print()
    print("The band is the largest mean difference you are willing to call noise.")
    print("A candidate must beat it to be promoted. Until it is a number, --compare")
    print("will report and decide nothing, which is the correct behaviour.")
    return 0


def compare(args, canary: dict) -> int:
    band = canary.get("noise_band")
    tasks = tasks_of(canary)
    controls = controls_of(canary)

    base = scores(Path(args.compare[0]), tasks)
    cand = scores(Path(args.compare[1]), tasks)
    shared = sorted(set(base) & set(cand))

    if not shared:
        print("no tasks in common between the two result sets", file=sys.stderr)
        return 2

    # `X-18`'s rule: say what was dropped. A suite that silently covers 11 of 20
    # reads exactly like one that covered all 20.
    missing = [t for t in tasks if t not in shared]
    if missing:
        print(f"NOT COMPARED ({len(missing)} of {len(tasks)}): {', '.join(missing)}")
        print()

    base_mean = statistics.mean(base[t] for t in shared)
    cand_mean = statistics.mean(cand[t] for t in shared)
    delta = cand_mean - base_mean

    print(f"tasks compared: {len(shared)} of {len(tasks)}")
    print(f"base:      {base_mean * 100:.2f}%")
    print(f"candidate: {cand_mean * 100:.2f}%")
    print(f"delta:     {delta * 100:+.2f} points")
    print()

    regressed = sorted(t for t in shared if t in controls and cand[t] < base[t] - 1e-9)
    for task in sorted(shared, key=lambda t: cand[t] - base[t]):
        move = cand[task] - base[task]
        if abs(move) > 1e-9:
            flag = "  <- control" if task in controls else ""
            print(f"  {task:38s} {base[task]:.2f} -> {cand[task]:.2f}  ({move:+.2f}){flag}")

    print()
    if band is None:
        print("VERDICT: none. The noise band has never been measured, so this")
        print("difference cannot be told apart from two runs of identical code.")
        print("Run `python tools/canary.py --calibrate --harness <name>` first.")
        return 3

    if regressed:
        print(f"VERDICT: reject — {len(regressed)} control task(s) regressed: {', '.join(regressed)}")
        print("A candidate that gains in the target classes and loses in the controls")
        print("has moved something it was not aiming at.")
        return 1

    if delta <= band:
        print(f"VERDICT: reject — {delta * 100:+.2f} does not clear the noise band ({band * 100:+.2f}).")
        return 1

    print(f"VERDICT: promote — {delta * 100:+.2f} clears the noise band ({band * 100:+.2f}),")
    print("and no control task regressed.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--calibrate", action="store_true", help="A/A run to measure the noise band")
    parser.add_argument("--harness", help="backend name, for --calibrate")
    parser.add_argument("--compare", nargs=2, metavar=("BASE", "CANDIDATE"),
                        help="two results directories")
    parser.add_argument("--list", action="store_true", help="print the suite and why each task is in it")
    args = parser.parse_args()

    canary = load_canary()

    if args.list:
        for name, cl in canary["classes"].items():
            print(f"{name} ({len(cl['tasks'])})")
            print(f"  {cl['why']}")
            for task in cl["tasks"]:
                print(f"    {task}")
            print()
        print(f"noise band: {canary['noise_band']}")
        return 0

    if args.calibrate:
        if not args.harness:
            parser.error("--calibrate needs --harness")
        return calibrate(args, canary)

    if args.compare:
        return compare(args, canary)

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
