"""Collect the five backends into one comparable shape, provenance included.

The provenance is not decoration. Three of these rounds ran against a perp
build that predates this session's fixes and two did not, and two result
directories hold runs from more than one date because tasks were re-run into
them. A table that averages over that silently would be measuring the
instrument again, which is the mistake this whole exercise keeps finding.

Writes `five-backends.json` for the renderer.
"""

from __future__ import annotations

import datetime
import json
import pathlib
import statistics
from collections import Counter

RESULTS = pathlib.Path("data_try6/results")
WORK = "d:\\harness-bench-work"

# (column key, results dir, label, what it actually is)
BACKENDS = [
    ("opus", "perpetum-opus", "claude-cli opus",
     "one link in every role"),
    ("sonnet", "perpetum-sonnet", "claude-cli sonnet",
     "one link in every role"),
    ("flash", "perpetum-deepseek-before-fixes", "deepseek-v4-flash",
     "one link in every role"),
    ("pro", "perpetum-deepseek-pro", "deepseek-v4-pro",
     "one link in every role"),
    ("mixture", "perpetum-mixture", "mixture of models",
     "opus codes, ds-pro verifies, ds-fast the rest"),
]


def journal_spend(sandbox: str) -> tuple[float, int, int]:
    """Charge, priced calls and tokens, read from the journal (`M-11`)."""
    jl = pathlib.Path(sandbox) / "perpetum-state" / ".harness" / "journal.jsonl"
    if not jl.is_file():
        return 0.0, 0, 0
    charge = 0.0
    calls = 0
    tokens = 0
    for line in jl.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("charge") is not None:
            charge += r["charge"]
            calls += 1
        tokens += (r.get("output_tokens") or 0) + (r.get("cache_miss") or 0) + (r.get("cache_hit") or 0)
    return charge, calls, tokens


def collect(key: str, folder: str, label: str, shape: str) -> dict:
    root = RESULTS / folder
    tasks: dict[str, dict] = {}
    dates = Counter()
    stale = 0

    for f in sorted(root.rglob("*.json")):
        j = json.loads(f.read_text(encoding="utf-8"))
        sandbox = str(j.get("sandbox", ""))
        if not sandbox.lower().startswith(WORK):
            stale += 1
            continue
        dates[datetime.datetime.fromtimestamp(f.stat().st_mtime).strftime("%m-%d")] += 1

        o = (j.get("oracle_result") or {}).get("outcome_score")
        s = j.get("scoring") or {}
        report = (j.get("adapter_result", {}).get("metadata") or {}).get("report") or {}
        turns = report.get("turns") or []
        charge, calls, tokens = journal_spend(sandbox)

        tasks[j["task_id"]] = {
            "score": o if isinstance(o, (int, float)) else 0.0,
            "combined": s.get("combined_score"),
            "process": s.get("process_score"),
            "elapsed": j.get("elapsed_sec") or 0,
            "turns": len(turns),
            "rungs": [t.get("rung", "") for t in turns],
            "charge": charge,
            "priced_calls": calls,
            "journal_tokens": tokens,
            "reported_usd": report.get("money_usd") or 0.0,
        }

    scores = [t["score"] for t in tasks.values()]
    rungs = Counter()
    for t in tasks.values():
        rungs.update(t["rungs"])
    native = rungs.get("native", 0)
    total_turns = sum(rungs.values())

    return {
        "key": key,
        "label": label,
        "shape": shape,
        "folder": folder,
        "tasks": len(tasks),
        "completion": statistics.mean(scores) * 100 if scores else 0.0,
        "perfect": sum(1 for s in scores if s == 1.0),
        "partial": sum(1 for s in scores if 0 < s < 1),
        "zeros": sum(1 for s in scores if s == 0.0),
        "zero_ids": sorted(k for k, v in tasks.items() if v["score"] == 0.0),
        "process_measured": sum(1 for t in tasks.values() if t["process"] is not None),
        "process_mean": (
            statistics.mean(t["process"] for t in tasks.values() if t["process"] is not None) * 100
            if any(t["process"] is not None for t in tasks.values()) else None
        ),
        "hours": sum(t["elapsed"] for t in tasks.values()) / 3600,
        "journal_usd": sum(t["charge"] for t in tasks.values()),
        "reported_usd": sum(t["reported_usd"] for t in tasks.values()),
        "priced_calls": sum(t["priced_calls"] for t in tasks.values()),
        "native_pct": (native / total_turns * 100) if total_turns else 0.0,
        "dates": dict(sorted(dates.items())),
        "stale_excluded": stale,
        "per_task": {k: v["score"] for k, v in tasks.items()},
    }


def main() -> int:
    out = [collect(*b) for b in BACKENDS]
    all_tasks = sorted({t for b in out for t in b["per_task"]})
    pathlib.Path("tools/five-backends.json").write_text(
        json.dumps({"backends": out, "tasks": all_tasks}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    for b in out:
        print(
            f"{b['label']:22} {b['tasks']:3}t  {b['completion']:6.2f}%  "
            f"perfect {b['perfect']:3} partial {b['partial']:3} zeros {b['zeros']:2}  "
            f"proc {b['process_measured']:3}  native {b['native_pct']:5.1f}%  "
            f"${b['journal_usd']:.4f}  {b['hours']:.1f}h  dates {b['dates']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
