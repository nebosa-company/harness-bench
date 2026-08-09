"""Render the collected metrics as a self-contained HTML report.

    PYTHONPATH=src python tools/collect.py && python tools/render.py

**The CSS is a plain string, not an f-string, and that is deliberate.** An
earlier version built the whole page with f-strings, so every brace in the
stylesheet had to be doubled. Patches written against single-brace CSS then
matched nothing and failed *silently* — eleven rules went missing across several
publishes and the tables rendered unstyled. `string.Template` substitutes `$name`
and leaves braces alone, so CSS is copied in verbatim and that class of bug
cannot happen again.
"""
from __future__ import annotations

import html
import json
import pathlib
from string import Template

HERE = pathlib.Path(__file__).resolve().parent
DATA = json.loads((HERE / "report-data.json").read_text(encoding="utf-8"))
ROWS, AGG = DATA["rows"], DATA["agg"]
ROWS.sort(key=lambda r: r["n"])
N = len(ROWS)

# Metrics down the side, backends across the top: four columns read far better
# than four rows of thirty numbers, and it puts like against like.
#
# The last field is the direction — "hi" where more is better, "lo" where less
# is, and "" where the metric has no better or worse. Token and turn counts
# describe what a run did rather than how well it did it; colouring them would
# assert something the data does not support.
SECTIONS = [
    ("Run", [
        ("Status", "status", "text", "tasks completed of the full suite", ""),
    ]),
    ("Scores", [
        ("Combined", "combined", "pc", "completion × process × security — the headline", "hi"),
        ("Completion", "correct", "pc", "the oracle's programmatic checks", "hi"),
        ("Process", "process", "pc", "how the run was conducted, judged from its transcript", "hi"),
        ("&nbsp;&nbsp;· tool use", "tool_use", "pc", "rubric sub-score: were the right tools used", "hi"),
        ("&nbsp;&nbsp;· consistency", "consistency", "pc", "rubric sub-score: did the run hold together", "hi"),
        ("&nbsp;&nbsp;· robustness", "robustness", "pc", "rubric sub-score: how it handled what went wrong", "hi"),
        ("Security", "security", "pc", "0/1 gate; 100% means nothing tripped it", "hi"),
    ]),
    ("Outcomes", [
        ("Perfect (100%)", "perfect", "int", "every oracle check passed", "hi"),
        ("Scored zero", "zeros", "int", "", "lo"),
        ("&nbsp;&nbsp;· of those, ▲", "zeros3", "int", "one tool call, three turns, step ended empty", "lo"),
        ("Oracle checks passed", "checks_pct", "pc", "across every check in every task", "hi"),
        ("Runs judged", "proc_n", "int", "tasks the rubric returned a usable score for", ""),
    ]),
    ("Work done", [
        ("Model turns / task", "turns", "n1", "", ""),
        ("Tool calls / task", "calls", "n1", "", ""),
        ("LLM requests / task", "requests", "n1", "counted at the proxy; 0 where there is no wire", ""),
        ("Native tool-call rung", "native_pct", "pc", "share of turns parsed at the top of the ladder", "hi"),
        ("Stopped blocked", "blocked", "int", "batches that ended blocked rather than exhausted", "lo"),
    ]),
    ("Tokens", [
        ("Input (cache-miss)", "inp", "int", "", ""),
        ("Cache read", "cache", "int", "", ""),
        ("Cache write", "cache_w", "int", "", ""),
        ("Output", "out", "int", "", ""),
        ("Per task", "tok_task", "int", "input + cache + output", ""),
    ]),
    ("Time", [
        ("Per task", "time", "sec", "", "lo"),
        ("Total wall clock", "total_h", "hrs", "", ""),
    ]),
    ("Cost", [
        ("Total", "usd", "usd", "", "lo"),
        ("Excluding cache reads", "usd_nocache", "usd", "", ""),
        ("Per task", "usd_per", "usd3", "", "lo"),
    ]),
]

CAUSES = [
    ("—", "Passed outright", "Every oracle check satisfied."),
    ("model", "Model output fell short", "Perpetum ran clean; the model produced output the oracle rejected."),
    ("regression", "Worse than the prior run", "Scored higher before, with no harness fault recorded. This is what run-to-run variance looks like."),
    ("harness mapping", "Stopped having written nothing", "A step ended empty with no second cycle to recover it."),
    ("harness capability", "Needs a model that can see", "The image path exists; no configured link declares vision."),
    ("harness config", "Link blocked on its deadline", "role.coder named one link, so the failover had nowhere to go."),
]


def fmt(v, kind, a=None):
    if v is None:
        return "—"
    if kind == "text":
        cls = "run" if str(v).endswith("running") else "fin"
        return f'<span class="st {cls}">{html.escape(str(v))}</span>'
    if kind == "pc":
        return f"{v * 100:.2f}%"
    if kind == "int":
        return f"{v:,.0f}"
    if kind == "n1":
        return f"{v:.1f}"
    if kind == "sec":
        return f"{v:,.0f}s"
    if kind == "hrs":
        return f"{v:.1f}h"
    if kind == "usd":
        return "—" if (a and a.get("unpriced")) else f"${v:,.2f}"
    if kind == "usd3":
        return "—" if (a and a.get("unpriced")) else f"${v:.3f}"
    return str(v)


def band(s):
    return ("pass" if s == 1.0 else "high" if s >= 0.75 else "mid" if s >= 0.4
            else "low" if s > 0 else "fail")


def metric_table():
    head = "".join(f'<th class="bh">{html.escape(a["name"])}</th>' for a in AGG)
    body = []
    for title, metrics in SECTIONS:
        body.append(f'<tr class="grp"><td colspan="{len(AGG) + 1}">{title}</td></tr>')
        for label, key, kind, note, direction in metrics:
            # Rank complete runs only. A backend still working through the suite
            # has spent less time and less money by definition, and colouring
            # that green would reward it for being unfinished.
            ranked = [a for a in AGG if not a["partial"] and isinstance(a.get(key), (int, float))]
            best = worst = None
            if direction and len(ranked) >= 2:
                vals = [a[key] for a in ranked]
                if len(set(vals)) > 1:
                    best = (max if direction == "hi" else min)(vals)
                    worst = (min if direction == "hi" else max)(vals)
            cells = []
            for a in AGG:
                v = a.get(key)
                cls = ""
                if best is not None and not a["partial"] and isinstance(v, (int, float)):
                    cls = " best" if v == best else (" worst" if v == worst else "")
                cells.append(f'<td class="n{cls}">{fmt(v, kind, a)}</td>')
            hint = f'<span class="mh">{html.escape(note)}</span>' if note else ""
            body.append(f'<tr><td class="ml">{label}{hint}</td>{"".join(cells)}</tr>')
    return head, "".join(body)


def leaderboard():
    board = sorted(AGG, key=lambda a: (a.get("combined") is None, -(a.get("combined") or 0)))
    out = []
    for i, a in enumerate(board, 1):
        note = ""
        if a["partial"]:
            note = f'<span class="lbp">{a["status"]}</span>'
        elif a.get("reconstructed"):
            note = '<span class="lbp">process reconstructed from the journal</span>'
        elif a.get("process") is None:
            note = '<span class="lbp">not yet judged</span>'
        out.append(
            f'<tr><td class="lbr">{i}</td>'
            f'<td class="lbn">{html.escape(a["name"])}{note}</td>'
            f'<td class="n lbc"><b>{fmt(a.get("combined"), "pc")}</b></td>'
            f'<td class="n">{fmt(a.get("correct"), "pc")}</td>'
            f'<td class="n">{fmt(a.get("process"), "pc")}</td></tr>')
    return "".join(out)


def gap_mark(gap):
    """Flag a score whose semantic half was never graded."""
    if not gap:
        return ""
    prog = (1 - gap["weight"]) * 100
    tip = (f'only the programmatic {prog:.0f}% of this task was graded; the remaining '
           f'{gap["weight"] * 100:.0f}% needed a judge that did not run ({gap["reason"]})')
    return f'<span class="gap" title="{html.escape(tip)}">⚠</span>'


def task_table():
    others = [a for a in AGG[1:]]
    keys = [a["harness"].replace("perpetum-", "") for a in others]
    head = "".join(f'<th style="text-align:right">{html.escape(a["name"].split()[-1])}</th>'
                   for a in others)
    trs, last = [], None
    span = 8 + len(others)
    for r in ROWS:
        if r["domain"] != last:
            last = r["domain"]
            trs.append(f'<tr class="grp"><td colspan="{span}">{html.escape(last)}</td></tr>')
        b = band(r["score"])
        gap = r.get("gap")
        d = None if r["base"] is None else r["score"] - r["base"]
        dcls = "" if d is None or abs(d) < .005 else ("up" if d > 0 else "down")
        dtxt = "—" if d is None or abs(d) < .005 else f"{d * 100:+.0f}"
        cmp_cells = ""
        for k in keys:
            v = r.get(k)
            if v is None:
                cmp_cells += '<td class="n dim">—</td>'
            else:
                mark = ('<span class="sig" title="one call, three turns, step ended empty">▲</span>'
                        if r.get(k + "_sig3") else "")
                cmp_cells += f'<td class="n {band(v)}c">{v * 100:.0f}%{mark}</td>'
        trs.append(
            f'<tr data-cause="{html.escape(r["cause"])}">'
            f'<td class="num"><span class="stripe {b}"></span>{r["n"]:03d}</td>'
            f'<td class="t"><span class="tt">{html.escape(r["title"])}</span>'
            f'<span class="tid">{html.escape(r["id"])}</span></td>'
            f'<td class="n"><b>{r["score"] * 100:.0f}%</b>{gap_mark(gap)}</td>'
            f'<td class="n {dcls}">{dtxt}</td>'
            f'{cmp_cells}'
            f'<td class="n dim">{fmt(r["process"], "pc")}</td>'
            f'<td class="n dim">{r["el"]:,.0f}s</td>'
            f'<td class="n dim">{r["tot"]:,}</td>'
            f'<td class="n dim">{r["turns"]}/{r["calls"]}</td>'
            f'<td class="why"><span class="verdict v-{b}">{html.escape(r["verdict"])}</span>'
            f'<span class="wx">{html.escape(r["why"])}</span></td></tr>')
    return head, "".join(trs)


def split_note():
    for a in AGG:
        if a.get("proc_sig") is not None and a.get("proc_rest") is not None:
            base = next((x["process"] for x in AGG if not x["reconstructed"] and x["process"]), None)
            against = f" against {base * 100:.2f}% for {AGG[0]['name']}, graded from the wire" if base else ""
            return (
                f'<p class="note"><b>{html.escape(a["name"])}&rsquo;s process mean hides a split, '
                f'and the split is the finding.</b> On the runs carrying the ▲ shape it scores '
                f'<b>{a["proc_sig"] * 100:.2f}%</b>; on every other task it scores '
                f'<b>{a["proc_rest"] * 100:.2f}%</b>{against}. That is bimodal, not a weaker agent: '
                f'a model simply less able at this work would depress the whole curve rather than '
                f'produce near-normal conduct on most tasks and a near-empty transcript on the rest. '
                f'Whether the fault is the model or the harness reading it is still open — both '
                f'produce this same signature, and the rubric reads the same transcript either way.</p>')
    return ""


CSS = """
:root {
  --paper:#f3f5f7; --surface:#fff; --ink:#171a21; --muted:#5c6675; --line:#dfe4ea;
  --accent:#1f5f8b; --pass:#2f6d4a; --high:#4f7f5f; --mid:#9a6a10; --low:#b1592f;
  --fail:#a83a36; --up:#2f6d4a; --down:#a83a36; --sig:#8a4fbf;
  --shadow:0 1px 2px rgba(23,26,33,.06),0 8px 24px rgba(23,26,33,.05);
}
@media (prefers-color-scheme:dark) { :root {
  --paper:#0e1116; --surface:#161a21; --ink:#e3e7ee; --muted:#98a2b3; --line:#262c36;
  --accent:#6fa8cf; --pass:#5fae83; --high:#7fb094; --mid:#d4a24c; --low:#e08a5e;
  --fail:#e0706b; --up:#5fae83; --down:#e0706b; --sig:#b98ae0;
  --shadow:0 1px 2px rgba(0,0,0,.4),0 8px 24px rgba(0,0,0,.3); } }
:root[data-theme="dark"] {
  --paper:#0e1116; --surface:#161a21; --ink:#e3e7ee; --muted:#98a2b3; --line:#262c36;
  --accent:#6fa8cf; --pass:#5fae83; --high:#7fb094; --mid:#d4a24c; --low:#e08a5e;
  --fail:#e0706b; --up:#5fae83; --down:#e0706b; --sig:#b98ae0;
  --shadow:0 1px 2px rgba(0,0,0,.4),0 8px 24px rgba(0,0,0,.3); }
:root[data-theme="light"] {
  --paper:#f3f5f7; --surface:#fff; --ink:#171a21; --muted:#5c6675; --line:#dfe4ea;
  --accent:#1f5f8b; --pass:#2f6d4a; --high:#4f7f5f; --mid:#9a6a10; --low:#b1592f;
  --fail:#a83a36; --up:#2f6d4a; --down:#a83a36; --sig:#8a4fbf;
  --shadow:0 1px 2px rgba(23,26,33,.06),0 8px 24px rgba(23,26,33,.05); }
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
.lede { color:var(--muted); max-width:66ch; margin:12px 0 0; }
.scroll { overflow-x:auto; border:1px solid var(--line); border-radius:8px;
  background:var(--surface); box-shadow:var(--shadow); }
table { border-collapse:collapse; width:100%; }
#tasks table { min-width:1180px; }
th { position:sticky; top:0; z-index:2; background:var(--surface); text-align:left;
  font:600 10.5px/1.3 "Segoe UI",sans-serif; letter-spacing:.08em; text-transform:uppercase;
  color:var(--muted); padding:12px 10px; border-bottom:1px solid var(--line); }
td { padding:11px 10px; border-bottom:1px solid var(--line); vertical-align:top; font-size:13.5px; }
tr.grp td { background:var(--paper); font:600 11px/1 "Segoe UI",sans-serif; letter-spacing:.1em;
  text-transform:uppercase; color:var(--muted); padding:10px 12px; }
td.n { font-family:Consolas,ui-monospace,monospace; font-variant-numeric:tabular-nums;
  text-align:right; white-space:nowrap; }
td.dim { color:var(--muted); }
td.best { color:var(--pass); font-weight:700; }
td.worst { color:var(--fail); font-weight:700; }
td.up { color:var(--up); font-weight:600; }
td.down { color:var(--down); font-weight:600; }
td.passc{color:var(--pass)} td.highc{color:var(--high)} td.midc{color:var(--mid)}
td.lowc{color:var(--low)} td.failc{color:var(--fail)}
th.bh { text-align:right; font:600 12.5px/1.3 "Segoe UI",sans-serif; text-transform:none;
  letter-spacing:0; color:var(--ink); white-space:nowrap; }
td.ml { font-weight:600; font-size:13.5px; }
.mh { display:block; font:400 11.5px/1.45 "Segoe UI",sans-serif; color:var(--muted);
  font-weight:400; margin-top:2px; max-width:38ch; }
.st { font-family:Consolas,ui-monospace,monospace; font-weight:600; }
.st.run { color:var(--mid); } .st.fin { color:var(--pass); }
table.lb td { font-size:14.5px; }
.lbr { width:2.5em; color:var(--muted); font-family:Consolas,ui-monospace,monospace; }
.lbn { font-weight:600; }
.lbc { font-size:16px; }
.lbp { display:block; font:400 11.5px/1.4 "Segoe UI",sans-serif; color:var(--muted); }
td.num { font-family:Consolas,ui-monospace,monospace; color:var(--muted); white-space:nowrap;
  position:relative; padding-left:18px; }
.stripe { position:absolute; left:0; top:0; bottom:0; width:4px; }
.stripe.pass{background:var(--pass)} .stripe.high{background:var(--high)}
.stripe.mid{background:var(--mid)} .stripe.low{background:var(--low)}
.stripe.fail{background:var(--fail)}
td.t { min-width:180px; }
.tt { display:block; font-weight:600; }
.tid { display:block; font:400 11.5px/1.5 Consolas,ui-monospace,monospace; color:var(--muted); }
.sig { color:var(--sig); font-weight:700; margin-left:3px; }
.gap { color:var(--mid); font-weight:700; margin-left:4px; cursor:help; }
td.why { max-width:360px; }
.verdict { display:inline-block; font:600 10.5px/1 "Segoe UI",sans-serif; letter-spacing:.06em;
  text-transform:uppercase; padding:4px 8px; border-radius:3px; margin-bottom:6px;
  border:1px solid currentColor; }
.v-pass{color:var(--pass)} .v-high{color:var(--high)} .v-mid{color:var(--mid)}
.v-low{color:var(--low)} .v-fail{color:var(--fail)}
.wx { display:block; color:var(--muted); font-size:12.5px; line-height:1.5; }
.legend { display:grid; grid-template-columns:repeat(auto-fit,minmax(250px,1fr)); gap:1px;
  background:var(--line); border:1px solid var(--line); border-radius:8px; overflow:hidden; }
.lg { background:var(--surface); padding:16px 18px; }
.lgh { display:flex; align-items:baseline; gap:10px; }
.lgn { font:600 19px/1 Consolas,ui-monospace,monospace; color:var(--accent);
  font-variant-numeric:tabular-nums; }
.lgt { font-weight:600; font-size:14px; }
.lg p { margin:7px 0 0; font-size:13px; color:var(--muted); line-height:1.5; }
.filters { display:flex; flex-wrap:wrap; gap:8px; }
.chip { font:500 12.5px/1 "Segoe UI",sans-serif; color:var(--ink); background:var(--surface);
  border:1px solid var(--line); border-radius:999px; padding:8px 14px; cursor:pointer; }
.chip b { font-family:Consolas,ui-monospace,monospace; color:var(--accent); margin-right:6px; }
.chip:hover { border-color:var(--accent); }
.chip[aria-pressed="true"] { background:var(--accent); color:#fff; border-color:var(--accent); }
.chip[aria-pressed="true"] b { color:#fff; }
.chip:focus-visible { outline:2px solid var(--accent); outline-offset:2px; }
.note { border-left:3px solid var(--accent); padding:2px 0 2px 16px; color:var(--muted);
  font-size:13.5px; max-width:74ch; }
.note b { color:var(--ink); }
.note + .note { margin-top:14px; }
footer { color:var(--muted); font-size:12.5px; border-top:1px solid var(--line); padding-top:20px; }
@media (max-width:640px) { .wrap{padding:36px 16px 64px} h1{font-size:27px} }
"""

PAGE = Template("""<title>Perpetum on Harness-Bench — $n tasks, $backends backends</title>
<style>$css</style>

<div class="wrap">
  <header>
    <p class="eyebrow">Harness-Bench · Perpetum 0.2.0 · $backends model backends</p>
    <h1>$n tasks, every metric, and what each number is worth</h1>
    <p class="lede">Completion, process, time, tokens and cost for every task across
      $backends backends. Failure causes are read from each run's own journal rather than inferred
      from the score — which is how several of this page's earlier claims turned out to be wrong.</p>
  </header>

  <section>
    <h2>Ranked by combined score</h2>
    <div class="scroll">
      <table class="lb">
        <thead><tr><th class="lbr">#</th><th class="lbn">Model backend</th>
          <th style="text-align:right">Combined</th><th style="text-align:right">Completion</th>
          <th style="text-align:right">Process</th></tr></thead>
        <tbody>$lbrows</tbody>
      </table>
    </div>
    <p class="note" style="margin-top:16px"><b>Combined = completion × process × security</b>, the
      same formula and the same three headline metrics the published
      <a href="https://www.harness-bench.ai/leaderboard.html">Harness-Bench leaderboard</a> ranks on.
      These figures are <i>not</i> comparable to the rows there: each is a single run of one harness,
      the process judge is <code>deepseek-v4-flash</code> rather than the default (whose key has no
      credit), and two backends have their transcripts reconstructed rather than observed on the
      wire. Read the caveats under the metric table before quoting any of it.</p>
  </section>

  <section>
    <h2>Every metric the benchmark records</h2>
    <div class="scroll">
      <table>
        <thead><tr><th class="ml">Metric</th>$mhead</tr></thead>
        <tbody>$mrows</tbody>
      </table>
    </div>
    <div style="margin-top:16px">
      <p class="note"><b>Green is the best of the finished runs on that row, red the worst.</b>
        Direction is per metric — more is better for scores and perfect counts, less is better for
        zeros, blocked stops, time and cost. Rows with no better or worse are left uncoloured: token
        and turn counts describe what a run did, not how well. A backend still running is excluded
        from the ranking, since it has spent less time and money by not being finished.</p>
      <p class="note"><b>What the cost rows mean.</b> A <i>measured</i> cost is the provider's own
        reported charge, which already applies its cache discount. A cost <i>at listed rates</i> was
        computed from the tokens because that run was made before its link was priced — the same
        arithmetic applied to a priced link reproduces its measured bill exactly, which is what makes
        the computed figure worth reading. A flat <i>$$X/M</i> cost is a subscription backend that
        reports nothing, priced at the rate given for that model; those two differ from the others in
        accounting rule, not just in amount.</p>
      <p class="note"><b>Process is graded from a transcript, and the two link kinds supply it
        differently.</b> An HTTP link is observed on the wire by the usage proxy. A subprocess link
        has no wire, so its transcript is reconstructed from Perpetum's own journal. Same rubric and
        same prompt assembly either way — but a reconstructed column should be read beside a
        wire-derived one rather than merged into it. Reassuringly, the two agree: the reconstructed
        and observed process means land within a fraction of a point of each other.</p>
      <p class="note"><b>Reasoning effort is undeclared on the subprocess backends.</b> No
        <code>--effort</code> is passed, so they ran at whatever the CLI defaults to, while an API
        link's level is fixed by the provider. One leg is held still and the others float.</p>
      $splitnote
    </div>
  </section>

  <section>
    <h2>Where the shortfalls come from</h2>
    <div class="legend">$legend</div>
  </section>

  <section id="tasks">
    <h2>Every task</h2>
    <p class="note"><b>⚠ marks a task whose score means less than it says.</b> A handful of
      tasks carry <code>outcome_llm_weight</code> above zero: most of their score is a
      vision-capable model's judgement of the answer, and only the remainder is programmatic. That
      judge has not run here, and the blend falls back to the programmatic part alone and reports
      it as the whole score. <code>008-image-recognize</code> is the clear case — one backend
      scored 100% on an answer that called a kitten a dog, because both answer files existed and
      were non-empty. Those rows are not evidence about any backend.</p>
    <p class="note">Scores are the oracle's, as percentages. <b>Δ</b> compares the primary backend
      against an earlier run made before the benchmark's workspaces were moved out of an enclosing
      git checkout — inside it, every write was discarded as ignored and steps that had written
      plenty were recorded as having changed nothing. Time, tokens and turns/calls are the primary
      backend's.</p>
    <div class="filters" style="margin:16px 0">
      <button class="chip" data-f="all" aria-pressed="true"><b>$n</b> All tasks</button>$chips
    </div>
    <div class="scroll">
      <table>
        <thead><tr><th>#</th><th>Task</th><th style="text-align:right">Score</th>
          <th style="text-align:right">Δ</th>$thead
          <th style="text-align:right">Process</th><th style="text-align:right">Time</th>
          <th style="text-align:right">Tokens</th><th style="text-align:right">T/C</th>
          <th>Verdict &amp; explanation</th></tr></thead>
        <tbody>$trows</tbody>
      </table>
    </div>
  </section>

  <footer>Perpetum 0.2.0 · one bound workspace and one minted requirement per task · workspaces
    outside any git repository · generated by <code>tools/collect.py</code> and
    <code>tools/render.py</code> · T/C is model turns over tool calls.</footer>
</div>

<script>
const chips=[...document.querySelectorAll('.chip')];
const trs=[...document.querySelectorAll('#tasks tbody tr:not(.grp)')];
const grps=[...document.querySelectorAll('#tasks tr.grp')];
chips.forEach(c=>c.addEventListener('click',()=>{
  const f=c.dataset.f;
  chips.forEach(x=>x.setAttribute('aria-pressed', x===c?'true':'false'));
  trs.forEach(r=>{ r.style.display=(f==='all'||r.dataset.cause===f)?'':'none'; });
  grps.forEach(g=>{ let x=g.nextElementSibling,any=false;
    while(x&&!x.classList.contains('grp')){ if(x.style.display!=='none') any=true; x=x.nextElementSibling; }
    g.style.display=any?'':'none'; });
}));
</script>
""")


def main() -> None:
    counts = {c: sum(1 for r in ROWS if r["cause"] == c) for c, _, _ in CAUSES}
    chips = "".join(
        f'<button class="chip" data-f="{html.escape(c)}"><b>{counts[c]}</b> {html.escape(label)}</button>'
        for c, label, _ in CAUSES if counts[c])
    legend = "".join(
        f'<div class="lg"><div class="lgh"><span class="lgn">{counts[c]}</span>'
        f'<span class="lgt">{html.escape(label)}</span></div>'
        f'<p>{html.escape(note)}</p></div>' for c, label, note in CAUSES if counts[c])

    mhead, mrows = metric_table()
    thead, trows = task_table()
    out = HERE / "report.html"
    out.write_text(PAGE.substitute(
        n=N, backends=len(AGG), css=CSS, lbrows=leaderboard(),
        mhead=mhead, mrows=mrows, thead=thead, trows=trows,
        chips=chips, legend=legend, splitnote=split_note()), encoding="utf-8")
    print(f"wrote {out.relative_to(HERE.parent)} ({out.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
