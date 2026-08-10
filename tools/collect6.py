"""Every metric the six rounds can honestly support, in one shape.

The scores were only ever a slice of what the rounds recorded. Each result
carries oracle checks, adapter exit state, turn/rung structure and elapsed time;
each journal carries one record per call with its role, link, model, latency,
tokens and charge. This pulls all of it into `six-backends.json` so the report
can show the whole picture rather than a headline.

Nothing here is derived from a figure that was not measured. Where a round could
not measure something — process scores, per-seat charges — the field is None and
stays None, because a blank is honest and a default is not (`L-39`).
"""

from __future__ import annotations

import datetime
import json
import pathlib
import statistics
from collections import Counter

RESULTS = pathlib.Path("data_try6/results")
WORK = "d:\\harness-bench-work"

# (key, results dir, label, shape, per-MTok price by model for the imputed cost)
PRICES = {
    "opus": (0.50, 5.00, 25.00),
    "sonnet": (0.30, 3.00, 15.00),
    "deepseek-v4-pro": (0.003625, 0.435, 0.87),
    "deepseek-v4-flash": (0.0028, 0.14, 0.28),
}

BACKENDS = [
    ("mixture", "perpetum-mixture", "mixture of models",
     "opus codes, ds-pro verifies, ds-fast the rest"),
    ("claude", "perpetum-claude", "pure Claude",
     "opus codes, sonnet verifies \u2014 the control"),
    ("opus", "perpetum-opus", "claude-cli opus", "one link in every role"),
    ("flash", "perpetum-deepseek-before-fixes", "deepseek-v4-flash", "one link in every role"),
    ("pro", "perpetum-deepseek-pro", "deepseek-v4-pro", "one link in every role"),
    ("sonnet", "perpetum-sonnet", "claude-cli sonnet", "one link in every role"),
]


def journal(sandbox: str) -> list[dict]:
    jl = pathlib.Path(sandbox) / "perpetum-state" / ".harness" / "journal.jsonl"
    if not jl.is_file():
        return []
    out = []
    for line in jl.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def collect(key: str, folder: str, label: str, shape: str) -> dict:
    scores: list[float] = []
    zeros: list[str] = []
    elapsed: list[float] = []
    turns_per: list[int] = []
    calls_per: list[int] = []
    steps_per: list[int] = []
    latency: list[int] = []
    checks_pass = checks_tot = 0
    adapter_fail = 0
    stopped = Counter()
    roles = Counter()
    links = Counter()
    rungs = Counter()
    dates = Counter()
    process_measured = 0
    tok = Counter()          # cache_hit / cache_miss / output, by model
    priced_calls = 0
    verifier_steps = 0
    reviewed = 0
    not_reviewed = 0
    money_reported = 0.0

    for f in sorted((RESULTS / folder).rglob("*.json")):
        j = json.loads(f.read_text(encoding="utf-8"))
        sandbox = str(j.get("sandbox", ""))
        if not sandbox.lower().startswith(WORK):
            continue
        dates[datetime.datetime.fromtimestamp(f.stat().st_mtime).strftime("%m-%d")] += 1

        o = (j.get("oracle_result") or {}).get("outcome_score")
        s = float(o) if isinstance(o, (int, float)) else 0.0
        scores.append(s)
        if s == 0.0:
            zeros.append(j["task_id"])

        for c in (j.get("oracle_result") or {}).get("checks") or []:
            checks_tot += 1
            if c.get("ok") or c.get("passed") or c.get("pass"):
                checks_pass += 1

        elapsed.append(j.get("elapsed_sec") or 0)
        ar = j.get("adapter_result") or {}
        if not ar.get("ok"):
            adapter_fail += 1
        md = ar.get("metadata") or {}
        report = md.get("report") or {}
        t = report.get("turns") or []
        turns_per.append(len(t))
        calls_per.append(sum(x.get("calls") or 0 for x in t))
        for x in t:
            rungs[x.get("rung") or "?"] += 1
        money_reported += report.get("money_usd") or 0.0
        if report.get("stopped"):
            stopped[str(report["stopped"])[:40]] += 1

        if (j.get("scoring") or {}).get("process_score") is not None:
            process_measured += 1

        recs = journal(sandbox)
        for r in recs:
            if (r.get("summary") or "") == "independent review":
                if "not reviewed" in (r.get("detail") or ""):
                    not_reviewed += 1
                else:
                    reviewed += 1
        steps_per.append(len({r.get("step") for r in recs if r.get("step") is not None}))
        seen_verifier_steps = set()
        for r in recs:
            if "charge" not in r:
                continue
            priced_calls += 1
            mdl = r.get("model") or "?"
            tok[(mdl, "hit")] += r.get("cache_hit") or 0
            tok[(mdl, "miss")] += r.get("cache_miss") or 0
            tok[(mdl, "out")] += r.get("output_tokens") or 0
            if r.get("latency_ms"):
                latency.append(int(r["latency_ms"]))
            if r.get("role"):
                roles[r["role"]] += 1
                if r["role"] == "verifier" and r.get("step") is not None:
                    seen_verifier_steps.add(r["step"])
            if r.get("link"):
                links[r["link"]] += 1
        verifier_steps += len(seen_verifier_steps)

    n = len(scores) or 1
    hit = sum(v for (m, k), v in tok.items() if k == "hit")
    miss = sum(v for (m, k), v in tok.items() if k == "miss")
    out = sum(v for (m, k), v in tok.items() if k == "out")
    cost = 0.0
    priced_any = False
    for (mdl, k), v in tok.items():
        pr = PRICES.get(mdl)
        if not pr:
            continue
        priced_any = True
        cost += v * pr[{"hit": 0, "miss": 1, "out": 2}[k]] / 1e6

    return {
        "key": key, "label": label, "shape": shape, "folder": folder,
        "tasks": len(scores),
        # outcome
        "completion": statistics.mean(scores) * 100,
        "median": statistics.median(scores) * 100,
        "stdev": statistics.pstdev(scores) * 100,
        "perfect": sum(1 for s in scores if s == 1.0),
        "partial": sum(1 for s in scores if 0 < s < 1),
        "zeros": sum(1 for s in scores if s == 0.0),
        "zero_ids": zeros,
        "below_half": sum(1 for s in scores if s < 0.5),
        "checks_pass": checks_pass, "checks_total": checks_tot,
        # scoring integrity
        "process_measured": process_measured,
        # reliability
        "adapter_fail": adapter_fail,
        "stopped": dict(stopped.most_common(3)),
        # work
        "turns_total": sum(turns_per), "turns_per_task": sum(turns_per) / n,
        "calls_total": sum(calls_per), "calls_per_task": sum(calls_per) / n,
        "steps_per_task": sum(steps_per) / n,
        "priced_calls": priced_calls,
        "verifier_steps": verifier_steps,
        "reviewed": reviewed, "not_reviewed": not_reviewed,
        "roles": dict(roles.most_common()),
        "links": dict(links.most_common()),
        "native_pct": (rungs.get("native", 0) / sum(rungs.values()) * 100) if rungs else 0.0,
        # speed
        "hours": sum(elapsed) / 3600,
        "sec_per_task": statistics.mean(elapsed) if elapsed else 0,
        "median_sec": statistics.median(elapsed) if elapsed else 0,
        "latency_ms": statistics.median(latency) if latency else None,
        # tokens
        "tok_in": miss, "tok_cache": hit, "tok_out": out,
        "cache_pct": (hit / (hit + miss) * 100) if (hit + miss) else 0.0,
        "tok_in_per_task": miss / n, "tok_out_per_task": out / n,
        # money
        "cost": round(cost, 4) if priced_any else None,
        "money_reported": round(money_reported, 4),
        "cost_per_task": round(cost / n, 4) if priced_any else None,
        # provenance
        "dates": dict(sorted(dates.items())),
        "per_task": {},
    }


def main() -> int:
    out = []
    for b in BACKENDS:
        d = collect(*b)
        # per-task scores, for the head-to-head
        per = {}
        for f in sorted((RESULTS / b[1]).rglob("*.json")):
            j = json.loads(f.read_text(encoding="utf-8"))
            if not str(j.get("sandbox", "")).lower().startswith(WORK):
                continue
            o = (j.get("oracle_result") or {}).get("outcome_score")
            per[j["task_id"]] = float(o) if isinstance(o, (int, float)) else 0.0
        d["per_task"] = per
        out.append(d)
        print(f"{d['label']:22} {d['completion']:6.2f}%  perfect {d['perfect']:3} zeros {d['zeros']:2}  "
              f"turns/task {d['turns_per_task']:5.1f}  in {d['tok_in']/1e6:5.2f}M out {d['tok_out']/1e6:5.2f}M  "
              f"cache {d['cache_pct']:4.1f}%  {'$%.2f' % d['cost'] if d['cost'] is not None else '   n/a'}")
    pathlib.Path("tools/six-backends.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
