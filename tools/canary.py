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
import os
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


def preserve_existing(results_root: Path, harness: str, tasks: list[str]) -> int:
    """Copy the results a round is about to overwrite (Stage 0.3).

    The runner keys results by task id alone, so starting a round destroys the
    previous one's answers for every task it touches. That already happened
    once: twelve canary baselines were overwritten before the collision was
    noticed, and they are not recoverable.

    Snapshotting between the two halves of an A/A pair — which is what this
    script did first — protects the pair and nothing else. A round still eats
    the round before it.
    """
    into = results_root.parent / "canary" / harness / "before-this-round"
    into.mkdir(parents=True, exist_ok=True)
    kept = 0
    for path in results_root.rglob("*.json"):
        if path.name.endswith(".regraded.json"):
            continue
        if path.stem not in tasks:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if data.get("model_id") != harness:
            continue
        (into / path.name).write_bytes(path.read_bytes())
        kept += 1
    if kept:
        print(f"[preserved] {kept} result(s) this round would overwrite -> {into}", flush=True)
    return kept


def run_suite(harness: str, tasks: list[str], label: str) -> int:
    """One canary round. Returns the process exit code."""
    cmd = [
        sys.executable, "-m", "harnessbench.cli", "run-suite",
        "--harness", harness, "--mode", "live",
        "--tasks", ",".join(tasks),
    ]
    print(f"[{label}] {' '.join(cmd)}", flush=True)
    # `src` on the path: the package is not installed into this interpreter, and
    # discovering that four hours into a calibration run would be a poor way to
    # learn it.
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
    # Belt and braces over `cli.py`'s own reconfigure. The characters that
    # killed the first calibration are not exotic and are not going away: 118 of
    # them were perp's own prose in `adapter_result.stdout` (it writes `→`, em
    # dashes and non-breaking hyphens by choice) and 72 were the Chinese labels
    # this repository's own task definitions carry. Any run capturing that
    # output on a cp1252 stream is one `print` away from the same death, so the
    # child is told UTF-8 rather than trusted to work it out.
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8:replace"
    return subprocess.call(cmd, cwd=ROOT, env=env)


def snapshot(results_root: Path, since: float, into: Path) -> int:
    """Copy this run's result files somewhere the next run cannot overwrite.

    The runner writes `results/<harness>/<label>/<task>.json`, keyed by task and
    nothing else, so a second run of the same suite overwrites the first — and
    an A/A calibration whose two halves land on the same paths measures nothing
    at all. Selected by modification time rather than by name, because the label
    directory is chosen by the runner and is not ours to predict.
    """
    into.mkdir(parents=True, exist_ok=True)
    copied = 0
    for path in results_root.rglob("*.json"):
        if path.stat().st_mtime >= since:
            (into / path.name).write_bytes(path.read_bytes())
            copied += 1
    return copied


def calibrate(args, canary: dict) -> int:
    """The A/A run: same code, twice, to find out what noise looks like."""
    import time

    tasks = tasks_of(canary)
    runs = canary.get("runs_for_noise_band", 2)
    results_root = ROOT / "data_try6" / "results"
    out_root = ROOT / "data_try6" / "canary" / args.harness

    print(f"A/A calibration: {args.harness}, {len(tasks)} tasks, {runs} times.")
    print("Nothing is being compared. This measures how much the suite moves on its own.")
    print(f"snapshots: {out_root}\n")

    # Before anything runs: whatever is on disk for these tasks is about to be
    # overwritten, and once it is, it is gone (Stage 0.3).
    preserve_existing(results_root, args.harness, tasks)

    kept = []
    for n in range(runs):
        started = time.time()
        code = run_suite(args.harness, tasks, f"run {n + 1} of {runs}")

        # Snapshot before judging the exit code, never after.
        #
        # The first calibration ran all twenty tasks and then died printing its
        # summary — a Windows encoding default, with every result already
        # safely on disk. This read the exit code, called it a failed run,
        # returned, and abandoned the second half. Ninety minutes of completed
        # work thrown away because the process that produced it stumbled on the
        # way out of the door.
        into = out_root / f"run-{n + 1}"
        copied = snapshot(results_root, started, into)
        kept.append(into)
        print(f"[run {n + 1} of {runs}] {copied} result files -> {into}", flush=True)

        if code != 0:
            if copied == 0:
                print(f"run {n + 1} exited {code} and produced nothing — abandoned",
                      file=sys.stderr)
                return code
            # Work survived. Say so loudly and carry on: a partial run is still
            # a measurement, and the comparison below reports what it covered.
            print(f"  run {n + 1} exited {code}, but {copied} results were written "
                  f"and have been kept", file=sys.stderr)

    print()
    if len(kept) >= 2:
        print("Per-task spread between two runs of identical code:")
        print()
        base = scores(kept[0], tasks)
        cand = scores(kept[1], tasks)
        shared = sorted(set(base) & set(cand))
        if shared:
            moves = [abs(cand[t] - base[t]) for t in shared]
            for task in sorted(shared, key=lambda t: -abs(cand[t] - base[t])):
                move = cand[task] - base[task]
                if abs(move) > 1e-9:
                    print(f"  {task:38s} {base[task]:.2f} -> {cand[task]:.2f}  ({move:+.2f})")
            mean_move = statistics.mean(cand[t] - base[t] for t in shared)
            print()
            print(f"  tasks compared:     {len(shared)}")
            print(f"  tasks that moved:   {sum(1 for m in moves if m > 1e-9)}")
            print(f"  largest single move:{max(moves) * 100:6.2f} points")
            print(f"  mean difference:    {mean_move * 100:+6.2f} points")
            print()
            print("  The mean difference is the number to beat. Two runs of the same")
            print("  code should average zero; whatever it actually is, is the floor")
            print("  below which a candidate's gain is indistinguishable from luck.")

    print()
    print("Write the band into")
    print(f"  {CANARY.relative_to(ROOT)}  ->  \"noise_band\"")
    print()
    print("Until it is a number, --compare will report and decide nothing, which is")
    print("the correct behaviour.")
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
