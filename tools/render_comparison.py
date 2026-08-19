"""Build docs/build/comparisson.html from `tools/four-rounds.json`.

Five rounds side by side. Every number here is read off a result file; where a
round could not measure something the cell is a dash, never a default.
"""
import json, math, os, pathlib, statistics, html, datetime, sys, collections

OUT = pathlib.Path(r"D:\repos\perpetum.io\docs\build\comparisson.html")
D = json.loads(pathlib.Path("tools/four-rounds.json").read_text(encoding="utf-8"))

# Same per-MTok table as tools/collect6.py: (cache-read, input, output).
# Applied to proxy token counts it reproduces Perpetum+Flash's journalled charge
# to within 0.2%, which is what licenses using it on dsh -- the one round that
# keeps no journal to charge against.
PRICES = {"opus": (0.50, 5.00, 25.00), "deepseek-v4-flash": (0.0028, 0.14, 0.28),
          # Same rates as `opus`, keyed by the full name a Claude Code
          # transcript records. Imputed: the round ran on a seat.
          "claude-opus-5": (0.50, 5.00, 25.00)}
PRICE_OF = {"grok": None, "pflash": "deepseek-v4-flash",
            "dsh": "deepseek-v4-flash", "opus": "opus",
            "cc": "claude-opus-5",
            # The shadow run priced like the column it is a delta against, or a
            # cost delta would compare a priced round to an unpriced one.
            "pflash_old": "deepseek-v4-flash"}

RUNS = [
    dict(key="grok",   label="Perpetum+Grok",  harness="perpetum", model="grok (xAI)",
         link="api", note="Perpetum 0.4.0 driving Grok over the metered API."),
    dict(key="pflash", label="Perpetum+Flash", harness="perpetum", model="deepseek-v4-flash",
         link="api", note="Perpetum 0.4.0 driving DeepSeek Flash at high effort, reviewed by "
              "DeepSeek v4 Pro. The coder is the same model as the next column; the "
              "verifier is not, and it is the first round here where review actually ran "
              "&mdash; every earlier round had `V-5` refuse it as self-review."),
    dict(key="dsh",    label="dsh+Flash",      harness="dsh", model="deepseek-v4-flash",
         link="api", note="DeepSeek's own harness on the same model, and now with the same thinking "
              "settings too &mdash; the column to its left sends the identical "
              "<span class=\"mono\">reasoning_effort:high</span> pairing, so what is left "
              "between them is the harness."),
    dict(key="opus",   label="Perpetum+Opus",  harness="perpetum", model="opus (claude-cli)",
         link="claude-cli", note="Perpetum driving Opus through the Claude Code CLI on subscription. Regraded pass."),
    dict(key="cc",     label="Claude Code+Opus 5", harness="claude-code", model="claude-opus-5",
         link="cli", note="Claude Code as a <em>harness</em>, not as a model endpoint &mdash; its own "
              "loop, its own tools, its own context management, at "
              "<span class=\"mono\">--effort high</span>. The column to its left reaches the same "
              "model through the same CLI but strips the agent out "
              "(<span class=\"mono\">--tools \"\"</span>, harness system prompt), so the two Opus "
              "columns measure different things: Perpetum's loop driving a bare model, and Claude "
              "Code driving itself."),
]
# Identity, with where each value came from:
#   harness_ver  -- `perp --version` for the surviving binary; git describe in
#                   D:/repos/deepseek-harness for dsh. The Opus round ran
#                   D:/repos/justcode/perp.exe, which no longer exists on disk,
#                   so its version is genuinely unrecoverable.
#   wire_model   -- the `model` field of the request body the usage proxy
#                   captured, not the config's label for it.
#   thinking     -- the thinking/reasoning params on that same request body,
#                   sampled across every completion call the round made.
IDENTITY = {
    "grok": dict(
        harness="Perpetum", harness_ver="perp 0.4.0",
        model_cfg="grok-4.6", wire_model="grok-4.6",
        thinking="none sent", effort="not set",
        wire_note="{model, stream, tool_choice}<span class=\"sub\">every one of 1,113 calls</span>",
        link="grok<span class=\"sub\">OpenAI-shaped, metered</span>", ran="2026-08-17"),
    "pflash": dict(
        harness="Perpetum", harness_ver="perp 0.4.0",
        model_cfg="deepseek-v4-flash", wire_model="deepseek-v4-flash",
        thinking="enabled", effort="high",
        wire_note="{model, reasoning_effort, thinking, tools, tool_choice, stream}"
                  "<span class=\"sub\">1,276 of 1,386 captured bodies; the other 110 are the "
                  "ds-pro verifier, which declares no effort</span>",
        link="deepseek<span class=\"sub\">metered</span>", ran="2026-08-19"),
    "dsh": dict(
        harness="DeepSeek Harness", harness_ver="dsh-v0.1.0-rc.7",
        model_cfg="deepseek-v4-flash", wire_model="deepseek-v4-flash",
        thinking="enabled", effort="high",
        wire_note="+ thinking:{type:enabled}<br>+ reasoning_effort:high<br>+ max_tokens:256000",
        link="deepseek<span class=\"sub\">metered</span>", ran="2026-08-17"),
    "opus": dict(
        harness="Perpetum", harness_ver="unknown<span class=\"sub\">binary gone</span>",
        model_cfg="opus", wire_model="not observable",
        thinking="not observable", effort="medium<span class=\"sub\">declared</span>",
        wire_note="&mdash;<span class=\"sub\">a claude-cli link is a subprocess; no request body is captured</span>",
        link="claude-cli<span class=\"sub\">subscription</span>", ran="2026-08-08"),
    "cc": dict(
        harness="Claude Code", harness_ver="2.1.234",
        model_cfg="claude-opus-5", wire_model="claude-opus-5",
        thinking="enabled", effort="high<span class=\"sub\">--effort high</span>",
        wire_note="&mdash;<span class=\"sub\">not proxyable: it authenticates a subscription, so it "
                  "is a subprocess rather than an address. Tokens here are read from the "
                  "transcript Claude Code writes itself &mdash; 1,897 priced requests &mdash; "
                  "which carries the tool results the wire never would</span>",
        link="generic_cli<span class=\"sub\">subscription seat</span>", ran="2026-08-19"),
}

KEYS = [r["key"] for r in RUNS]
TOTAL_TASKS = 106

# A column that reports how far it moved, and the run it moved from. The prior
# run is loaded and summarised exactly like a rendered one but stays out of
# KEYS, so best/worst marking, the shared-task set and the frontier all still
# see every rendered round.
#
# Deltas are paired: the prior run's summary is computed over only the tasks
# *both* rounds scored. Without that, a sum like total tokens would diff 101
# tasks against 106 and read as an efficiency gain that is really five missing
# rows.
DELTA_OF = {"pflash": "pflash_old"}


def _window(k):
    """(day, hours) spanned by a round's result files, for provenance prose.

    Written because the paragraph this feeds was hardcoded -- "105 of its 106
    tasks ran on 16 Aug within a 4.1-hour window" -- and survived the column
    being repointed at a different round, describing a round the report no
    longer showed.
    """
    import datetime
    ts = sorted(r["mtime"] for r in rows[k].values() if r.get("mtime"))
    if not ts:
        return "&mdash;", None
    lo, hi = datetime.datetime.fromtimestamp(ts[0]), datetime.datetime.fromtimestamp(ts[-1])
    day = lo.strftime("%-d %b") if os.name != "nt" else lo.strftime("%d %b").lstrip("0")
    return day, (ts[-1] - ts[0]) / 3600.0
SHADOW = [v for v in DELTA_OF.values()]

rows = {k: {} for k in KEYS + SHADOW}
for r in D["rows"]:
    if r["run"] in rows:
        rows[r["run"]][r["task"]] = r

ALL_TASKS = sorted({t for k in KEYS for t in rows[k]}, key=lambda t: int(t[:3]))
COMMON = [t for t in ALL_TASKS
          if all(isinstance((rows[k].get(t) or {}).get("combined"), (int, float)) for k in KEYS)]

# A round still in flight has not "dropped" the tasks it has not reached yet.
# The frontier separates the two, so an unfinished round is not charged for
# work it was never given the chance to do.
FRONTIER = {k: (max(int(t[:3]) for t in rows[k]) if rows[k] else 0) for k in KEYS + SHADOW}
DROPPED = {k: [t for t in ALL_TASKS
               if t not in rows[k] and int(t[:3]) <= FRONTIER[k]] for k in KEYS + SHADOW}
PENDING = {k: [t for t in ALL_TASKS
               if t not in rows[k] and int(t[:3]) > FRONTIER[k]] for k in KEYS + SHADOW}


# ---------------------------------------------------------------- helpers
def vals(k, field, tasks=None):
    # A shadow run answers over its paired task set unless asked otherwise, so
    # every mean derived from it is like-for-like with the column it is a delta
    # against. Patched here rather than at each call site: the summary block
    # below calls this a dozen times and one missed call would silently mix
    # denominators.
    if tasks is None:
        tasks = SHADOW_TASKS.get(k) or rows[k].keys()
    return [rows[k][t][field] for t in tasks
            if t in rows[k] and isinstance(rows[k][t].get(field), (int, float))]


def mean(xs):
    xs = [x for x in xs if isinstance(x, (int, float))]
    return sum(xs) / len(xs) if xs else None


def pct(x, d=2):
    return "&mdash;" if x is None else f"{x * 100:.{d}f}%"


def num(x, d=0):
    return "&mdash;" if x is None else f"{x:,.{d}f}"


def tok(x):
    if x is None or x == 0:
        return "&mdash;"
    return f"{x / 1e6:.2f}M" if x >= 1e6 else f"{x / 1e3:.0f}K"


# The bar a task is expected to clear. Stated here rather than assumed, because
# every capability figure below is only meaningful relative to it.
LSL = 0.70


def sigma_level(dpmo):
    """Defects per million to a sigma level, on the usual 1.5-shift convention.

    Bisected against the normal CDF rather than pulled from scipy, which is not
    a dependency of this repo for one inverse.
    """
    if not dpmo or dpmo <= 0 or dpmo >= 1e6:
        return None
    p = dpmo / 1e6
    lo, hi = -6.0, 6.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if 1 - 0.5 * (1 + math.erf(mid / math.sqrt(2))) > p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2 + 1.5


def pctl(xs, q):
    if not xs:
        return None
    xs = sorted(xs)
    return xs[min(int(q * len(xs)), len(xs) - 1)]


def cls(v, lo=0.3, mid=0.7, hi=0.9):
    if v is None:      return ""
    if v >= 0.999:     return "pass"
    if v >= hi:        return "high"
    if v >= mid:       return "mid"
    if v > lo:         return "low"
    return "fail"


# ---------------------------------------------------------------- per-run rollup
S = {}
# The paired task set per delta column: the tasks *both* rounds scored. The
# shadow run is summarised over this rather than over its own full round --
# otherwise a sum like total tokens diffs 101 tasks against 106 and reads as an
# efficiency gain that is really five missing rows.
PAIRED = {new: sorted(t for t in rows[new]
                      if isinstance((rows[new].get(t) or {}).get('combined'), (int, float))
                      and isinstance((rows[prev].get(t) or {}).get('combined'), (int, float)))
          for new, prev in DELTA_OF.items()}
SHADOW_TASKS = {prev: PAIRED[new] for new, prev in DELTA_OF.items()}

for k in KEYS + SHADOW:
    only = SHADOW_TASKS.get(k)
    rs = [r for t, r in rows[k].items() if only is None or t in only]
    comb = vals(k, "combined")
    el = vals(k, "elapsed")
    proc = vals(k, "process")
    inp = sum(r["inp"] for r in rs)
    cr = sum(r["cache_read"] for r in rs)
    cw_all = sum(r["cache_write"] for r in rs)
    out_t = sum(r["out"] for r in rs)
    tot = sum(r["total_tokens"] for r in rs)
    tcalls = sum(r["tool_calls"] or 0 for r in rs) or None
    tres = sum(r["tool_results"] or 0 for r in rs) or None
    tfail = sum(r["tool_failed"] or 0 for r in rs) if tres else None
    jcalls = sum(r["journal_calls"] or 0 for r in rs) or None
    money = sum(r["money"] or 0 for r in rs)
    S[k] = dict(
        files=len(rs), scored=len(comb),
        combined=mean(comb), median=statistics.median(comb) if comb else None,
        stdev=statistics.pstdev(comb) if len(comb) > 1 else None,
        outcome=mean(vals(k, "outcome")),
        outcome_median=(statistics.median(vals(k, "outcome")) if vals(k, "outcome") else None),
        outcome_sd=(statistics.pstdev(vals(k, "outcome")) if len(vals(k, "outcome")) > 1 else None),
        process=mean(proc),
        process_sd=statistics.pstdev(proc) if len(proc) > 1 else None,
        security=mean(vals(k, "security")),
        tool_use=mean(vals(k, "tool_use")), consistency=mean(vals(k, "consistency")),
        robustness=mean(vals(k, "robustness")),
        b_full=sum(1 for c in comb if c >= 0.999),
        b_high=sum(1 for c in comb if 0.7 <= c < 0.999),
        b_mid=sum(1 for c in comb if 0.3 <= c < 0.7),
        b_low=sum(1 for c in comb if 0 < c < 0.3),
        b_zero=sum(1 for c in comb if c == 0),
        ge90=sum(1 for c in comb if c >= 0.9), lt50=sum(1 for c in comb if c < 0.5),
        dropped=len(DROPPED[k]), pending=TOTAL_TASKS - len(rs) - len(DROPPED[k]),
        adapter_fail=sum(1 for r in rs if not r["adapter_ok"]),
        rubric_skipped=sum(1 for r in rs if r["rubric_skipped"]),
        oracle_pass=sum(r["oracle_pass"] for r in rs),
        oracle_total=sum(r["oracle_total"] for r in rs),
        elapsed_total=sum(el) / 60 if el else None,
        sec_mean=mean(el), sec_median=statistics.median(el) if el else None,
        inp=inp, cache_read=cr, out=out_t, total=tot,
        # Cache writes belong in the denominator or the rate is not a rate.
        # Only Claude Code reports them (the others come back 0, so this leaves
        # them bit-identical), and it also reports `input_tokens` as *only* the
        # uncached remainder -- 3,792 tokens across a 78M-token round. Dividing
        # by cache reads plus that remainder alone scored it 100.0%, marked it
        # best in class, and measured its token accounting rather than its
        # cache behaviour.
        cache_hit=(cr / (cr + inp + cw_all)) if (cr + inp + cw_all) else None,
        inp_task=inp / len(rs) if rs else None, out_task=out_t / len(rs) if rs else None,
        requests=sum(r["requests"] for r in rs) or None,
        tool_calls=tcalls, tool_results=tres, tool_failed=tfail,
        fail_rate=(tfail / tres) if tres else None,
        journal_calls=jcalls,
        turns=sum(r["turns"] for r in rs) or None,
        model_calls=sum(r["model_calls"] or 0 for r in rs) or None,
        money=money if money > 0 else None,
        partial=sum(1 for c in comb if 0 < c < 0.999),
        process_measured=sum(1 for r in rs if isinstance(r["process"], (int, float))),
        judged=sum(1 for r in rs if not r["rubric_skipped"] and isinstance(r["tool_use"], (int, float))),
        steps=sum(r["steps"] or 0 for r in rs) or None,
        no_gate=(sum(1 for r in rs if r["no_gate"]) if any(r["no_gate"] is not None for r in rs) else None),
        gate_ran=(sum(1 for r in rs if r["no_gate"] is False) if any(r["no_gate"] is not None for r in rs) else None),
        rung=(max({r["rung"] for r in rs if r["rung"]}, key=lambda x: sum(1 for r in rs if r["rung"] == x))
              if any(r["rung"] for r in rs) else None),
        rung_native=mean([r["rung_native"] for r in rs if r["rung_native"] is not None]) or None,
        cache_write=sum(r["cache_write"] for r in rs) or None,
        priced_calls=sum(r.get("priced_calls") or 0 for r in rs) or None,
        latency=(statistics.median([x for r in rs for x in (r.get("latencies") or [])])
                 if any(r.get("latencies") for r in rs) else None),
        latency_mean=(mean([x for r in rs for x in (r.get("latencies") or [])])
                      if any(r.get("latencies") for r in rs) else None),
        j_records=sum(r.get("j_records") or 0 for r in rs) or None,
        reviewed=(sum(r.get("j_reviewed") or 0 for r in rs)
                  if any(r.get("j_records") for r in rs) else None),
        refused=(sum(r.get("j_not_reviewed") or 0 for r in rs)
                 if any(r.get("j_records") for r in rs) else None),
        verifier_steps=(sum(r.get("verifier_steps") or 0 for r in rs)
                        if any(r.get("j_records") for r in rs) else None),
        imputed=(sum(r.get("imputed") or 0 for r in rs)
                 if any(r.get("imputed") for r in rs) else None),
    )
    S[k]["calls_task"] = (tcalls / len(rs)) if tcalls else None
    S[k]["turns_task"] = (S[k]["turns"] / len(rs)) if S[k]["turns"] else None
    S[k]["tok_point"] = (tot / (S[k]["combined"] * S[k]["scored"])) if tot and S[k]["combined"] else None
    S[k]["steps_task"] = (S[k]["steps"] / len(rs)) if S[k]["steps"] else None
    S[k]["tok_task"] = (tot / len(rs)) if tot else None
    S[k]["money_task"] = (money / len(rs)) if money > 0 else None
    S[k]["money_point"] = (money / (S[k]["combined"] * S[k]["scored"])) if money > 0 else None
    S[k]["oracle_rate"] = (S[k]["oracle_pass"] / S[k]["oracle_total"]) if S[k]["oracle_total"] else None
    S[k]["no_gate_rate"] = (S[k]["no_gate"] / len(rs)) if S[k]["no_gate"] is not None else None
    S[k]["latency_s"] = (S[k]["latency"] / 1000) if S[k]["latency"] else None
    S[k]["latency_mean_s"] = (S[k]["latency_mean"] / 1000) if S[k]["latency_mean"] else None
    S[k]["calls_per_task_j"] = (S[k]["priced_calls"] / len(rs)) if S[k]["priced_calls"] else None
    S[k]["imputed_task"] = (S[k]["imputed"] / len(rs)) if S[k]["imputed"] else None
    S[k]["imputed_point"] = (S[k]["imputed"] / (S[k]["combined"] * S[k]["scored"])) if S[k]["imputed"] else None
    S[k]["elapsed_hours"] = (S[k]["elapsed_total"] / 60) if S[k]["elapsed_total"] else None
    st = sorted(r["started"] for r in rs if r.get("started"))
    if st:
        # The last task's own runtime falls outside first->last, so add it back.
        tail = next((r["elapsed"] or 0 for r in rs if r.get("started") == st[-1]), 0)
        S[k]["wall_h"] = (st[-1] - st[0] + tail) / 3600
        S[k]["began"] = datetime.datetime.fromtimestamp(st[0])
        S[k]["ended"] = datetime.datetime.fromtimestamp(st[-1] + tail)
        S[k]["days"] = len({datetime.datetime.fromtimestamp(x).date() for x in st})
        gaps = [(st[i + 1] - st[i]) / 3600 for i in range(len(st) - 1)]
        S[k]["maxgap"] = max(gaps) if gaps else None
        S[k]["busy"] = (S[k]["elapsed_hours"] / S[k]["wall_h"]) if S[k]["wall_h"] else None
    else:
        S[k].update(wall_h=None, began=None, ended=None, days=None, maxgap=None, busy=None)
    px = PRICES.get(PRICE_OF[k])
    S[k]["proxy_cost"] = ((cr / 1e6 * px[0] + inp / 1e6 * px[1] + out_t / 1e6 * px[2])
                          if px and tot else None)
    S[k]["proxy_cost_task"] = (S[k]["proxy_cost"] / len(rs)) if S[k]["proxy_cost"] else None
    S[k]["proxy_cost_point"] = (S[k]["proxy_cost"] / (S[k]["combined"] * S[k]["scored"])
                                if S[k]["proxy_cost"] else None)
    # The six-backend report divides by completion, not by the combined score.
    # Kept as a separate row rather than swapped in: they answer different
    # questions and the denominators are not interchangeable.
    S[k]["cost_completion_pt"] = (S[k]["proxy_cost"] / (S[k]["outcome"] * S[k]["scored"])
                                  if S[k]["proxy_cost"] and S[k]["outcome"] else None)

    # ---- Lean and Six Sigma, on the definitions stated in the section itself.
    # An oracle check is one pass/fail opportunity, which is the closest thing
    # this suite has to a unit of conformance.
    opp = S[k]["oracle_total"]
    defects = opp - S[k]["oracle_pass"]
    S[k]["opportunities"] = opp or None
    S[k]["defects"] = defects if opp else None
    S[k]["dpmo"] = (defects / opp * 1e6) if opp else None
    S[k]["sigma"] = sigma_level(S[k]["dpmo"])

    # Rolled throughput: the odds a task clears every gate without rework.
    n = len(rs) or 1
    S[k]["y_adapter"] = sum(1 for r in rs if r["adapter_ok"]) / n
    S[k]["y_oracle"] = sum(1 for r in rs if isinstance(r["outcome"], (int, float))
                           and r["outcome"] >= 0.999) / n
    S[k]["y_rubric"] = sum(1 for r in rs if isinstance(r["process"], (int, float))
                           and r["process"] >= 0.999) / n
    S[k]["y_security"] = sum(1 for r in rs if r["security"] == 1.0) / n
    S[k]["rty"] = (S[k]["y_adapter"] * S[k]["y_oracle"]
                   * S[k]["y_rubric"] * S[k]["y_security"])

    S[k]["cpk"] = ((S[k]["combined"] - LSL) / (3 * S[k]["stdev"])
                   if S[k]["stdev"] else None)

    # Process cycle efficiency: time the model spent thinking, over lead time.
    # A figure over 100% would mean calls overlapped and the sum is not a
    # duration -- report nothing rather than a number that cannot be true.
    lat = [x for r in rs for x in (r.get("latencies") or [])]
    S[k]["model_min"] = (sum(lat) / 1000 / 60) if lat else None
    S[k]["pce"] = ((S[k]["model_min"] / S[k]["elapsed_total"])
                   if S[k]["model_min"] and S[k]["elapsed_total"] else None)
    if S[k]["pce"] and S[k]["pce"] > 1:
        S[k]["pce"] = None
    S[k]["harness_min"] = ((S[k]["elapsed_total"] - S[k]["model_min"])
                           if S[k]["model_min"] else None)

    S[k]["p75"] = pctl(el, .75)
    S[k]["p90"] = pctl(el, .90)
    S[k]["p95"] = pctl(el, .95)
    S[k]["pmax"] = max(el) if el else None

    # Individuals / moving-range: is the round in statistical control, or is
    # some of its variation special-cause and worth naming task by task?
    seq = [rows[k][t]["combined"] for t in sorted(rows[k])
           if isinstance(rows[k][t]["combined"], (int, float))]
    ids = [t for t in sorted(rows[k])
           if isinstance(rows[k][t]["combined"], (int, float))]
    mr = [abs(seq[i + 1] - seq[i]) for i in range(len(seq) - 1)]
    mrbar = statistics.fmean(mr) if mr else 0
    S[k]["mrbar"] = mrbar or None
    S[k]["ucl"] = min(S[k]["combined"] + 2.66 * mrbar, 1.0)
    S[k]["lcl"] = max(S[k]["combined"] - 2.66 * mrbar, 0.0)
    ooc = [(ids[i], v) for i, v in enumerate(seq)
           if v > S[k]["combined"] + 2.66 * mrbar or v < S[k]["combined"] - 2.66 * mrbar]
    S[k]["ooc"] = len(ooc)
    S[k]["ooc_tasks"] = ooc

# common-set means
C = {k: dict(combined=mean(vals(k, "combined", COMMON)),
             outcome=mean(vals(k, "outcome", COMMON)),
             process=mean(vals(k, "process", COMMON)),
             tool_use=mean(vals(k, "tool_use", COMMON)),
             consistency=mean(vals(k, "consistency", COMMON)),
             robustness=mean(vals(k, "robustness", COMMON)),
             sec=mean(vals(k, "elapsed", COMMON))) for k in KEYS}

wins = {k: 0 for k in KEYS}
ties = 0
for t in COMMON:
    v = {k: rows[k][t]["combined"] for k in KEYS}
    best = max(v.values())
    top = [k for k in KEYS if v[k] >= best - 1e-9]
    if len(top) == 1:
        wins[top[0]] += 1
    else:
        ties += 1

DOMAIN_ORDER = ["Workspace, tool use & multimodal", "Office & business communication",
                "Knowledge, evidence & retrieval", "Software engineering",
                "Data, BI & finance analytics", "Long-running autonomy",
                "SRE, DevOps & release ops", "Vertical professional workflows",
                "Second pass, all domains"]


def domain_of(t):
    return next((rows[k][t]["domain"] for k in KEYS if t in rows[k]), "unclassified")


def title_of(t):
    return next((rows[k][t]["title"] for k in KEYS if t in rows[k]), t)


# ---------------------------------------------------------------- metric table
def mark(key, values, higher_better=True):
    """Green best, red worst, across the cells of one row.

    `higher_better=None` means the row has no better or worse and is left
    unmarked. Two rows pass it deliberately -- "not yet run", whose own hint
    says *not a failure*, and "oracle checks passed", a raw count whose
    denominator moves with how many tasks a round reached. Before this, `None`
    was merely falsy, so both were marked as though *fewer was better*: the
    round that had run the fewest tasks was coloured green for it.
    """
    if higher_better is None:
        return ""
    got = [(k, v) for k, v in values.items() if v is not None]
    if len(got) < 2:
        return ""
    best = max(g[1] for g in got) if higher_better else min(g[1] for g in got)
    worst = min(g[1] for g in got) if higher_better else max(g[1] for g in got)
    v = values.get(key)
    if v is None:            return ""
    if v == best == worst:   return ""
    if v == best:            return " best"
    if v == worst:           return " worst"
    return ""


def delta(k, field, fmt, value, src=None, higher=True):
    """`fmt(value)` and, for a delta column, how far it moved.

    The signed part is formatted with the same `fmt` as the value, so a
    percentage row reads `68.65% (+2.71%)` and a token row `2.15M (+0.07M)` --
    a delta in different units from the number beside it is a delta nobody can
    check. `higher` only colours it: on a row where lower is better, a negative
    move is the good one.

    Silent when there is nothing to compare. A column with no prior run, or a
    field the prior run could not measure, shows the bare value rather than a
    `(+0)` that would claim the two were equal.
    """
    prev_key = DELTA_OF.get(k)
    if prev_key is None or value is None:
        return fmt(value)
    prev = (src or S).get(prev_key, {}).get(field)
    if not isinstance(prev, (int, float)) or not isinstance(value, (int, float)):
        return fmt(value)
    d = value - prev
    if d == 0:
        return f'{fmt(value)}<span class="dlt flat">(&plusmn;0)</span>'
    sign = "+" if d > 0 else "&minus;"
    body = fmt(abs(d)).lstrip("+")
    # A row formatted `x / N` is a count against a fixed denominator, and the
    # delta is a change in x -- not a change in the ratio. Rendered with the
    # row's own formatter it came out as `(+1 / 106)`, which reads as one task
    # in a hundred and six rather than one more than last time.
    if " / " in body:
        body = body.split(" / ", 1)[0]
    # `higher is None` is a row with no better or worse -- the same rows `mark`
    # leaves unmarked. Show the movement, colour it neither way: tinting a raw
    # count green would be claiming something the row explicitly disclaims.
    if higher is None:
        tone = "flat"
    else:
        tone = "up" if ((d > 0) if higher else (d < 0)) else "down"
    return f'{fmt(value)}<span class="dlt {tone}">({sign}{body})</span>'


def mrow(label, field, fmt, higher=True, strong=False, hint=None, src=None):
    src = src or S
    v = {k: src[k].get(field) for k in KEYS}
    lab = f"<strong>{label}</strong>" if strong else label
    if hint:
        lab += f'<span class="mh">{hint}</span>'
    cells = "".join(
        f'<td class="n{mark(k, v, higher)}">{delta(k, field, fmt, v[k], src, higher)}</td>'
        for k in KEYS
    )
    return f"<tr><td class='ml'>{lab}</td>{cells}</tr>"


def grp(title):
    return f'<tr class="grp"><td colspan="{len(KEYS) + 1}">{title}</td></tr>'


def irow(label, field, hint=None, mono=False):
    lab = label + (f'<span class="mh">{hint}</span>' if hint else "")
    cells = "".join(f'<td class="id">{IDENTITY[k][field]}</td>' for k in KEYS)
    return f"<tr><td class='ml'>{lab}</td>{cells}</tr>"


metric_rows = [
    grp("&#127991;&#65039; Identity"),
    irow("harness", "harness"),
    irow("harness version", "harness_ver",
         hint="the Opus round ran a binary from a repo path that no longer exists"),
    irow("model, as configured", "model_cfg"),
    irow("model full name, on the wire", "wire_model",
         hint="the model string the proxy captured, not the config's label"),
    irow("thinking mode", "thinking",
         hint="whether the round asked the model to think, as sent on the wire"),
    irow("reasoning effort", "effort"),
    irow("request parameters", "wire_note"),
    irow("link", "link"),
    irow("round date", "ran"),

    grp("&#128203; Coverage"),
    mrow("tasks scored", "scored", lambda v: f"{v} / {TOTAL_TASKS}", True,
         hint="a task that produced no result file shrinks the denominator instead of scoring zero"),
    mrow("tasks dropped", "dropped", lambda v: num(v), False,
         hint="finished without writing a result file, below the round's own frontier"),
    mrow("not yet run", "pending", lambda v: num(v) if v else "&mdash;", None,
         hint="beyond the frontier of a round still in flight; not a failure"),
    mrow("adapter failures", "adapter_fail", lambda v: num(v), False),
    mrow("rubric skipped", "rubric_skipped", lambda v: num(v), False,
         hint="a skipped rubric defaults process to 1.0 and flatters the round"),
    mrow("process measured", "process_measured", lambda v: f"{v} / {TOTAL_TASKS}", True,
         hint="tasks where the rubric returned a real process score rather than a default"),
    mrow("runs judged", "judged", lambda v: f"{v} / {TOTAL_TASKS}", True,
         hint="tasks the rubric returned usable sub-scores for"),

    grp("&#127919; Outcome"),
    mrow("combined score (mean)", "combined", lambda v: pct(v), True, strong=True,
         hint="mean of completion &times; process &times; security &mdash; the headline"),
    mrow("&middot; median task", "median", lambda v: pct(v), True,
         hint="the middle task, not the average one &mdash; a long tail moves the mean and not this"),
    mrow("&middot; spread (&sigma;)", "stdev", lambda v: pct(v), False,
         hint="lower is steadier across the suite"),
    mrow("completion (mean)", "outcome", lambda v: pct(v), True, strong=True,
         hint="the oracle's programmatic checks alone &mdash; `outcome`, before process and security "
              "are multiplied in. The six-backend report calls this completion."),
    mrow("&middot; median task score", "outcome_median", lambda v: pct(v), True),
    mrow("&middot; spread (&sigma;)", "outcome_sd", lambda v: pct(v), False),
    mrow("security", "security", lambda v: pct(v)),
    mrow("oracle checks passed", "oracle_pass", lambda v: num(v), None,
         hint="raw count; the denominator moves with how many tasks a round reached"),
    mrow("oracle pass rate", "oracle_rate", lambda v: pct(v, 1), True, strong=True,
         hint="checks passed as a share of checks attempted &mdash; denominator-safe"),

    grp("&#128202; Distribution"),
    mrow("scored 1.0", "b_full", lambda v: num(v), True, hint="perfect"),
    mrow("scored 0.7 &ndash; 1.0", "b_high", lambda v: num(v)),
    mrow("scored 0.3 &ndash; 0.7", "b_mid", lambda v: num(v), False),
    mrow("scored 0 &ndash; 0.3", "b_low", lambda v: num(v), False),
    mrow("scored 0", "b_zero", lambda v: num(v), False, strong=True,
         hint="zeros &mdash; combined is a <em>product</em>, so a zero in any one factor "
              "zeroes the row however well the other two went; the roll-call is under the table"),
    mrow("partial", "partial", lambda v: num(v), None,
         hint="scored above zero but short of perfect &mdash; the middle four buckets above, summed"),
    mrow("at or above 0.9", "ge90", lambda v: num(v)),
    mrow("below 0.5", "lt50", lambda v: num(v), False),

    grp("&#9881;&#65039; Process"),
    mrow("process score", "process", lambda v: pct(v), True, strong=True,
         hint="the rubric's verdict on how the run was conducted"),
    mrow("&middot; tool use", "tool_use", lambda v: pct(v), True,
         hint="rubric sub-score: were the right tools used"),
    mrow("&middot; consistency", "consistency", lambda v: pct(v), True,
         hint="rubric sub-score: did the run hold together"),
    mrow("&middot; robustness", "robustness", lambda v: pct(v), True,
         hint="rubric sub-score: how it handled what went wrong"),
    mrow("process stability (&sigma;)", "process_sd", lambda v: pct(v), False,
         hint="task-to-task variation in process; lower is steadier"),
    mrow("tool-use rung", "rung", lambda v: v or "&mdash;", None,
         hint="native = the provider's own tool-call protocol; prompted = a protocol described in the prompt and parsed back out of prose"),
    mrow("native rung", "rung_native", lambda v: pct(v, 0), True,
         hint="a claude-cli link cannot do native tool calls, which is where Opus's tool-use score goes"),

    grp("&#128269; Review"),
    mrow("steps genuinely reviewed", "reviewed", lambda v: num(v), True, strong=True,
         hint="a verifier on a different link actually looked at the work"),
    mrow("review logged, then refused", "refused", lambda v: num(v), False,
         hint="Perpetum declines to let a model review its own work on the same context (V-5)"),
    mrow("steps with a verifier call", "verifier_steps", lambda v: num(v), True,
         hint="distinct steps where a priced call carried role=verifier &mdash; every priced call in "
              "all three journals is role=coder, so there are none"),
    mrow("steps closed with no gate at all", "no_gate", lambda v: num(v), False,
         hint="closed on file-resident claims without the gate running (L-64)"),
    mrow("&middot; as a share", "no_gate_rate", lambda v: pct(v, 0), False),

    grp("&#128296; Work done"),
    mrow("tool calls (proxy trace)", "tool_calls", lambda v: num(v), None,
         hint="what the model actually emitted; no trace exists for a claude-cli link"),
    mrow("tool calls (journal)", "journal_calls", lambda v: num(v), None,
         hint="Perpetum's own count; dsh keeps no journal the bench can read"),
    mrow("tool calls / task", "calls_task", lambda v: num(v, 1), None),
    mrow("failing tool results", "tool_failed", lambda v: num(v), False),
    mrow("&middot; as a share", "fail_rate", lambda v: pct(v, 1), False, strong=True,
         hint="heuristic &mdash; see the note below the table"),
    mrow("coder turns", "turns", lambda v: num(v), None),
    mrow("turns / task", "turns_task", lambda v: num(v, 1), None),
    mrow("model calls", "model_calls", lambda v: num(v), None),
    mrow("steps", "steps", lambda v: num(v), None,
         hint="a step is one closed unit of work in the harness's own accounting"),
    mrow("steps / task", "steps_task", lambda v: num(v, 2), None),
    mrow("LLM requests (proxy)", "requests", lambda v: num(v), None),
    mrow("priced model calls", "priced_calls", lambda v: num(v), None, strong=True,
         hint="journal records carrying a charge &mdash; the bench's own definition (collect6)"),
    mrow("priced calls / task", "calls_per_task_j", lambda v: num(v, 1), None),
    mrow("journal records", "j_records", lambda v: num(v), None),

    grp("&#9201;&#65039; Speed"),
    mrow("total execution", "elapsed_total", lambda v: "&mdash;" if v is None else f"{v:,.0f} min", False,
         strong=True,
         hint="agent time summed over tasks. The six-backend report prints this same sum and labels "
              "it wall clock; it is not one, and the real figure is the row below."),
    mrow("&middot; in hours", "elapsed_hours", lambda v: "&mdash;" if v is None else f"{v:,.1f} h", False),
    mrow("wall clock", "wall_h", lambda v: "&mdash;" if v is None else f"{v:,.1f} h", False,
         hint="first task started to last task finished, read off the sandbox names &mdash; a real "
              "clock, unlike the summed agent time above"),
    mrow("&middot; machine busy", "busy", lambda v: "&mdash;" if v is None else f"{v * 100:,.0f}%", True,
         hint="agent time as a share of wall clock; below 100% is idle between tasks, above is "
              "impossible and would mean tasks overlapped"),
    mrow("&middot; longest pause", "maxgap", lambda v: "&mdash;" if v is None else
         (f"{v * 60:,.0f} min" if v < 1.5 else f"{v:,.1f} h"), False,
         hint="the biggest gap between two consecutive task starts. A round that crossed midnight "
              "unbroken and one resumed a week later both span two dates; only this separates them."),
    mrow("mean task", "sec_mean", lambda v: "&mdash;" if v is None else f"{v:,.0f}s", False),
    mrow("median task", "sec_median", lambda v: "&mdash;" if v is None else f"{v:,.0f}s", False, strong=True),
    mrow("median call latency", "latency_s", lambda v: "&mdash;" if v is None else f"{v:,.2f}s", False, strong=True,
         hint="median latency_ms over every priced call in the journal; dsh keeps no journal"),
    mrow("mean call latency", "latency_mean_s", lambda v: "&mdash;" if v is None else f"{v:,.2f}s", False),

    grp("&#129689; Tokens"),
    mrow("total tokens", "total", lambda v: tok(v), None, strong=True),
    mrow("input, excl. cache", "inp", lambda v: tok(v), False),
    mrow("served from cache", "cache_read", lambda v: tok(v), None),
    mrow("cache hit", "cache_hit", lambda v: pct(v, 1), True),
    mrow("output tokens", "out", lambda v: tok(v), False),
    mrow("input / task", "inp_task", lambda v: tok(v), False),
    mrow("output / task", "out_task", lambda v: tok(v), False),
    mrow("tokens / task", "tok_task", lambda v: tok(v), False,
         hint="input + cache + output, over the tasks the round actually ran"),
    mrow("cache write", "cache_write", lambda v: tok(v), None,
         hint="no round recorded a cache write; the dash is the state of the accounting"),
    mrow("tokens per point", "tok_point", lambda v: tok(v), False, strong=True,
         hint="total tokens &divide; (mean score &times; tasks scored) &mdash; what a point of score costs"),

    grp("&#128181; Money"),
    mrow("charged in the journal", "money", lambda v: "&mdash;" if v is None else f"${v:,.2f}", False,
         hint="what the run actually recorded being billed. A dash is deliberate: a subscription "
              "link journals no charge and a zero would be a fabrication."),
    mrow("cost / task", "money_task", lambda v: "&mdash;" if v is None else f"${v:,.4f}", False),
    mrow("cost / point of score", "money_point", lambda v: "&mdash;" if v is None else f"${v:,.4f}", False,
         hint="what a point of combined score cost, where a charge was journalled at all"),
    mrow("cost at API rates", "imputed", lambda v: "&mdash;" if v is None else f"${v:,.2f}", False, strong=True,
         hint="journal tokens priced at the same per-MTok table the six-backend report uses; a subscription round is imputed, not billed"),
    mrow("&middot; per task", "imputed_task", lambda v: "&mdash;" if v is None else f"${v:,.4f}", False),
    mrow("&middot; per point of score", "imputed_point", lambda v: "&mdash;" if v is None else f"${v:,.4f}", False),
    mrow("cost at API rates, from proxy tokens", "proxy_cost",
         lambda v: "&mdash;" if v is None else f"${v:,.2f}", False, strong=True,
         hint="the same price table over proxy usage instead of the journal &mdash; the only route that reaches dsh"),
    mrow("&middot; per task", "proxy_cost_task", lambda v: "&mdash;" if v is None else f"${v:,.4f}", False),
    mrow("&middot; per point of score", "proxy_cost_point", lambda v: "&mdash;" if v is None else f"${v:,.4f}", False),
    mrow("cost / completion point", "cost_completion_pt",
         lambda v: "&mdash;" if v is None else f"${v:,.4f}", False,
         hint="divided by completion rather than by the combined score &mdash; the six-backend "
              "report's denominator, kept alongside rather than instead of"),
]


# ---------------------------------------------------------------- task map
def strip(k):
    out = []
    for t in ALL_TASKS:
        r = rows[k].get(t)
        if r is None:
            pend = t in PENDING[k]
            klass = "pend" if pend else "miss"
            why = "not yet run" if pend else "no result file"
            out.append(f'<div class="cell {klass}" title="{t} &middot; {why}"></div>')
            continue
        c = r.get("combined")
        if not isinstance(c, (int, float)):
            out.append(f'<div class="cell miss" title="{t} &middot; unscored"></div>')
            continue
        out.append(f'<div class="cell c-{cls(c)}" title="{t} &middot; {c:.3f}"></div>')
    return "".join(out)


# ---------------------------------------------------------------- per-task table
def task_rows():
    out = []
    seen = None
    ordered = sorted(ALL_TASKS, key=lambda t: (DOMAIN_ORDER.index(domain_of(t))
                                               if domain_of(t) in DOMAIN_ORDER else 99,
                                               int(t[:3])))
    for t in ordered:
        d = domain_of(t)
        if d != seen:
            seen = d
            out.append(f'<tr class="grp"><td colspan="{2 * len(KEYS) + 2}">{d}</td></tr>')
        cells, cs = [], []
        for k in KEYS:
            r = rows[k].get(t)
            c = (r or {}).get("combined")
            cs.append(c if isinstance(c, (int, float)) else None)
            if r is None:
                lab = "not run" if t in PENDING[k] else "dropped"
                cells.append(f'<td class="n dim">{lab}</td><td class="n dim">&mdash;</td>')
            elif not isinstance(c, (int, float)):
                cells.append('<td class="n dim">unscored</td><td class="n dim">&mdash;</td>')
            else:
                oc = f"{r['oracle_pass']}/{r['oracle_total']}" if r["oracle_total"] else "&mdash;"
                cells.append(f'<td class="n {cls(c)}c">{c:.3f}</td><td class="n dim">{oc}</td>')
        got = [c for c in cs if c is not None]
        spread = (max(got) - min(got)) if len(got) > 1 else None
        sp = "&mdash;" if spread is None else f"{spread:.2f}"
        spc = " gapbig" if spread and spread >= 0.5 else ""
        out.append(
            f'<tr><td class="t"><span class="tt">{html.escape(title_of(t))}</span>'
            f'<span class="tid">{t}</span></td>{"".join(cells)}'
            f'<td class="n{spc}">{sp}</td></tr>')
    return "".join(out)


# ---------------------------------------------------------------- assemble
now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
dsh_running = S["dsh"]["files"] < TOTAL_TASKS

lead = sorted(KEYS, key=lambda k: -(C[k]["combined"] or 0))

CSS = """
:root {
  --paper:#f3f5f7; --surface:#fff; --ink:#171a21; --muted:#5c6675; --line:#dfe4ea;
  --accent:#1f5f8b; --pass:#2f6d4a; --high:#4f7f5f; --mid:#9a6a10; --low:#b1592f;
  --fail:#a83a36; --miss:#c9ced6; --sig:#8a4fbf;
  --shadow:0 1px 2px rgba(23,26,33,.06),0 8px 24px rgba(23,26,33,.05);
}
@media (prefers-color-scheme:dark) { :root:not([data-theme="light"]) {
  --paper:#0e1116; --surface:#161a21; --ink:#e3e7ee; --muted:#98a2b3; --line:#262c36;
  --accent:#6fa8cf; --pass:#5fae83; --high:#7fb094; --mid:#d4a24c; --low:#e08a5e;
  --fail:#e0706b; --miss:#39404c; --sig:#b98ae0;
  --shadow:0 1px 2px rgba(0,0,0,.4),0 8px 24px rgba(0,0,0,.3); } }
:root[data-theme="dark"] {
  --paper:#0e1116; --surface:#161a21; --ink:#e3e7ee; --muted:#98a2b3; --line:#262c36;
  --accent:#6fa8cf; --pass:#5fae83; --high:#7fb094; --mid:#d4a24c; --low:#e08a5e;
  --fail:#e0706b; --miss:#39404c; --sig:#b98ae0;
  --shadow:0 1px 2px rgba(0,0,0,.4),0 8px 24px rgba(0,0,0,.3); }
* { box-sizing:border-box; }
body { margin:0; background:var(--paper); color:var(--ink);
  font:400 15px/1.6 "Segoe UI",system-ui,-apple-system,sans-serif; }
.wrap { max-width:1320px; margin:0 auto; padding:56px 28px 96px;
  display:flex; flex-direction:column; gap:40px; }
h1 { font:600 34px/1.15 Georgia,"Palatino Linotype",serif; margin:0;
  letter-spacing:-.01em; text-wrap:balance; }
h2 { font:600 20px/1.2 Georgia,"Palatino Linotype",serif; margin:0 0 14px; }
a { color:var(--accent); }
.eyebrow { font:600 11px/1 "Segoe UI",sans-serif; letter-spacing:.14em;
  text-transform:uppercase; color:var(--accent); margin:0 0 12px; }
.lede { color:var(--muted); max-width:70ch; margin:12px 0 0; }
.mono { font-family:Consolas,ui-monospace,monospace; }
.scroll { overflow-x:auto; border:1px solid var(--line); border-radius:8px;
  background:var(--surface); box-shadow:var(--shadow); }
table { border-collapse:collapse; width:100%; }
th { position:sticky; top:0; z-index:2; background:var(--surface); text-align:left;
  font:600 10.5px/1.3 "Segoe UI",sans-serif; letter-spacing:.08em; text-transform:uppercase;
  color:var(--muted); padding:12px 10px; border-bottom:1px solid var(--line); }
th.bh { text-align:right; font:600 12.5px/1.3 "Segoe UI",sans-serif; text-transform:none;
  letter-spacing:0; color:var(--ink); white-space:nowrap; }
th.bh small { display:block; font:400 11px/1.4 "Segoe UI",sans-serif; color:var(--muted); }
td { padding:11px 10px; border-bottom:1px solid var(--line); vertical-align:top; font-size:13.5px; }
tr.grp td { background:var(--paper); font:600 11px/1 "Segoe UI",sans-serif; letter-spacing:.1em;
  text-transform:uppercase; color:var(--muted); padding:10px 12px; }
td.n { font-family:Consolas,ui-monospace,monospace; font-variant-numeric:tabular-nums;
  text-align:right; white-space:nowrap; }
td.dim { color:var(--muted); }
td.best { color:var(--pass); font-weight:700; }
td.worst { color:var(--fail); font-weight:700; }
td.ml { font-weight:600; font-size:13.5px; }
/* The metric tables carry a long label and four narrow numbers. Without an
   explicit floor the label column collapses to a word per line and every row
   grows to the height of its own hint. */
.mtbl table { min-width:940px; table-layout:fixed; }
.mtbl th:first-child, .mtbl td:first-child { width:290px; }
.mtbl th.bh, .mtbl td.n { width:auto; min-width:132px; }
.mtbl td.ml { max-width:none; }
/* Identity values are prose and paths, not figures: they wrap, where a number
   never should. */
.vsrow { display:flex; align-items:center; gap:14px; margin:9px 0; }
.vsname { width:180px; font-weight:600; font-size:13px; flex:none; }
.vsbar { flex:1; display:flex; height:26px; border-radius:4px; overflow:hidden;
  background:var(--line); font:600 11px/26px "Segoe UI",sans-serif; }
.vsmodel { background:var(--accent); color:#fff; padding-left:9px; white-space:nowrap;
  overflow:hidden; }
.vsharness { background:var(--mid); }
.vsnone { color:var(--muted); font-weight:400; line-height:26px; padding-left:9px; }
.vspct { width:62px; text-align:right; font:700 14px/1 Consolas,monospace;
  font-variant-numeric:tabular-nums; flex:none; }
.vskey { display:flex; flex-wrap:wrap; gap:18px; font-size:12.5px; color:var(--muted);
  margin-top:12px; }
.vskey i { width:11px; height:11px; border-radius:3px; display:inline-block;
  margin-right:6px; vertical-align:-1px; }
.cumbar { display:inline-block; height:3px; width:var(--w); background:var(--sig);
  border-radius:2px; margin-right:8px; vertical-align:middle; max-width:80px; }
h3.sub { font:600 15px/1.3 Georgia,"Palatino Linotype",serif; margin:30px 0 10px; }
td.why { white-space:normal; font-size:13px; color:var(--muted); line-height:1.55; }
td.why em { color:var(--ink); font-style:normal; }
td.id { font-family:Consolas,ui-monospace,monospace; font-size:12px; line-height:1.5;
  text-align:right; white-space:normal; overflow-wrap:anywhere; font-weight:600; }
td.id .sub { display:block; font:400 11px/1.45 "Segoe UI",sans-serif; color:var(--muted);
  margin-top:3px; }
.mh { display:block; font:400 11.5px/1.45 "Segoe UI",sans-serif; color:var(--muted);
  font-weight:400; margin-top:3px; }
/* How far a superseded column moved. Deliberately quieter than the value it
   annotates -- the number is the reading, the delta is context for it. */
.dlt { margin-left:5px; font:600 11px/1 ui-monospace,SFMono-Regular,Menlo,monospace;
  white-space:nowrap; letter-spacing:-.1px; }
.dlt.up   { color:var(--pass); }
.dlt.down { color:var(--low); }
.dlt.flat { color:var(--muted); font-weight:400; }
td.passc{color:var(--pass)} td.highc{color:var(--high)} td.midc{color:var(--mid)}
td.lowc{color:var(--low)} td.failc{color:var(--fail)}
td.gapbig { color:var(--sig); font-weight:700; }
td.t { min-width:210px; }
.tt { display:block; font-weight:600; font-family:Consolas,ui-monospace,monospace; font-size:12.5px; }
.tid { display:block; font:400 11px/1.5 "Segoe UI",sans-serif; color:var(--muted); }
#tasks table { min-width:1100px; }
.hero { display:grid; grid-template-columns:repeat(auto-fit,minmax(280px,1fr)); gap:1px;
  background:var(--line); border:1px solid var(--line); border-radius:10px; overflow:hidden;
  box-shadow:var(--shadow); }
.hcard { background:var(--surface); padding:18px 20px; }
.hcard .rank { font:600 10.5px/1 "Segoe UI",sans-serif; letter-spacing:.1em;
  text-transform:uppercase; color:var(--muted); }
.hcard .nm { font-weight:700; font-size:16px; margin-top:6px; }
.hcard .sc { font:700 46px/1 Consolas,ui-monospace,monospace; letter-spacing:-.03em;
  font-variant-numeric:tabular-nums; margin:8px 0 2px; color:var(--accent); }
.hcard .sc small { font-size:17px; color:var(--muted); font-weight:600; }
.hcard p { margin:8px 0 0; font-size:12.5px; color:var(--muted); line-height:1.5; }
.pill { display:inline-block; font:600 10px/1 "Segoe UI",sans-serif; letter-spacing:.07em;
  text-transform:uppercase; padding:4px 8px; border-radius:3px; border:1px solid currentColor;
  margin-top:10px; }
.p-done { color:var(--pass); } .p-run { color:var(--mid); }
.maps { display:flex; flex-direction:column; gap:18px; }
.maprow .mh2 { display:flex; align-items:baseline; gap:10px; margin-bottom:7px; }
.maprow .mn { font-weight:700; font-size:14px; }
.maprow .ms { font-size:12.5px; color:var(--muted); font-family:Consolas,monospace; }
.strip { display:flex; flex-wrap:wrap; gap:3px; }
.cell { width:13px; height:13px; border-radius:3px; background:var(--miss); }
.cell.c-pass{background:var(--pass)} .cell.c-high{background:var(--high)}
.cell.c-mid{background:var(--mid)} .cell.c-low{background:var(--low)}
.cell.c-fail{background:var(--fail)} .cell.miss{background:var(--miss);opacity:.55}
.cell.pend { background:transparent; border:1px dashed var(--miss); }
.key { display:flex; flex-wrap:wrap; gap:16px; font-size:12.5px; color:var(--muted); }
.key span { display:flex; align-items:center; gap:6px; }
.key i { width:11px; height:11px; border-radius:3px; display:inline-block; }
.note { border-left:3px solid var(--accent); padding:2px 0 2px 16px; color:var(--muted);
  font-size:13.5px; max-width:76ch; }
.note b { color:var(--ink); }
.note + .note { margin-top:14px; }
.legend { display:grid; grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); gap:1px;
  background:var(--line); border:1px solid var(--line); border-radius:8px; overflow:hidden; }
.lg { background:var(--surface); padding:16px 18px; }
.lgn { font:600 19px/1 Consolas,ui-monospace,monospace; color:var(--accent); }
.lgt { font-weight:600; font-size:14px; margin-top:4px; }
.lg p { margin:7px 0 0; font-size:12.5px; color:var(--muted); line-height:1.5; }
footer { color:var(--muted); font-size:12.5px; border-top:1px solid var(--line); padding-top:20px; }
@media (max-width:640px) { .wrap{padding:36px 16px 64px} h1{font-size:27px} }

/* ---- print / PDF -------------------------------------------------------
   Every table on this page lives in an `overflow-x:auto` box, which is right
   on screen and catastrophic on paper: the overflow is simply cut off, and a
   reader would never know a column was missing. On paper the boxes open up
   and the page turns landscape to hold them. */
@media print {
  @page { size: A3 landscape; margin: 11mm 10mm; }

  /* Paper is white whatever the screen was set to, and the colours that carry
     meaning -- the task map, the value-stream bars, the score chips -- have to
     survive the printer's instinct to drop backgrounds. */
  :root, :root[data-theme="dark"], :root:not([data-theme="light"]) {
    --paper:#fff; --surface:#fff; --ink:#171a21; --muted:#5c6675; --line:#c9ced6;
    --accent:#1f5f8b; --pass:#2f6d4a; --high:#4f7f5f; --mid:#9a6a10; --low:#b1592f;
    --fail:#a83a36; --miss:#c9ced6; --sig:#8a4fbf; --shadow:none;
  }
  * { -webkit-print-color-adjust:exact !important; print-color-adjust:exact !important; }
  body { background:#fff; font-size:9.5pt; }
  .wrap { max-width:none; padding:0; gap:22px; }

  .scroll { overflow:visible !important; box-shadow:none; border-radius:0; }
  table { width:100%; }
  #tasks table, .mtbl table { min-width:0 !important; }
  .mtbl th:first-child, .mtbl td:first-child { width:230px; }
  td, th { padding:5px 7px; font-size:8.5pt; }
  .mh { font-size:7.5pt; }

  /* A header that repeats is the difference between page four being readable
     and page four being a grid of unlabelled numbers. */
  thead { display:table-header-group; }
  tr { break-inside:avoid; }
  th { position:static !important; }

  h1 { font-size:20pt; }
  h2 { font-size:13pt; break-after:avoid; }
  h3.sub { font-size:11pt; break-after:avoid; }
  section { break-inside:auto; }
  .hero, .legend, .vsrow, .maprow, .note { break-inside:avoid; }
  .lede { max-width:none; }
  a { color:inherit; text-decoration:none; }

  /* 424 cells of task map are worth the ink; keep them from splitting a run
     across a page turn. */
  .strip { break-inside:avoid; }
  .cell { width:11px; height:11px; }
}
"""

hero = ""
for i, k in enumerate(lead):
    r = next(x for x in RUNS if x["key"] == k)
    running = (k == "dsh" and dsh_running)
    pill = (f'<span class="pill p-run">running &middot; {S[k]["files"]}/{TOTAL_TASKS}</span>'
            if running else f'<span class="pill p-done">complete &middot; {S[k]["scored"]}/{TOTAL_TASKS}</span>')
    hero += (f'<div class="hcard"><div class="rank">#{i + 1} on the shared set</div>'
             f'<div class="nm">{r["label"]}</div>'
             f'<div class="sc">{C[k]["combined"] * 100:.1f}<small> / 100</small></div>'
             f'<div class="mono" style="font-size:12px;color:var(--muted)">{r["model"]}</div>'
             f'<p>{r["note"]}</p>{pill}</div>')

maps = ""
for k in KEYS:
    r = next(x for x in RUNS if x["key"] == k)
    pend = f' &middot; {S[k]["pending"]} not yet run' if S[k]["pending"] else ""
    maps += (f'<div class="maprow"><div class="mh2"><span class="mn">{r["label"]}</span>'
             f'<span class="ms">{S[k]["scored"]} scored &middot; {S[k]["dropped"]} dropped'
             f'{pend} &middot; mean {S[k]["combined"] * 100:.1f}</span></div>'
             f'<div class="strip">{strip(k)}</div></div>')

head_cells = "".join(
    f'<th class="bh">{r["label"]}<small>{r["model"]}</small></th>' for r in RUNS)

h2h = ""
for label, field, fmt in [("combined", "combined", lambda v: pct(v)),
                          ("outcome", "outcome", lambda v: pct(v)),
                          ("process", "process", lambda v: pct(v)),
                          ("&middot; tool use", "tool_use", lambda v: pct(v)),
                          ("&middot; consistency", "consistency", lambda v: pct(v)),
                          ("&middot; robustness", "robustness", lambda v: pct(v)),
                          ("seconds / task", "sec", lambda v: f"{v:,.0f}s")]:
    v = {k: C[k][field] for k in KEYS}
    higher = field != "sec"
    h2h += (f'<tr><td class="ml">{label}</td>' +
            "".join(f'<td class="n{mark(k, v, higher)}">{fmt(v[k])}</td>' for k in KEYS) + "</tr>")
wv = {k: wins[k] for k in KEYS}
h2h += ('<tr><td class="ml"><strong>tasks won outright</strong>'
        f'<span class="mh">plus {ties} ties across all five</span></td>' +
        "".join(f'<td class="n{mark(k, wv, True)}">{wins[k]}</td>' for k in KEYS) + "</tr>")

band_rows = ""
for b in DOMAIN_ORDER:
    ts = [t for t in COMMON if domain_of(t) == b]
    if not ts:
        continue
    v = {k: mean(vals(k, "combined", ts)) for k in KEYS}
    o = {k: mean(vals(k, "outcome", ts)) for k in KEYS}
    band_rows += (f'<tr><td class="ml">{b}<span class="mh">{len(ts)} shared tasks &middot; '
                  f'outcome {min(x for x in o.values() if x is not None) * 100:.0f}&ndash;'
                  f'{max(x for x in o.values() if x is not None) * 100:.0f}%</span></td>' +
                  "".join(f'<td class="n{mark(k, v, True)}">{pct(v[k])}</td>' for k in KEYS) + "</tr>")

# Every zero, and which factor produced it. A zero reads as "nothing worked",
# and in this data that is usually false, so the report names each one.
def zero_cause(r):
    if r["security"] == 0:
        return "security gate tripped"
    if r["process"] == 0:
        got = ("outcome {:.2f}, {}/{} oracle checks passed"
               .format(r["outcome"], r["oracle_pass"], r["oracle_total"])
               if isinstance(r["outcome"], (int, float)) else "outcome not scored")
        tail = "" if r["adapter_ok"] else "; the adapter also failed"
        return f"process 0 &mdash; {got}{tail}"
    if r["outcome"] == 0:
        return f"outcome 0 &mdash; {r['oracle_pass']}/{r['oracle_total']} oracle checks passed"
    return "combined 0"


zeros = []
for k in KEYS:
    for t in sorted(rows[k]):
        r = rows[k][t]
        if isinstance(r.get("combined"), (int, float)) and r["combined"] == 0:
            zeros.append((next(x["label"] for x in RUNS if x["key"] == k), t, zero_cause(r)))

zero_html = "".join(
    f'<tr><td class="ml">{t}<span class="mh">{lbl}</span></td>'
    f'<td class="why" colspan="4">{why}</td></tr>'
    for lbl, t, why in zeros) or '<tr><td colspan="5" class="dim">no round scored a zero</td></tr>'

# Where the suite loses its points. Sorted on the total across all five rounds
# so the table is one Pareto of the benchmark, not four stacked on each other.
dom_loss = {k: collections.Counter() for k in KEYS}
for k in KEYS:
    for t, r in rows[k].items():
        if isinstance(r.get("combined"), (int, float)):
            dom_loss[k][r["domain"]] += 1 - r["combined"]
tot_loss = collections.Counter()
for k in KEYS:
    tot_loss.update(dom_loss[k])
grand = sum(tot_loss.values()) or 1
pareto_rows, cum = "", 0.0
for dom, v in tot_loss.most_common():
    cum += v
    pareto_rows += (
        f'<tr><td class="ml">{dom}</td>' +
        "".join(f'<td class="n">{dom_loss[k][dom]:.1f}</td>' for k in KEYS) +
        f'<td class="n">{v:.1f}</td><td class="n">{v / grand * 100:.1f}%</td>'
        f'<td class="n"><span class="cumbar" style="--w:{cum / grand * 100:.1f}%"></span>'
        f'{cum / grand * 100:.1f}%</td></tr>')

# The value stream, such as it is: two stages with a measured duration.
pce_bars = ""
for k in KEYS:
    r = next(x for x in RUNS if x["key"] == k)
    if not S[k]["pce"]:
        pce_bars += (f'<div class="vsrow"><div class="vsname">{r["label"]}</div>'
                     f'<div class="vsbar vsnone">no per-call latency &mdash; '
                     f'{r["harness"]} keeps no journal to time</div></div>')
        continue
    m = S[k]["pce"] * 100
    pce_bars += (
        f'<div class="vsrow"><div class="vsname">{r["label"]}</div>'
        f'<div class="vsbar"><span class="vsmodel" style="width:{m:.1f}%">'
        f'{S[k]["model_min"]:,.0f} min model</span>'
        f'<span class="vsharness" style="width:{100 - m:.1f}%"></span></div>'
        f'<div class="vspct">{m:.1f}%</div></div>')

# --- everything the statistical section interpolates
_pce = [x["pce"] for x in S.values() if x["pce"]]
pce_lo, pce_hi = min(_pce) * 100, max(_pce) * 100
inv_lo, inv_hi = 100 - pce_lo, 100 - pce_hi
_cpk = [x["cpk"] for x in S.values() if x["cpk"] is not None]
cpk_lo, cpk_hi = min(_cpk), max(_cpk)
steadiest = next(x["label"] for x in RUNS
                 if S[x["key"]]["ooc"] == min(S[k]["ooc"] for k in KEYS))

stat_rows = "".join([
    grp("&#127919; Conformance"),
    mrow("opportunities", "opportunities", lambda v: num(v), None,
         hint="oracle checks attempted &mdash; one pass/fail opportunity each"),
    mrow("defects", "defects", lambda v: num(v), False, hint="checks that did not pass"),
    mrow("DPMO", "dpmo", lambda v: num(v), False, strong=True,
         hint="defects per million opportunities"),
    mrow("sigma level", "sigma",
         lambda v: "&mdash;" if v is None else f"{v:.2f}&sigma;", True, strong=True,
         hint="on the conventional 1.5-shift long-term convention. Manufacturing calls "
              "6&sigma; the goal and 3&sigma; poor."),
    grp("&#127981; Yield"),
    mrow("&middot; adapter completed", "y_adapter", lambda v: pct(v, 1), True),
    mrow("&middot; oracle perfect", "y_oracle", lambda v: pct(v, 1), True),
    mrow("&middot; rubric perfect", "y_rubric", lambda v: pct(v, 1), True),
    mrow("&middot; security clean", "y_security", lambda v: pct(v, 1), True),
    mrow("rolled throughput yield", "rty", lambda v: pct(v, 1), True, strong=True,
         hint="the four above multiplied &mdash; the odds a task clears every gate "
              "with nothing to redo"),
    grp("&#128207; Capability"),
    mrow("Cpk", "cpk", lambda v: "&mdash;" if v is None else f"{v:+.3f}", True, strong=True,
         hint=f"against a one-sided lower spec of {LSL:.2f}. Manufacturing wants 1.33; "
              "see the caveat below."),
    grp("&#128200; Statistical control"),
    mrow("mean moving range", "mrbar", lambda v: pct(v, 1), False,
         hint="the average task-to-task jump &mdash; the width of the natural variation"),
    mrow("upper control limit", "ucl", lambda v: pct(v, 1), None),
    mrow("lower control limit", "lcl", lambda v: pct(v, 1), None),
    mrow("points out of control", "ooc", lambda v: num(v), False, strong=True,
         hint="tasks outside the limits &mdash; special-cause variation, worth reading "
              "one by one rather than averaging"),
    grp("&#9203; Lead time"),
    mrow("p50", "sec_median", lambda v: "&mdash;" if v is None else f"{v:,.0f}s", False),
    mrow("p75", "p75", lambda v: "&mdash;" if v is None else f"{v:,.0f}s", False),
    mrow("p90", "p90", lambda v: "&mdash;" if v is None else f"{v:,.0f}s", False, strong=True),
    mrow("p95", "p95", lambda v: "&mdash;" if v is None else f"{v:,.0f}s", False),
    mrow("longest task", "pmax", lambda v: "&mdash;" if v is None else f"{v:,.0f}s", False),
    grp("&#9851;&#65039; Efficiency"),
    mrow("model time", "model_min",
         lambda v: "&mdash;" if v is None else f"{v:,.0f} min", None),
    mrow("harness time", "harness_min",
         lambda v: "&mdash;" if v is None else f"{v:,.0f} min", False),
    mrow("process cycle efficiency", "pce", lambda v: pct(v, 1), None, strong=True,
         hint="model time over lead time"),
])

ooc_rows = ""
for k in KEYS:
    lab = next(x["label"] for x in RUNS if x["key"] == k)
    named = ", ".join(f"{t} ({v:.2f})" for t, v in S[k]["ooc_tasks"])
    ooc_rows += (f'<tr><td class="ml">{lab}<span class="mh">limits '
                 f'{S[k]["lcl"] * 100:.1f}&ndash;{S[k]["ucl"] * 100:.1f}%</span></td>'
                 f'<td class="why" colspan="4">'
                 f'{named or "none &mdash; every task inside the limits"}</td></tr>')

pareto_head = "".join(f'<th class="bh">{r["label"]}</th>' for r in RUNS)

# Who leads is read from the shared set rather than written down, because it has
# already changed once: this table compared every domain against dsh until a
# fifth round was added and dsh stopped being the round to compare against.
LEADER = max(KEYS, key=lambda k: C[k]["combined"] or 0)
LEADER_LABEL = next(x["label"] for x in RUNS if x["key"] == LEADER)
RUNNER_UP = max((k for k in KEYS if k != LEADER), key=lambda k: C[k]["combined"] or 0)
RUNNER_UP_LABEL = next(x["label"] for x in RUNS if x["key"] == RUNNER_UP)
ORACLE_TOP = max(KEYS, key=lambda k: S[k]["oracle_rate"] or 0)
ORACLE_TOP_LABEL = next(x["label"] for x in RUNS if x["key"] == ORACLE_TOP)

# domains where the shared-set leader is not the overall leader
flips = []
for b in DOMAIN_ORDER:
    ts = [t for t in COMMON if domain_of(t) == b]
    if not ts:
        continue
    v = {k: mean(vals(k, "combined", ts)) for k in KEYS}
    top = max(v, key=lambda k: v[k] or 0)
    if top != LEADER:
        lbl = next(x["label"] for x in RUNS if x["key"] == top)
        flips.append((b, lbl, v[top], v[LEADER], len(ts)))

flip_html = "".join(
    f'<tr><td class="ml">{b}<span class="mh">{n} shared tasks</span></td>'
    f'<td class="n best">{lbl}</td><td class="n">{pct(tv)}</td>'
    f'<td class="n">{pct(dv)}</td><td class="n">{(tv - dv) * 100:+.1f}</td></tr>'
    for b, lbl, tv, dv, n in flips)

# controlled pair
gap = C["dsh"]["combined"] - C["pflash"]["combined"]

HTML = f"""<title>Five rounds, one suite</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>{CSS}</style>
<div class="wrap">

<header>
  <p class="eyebrow">HarnessBench &middot; {len(COMMON)} shared tasks</p>
  <h1>Five rounds, side by side &mdash; and the one variable nobody held still</h1>
  <p class="lede">Three harnesses, five rounds, one 106-task suite. Every number
  below is read off the runner's own result files. Where a round could not measure
  something the cell is a dash, never a default &mdash; a subscription link journals no
  charge, and a fabricated zero would rank it first.</p>
  <p class="lede"><b>The pair that matters</b> is <span class="mono">Perpetum+Flash</span>
  against <span class="mono">dsh+Flash</span>: same model, same tasks, and dsh leads by
  <b>{gap * 100:.1f} points</b> while costing
  <b>{(1 - S["dsh"]["proxy_cost_point"] / S["pflash"]["proxy_cost_point"]) * 100:.0f}% less per
  point</b> at the same prices.</p>
  <p class="lede"><b>It is now a controlled pair, which it was not before.</b> Both sides ask the
  model to think, with the same words: <span class="mono">thinking:{{type:enabled}},
  reasoning_effort:high</span>. Read off the captured request bodies, 1,276 of this round's 1,386
  completion calls carry both &mdash; the other 110 are its <span class="mono">ds-pro</span>
  verifier, which declares no effort. The round this column superseded sent
  <span class="mono">{{model, stream, tool_choice}}</span> and nothing else on all 1,231 of its
  calls, so the gap then was <em>harness plus thinking mode</em> and this page could not separate
  them. That experiment has now been run, and it moved this column
  <b>{(S["pflash"]["combined"] - S["pflash_old"]["combined"]) * 100:+.1f} points</b>. The
  <b>{gap * 100:.1f}-point</b> gap that remains is the harness.</p>
  <p class="lede"><b>One thing this pair does not control for.</b> This round also moved its
  verifier and mutator to <span class="mono">deepseek-v4-pro</span>, because with coder and
  verifier on one link <span class="mono">V-5</span> refuses every review as self-review &mdash;
  across every earlier round on this page, <em>not one step was independently reviewed</em>. So
  this is the first column here whose process scores describe reviewed work, and the price of that
  is a second changed variable. Review is not what closed the gap: on the tasks both rounds
  scored, excluding the five that the <span class="mono">L-131</span> defect had depressed, the
  two are within noise of each other.</p>
</header>

<section>
  <h2>Ranked on the shared set</h2>
  <div class="hero">{hero}</div>
  <p class="note" style="margin-top:16px">Ranked on the <b>{len(COMMON)} tasks every round has
  scored</b>, not on each round's own denominator &mdash; dsh is still running and its full-suite
  mean is measured against a smaller, easier-so-far set. Both figures appear in the metric table.</p>
</section>

<section>
  <h2>Every task, every round</h2>
  <p class="lede">One cell per task, in suite order. Hover for the score. Grey is a task
  that produced no result file &mdash; it shrinks the denominator instead of scoring zero,
  which is the one failure mode a mean will not show you.</p>
  <div class="maps" style="margin-top:18px">{maps}</div>
  <div class="key" style="margin-top:18px">
    <span><i style="background:var(--pass)"></i> 1.0</span>
    <span><i style="background:var(--high)"></i> 0.9 &ndash; 1.0</span>
    <span><i style="background:var(--mid)"></i> 0.7 &ndash; 0.9</span>
    <span><i style="background:var(--low)"></i> 0.3 &ndash; 0.7</span>
    <span><i style="background:var(--fail)"></i> below 0.3</span>
    <span><i style="background:var(--miss);opacity:.55"></i> dropped &mdash; no result file</span>
    <span><i style="border:1px dashed var(--miss)"></i> not yet run</span>
  </div>
</section>

<section>
  <h2>Every metric the five rounds record</h2>
  <p class="lede">Green is best in row, red worst. Rows where "best" is meaningless are left
  unmarked. Each round is on its own denominator here &mdash; see the head-to-head below for
  the shared-task cut.</p>
  <div class="scroll mtbl" style="margin-top:16px">
  <table>
    <thead><tr><th>&nbsp;</th>{head_cells}</tr></thead>
    <tbody>{"".join(metric_rows)}</tbody>
  </table>
  </div>
  <p class="note" style="margin-top:16px"><b>Claude Code counts its input differently, and the
  input rows show it.</b> Its transcript reports <span class="mono">input_tokens</span> as only
  the uncached remainder &mdash; <b>3,792 tokens across the whole 78M-token round</b>, which is
  why <em>input / task</em> rounds to 0K in that column. It is not a round that sent almost no
  input; it is a round whose input arrived as 68.7M cache reads and 5.6M cache writes, both
  counted in their own rows. It is also the only round reporting cache writes at all, so
  <em>cache write</em> is a dash everywhere else rather than a zero. Compare the four columns on
  total tokens and cost, which are on the same footing, rather than on input.</p>
  <p class="note"><b>Two cost routes, and they agree where both exist.</b>
  The journal route prices the charges Perpetum recorded; the proxy route prices the tokens the
  usage proxy counted, both against the same per-MTok table the six-backend report uses. For
  Perpetum+Flash they land on ${S["pflash"]["imputed"]:.4f} and ${S["pflash"]["proxy_cost"]:.4f}
  &mdash; a {abs(S["pflash"]["imputed"] - S["pflash"]["proxy_cost"]) / S["pflash"]["imputed"] * 100:.1f}%
  disagreement. That agreement is what licenses the proxy route on <b>dsh</b>, which keeps no
  journal at all. Grok stays a dash on both: no price is published for it in the bench's table,
  and its proxy counted zero tokens.</p>
  <p class="note"><b>Failing tool results is a heuristic, not a
  recorded field.</b> Neither harness flags a failed call. dsh returns results as
  <span class="mono">role: tool</span> messages; Perpetum inlines them in the next user turn
  inside <span class="mono">&lt;&lt;&lt; name output &gt;&gt;&gt;</span> fences. Each is read on
  its own terms &mdash; a non-zero <span class="mono">[exit N]</span> for Perpetum, plus a shared
  list of failure markers (traceback, command not found, no such file, permission denied, the
  named Python exceptions, <span class="mono">fatal:</span>). Bare "error" is deliberately not
  on the list: a file that contains the word is not a failed call. Read these as
  harness-internal rates, not as a strict like-for-like.</p>
  <p class="note"><b>What a zero actually was.</b> Every one on this page, and the factor that
  produced it. Note the second row: it passed every oracle check its task had and still scored
  zero, because the rubric scored its conduct at 0 and the combined score multiplies. No round
  tripped the security gate.</p>
  <div class="scroll mtbl" style="margin:14px 0">
  <table><tbody>{zero_html}</tbody></table>
  </div>
  <p class="note"><b>Two tool-call rows, because the two harnesses are legible in different
  places.</b> The proxy trace counts what the model emitted and covers every metered link;
  a <span class="mono">claude-cli</span> link is a subprocess rather than an address, so it has
  no trace and Opus takes a dash. The journal is Perpetum's own record and dsh keeps none the
  bench can read. Neither row is complete on its own, and averaging them would invent a number.</p>
</section>

<section>
  <h2>Head to head on the {len(COMMON)} shared tasks</h2>
  <p class="lede">The honest cut &mdash; every round restricted to the tasks all five have
  scored, so no round is credited for a task another never reached.</p>
  <div class="scroll mtbl" style="margin-top:16px">
  <table>
    <thead><tr><th>&nbsp;</th>{head_cells}</tr></thead>
    <tbody>{h2h}</tbody>
  </table>
  </div>
</section>

<section>
  <h2>By domain</h2>
  <p class="lede">The suite's own grouping, restricted to shared tasks. The sub-line gives the range of outcome scores across the five rounds &mdash; a wide range is a domain the harness choice actually decides.</p>
  <div class="scroll mtbl">
  <table>
    <thead><tr><th>&nbsp;</th>{head_cells}</tr></thead>
    <tbody>{band_rows}</tbody>
  </table>
  </div>
</section>

<section>
  <h2>Where the ranking turns over</h2>
  <p class="lede">{LEADER_LABEL} leads the suite, and it does not lead everywhere.
  {len(flips)} of the nine domains put a different round on top &mdash; which is the difference
  between "the better harness" and "the harness that wins this average". A finding below
  applies to all five equally.</p>
  <div class="scroll" style="margin-top:16px">
  <table>
    <thead><tr><th>domain</th><th class="bh">leader</th><th class="bh">its score</th>
    <th class="bh">{LEADER_LABEL}</th><th class="bh">margin</th></tr></thead>
    <tbody>{flip_html}</tbody>
  </table>
  </div>
  <p class="note" style="margin-top:16px"><b>The oracle pass rate agrees on the leader and on
  almost nothing else.</b> Counting checks rather than averaging task scores also puts
  <b>{ORACLE_TOP_LABEL} first, at {S[ORACLE_TOP]["oracle_rate"] * 100:.1f}%</b> &mdash; but the
  order beneath it inverts: <span class="mono">Perpetum+Grok</span> is second on checks at
  {S["grok"]["oracle_rate"] * 100:.1f}% while third on the combined score, and
  <span class="mono">dsh+Flash</span> is second on the combined score while fourth on checks at
  {S["dsh"]["oracle_rate"] * 100:.1f}%. The combined score weights every task equally; the pass
  rate weights every check equally, so a round that half-finishes many-check tasks and a round
  that cleanly fails few-check ones swap places. Neither is wrong. They answer different
  questions, and only the pass rate survives the unequal denominators intact.</p>
  <p class="note"><b>Not one step in any round was independently reviewed.</b> Every priced call
  in all three journals carries <span class="mono">role: coder</span>. There are no verifier calls
  and no gated steps anywhere. The two rounds get there by different routes: Grok and
  Perpetum+Flash closed on file-resident claims without the gate running at all
  ({S["grok"]["no_gate"]} and {S["pflash"]["no_gate"]} steps, <span class="mono">L-64</span>),
  while Opus reached the review stage {S["opus"]["refused"]} times and Perpetum refused it &mdash;
  <em>&ldquo;claude would be reviewing its own work. Self-review by the same model on the same
  context is not review&rdquo;</em> (<span class="mono">V-5</span>). That refusal is correct
  behaviour in a one-link config, and it means the process column across this whole page measures
  unreviewed work. An earlier draft of this report read the absence of a
  <span class="mono">NO GATE RAN</span> note as evidence that Opus <em>had</em> been gated; the
  journal says otherwise, and the journal is the record.</p>
</section>

<section>
  <h2>What the near-controlled pair says</h2>
  <div class="legend">
    <div class="lg"><div class="lgn">{gap * 100:+.1f}</div><div class="lgt">points, dsh over Perpetum</div>
      <p>Same model, same tasks, same rubric &mdash; but <b>two</b> variables, not one: the
      harness, and whether the model was asked to think. Attributing the gap to the harness
      alone would overclaim.</p></div>
    <div class="lg"><div class="lgn">{(C["dsh"]["outcome"] - C["pflash"]["outcome"]) * 100:+.1f}</div>
      <div class="lgt">of it is outcome</div>
      <p>Checks that passed for one harness and failed for the other, on identical work.</p></div>
    <div class="lg"><div class="lgn">{(C["dsh"]["process"] - C["pflash"]["process"]) * 100:+.1f}</div>
      <div class="lgt">of it is process</div>
      <p>The rubric's read on conduct &mdash; tool choice, coherence, recovery.</p></div>
    <div class="lg"><div class="lgn">{S["dsh"]["tok_point"] / S["pflash"]["tok_point"]:.1f}&times;</div>
      <div class="lgt">the tokens per point of score</div>
      <p>{tok(S["dsh"]["tok_point"])} against {tok(S["pflash"]["tok_point"])}, per point rather
      than per round so the unequal denominators cancel. dsh reads far more context to get
      its answer.</p></div>
    <div class="lg"><div class="lgn">${S["dsh"]["proxy_cost_point"]:.4f}</div>
      <div class="lgt">but it costs less per point</div>
      <p>Against Perpetum+Flash's ${S["pflash"]["proxy_cost_point"]:.4f} &mdash;
      {(1 - S["dsh"]["proxy_cost_point"] / S["pflash"]["proxy_cost_point"]) * 100:.0f}% cheaper,
      at the same prices. {S["dsh"]["cache_hit"] * 100:.1f}% of dsh's tokens are cache reads
      against Perpetum+Flash's {S["pflash"]["cache_hit"] * 100:.1f}%, and a cache read is priced
      at 1/50th of an input token. More tokens, cheaper tokens, better score. The only axis
      Perpetum+Flash still wins is wall time.</p></div>
  </div>
</section>

<section id="tasks">
  <h2>Every task, every round, with its oracle</h2>
  <p class="lede">Combined score and oracle checks passed, per round. <span class="mono">spread</span>
  is the distance between the best and worst round on that task; purple marks half a point or more,
  which is where the harnesses genuinely disagree rather than drift.</p>
  <div class="scroll" style="margin-top:16px">
  <table>
    <thead><tr><th>task</th>
    {"".join(f'<th class="bh">{r["label"]}<small>score &middot; oracle</small></th><th></th>' for r in RUNS)}
    <th class="bh">spread</th></tr></thead>
    <tbody>{task_rows()}</tbody>
  </table>
  </div>
</section>

<section>
  <h2>&#128208; The statistical view</h2>
  <p class="lede">The same rounds read as a process rather than a scoreboard. Every definition
  here is a choice and each one is stated: a benchmark is not a production line, and borrowed
  vocabulary is only worth anything if it says plainly what it is counting.</p>

  <h3 class="sub">Value stream &mdash; where the lead time goes</h3>
  <p class="lede" style="margin-bottom:14px">Two stages carry a measured duration: the model
  thinking, and everything the harness does around it.</p>
  {pce_bars}
  <div class="vskey"><span><i style="background:var(--accent)"></i>model latency</span>
    <span><i style="background:var(--mid)"></i>harness: tools, journalling, gating, scoring</span></div>
  <p class="note" style="margin-top:16px"><b>This is inverted from a factory floor.</b> Process
  cycle efficiency on a production line is typically 5&ndash;15%, and Lean goes after the waiting.
  Here it is <b>{pce_lo:.1f}&ndash;{pce_hi:.1f}%</b>: almost the whole clock is the model
  thinking, and the harness accounts for {inv_hi:.0f}&ndash;{inv_lo:.0f}% of it. There is no queue
  to drain and no waste worth removing from the schedule &mdash; a faster harness cannot give back
  time it never spent. Speed here is bought by changing the model, or how hard it is asked to
  think, not by tuning the loop around it.</p>

  <h3 class="sub">Conformance, capability and control</h3>
  <div class="scroll mtbl">
  <table>
    <thead><tr><th>&nbsp;</th>{head_cells}</tr></thead>
    <tbody>{stat_rows}</tbody>
  </table>
  </div>

  <p class="note" style="margin-top:16px"><b>Cpk is the one number here not to lean on.</b> A
  capability index assumes a stable, roughly normal process. These scores are bounded at 1.0 and
  skewed left, so the index is not trustworthy as stated. Its conclusion survives the assumption
  anyway: at {cpk_lo:+.2f} to {cpk_hi:+.2f} against a manufacturing threshold of 1.33, no round is
  anywhere near capable of reliably clearing {LSL:.2f}, and two sit below the bar on the mean
  alone.</p>
  <p class="note"><b>Stable is not the same as good.</b> The fewest points outside the control
  limits belongs to {steadiest}, which says its variation is common-cause &mdash; the process
  behaving consistently, at whatever mean it has. Special-cause points are the ones worth opening
  individually rather than averaging away, so they are named:</p>
  <div class="scroll mtbl" style="margin:14px 0">
  <table><tbody>{ooc_rows}</tbody></table>
  </div>

  <h3 class="sub">Pareto &mdash; where the points are lost</h3>
  <p class="lede" style="margin-bottom:14px">Points forfeited (1 &minus; combined) per domain,
  summed across all five rounds and sorted. The cumulative column is this benchmark's own 80/20.</p>
  <div class="scroll mtbl">
  <table>
    <thead><tr><th>domain</th>{pareto_head}
      <th class="bh">total</th><th class="bh">share</th><th class="bh">cumulative</th></tr></thead>
    <tbody>{pareto_rows}</tbody>
  </table>
  </div>
</section>

<section>
  <h2>The machine underneath</h2>
  <p class="lede">One laptop, two environments. Four rounds ran natively on Windows &mdash; the three
  Perpetum ones and Claude Code;
  the dsh round ran inside WSL2 on the same silicon. That is not a like-for-like bench host, and
  the differences that could plausibly move a number are named below rather than left implicit.</p>
  <div class="scroll mtbl" style="margin-top:16px">
  <table>
    <thead><tr><th>&nbsp;</th>
      <th class="bh">Windows host<small>Perpetum+Grok, +Flash, +Opus; Claude Code+Opus 5</small></th>
      <th class="bh">WSL2 guest<small>dsh+Flash</small></th></tr></thead>
    <tbody>
      <tr><td class="ml">operating system</td><td class="id">Windows 11 Home<span class="sub">10.0.26200, build 26200</span></td><td class="id">Ubuntu 24.04.4 LTS<span class="sub">kernel 6.18.33.2-microsoft-standard-WSL2</span></td></tr>
      <tr><td class="ml">CPU</td><td class="id">12th Gen Intel Core i5-12500H<span class="sub">12 cores / 16 threads, 2.5 GHz base</span></td><td class="id">the same silicon<span class="sub">all 16 logical CPUs visible to the guest</span></td></tr>
      <tr><td class="ml">memory</td><td class="ml" style="text-align:right;font-family:Consolas,monospace">15.7 GB</td><td class="id">7.8 GB<span class="sub">WSL's default half-of-host; no .wslconfig on this machine</span></td></tr>
      <tr><td class="ml">storage</td><td class="id">NVMe TS1TMTE300S, 954 GB<span class="sub">NTFS, workspaces under D:&#92;harness-bench-work</span></td><td class="id">ext4 inside the VM disk<span class="sub">workspaces under /home/gaddl/harness-bench-work</span></td></tr>
      <tr><td class="ml">Python</td><td class="id">3.12.10</td><td class="id">3.12.3</td></tr>
      <tr><td class="ml">toolchain</td><td class="id">rustc 1.97.1<span class="sub">perp.exe built here</span></td><td class="id">&mdash;<span class="sub">dsh runs from a venv, not compiled</span></td></tr>
    </tbody>
  </table>
  </div>

  <h2 style="margin-top:34px">When each round ran</h2>
  <div class="scroll mtbl">
  <table>
    <thead><tr><th>&nbsp;</th>{head_cells}</tr></thead>
    <tbody>
      <tr><td class="ml">began</td>{"".join(f'<td class="id">{S[k]["began"].strftime("%Y-%m-%d %H:%M") if S[k]["began"] else "&mdash;"}</td>' for k in KEYS)}</tr>
      <tr><td class="ml">ended</td>{"".join(f'<td class="id">{S[k]["ended"].strftime("%Y-%m-%d %H:%M") if S[k]["ended"] else "&mdash;"}</td>' for k in KEYS)}</tr>
      <tr><td class="ml">wall clock</td>{"".join(f'<td class="n">{S[k]["wall_h"]:.1f} h</td>' if S[k]["wall_h"] else '<td class="n">&mdash;</td>' for k in KEYS)}</tr>
      <tr><td class="ml">machine busy<span class="mh">agent time over wall clock</span></td>{"".join(f'<td class="n">{S[k]["busy"] * 100:.0f}%</td>' if S[k]["busy"] else '<td class="n">&mdash;</td>' for k in KEYS)}</tr>
      <tr><td class="ml">longest pause<span class="mh">between consecutive task starts</span></td>{"".join(f'<td class="n">{(str(round(S[k]["maxgap"] * 60)) + " min") if S[k]["maxgap"] is not None and S[k]["maxgap"] < 1.5 else (f"{S[k]['maxgap']:.1f} h" if S[k]["maxgap"] is not None else "&mdash;")}</td>' for k in KEYS)}</tr>
      <tr><td class="ml">calendar days touched</td>{"".join(f'<td class="n">{S[k]["days"]}</td>' for k in KEYS)}</tr>
    </tbody>
  </table>
  </div>

  <p class="note" style="margin-top:16px"><b>No two rounds overlapped.</b> Grok finished at
  {S["grok"]["ended"].strftime("%H:%M")} on {S["grok"]["ended"].strftime("%d %b")} and dsh began at
  {S["dsh"]["began"].strftime("%H:%M")} the same evening, so neither was competing with the other
  for the machine. The operator's own dsh instance was serving on port 3080 throughout the dsh
  round, which is a background load the Perpetum rounds did not carry.</p>
  <p class="note"><b>dsh had half the memory and the faster filesystem.</b> 7.8 GB against
  15.7 GB, on the same 16 threads &mdash; but its workspaces sat on native ext4 while the Perpetum
  rounds wrote to NTFS. For a suite this shell-heavy the second difference probably matters more
  than the first, and it favours dsh. Neither is quantified here; both are reasons not to read the
  speed rows as a pure harness comparison.</p>
  <p class="note"><b>Perpetum+Flash ran in one sitting.</b> All {S["pflash"]["files"]} of its result
  files were written on {_window("pflash")[0]} inside a {_window("pflash")[1]:.1f}-hour window, so the
  wall-clock figure above is the round's runtime and not merely its provenance. The round this column
  superseded could not say that: 105 of its 106 tasks ran in one 4.1-hour window and
  <span class="mono">008-image-recognize</span> was dated a week earlier &mdash; a straggler from
  different conditions sitting in the distribution, and one of that round's three zeros.</p>
</section>

<section>
  <h2>What this does not show</h2>
  <p class="note"><b>dsh has not finished.</b> {S["dsh"]["files"]} of {TOTAL_TASKS} result files at
  build time. Its full-suite mean is against a smaller set that has not yet met the adversarial
  tail, so treat the shared-task column as the real one.</p>
  <p class="note"><b>The scoring passes are not uniform.</b> Opus is read from
  <span class="mono">.regraded.json</span> &mdash; its first pass had no proxy trace and scored
  outcome only. The other three are first-pass. Same rubric, different runs of it.</p>
  <p class="note"><b>Cost is mostly unrecorded.</b> Only Perpetum+Flash journalled a charge.
  Grok's round recorded requests but zero tokens and zero money; Opus runs on a subscription
  through <span class="mono">claude-cli</span> and is genuinely unpriced; dsh's adapter writes
  no money field at all. The dashes are the finding, not a gap in this report.</p>
  <p class="note"><b>Wall clock comes from the sandbox names, not the file times.</b> An earlier
  draft of this report left it out, on the grounds that result-file mtimes are unusable &mdash;
  they lag over the WSL <span class="mono">/mnt/d</span> mount and a regrade rewrites them all,
  which put one round at 170 hours and another at six minutes. Every sandbox is stamped
  <span class="mono">&hellip;-YYYYMMDD-HHMMSS-&lt;hash&gt;</span> at the moment its task started,
  which is a real clock. The two agree where they should: Opus's summed agent time is
  {S["opus"]["elapsed_hours"]:.1f} h inside a {S["opus"]["wall_h"]:.1f} h window.</p>
  <p class="note"><b>Thinking mode is the confound this report cannot remove.</b> dsh runs
  deepseek-v4-flash with thinking enabled at high reasoning effort; Perpetum runs the same model
  with no thinking parameters at all. That is visible on the wire in every captured request of
  both rounds, and it is a plausible share of the {gap * 100:.1f}-point gap on its own. Until a
  Perpetum round is made with thinking enabled, treat "dsh beats Perpetum" as "dsh-with-thinking
  beats Perpetum-without", which is a weaker and more accurate claim.</p>
  <p class="note"><b>The rungs are not the same.</b> Grok and Perpetum+Flash used the provider's
  native tool-call protocol. Opus could not: a <span class="mono">claude-cli</span> link has no
  native tool channel, so its tools were described in the prompt and parsed back out of prose.
  That is a plausible mechanism for its last-place tool-use sub-score, and it is a property of
  the link rather than of the model.</p>
  <p class="note"><b>A dropped task is not a zero.</b> Every round has tasks that finished
  without writing a result file &mdash; solid grey in the map, and absent from every mean rather
  than scored badly in it. A round that drops its hardest tasks looks better than one that
  scores them. Dashed cells are different: those are tasks a running round has not reached,
  and charging them to it would be just as wrong in the other direction.</p>
</section>

<footer>
  Built {now} from <span class="mono">data_try6/results/</span> &mdash;
  {len(D["rows"])} result files across five rounds, {len(COMMON)} tasks shared by all.
  Regenerate with <span class="mono">extract.py</span> then <span class="mono">gen_comparison.py</span>.
</footer>
</div>
"""

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(HTML, encoding="utf-8", newline="\n")
print(f"wrote {OUT} ({len(HTML):,} bytes)")
for k in lead:
    print(f"  {k:7} shared={C[k]['combined']:.4f} full={S[k]['combined']:.4f} "
          f"scored={S[k]['scored']} wins={wins[k]}")
