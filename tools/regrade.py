"""Grade finished results again, without re-running them.

    python tools/regrade.py --harness perpetum-mixture --since "2026-08-10 20:10"

A round's expensive half is the running. The grading is one model call per task
against a trace that is already on disk, so a run whose rubric was
misconfigured — 429 on every task, process recorded as skipped — does not have
to be thrown away and repeated. It has to be graded again.

Writes `<result>.regraded.json` beside each result rather than editing it. The
original is evidence of what the run actually produced, including its broken
grading, and overwriting it would erase the record of the failure that made
this script necessary.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from harnessbench.grading.process_grade import compute_scoring  # noqa: E402
from harnessbench.tasks import load_tasks  # noqa: E402


def results_for(harness: str, since: float) -> list[Path]:
    out = []
    for path in (ROOT / "data_try6" / "results").rglob("*.json"):
        if path.name.endswith(".regraded.json") or path.stat().st_mtime <= since:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if data.get("model_id") == harness:
            out.append(path)
    return sorted(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--harness", required=True)
    parser.add_argument("--since", required=True, help='"YYYY-MM-DD HH:MM"')
    parser.add_argument("--write", action="store_true",
                        help="write .regraded.json files; without it, only report")
    args = parser.parse_args()

    since = time.mktime(time.strptime(args.since, "%Y-%m-%d %H:%M"))
    paths = results_for(args.harness, since)
    if not paths:
        print("no results to regrade", file=sys.stderr)
        return 2

    tasks = load_tasks(ROOT / "tasks")
    print(f"regrading {len(paths)} result(s) for {args.harness}\n")
    print(f"{'task':34s} {'outcome':>8s} {'process':>8s} {'sec':>4s} {'combined':>9s}")
    print("-" * 68)

    outs, procs, combs, failed = [], [], [], []
    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        task_id = data.get("task_id", "?")
        sandbox = Path(data.get("sandbox", ""))
        if not sandbox.is_dir():
            failed.append((task_id, "sandbox is gone"))
            continue
        try:
            task = tasks[task_id]
            scoring = compute_scoring(task, sandbox, data.get("oracle_result") or {})
        except Exception as exc:
            failed.append((task_id, str(exc)[:70]))
            continue

        rubric = scoring.get("rubric") or {}
        if rubric.get("skipped"):
            failed.append((task_id, f"rubric skipped: {str(rubric.get('reason'))[:50]}"))
            continue

        o = scoring.get("outcome_score")
        p = scoring.get("process_effective", scoring.get("process_score"))
        s = scoring.get("security_score", 1.0)
        c = scoring.get("combined_score")
        if o is not None:
            outs.append(o)
        if p is not None:
            procs.append(p)
        if c is not None:
            combs.append(c)
        print(f"{task_id:34s} {o or 0:8.2f} {p or 0:8.2f} {s or 0:4.1f} {c or 0:9.2f}")

        if args.write:
            data["scoring"] = scoring
            path.with_suffix(".regraded.json").write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )

    print("-" * 68)
    if outs:
        print(f"outcome:   {statistics.mean(outs) * 100:6.2f}%  ({len(outs)} tasks)")
    if procs:
        print(f"process:   {statistics.mean(procs) * 100:6.2f}%  ({len(procs)} tasks)")
    if combs:
        print(f"COMBINED:  {statistics.mean(combs) * 100:6.2f}%  ({len(combs)} tasks)")

    # Say what was dropped, always. A mean over the tasks that happened to grade
    # is not a mean over the suite, and the difference is invisible unless
    # printed.
    if failed:
        print()
        print(f"NOT GRADED ({len(failed)}):")
        for task_id, why in failed:
            print(f"  {task_id:34s} {why}")
    if not args.write:
        print()
        print("(report only — pass --write to save .regraded.json files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
