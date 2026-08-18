"""Normalise four HarnessBench rounds into one flat row per (run, task).

Pulls together what no single file holds: the result JSON's scoring, oracle and
usage blocks; the adapter's stdout, for the tool calls the model actually
emitted and the results that came back looking like failures; Perpetum's
journal, for latency, priced calls, charge and refused reviews; and the sandbox
directory name, which is the only reliable clock in the round.

Writes `tools/four-rounds.json`. `render_comparison.py` reads only that, so the
slow part -- an 80 KB adapter stdout parsed per task -- happens once.

Run from the repository root:

    python tools/collect_comparison.py && python tools/render_comparison.py

Nothing here is derived from a figure that was not measured. Where a round could
not record something the field stays None and the report prints a dash (`L-39`).
"""
import datetime, json, os, pathlib, re, sys

DOMAINS = json.loads(pathlib.Path("tools/task-domains.json").read_text(encoding="utf-8"))

BASE = pathlib.Path(r"D:\repos\harness-bench\data_try6\results")
OUT = pathlib.Path("tools/four-rounds.json")

RUNS = [
    dict(key="grok",   label="Perpetum+Grok",  rel="perpetum-grok/unknown-api",
         harness="perpetum", model="grok", link="api",        regraded=False, price=None),
    dict(key="pflash", label="Perpetum+Flash", rel="perpetum-deepseek/deepseek-v4-flash",
         harness="perpetum", model="deepseek-v4-flash", link="api", regraded=False,
         price="deepseek-v4-flash"),
    dict(key="dsh",    label="dsh+Flash",      rel="dsh-deepseek-flash/deepseek-v4-flash",
         harness="dsh", model="deepseek-v4-flash", link="api",      regraded=False,
         price="deepseek-v4-flash"),
    dict(key="opus",   label="Perpetum+Opus",  rel="perpetum-opus/opus",
         harness="perpetum", model="opus", link="claude-cli",  regraded=True, price="opus"),
]

# A tool result counts as failing when it carries one of these. Deliberately
# narrow: a shell that printed the word "error" inside a file it was asked to
# read is not a failed call, so bare "error" is not on the list.
FAIL_PAT = re.compile(
    r"traceback \(most recent call last\)"
    r"|command not found"
    r"|no such file or directory"
    r"|permission denied"
    r"|is not recognized as an internal or external command"
    r"|\b(?:syntax|name|type|value|key|index|import|attribute|module ?not ?found)error\b"
    r"|^\s*error:"
    r"|exit(?: code|status) [1-9]"
    r"|fatal:"
    r"|npm err!"
    r"|\bE\d{3}\b.*not found",
    re.I | re.M,
)


# Per-MTok prices, lifted verbatim from tools/collect6.py so the imputed cost
# here and the cost in the six-backend report mean the same thing.
# (cache-read, input, output)
PRICES = {
    "opus": (0.50, 5.00, 25.00),
    "sonnet": (0.30, 3.00, 15.00),
    "deepseek-v4-pro": (0.003625, 0.435, 0.87),
    "deepseek-v4-flash": (0.0028, 0.14, 0.28),
}


def journal(sandbox):
    """Perpetum's own call log. One record per call: role, link, latency, charge.

    dsh keeps nothing of the kind, which is why every metric derived from here
    is a dash in its column rather than a zero.
    """
    jl = pathlib.Path(str(sandbox)) / "perpetum-state" / ".harness" / "journal.jsonl"
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


def journal_stats(sandbox, price_key):
    recs = journal(sandbox)
    if not recs:
        return {}
    priced = [r for r in recs if "charge" in r]
    lat = [int(r["latency_ms"]) for r in priced if r.get("latency_ms")]
    reviewed = not_reviewed = 0
    for r in recs:
        sm = (r.get("summary") or "")
        if sm == "review refused":
            not_reviewed += 1
        elif sm == "independent review":
            if "not reviewed" in (r.get("detail") or ""):
                not_reviewed += 1
            else:
                reviewed += 1
    vsteps = {r.get("step") for r in priced
              if r.get("role") == "verifier" and r.get("step") is not None}
    hit = sum(r.get("cache_hit") or 0 for r in priced)
    miss = sum(r.get("cache_miss") or 0 for r in priced)
    outp = sum(r.get("output_tokens") or 0 for r in priced)
    px = PRICES.get(price_key)
    imputed = (hit / 1e6 * px[0] + miss / 1e6 * px[1] + outp / 1e6 * px[2]) if px else None
    roles = {}
    for r in priced:
        if r.get("role"):
            roles[r["role"]] = roles.get(r["role"], 0) + 1
    return dict(
        j_records=len(recs), priced_calls=len(priced),
        latencies=lat,
        j_reviewed=reviewed, j_not_reviewed=not_reviewed,
        verifier_steps=len(vsteps),
        j_steps=len({r.get("step") for r in recs if r.get("step") is not None}),
        j_hit=hit, j_miss=miss, j_out=outp,
        charge=sum(r.get("charge") or 0 for r in priced),
        imputed=imputed, roles=roles,
        ok_calls=sum(1 for r in priced if r.get("ok")),
        failed_calls=sum(1 for r in priced if r.get("ok") is False),
    )


# Every sandbox is named `...-<harness>-YYYYMMDD-HHMMSS-<hash>`, stamped when
# the task started. That is a real clock, unlike the result files' mtimes, which
# lag badly over the WSL `/mnt/d` mount and are rewritten wholesale by a regrade.
SANDBOX_STAMP = re.compile(r"-(\d{8})-(\d{6})-[0-9a-f]+")


def started(sandbox):
    m = SANDBOX_STAMP.search(str(sandbox or ""))
    if not m:
        return None
    try:
        return datetime.datetime.strptime(m.group(1) + m.group(2),
                                          "%Y%m%d%H%M%S").timestamp()
    except ValueError:
        return None


def band(tid):
    n = int(tid[:3])
    if n <= 20:  return "core tools & basics"
    if n <= 40:  return "coding & repair"
    if n <= 60:  return "data & analytics"
    if n <= 80:  return "ops & domain"
    return "long-horizon & adversarial"


# Perpetum feeds a tool result back as a *user* turn, fenced like
#   <<< shell output - 9 bytes >>> ... [exit 0] <<< end output ... >>>
# so its results have to be cut out of the prose rather than read off a role.
PERP_BLOCK = re.compile(
    r"<<<\s*(\w+) output[^>]*>>>\n(.*?)(?:<<< end output|\Z)", re.S)
EXIT_NONZERO = re.compile(r"\[exit ([1-9]\d*)\]")


def tool_stats(adapter_result):
    """Tool calls emitted, and how many results came back looking like a failure.

    Two shapes. dsh returns `role: tool` messages; Perpetum inlines the result
    in the next user turn. Counting them the same way would be a fiction, so
    each is read on its own terms and the report says which was used.
    """
    so = (adapter_result or {}).get("stdout") or ""
    if not so.startswith("{"):
        return None, None, None
    try:
        o = json.loads(so)
    except Exception:
        return None, None, None
    rounds = o.get("rounds") or []
    calls = sum(len(r.get("tool_calls") or []) for r in rounds)
    if not rounds:
        return None, None, None

    msgs = o.get("unified_transcript") or []
    tool_msgs = [m for m in msgs if m.get("role") == "tool"]
    if tool_msgs:                                    # dsh
        failed = sum(1 for m in tool_msgs
                     if FAIL_PAT.search(str(m.get("content") or "")))
        return calls, len(tool_msgs), failed

    results = failed = 0                             # Perpetum
    for m in msgs:
        if m.get("role") != "user":
            continue
        for _name, body in PERP_BLOCK.findall(str(m.get("content") or "")):
            results += 1
            if EXIT_NONZERO.search(body) or FAIL_PAT.search(body):
                failed += 1
    return calls, (results or None), (failed if results else None)


def row(run, path):
    j = json.loads(path.read_text(encoding="utf-8"))
    sc = j.get("scoring") or {}
    us = j.get("usage_summary") or {}
    ora = j.get("oracle_result") or {}
    md = (j.get("adapter_result") or {}).get("metadata") or {}
    rep = md.get("report") or {}
    rub = sc.get("rubric") or {}
    subs = rub.get("scores") or {}
    checks = ora.get("checks") or []

    calls, results, failed = tool_stats(j.get("adapter_result"))
    turns = rep.get("turns") or []
    tid = path.name.split(".")[0]
    domain, title = DOMAINS.get(tid, ("unclassified", tid))
    # `rung` is how a turn reached its tools: `native` is the provider's own
    # tool-call protocol, `prompted` is a protocol described in the prompt and
    # parsed back out of prose. A claude-cli link can only do the latter.
    rungs = [t.get("rung") for t in turns if t.get("rung")]
    stopped = rep.get("stopped") or ""

    return dict(
        run=run["key"], task=tid, band=band(path.name),
        domain=domain.replace("&amp;", "&"), title=title.replace("&amp;", "&"),
        adapter_ok=bool((j.get("adapter_result") or {}).get("ok")),
        combined=sc.get("combined_score"), outcome=sc.get("outcome_score"),
        process=sc.get("process_score"), process_eff=sc.get("process_effective"),
        security=sc.get("security_score"),
        tool_use=subs.get("tool_use_appropriate"), consistency=subs.get("consistency"),
        robustness=subs.get("robustness"),
        rubric_skipped=bool(rub.get("skipped")), rubric_model=sc.get("rubric_model"),
        extract_mode=sc.get("extract_mode"),
        oracle_pass=sum(1 for c in checks if c.get("pass")), oracle_total=len(checks),
        elapsed=j.get("elapsed_sec"),
        inp=us.get("input_tokens") or 0, out=us.get("output_tokens") or 0,
        cache_read=us.get("cache_read_tokens") or 0,
        cache_write=us.get("cache_write_tokens") or 0,
        total_tokens=us.get("total_tokens") or 0,
        requests=us.get("request_count") or 0, usage_source=us.get("source"),
        tool_calls=calls, tool_results=results, tool_failed=failed,
        journal_calls=sum(t.get('calls', 0) for t in turns) or None,
        model_calls=md.get("model_calls"), records=md.get("records"),
        turns=len(turns), money=rep.get("money_usd"),
        steps=len(j.get("adapter_results") or []) or None,
        rung_native=(sum(1 for r in rungs if r == "native") / len(rungs)) if rungs else None,
        rung=(max(set(rungs), key=rungs.count) if rungs else None),
        no_gate=("NO GATE RAN" in stopped) if stopped else None,
        stopped=stopped[:120] or None,
        requirement=md.get("requirement"),
        mtime=path.stat().st_mtime,
        started=started(j.get("sandbox")),
        **journal_stats(j.get("sandbox") or "", run.get("price")),
    )


def main():
    out = {"runs": [], "rows": []}
    for run in RUNS:
        d = BASE / run["rel"]
        files = sorted(d.glob("*.json"))
        files = [p for p in files
                 if p.name.endswith(".regraded.json") == run["regraded"]]
        print(f"{run['key']}: {len(files)} files", file=sys.stderr)
        for i, p in enumerate(files):
            out["rows"].append(row(run, p))
            if i % 25 == 0:
                print(f"  {run['key']} {i}/{len(files)}", file=sys.stderr)
        out["runs"].append({k: v for k, v in run.items()})
    OUT.write_text(json.dumps(out), encoding="utf-8")
    print(f"wrote {OUT}: {len(out['rows'])} rows", file=sys.stderr)


if __name__ == "__main__":
    main()
