"""Collect every metric the benchmark records, for one or more harnesses.

Reads the result files a suite run leaves behind and emits a single JSON
document: one row per task, plus one aggregate per backend. `render.py` turns
that into the report; nothing here knows about HTML.

Run from the repository root:

    PYTHONPATH=src python tools/collect.py

Two things this does that a naive pass over `results/` does not:

- **It ignores results from another work root.** The api-slug directory a result
  lands in is derived from the run, so re-running a task under a different
  configuration can leave the old file in a *different* directory rather than
  overwriting it. One such leftover produced 107 files for 106 tasks, and which
  one won depended on directory order — with scores of 0.86 and 0.04.
- **It prices a run that was made before its link was priced.** Perpetum charges
  from the prices declared on the link; a run made without them reports nothing.
  The tokens are on record, so the bill is arithmetic — and the same arithmetic
  applied to a priced link reproduces its measured cost exactly, which is what
  makes the computed figure trustworthy.
"""
from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from harnessbench.config import load_app_config  # noqa: E402
from harnessbench.tasks import load_tasks  # noqa: E402

HARNESSES = [
    ("deepseek-v4-flash", "perpetum-deepseek"),
    ("deepseek-v4-pro", "perpetum-deepseek-pro"),
    ("claude-cli sonnet", "perpetum-sonnet"),
    ("claude-cli opus", "perpetum-opus"),
]

# Subprocess links have no wire, so their process scores come from a transcript
# reconstructed by `journal_to_trace.py` rather than captured by the proxy.
RECONSTRUCTED = {"perpetum-sonnet", "perpetum-opus"}

# A flat per-million rate, for a backend that bills to a subscription and so
# reports nothing. Applied to every token; the non-cached figure is carried
# alongside because cache reads dominate and are normally billed at a fraction.
FLAT_RATES = {"perpetum-sonnet": 3.0, "perpetum-opus": 5.0}

# Per-component prices for a run made before its link was priced.
COMPONENT_RATES = {
    "perpetum-deepseek-pro": {"hit": 0.003625, "miss": 0.435, "output": 0.87},
}

DOMAINS = [
    (1, 23, "Workspace, tool use & multimodal"),
    (24, 32, "Office & business communication"),
    (33, 38, "Knowledge, evidence & retrieval"),
    (39, 48, "Software engineering"),
    (49, 56, "Data, BI & finance analytics"),
    (57, 61, "Long-running autonomy"),
    (62, 67, "SRE, DevOps & release ops"),
    (68, 76, "Vertical professional workflows"),
    (77, 106, "Second pass, all domains"),
]

# Needs a model that can look at a picture. `013-image-edit` is deliberately not
# here: it was filed as a vision failure on the strength of its name, and its
# oracle is satisfied by driving PIL through the shell — which is what it did.
VISION_TASKS = {"008-image-recognize"}

APP = load_app_config()
TASKS = load_tasks(APP.tasks_dir)
WORK = str(APP.work_root.resolve()).lower()
RESULTS = APP.results_dir
RUBRIC = RESULTS.parent / "results-rubric-deepseek"
BASELINE = RESULTS.parent / "results-baseline-prefix"


def mean(xs):
    xs = [x for x in xs if isinstance(x, (int, float))]
    return (sum(xs) / len(xs)) if xs else None


def domain(tid: str) -> str:
    n = int(tid.split("-")[0])
    for lo, hi, name in DOMAINS:
        if lo <= n <= hi:
            return name
    return "?"


def load_runs(harness: str) -> dict:
    out = {}
    d = RESULTS / harness
    if not d.is_dir():
        return out
    for f in d.rglob("*.json"):
        j = json.loads(f.read_text(encoding="utf-8"))
        if not str(j.get("sandbox", "")).lower().startswith(WORK):
            continue  # a leftover from an earlier configuration
        u = j.get("usage_summary") or {}
        rep = (j["adapter_result"]["metadata"].get("report") or {})
        checks = j["oracle_result"].get("checks") or []
        failed = [c for c in checks if not c.get("pass")]
        score = j["oracle_result"].get("outcome_score")
        turns = rep.get("turns") or []

        sig = []
        jl = pathlib.Path(j["sandbox"]) / "perpetum-state" / ".harness" / "journal.jsonl"
        if jl.is_file():
            txt = jl.read_text(encoding="utf-8", errors="replace")
            if "changed nothing" in txt:
                sig.append("no-op-step")
            if "M-23" in txt:
                sig.append("m23-timeout")
            if "not the workspace" in txt:
                sig.append("git-refused")

        out[j["task_id"]] = dict(
            score=score if isinstance(score, (int, float)) else 0.0,
            el=round(j.get("elapsed_sec") or 0, 1),
            inp=int(u.get("input_tokens") or 0),
            out=int(u.get("output_tokens") or 0),
            cache=int(u.get("cache_read_tokens") or 0),
            cache_w=int(u.get("cache_write_tokens") or 0),
            tot=int(u.get("total_tokens") or 0),
            requests=int(u.get("request_count") or 0),
            usd=round(rep.get("money_usd") or 0, 6),
            rate=None,
            turns=len(turns),
            calls=sum(x.get("calls", 0) for x in turns),
            rungs=[x.get("rung", "") for x in turns],
            stopped=rep.get("stopped", ""),
            blocked=1 if "blocked" in (rep.get("stopped") or "") else 0,
            checks_total=len(checks),
            checks_pass=len(checks) - len(failed),
            checks_failed=len(failed),
            first_fail=(str(failed[0].get("label") or failed[0].get("id") or "")[:80] if failed else ""),
            first_detail=(str(failed[0].get("detail"))[:110] if failed and failed[0].get("detail") else ""),
            sig=sig,
        )
    return out


def load_rubric(harness: str) -> dict:
    """process, security, combined and the three rubric sub-scores, per task."""
    out = {}
    d = RUBRIC / harness
    if not d.is_dir():
        return out
    for f in d.glob("*.json"):
        j = json.loads(f.read_text(encoding="utf-8"))
        sc = j.get("scoring") or {}
        out[j["task_id"]] = dict(
            process=sc.get("process_score"),
            security=sc.get("security_score"),
            combined=sc.get("combined_score"),
            **((sc.get("rubric") or {}).get("scores") or {}),
        )
    return out


def price(harness: str, runs: dict) -> None:
    """Fill in cost for a backend whose own ledger reports nothing."""
    if harness in COMPONENT_RATES:
        r = COMPONENT_RATES[harness]
        for row in runs.values():
            if row["usd"]:
                continue
            row["usd"] = round(row["inp"] / 1e6 * r["miss"] + row["cache"] / 1e6 * r["hit"]
                               + row["out"] / 1e6 * r["output"], 6)
            row["usd_nocache"] = round(row["inp"] / 1e6 * r["miss"]
                                       + row["out"] / 1e6 * r["output"], 6)
            row["rate"] = "component"
    elif harness in FLAT_RATES:
        rate = FLAT_RATES[harness]
        for row in runs.values():
            row["usd"] = round(row["tot"] / 1e6 * rate, 6)
            row["usd_nocache"] = round((row["inp"] + row["out"]) / 1e6 * rate, 6)
            row["rate"] = rate
    for row in runs.values():
        row.setdefault("usd_nocache", row["usd"])


def classify(tid: str, run: dict, base):
    """Cause and verdict for the primary backend's run of this task."""
    s = run["score"]
    sig = set(run["sig"])
    moved = None if base is None else s - base
    if s == 1.0:
        return "—", "as expected", "Every oracle check passed."
    if tid in VISION_TASKS:
        return ("harness capability", "no — needs a vision model",
                "Asks what is in a picture. The image path exists, but no configured link declares "
                "vision and the model under test cannot see. Configuration, not code.")
    if "m23-timeout" in sig:
        return ("harness config", "no — link blocked",
                "The link passed its first-token deadline and was failed over, but the role names "
                "one link so the failover had nowhere to go.")
    if "no-op-step" in sig and s < 0.4:
        return ("harness mapping", "no — stopped empty",
                f"A step ended having written nothing, with no second cycle to recover it. "
                f"Failed: {run['first_fail']}.")
    if moved is not None and moved <= -0.2:
        return ("regression", "worse than before",
                f"Scored {base:.2f} on the earlier run and {s:.2f} here, with no harness fault "
                f"recorded. Run-to-run variance on this suite is large. "
                f"{run['checks_failed']} of {run['checks_total']} checks failed.")
    if s == 0.0:
        return ("model", "no",
                f"Clean finish, no harness fault; the output did not satisfy the oracle. "
                f"{run['checks_failed']} of {run['checks_total']} checks failed"
                + (f", first: {run['first_fail']}." if run["first_fail"] else "."))
    return ("model", "partial",
            f"{run['checks_failed']} of {run['checks_total']} checks failed."
            + (f" First: {run['first_fail']}" if run["first_fail"] else "")
            + (f" :: {run['first_detail']}" if run["first_detail"] else ""))


def main() -> None:
    base = {}
    if BASELINE.is_dir():
        for f in BASELINE.rglob("*.json"):
            j = json.loads(f.read_text(encoding="utf-8"))
            s = j["oracle_result"].get("outcome_score")
            base[j["task_id"]] = s if isinstance(s, (int, float)) else 0.0

    runs, rubric = {}, {}
    for _, harness in HARNESSES:
        runs[harness] = load_runs(harness)
        price(harness, runs[harness])
        rubric[harness] = load_rubric(harness)

    primary = HARNESSES[0][1]
    total = len(TASKS)

    rows = []
    for tid in sorted(TASKS):
        run = runs[primary].get(tid)
        if not run:
            continue
        cause, verdict, why = classify(tid, run, base.get(tid))
        rb = rubric[primary].get(tid, {})
        row = {
            "id": tid, "n": int(tid.split("-")[0]), "title": TASKS[tid].title,
            "domain": domain(tid), "score": run["score"], "base": base.get(tid),
            "process": rb.get("process"), "combined": rb.get("combined"),
            "el": run["el"], "tot": run["tot"], "usd": run["usd"],
            "turns": run["turns"], "calls": run["calls"],
            "checks": f"{run['checks_pass']}/{run['checks_total']}",
            "cause": cause, "verdict": verdict, "why": why,
        }
        for name, harness in HARNESSES[1:]:
            r = runs[harness].get(tid)
            key = harness.replace("perpetum-", "")
            row[key] = None if not r else r["score"]
            row[key + "_sig3"] = bool(r and r["score"] == 0.0 and r["turns"] == 3)
        rows.append(row)

    agg = []
    for name, harness in HARNESSES:
        r = runs[harness]
        if not r:
            continue
        v = list(r.values())
        n = len(v)
        rb = rubric[harness]
        sig3 = [k for k, x in r.items() if x["score"] == 0.0 and x["turns"] == 3]
        rungs = [g for x in v for g in x["rungs"]]
        agg.append({
            "name": name, "harness": harness, "n": n, "total": total,
            "partial": n < total,
            "status": f"{n}/{total} {'running' if n < total else 'finished'}",
            "correct": mean([x["score"] for x in v]),
            "process": mean([rb.get(k, {}).get("process") for k in r]),
            "combined": mean([rb.get(k, {}).get("combined") for k in r]),
            "security": mean([rb.get(k, {}).get("security") for k in r]),
            "tool_use": mean([rb.get(k, {}).get("tool_use_appropriate") for k in r]),
            "consistency": mean([rb.get(k, {}).get("consistency") for k in r]),
            "robustness": mean([rb.get(k, {}).get("robustness") for k in r]),
            "proc_n": sum(1 for k in r if isinstance(rb.get(k, {}).get("process"), (int, float))),
            "reconstructed": harness in RECONSTRUCTED,
            "perfect": sum(1 for x in v if x["score"] == 1.0),
            "zeros": sum(1 for x in v if x["score"] == 0.0),
            "zeros3": len(sig3),
            "checks_pct": sum(x["checks_pass"] for x in v) / max(sum(x["checks_total"] for x in v), 1),
            "turns": sum(x["turns"] for x in v) / n,
            "calls": sum(x["calls"] for x in v) / n,
            "requests": sum(x["requests"] for x in v) / n,
            "native_pct": (rungs.count("native") / len(rungs)) if rungs else None,
            "blocked": sum(x["blocked"] for x in v),
            "inp": sum(x["inp"] for x in v), "out": sum(x["out"] for x in v),
            "cache": sum(x["cache"] for x in v), "cache_w": sum(x["cache_w"] for x in v),
            "tok_task": sum(x["tot"] for x in v) / n,
            "time": sum(x["el"] for x in v) / n, "total_h": sum(x["el"] for x in v) / 3600,
            "usd": sum(x["usd"] for x in v),
            "usd_nocache": sum(x["usd_nocache"] for x in v),
            "usd_per": sum(x["usd"] for x in v) / n,
            "rate": v[0].get("rate"),
            "measured": v[0].get("rate") is None,
            "component": v[0].get("rate") == "component",
            "unpriced": v[0].get("rate") is None and sum(x["usd"] for x in v) == 0,
            # A single process mean flattens a distribution that is not unimodal.
            "proc_sig": mean([rb.get(k, {}).get("process") for k in sig3]),
            "proc_rest": mean([rb.get(k, {}).get("process") for k in r if k not in sig3]),
        })

    out = ROOT / "tools" / "report-data.json"
    out.write_text(json.dumps({"rows": rows, "agg": agg}, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    print(f"{len(rows)} tasks, {len(agg)} backends -> {out.relative_to(ROOT)}")
    for a in agg:
        basis = ("unpriced" if a["unpriced"] else "measured" if a["measured"]
                 else "listed rates" if a["component"] else f"${a['rate']:.0f}/M")
        print(f"  {a['name']:20} {a['status']:16} completion "
              f"{(a['correct'] or 0) * 100:6.2f}%  cost ${a['usd']:8.2f} ({basis})")


if __name__ == "__main__":
    main()
