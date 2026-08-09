"""Read a round's journals and say what the harness did, and what it did not say.

The scoring pipeline answers *how well did it do*. This answers *what happened,
and where the record is thin* — which is the question that improves the harness
rather than ranking it. Everything here is read out of Perpetum's own journal
except where noted, because the journal is meant to be the source of truth and
the gaps are the finding.

Emits `mixture-observations.json`: per task, the links each role actually used,
the rungs parsed, the refusals, the failovers, and a list of things that
happened which the journal does not record well enough to act on.
"""

from __future__ import annotations

import json
import pathlib
import re
import sys
from collections import Counter, defaultdict

RESULTS = pathlib.Path("data_try6/results")
OUT = pathlib.Path("tools/mixture-observations.json")


def journal_of(sandbox: str) -> pathlib.Path:
    return pathlib.Path(sandbox) / "perpetum-state" / ".harness" / "journal.jsonl"


def read_records(path: pathlib.Path) -> list[dict]:
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


ROLE_LINK = re.compile(r"^(\w[\w-]*) — link ([\w-]+) · model (\S+)")


def observe(task_id: str, sandbox: str, result: dict) -> dict:
    records = read_records(journal_of(sandbox))
    text = "\n".join(json.dumps(r, ensure_ascii=False) for r in records)

    role_links: dict[str, Counter] = defaultdict(Counter)
    for r in records:
        m = ROLE_LINK.match((r.get("summary") or "").replace("·", "·"))
        if m:
            role, link, model = m.groups()
            role_links[role][f"{link}:{model}"] += 1

    report = (result.get("adapter_result", {}).get("metadata") or {}).get("report") or {}
    turns = report.get("turns") or []

    signals = {
        # Things the loop says about itself, worth counting across a round.
        "no_op_step": "changed nothing" in text,
        "gave_up_told": "L-25" in text,
        "format_repair": "could not be parsed" in text or "repair" in text,
        "injection_claim": "prompt injection" in text.lower(),
        "approval_refused": "needs an approval" in text or "needs approval" in text,
        "git_refused": "not the workspace" in text,
        "egress_refused": "egress refused" in text,
        "shell_not_a_shell": "is not one" in text,
        "unknown_flag": "unknown flag" in text,
        "m23_timeout": "M-23" in text,
        "failover": "every link failed" in text or text.count("falling through") > 0,
    }

    return {
        "task_id": task_id,
        "sandbox": sandbox,
        "score": (result.get("oracle_result") or {}).get("outcome_score"),
        "combined": (result.get("scoring") or {}).get("combined_score"),
        "elapsed_sec": result.get("elapsed_sec"),
        "journal_records": len(records),
        "role_links": {role: dict(c) for role, c in role_links.items()},
        "turns": len(turns),
        "calls": sum(t.get("calls", 0) for t in turns),
        "rungs": Counter(t.get("rung", "") for t in turns),
        "stopped": report.get("stopped", ""),
        "signals": {k: v for k, v in signals.items() if v},
    }


def main() -> int:
    harness = sys.argv[1] if len(sys.argv) > 1 else "perpetum-mixture"
    root = RESULTS / harness
    if not root.is_dir():
        print(f"no results for {harness}")
        return 1

    rows = []
    for f in sorted(root.rglob("*.json")):
        j = json.loads(f.read_text(encoding="utf-8"))
        rows.append(observe(j["task_id"], j["sandbox"], j))

    # Round-level roll-ups, which is where the shortcomings show.
    roles = defaultdict(Counter)
    for r in rows:
        for role, links in r["role_links"].items():
            for link, n in links.items():
                roles[role][link] += n

    signals = Counter()
    for r in rows:
        signals.update(r["signals"].keys())

    rungs = Counter()
    for r in rows:
        rungs.update(r["rungs"])

    silent = [r["task_id"] for r in rows if r["journal_records"] == 0]
    no_role_line = [r["task_id"] for r in rows if not r["role_links"]]

    summary = {
        "harness": harness,
        "tasks": len(rows),
        "roles_observed": {role: dict(c) for role, c in roles.items()},
        "rungs": dict(rungs),
        "signals": dict(signals),
        "tasks_with_no_journal": silent,
        "tasks_with_no_role_attribution": no_role_line,
    }

    OUT.write_text(
        json.dumps({"summary": summary, "tasks": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
