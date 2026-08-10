"""Render the six-backend report from `six-backends.json`.

One collector, one renderer. The five-backend page derived its numbers from two
places and they disagreed by a tenth of a point on one round, which took longer
to chase than writing this did.
"""

from __future__ import annotations

import json
import pathlib
import statistics
from string import Template

DATA = json.loads(pathlib.Path("tools/six-backends.json").read_text(encoding="utf-8"))
OUT = pathlib.Path("D:/repos/perpetum.io/docs/build/perpetum-on-harness-bench-6-model-backends.html")

COST_NOTE = {
    "opus": "imputed — subscription, priced at API rates",
    "sonnet": "imputed — subscription, priced at API rates",
    "claude": "imputed — subscription, priced at API rates",
    "flash": "measured",
    "pro": "reconstructed — the round predates its prices",
    "mixture": "Opus imputed + DeepSeek measured",
}

LEADERBOARD = [
    ("#1", "Nanobot", "GPT-5.4", 81.3, 85.1, 94.7, "3.55M", "306.2K"),
    ("#2", "Nanobot", "GLM-5.1", 80.4, 84.3, 96.1, "2.09M", "716.3K"),
    ("#3", "Codex", "GPT-5.4", 80.4, 86.5, 92.6, "8.84M", "282.1K"),
]

FIELD = {
    "005-email-triage": 93.9, "006-access-bilibili": 92.4, "001-file": 90.6,
    "016-code-repair-pytest": 89.7, "032-customer-followup-draft": 87.4,
    "003-browser": 84.9, "017-db-doc-consistency": 84.4,
    "034-evidence-matrix-claims": 83.9, "009-git-pr-merge": 83.3,
    "004-meeting-summary": 82.8, "030-word-revision-plan": 82.8, "002-exec": 82.1,
    "026-ppt-brief-generation": 81.1, "010-office-docs": 80.6,
    "020-archive-checksum": 77.5, "033-offline-knowledge-qa": 77.4,
}

CSS = """
  :root{color-scheme:light dark;--bg:#fbfbfa;--panel:#fff;--ink:#1c1c1a;--dim:#6b6b66;
    --line:#e3e2dd;--good:#2f7d4f;--warn:#b07a1e;--bad:#a33a3a;--acc:#5b53a6;--code:#f4f3ef}
  @media (prefers-color-scheme:dark){:root{--bg:#16171a;--panel:#1d1f23;--ink:#e6e5e1;--dim:#9a9a95;
    --line:#2e3137;--good:#6fcf97;--warn:#e0b356;--bad:#e07b7b;--acc:#a79ef0;--code:#23262b}}
  :root[data-theme="dark"]{--bg:#16171a;--panel:#1d1f23;--ink:#e6e5e1;--dim:#9a9a95;
    --line:#2e3137;--good:#6fcf97;--warn:#e0b356;--bad:#e07b7b;--acc:#a79ef0;--code:#23262b}
  :root[data-theme="light"]{--bg:#fbfbfa;--panel:#fff;--ink:#1c1c1a;--dim:#6b6b66;
    --line:#e3e2dd;--good:#2f7d4f;--warn:#b07a1e;--bad:#a33a3a;--acc:#5b53a6;--code:#f4f3ef}
  *{box-sizing:border-box}
  body{margin:0;padding:2.5rem 1.25rem 5rem;background:var(--bg);color:var(--ink);
    font:16px/1.6 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}
  .wrap{max-width:80rem;margin:0 auto}
  h1{font-size:1.8rem;margin:0 0 .25rem;letter-spacing:-.02em}
  .sub{color:var(--dim);margin:0 0 2rem;font-size:.95rem}
  h2{font-size:1.15rem;margin:3rem 0 .6rem;letter-spacing:-.01em}
  h3{font-size:.78rem;margin:1.6rem 0 .4rem;text-transform:uppercase;letter-spacing:.08em;color:var(--acc)}
  .lede{color:var(--dim);margin:0 0 1rem}
  code{background:var(--code);padding:.1em .35em;border-radius:3px;
    font:.875em ui-monospace,Consolas,monospace}
  .scroll{overflow-x:auto}
  table{width:100%;border-collapse:collapse;font-size:.88rem}
  th,td{text-align:left;padding:.45rem .6rem;border-bottom:1px solid var(--line);vertical-align:top}
  th{font-size:.7rem;text-transform:uppercase;letter-spacing:.06em;color:var(--dim);font-weight:600}
  td.n{text-align:right;font-variant-numeric:tabular-nums}
  td.id{font:.82rem ui-monospace,Consolas,monospace;white-space:nowrap}
  tbody tr:last-child td{border-bottom:0}
  .tbl{background:var(--panel);border:1px solid var(--line);border-radius:10px;overflow:hidden}
  .best{color:var(--good);font-weight:700}
  .worst{color:var(--bad)}
  .grp td{background:var(--code);font-size:.7rem;text-transform:uppercase;letter-spacing:.08em;
    color:var(--acc);font-weight:700;border-bottom:1px solid var(--line)}
  .note{border-left:3px solid var(--warn);background:var(--panel);padding:.9rem 1.1rem;
    border-radius:0 8px 8px 0;margin:1rem 0}
  .note.bad{border-left-color:var(--bad)}.note.good{border-left-color:var(--good)}
  .note p{margin:0 0 .6rem}.note p:last-child{margin:0}
  .pill{display:inline-block;padding:.05em .5em;border-radius:999px;font-size:.7rem;
    font-weight:600;border:1px solid;white-space:nowrap}
  .p-clean{color:var(--good);border-color:var(--good)}
  .p-mixed{color:var(--bad);border-color:var(--bad)}
  ul{padding-left:1.2rem}li{margin:.35rem 0}
  footer{margin-top:4rem;padding-top:1.25rem;border-top:1px solid var(--line);
    color:var(--dim);font-size:.82rem}
"""


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def main() -> int:
    order = ["mixture", "claude", "opus", "flash", "pro", "sonnet"]
    by = {b["key"]: b for b in DATA}
    bs = [by[k] for k in order]
    head = "".join(f'<th style="text-align:right">{esc(b["label"])}</th>' for b in bs)

    def row(label, fmt, pick, best="max", note=""):
        vals = [pick(b) for b in bs]
        nums = [v for v in vals if isinstance(v, (int, float))]
        win = (max(nums) if best == "max" else min(nums)) if nums else None
        lose = (min(nums) if best == "max" else max(nums)) if nums else None
        cells = []
        for v in vals:
            if v is None:
                cells.append('<td class="n" style="color:var(--dim)">&mdash;</td>')
                continue
            cls = ""
            if best != "none" and len(set(nums)) > 1:
                cls = "best" if v == win else ("worst" if v == lose else "")
            cells.append(f'<td class="n {cls}">{fmt(v)}</td>')
        return f"<tr><td>{label}{note}</td>{''.join(cells)}</tr>"

    def group(title):
        return f'<tr class="grp"><td colspan="{len(bs)+1}">{title}</td></tr>'

    pct = lambda v: f"{v:.2f}%"
    pct1 = lambda v: f"{v:.1f}%"
    i = lambda v: f"{v:,}"
    f1 = lambda v: f"{v:.1f}"
    M = lambda v: f"{v/1e6:.2f}M"
    usd = lambda v: f"${v:,.2f}"

    shapes = "".join(f'<td class="n" style="color:var(--dim);font-size:.76rem">{esc(b["shape"])}</td>' for b in bs)
    prov = "".join(
        '<td class="n"><span class="pill %s">%s</span></td>'
        % (("p-mixed", "mixed dates") if len(b["dates"]) > 1 else ("p-clean", "one round"))
        for b in bs)

    metrics = [
        f"<tr><td>shape</td>{shapes}</tr>",
        f"<tr><td>provenance</td>{prov}</tr>",
        group("Outcome"),
        row("<strong>completion</strong> (mean)", pct, lambda b: b["completion"]),
        row("median task score", pct, lambda b: b["median"]),
        row("spread (std dev)", pct, lambda b: b["stdev"], best="min"),
        row("perfect (1.00)", i, lambda b: b["perfect"]),
        row("partial", i, lambda b: b["partial"], best="none"),
        row("<strong>zeros</strong>", i, lambda b: b["zeros"], best="min"),
        row("scored below 0.50", i, lambda b: b["below_half"], best="min"),
        row("oracle checks passed", lambda v: f"{v:,}", lambda b: b["checks_pass"], best="none"),
        group("Reliability"),
        row("adapter failures", i, lambda b: b["adapter_fail"], best="min"),
        row("process measured", lambda v: f"{v} / 106", lambda b: b["process_measured"], best="none"),
        group("Work done"),
        row("coder turns (total)", i, lambda b: b["turns_total"], best="none"),
        row("turns per task", f1, lambda b: b["turns_per_task"], best="none"),
        row("tool calls per task", f1, lambda b: b["calls_per_task"], best="none"),
        row("steps per task", f1, lambda b: b["steps_per_task"], best="none"),
        row("priced model calls", i, lambda b: b["priced_calls"], best="none"),
        row("steps with a verifier call", i, lambda b: b["verifier_steps"], best="none"),
        row("<strong>steps genuinely reviewed</strong>", i, lambda b: b["reviewed"]),
        row('<strong>logged reviewed, actually refused</strong>', i, lambda b: b["not_reviewed"], best="min"),
        row("native tool-use rung", pct1, lambda b: b["native_pct"], best="none"),
        group("Speed"),
        row("wall clock", lambda v: f"{v:.1f} h", lambda b: b["hours"], best="min"),
        row("mean seconds / task", lambda v: f"{v:,.0f}s", lambda b: b["sec_per_task"], best="min"),
        row("median seconds / task", lambda v: f"{v:,.0f}s", lambda b: b["median_sec"], best="min"),
        row("median call latency", lambda v: f"{v/1000:,.1f}s", lambda b: b["latency_ms"], best="min"),
        group("Tokens"),
        row("input, excl. cache", M, lambda b: b["tok_in"], best="min"),
        row("served from cache", M, lambda b: b["tok_cache"], best="none"),
        row("cache hit rate", pct1, lambda b: b["cache_pct"]),
        row("output", M, lambda b: b["tok_out"], best="min"),
        row("input / task", lambda v: f"{v/1e3:,.0f}K", lambda b: b["tok_in_per_task"], best="min"),
        row("output / task", lambda v: f"{v/1e3:,.0f}K", lambda b: b["tok_out_per_task"], best="min"),
        group("Money"),
        row("cost (API rates)", usd, lambda b: b["cost"], best="min"),
        row("cost / task", lambda v: f"${v:,.3f}", lambda b: b["cost_per_task"], best="min"),
        row("cost / completion point", lambda v: f"${v:,.2f}",
            lambda b: (b["cost"] / b["completion"]) if b["cost"] else None, best="min"),
        row("charged in the journal", lambda v: f"${v:,.4f}", lambda b: b["money_reported"], best="none"),
    ]

    # head to head
    mix, cla = by["mixture"], by["claude"]
    both = sorted(set(mix["per_task"]) & set(cla["per_task"]))
    ties = sum(1 for t in both if abs(mix["per_task"][t] - cla["per_task"][t]) < 0.005)
    mix_w = sum(1 for t in both if mix["per_task"][t] > cla["per_task"][t] + 0.005)
    cla_w = sum(1 for t in both if cla["per_task"][t] > mix["per_task"][t] + 0.005)

    # frozen vs movers, across all six
    allt = set.intersection(*[set(b["per_task"]) for b in bs])
    frozen = [t for t in allt if max(b["per_task"][t] for b in bs) - min(b["per_task"][t] for b in bs) < 0.005]
    movers = sorted(allt - set(frozen))
    mrows = "".join(
        f'<tr><td>{esc(b["label"])}</td>'
        f'<td class="n">{statistics.mean(b["per_task"][t] for t in allt)*100:.2f}%</td>'
        f'<td class="n">{statistics.mean(b["per_task"][t] for t in movers)*100:.2f}%</td></tr>'
        for b in bs)

    # leaderboard
    def brow(rank, harness, model, comb, comp, proc, tin, tout, ours=False):
        st = ' style="font-weight:700"' if ours else ''
        pc = f"{proc:.1f}%" if proc is not None else '<span style="color:var(--bad)">not measured</span>'
        cb = f'<span class="worst">{comb:.2f}%</span>' if ours else f"{comb:.1f}%"
        return (f'<tr{st}><td class="n" style="color:var(--dim)">{rank}</td><td>{esc(harness)}</td>'
                f'<td class="id">{esc(model)}</td><td class="n">{cb}</td><td class="n">{comp:.1f}%</td>'
                f'<td class="n">{pc}</td><td class="n">{tin}</td><td class="n">{tout}</td></tr>')
    brows = "".join(brow(*e) for e in LEADERBOARD) + brow(
        "&mdash;", "Perpetum", "mixture of models", mix["completion"], mix["completion"], None,
        f'{mix["tok_in"]/1e6:.2f}M', f'{mix["tok_out"]/1e6:.2f}M', ours=True)

    # per-task vs field
    trows = []
    for t in sorted(FIELD):
        cells = "".join(
            f'<td class="n">{b["per_task"][t]*100:.0f}%</td>' if t in b["per_task"] else '<td class="n">&mdash;</td>'
            for b in bs)
        d = mix["per_task"].get(t)
        delta = (d * 100 - FIELD[t]) if d is not None else None
        trows.append(f'<tr><td class="id">{esc(t)}</td>{cells}'
                     f'<td class="n" style="color:var(--dim)">{FIELD[t]:.1f}%</td>'
                     f'<td class="n {"best" if delta and delta>0 else "worst"}">{delta:+.0f}</td></tr>')

    zeros_line = ", ".join(f'{esc(b["label"])} {b["zeros"]}' for b in bs)

    html = Template(PAGE).substitute(
        css=CSS, head=head, metrics="".join(metrics), brows=brows, trows="".join(trows),
        mrows=mrows, zeros_line=zeros_line,
        n_frozen=len(frozen), n_movers=len(movers), n_all=len(allt),
        pct_frozen=f"{100*len(frozen)/len(allt):.0f}",
        ties=ties, mix_w=mix_w, cla_w=cla_w, n_both=len(both),
        mix_c=f'{mix["completion"]:.2f}', cla_c=f'{cla["completion"]:.2f}',
        gap=f'{cla["completion"]-mix["completion"]:+.2f}',
        field_mix=f'{statistics.mean(mix["per_task"][t]*100 for t in FIELD if t in mix["per_task"]):.1f}',
        field_mean=f'{statistics.mean(FIELD.values()):.1f}',
        field_ahead=sum(1 for t in FIELD if t in mix["per_task"] and mix["per_task"][t]*100 > FIELD[t]),
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8", newline="\n")
    print(f"wrote {OUT} ({len(html):,} bytes)")
    return 0


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Perpetum on Harness-Bench — six model backends</title>
<style>$css</style>
</head>
<body>
<div class="wrap">

<h1>Perpetum on Harness-Bench</h1>
<p class="sub">Six model backends over the same 106 tasks &middot; scores from each round's result
files, spend and effort from Perpetum's journal</p>

<h2>What the control settled</h2>
<div class="note good">
  <p>The mixture round confounded two things: whether the gain came from <em>having roles</em> or
  from the roles being filled by <em>different families</em>. The pure-Claude control holds the first
  fixed and removes the second, and the answer is that cross-family independence contributes
  almost nothing. Over $n_both tasks the two configurations tie on <strong>$ties</strong>; of the
  rest the mixture wins $mix_w and pure Claude $cla_w. Final completion: <strong>$mix_c%</strong>
  against <strong>$cla_c%</strong>.</p>
  <p><strong>Zeros, by backend: $zeros_line.</strong> Across all six rounds this is the only
  property that separates them consistently. A zero is a task the harness abandoned, and abandoning
  nothing across a full suite is what an unattended harness is judged on &mdash; but the mixture's
  margin here is a single task, and one task is not a finding.</p>
</div>

<div class="note bad">
  <p><strong>Four of these six rounds ran with no independent verification at all, and their journals
  say otherwise.</strong> <code>Agent::review</code> is correct: when the verifier would be reviewing
  its own work it returns <em>"verdict: not reviewed &mdash; &lt;link&gt; would be reviewing its own
  work"</em> without paying for a call, exactly as <code>V-5</code> intends. The engine then writes
  that refusal as an outcome record with <code>ok = true</code> and the summary
  <em>independent review</em>, the refusal text buried in a <code>detail</code> field nothing reads.
  The <code>true</code> is a literal, not derived from the verdict.</p>
  <p><strong>Across the six rounds: 233 steps genuinely reviewed, 450 recorded as a passing
  independent review while explicitly refused.</strong> The split is structural rather than random
  &mdash; with a single link the verifier chain and the coder chain are the same chain, so
  <code>V-5</code> refuses every time. Every single-link round reviewed nothing; both two-family
  rounds reviewed everything.</p>
  <p>This is the shape <code>V-2</code> and <code>V-12</code> exist to refuse &mdash; a green no
  evidence earned &mdash; and it is worse than no review, because no review is legible and this is
  not. It also reframes the whole comparison: the four single-model rounds were not
  <em>verified worse</em>, they were <strong>not verified</strong>. Filed as <code>V-16</code>.</p>
</div>

<h2>Against the public leaderboard</h2>
<p class="lede">The three highest-ranked pairs on <code>harness-bench.ai/leaderboard.html</code>,
named, with Perpetum in the same columns. The board ranks on combined score.</p>
<div class="tbl scroll">
<table>
<thead><tr><th>&nbsp;</th><th>harness</th><th>model</th><th style="text-align:right">combined</th>
<th style="text-align:right">completion</th><th style="text-align:right">process</th>
<th style="text-align:right">input tok<br><span style="font-weight:400;text-transform:none">(excl. cache)</span></th>
<th style="text-align:right">output tok</th></tr></thead>
<tbody>$brows</tbody>
</table>
</div>
<div class="note bad">
  <p><strong>Perpetum's figure is not comparable to theirs.</strong> Nanobot/GLM-5.1 reaches 80.4%
  <em>after</em> a 96.1% process multiplier; Perpetum's has no multiplier at all, because the rubric
  returned HTTP 429 on every task in every round and <code>process_effective</code> defaulted to
  <strong>1.0</strong>. Read completion instead &mdash; <strong>$mix_c%</strong> against
  84.3&ndash;86.5%, below all three. A realistic ~91% process gives roughly <strong>73%</strong>
  combined, about 15th on the pairs table rather than 2nd.</p>
  <p>The 429 was diagnosed after these rounds ran: <code>insufficient_quota /
  credit_balance_exhausted</code> &mdash; the grading account was out of credits, which is why it was
  106/106 rather than intermittent. The rubric now grades through DeepSeek, and an unmeasured
  process reports <code>null</code> rather than 1.0. Neither fix is retroactive: these six rounds
  keep their unmeasured process, and a real combined score needs a fresh round.</p>
</div>

<h2>Per task, against the field</h2>
<p class="lede">The sixteen tasks where the leaderboard publishes a field mean across seven harnesses
and eight models. Comparing per task controls for difficulty; comparing totals does not.</p>
<div class="tbl scroll">
<table>
<thead><tr><th>task</th>$head<th style="text-align:right">field</th>
<th style="text-align:right">mix &minus; field</th></tr></thead>
<tbody>$trows</tbody>
</table>
</div>
<p class="lede">On those sixteen the mixture averages <strong>$field_mix%</strong> against a field mean
of <strong>$field_mean%</strong>, ahead on <strong>$field_ahead</strong> of them.</p>

<h2>Does the suite actually move?</h2>
<p class="lede">If most tasks scored the same whatever ran them, every mean on this page would be
measuring a much smaller signal than 106 tasks implies. Across all six rounds,
<strong>$n_frozen of $n_all tasks ($pct_frozen%) never moved at all</strong>. Recomputing each round
on only the $n_movers that can move barely shifts anything, so the ranking is not an artefact of a
frozen benchmark.</p>
<div class="tbl scroll">
<table>
<thead><tr><th>backend</th><th style="text-align:right">all $n_all tasks</th>
<th style="text-align:right">movers only ($n_movers)</th></tr></thead>
<tbody>$mrows</tbody>
</table>
</div>

<h2>Every metric</h2>
<p class="lede">Everything the six rounds recorded. Green is best in row, red worst; rows where
"best" is meaningless are left unmarked. A dash means the round could not measure it, and a dash is
deliberate &mdash; a subscription link journals no charge, and a default would be a fabrication
(<code>L-39</code>).</p>
<div class="tbl scroll">
<table>
<thead><tr><th>&nbsp;</th>$head</tr></thead>
<tbody>$metrics</tbody>
</table>
</div>

<div class="note">
  <p><strong>Reading the money rows.</strong> Every round is priced at API rates so the columns
  compare. <em>Charged in the journal</em> is what the links actually billed, and the gap between the
  two rows is the whole of <code>L-39</code>: the mixture journalled &#36;0.45 against a &#36;5.00
  ceiling while consuming &#36;52.79 of equivalent resource, because a per-seat link journals zero and
  <code>L-9</code>'s ceiling cannot move for it.</p>
  <p><strong>Reading the token rows.</strong> Input excludes cache reads, which is the like-for-like
  figure &mdash; though the leaderboard does not state whether its own input column counts them, so
  one of the two readings is right and this page cannot tell which. Cache hit rates near 90% are why
  these rounds cost tens of dollars rather than hundreds.</p>
  <p><strong>Reading the native-rung row.</strong> It covers the coder's loop only. A round whose
  coder is a <code>claude-cli</code> link reads 0% because that link can never reach the native rung
  &mdash; it says nothing about the DeepSeek roles in the same round, whose calls no turn record
  describes.</p>
</div>

<h2>What this does not show</h2>
<ul>
  <li><strong>The rounds are not controlled.</strong> Opus, Sonnet and Pro ran on a Perpetum build
  predating this session's fixes; Flash, the mixture and the control ran after. A difference between
  an early round and a late one is a difference in two things at once.</li>
  <li><strong>Two rounds' data is mixed</strong> &mdash; Sonnet is 92 original results plus 14
  re-runs, which is why it reads 70.26% here against the 61.67% its own round produced; Flash holds
  6 stale files. Marked in the provenance row.</li>
  <li><strong>Process is unmeasured in all six.</strong> 0 of 106 every time.</li>
  <li><strong>Two tasks are scored on a tenth of themselves</strong> &mdash; <code>008</code> and
  <code>013</code> carry a 0.9 semantic weight whose judge also returned 429.</li>
  <li><strong>One round each.</strong> Between two runs of identical code, 53 of 106 tasks moved.
  Differences under a few points are noise, and the mixture-versus-control gap is one point.</li>
</ul>

<footer>
Completion is the oracle's <code>outcome_score</code>, meaned over 106 tasks. Effort, latency, tokens
and spend are summed from Perpetum's journal, one record per call (<code>M-11</code>). Field means
from <a href="https://www.harness-bench.ai/leaderboard.html">harness-bench.ai/leaderboard.html</a>,
which ranks on combined score across 7 harnesses and 8 model backends.
</footer>

</div>
</body>
</html>
"""

if __name__ == "__main__":
    raise SystemExit(main())
