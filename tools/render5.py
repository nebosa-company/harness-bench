"""Render the five-backend comparison.

Cost is reconstructed from journal tokens for rounds that ran before their
prices were configured, and the method is validated against a round where a
measured figure exists — Flash reconstructs to $0.6399 against a measured
$0.6399. A reconstructed number is labelled as one.
"""

from __future__ import annotations

import json
import pathlib
from string import Template

DATA = json.loads(pathlib.Path("tools/five-backends.json").read_text(encoding="utf-8"))
OUT = pathlib.Path("D:/repos/perpetum.io/docs/build/perpetum-on-harness-bench-5-model-backends.html")

PRICES = {"pro": (0.003625, 0.435, 0.87), "flash": (0.0028, 0.14, 0.28)}

# Cost per backend: (value, how it was arrived at)
COST = {
    "opus": (None, "subscription — billed per seat, not per token"),
    "sonnet": (None, "subscription — billed per seat, not per token"),
    "flash": (0.6399, "measured"),
    "pro": (1.1882, "reconstructed — the round predates its prices"),
    "mixture": (0.4545, "measured, DeepSeek half only"),
}

# Leaderboard field means, for the tasks harness-bench.ai publishes them for.
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
  .wrap{max-width:74rem;margin:0 auto}
  h1{font-size:1.8rem;margin:0 0 .25rem;letter-spacing:-.02em}
  .sub{color:var(--dim);margin:0 0 2rem;font-size:.95rem}
  h2{font-size:1.15rem;margin:3rem 0 .6rem;letter-spacing:-.01em}
  .lede{color:var(--dim);margin:0 0 1rem}
  code{background:var(--code);padding:.1em .35em;border-radius:3px;
    font:.875em ui-monospace,Consolas,monospace}
  .scroll{overflow-x:auto}
  table{width:100%;border-collapse:collapse;font-size:.88rem}
  th,td{text-align:left;padding:.5rem .65rem;border-bottom:1px solid var(--line);vertical-align:top}
  th{font-size:.72rem;text-transform:uppercase;letter-spacing:.06em;color:var(--dim);font-weight:600}
  td.n{text-align:right;font-variant-numeric:tabular-nums}
  td.id{font:.82rem ui-monospace,Consolas,monospace;white-space:nowrap}
  tbody tr:last-child td{border-bottom:0}
  .tbl{background:var(--panel);border:1px solid var(--line);border-radius:10px;overflow:hidden}
  .best{color:var(--good);font-weight:700}
  .worst{color:var(--bad)}
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
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def main() -> int:
    bs = DATA["backends"]
    by = {b["key"]: b for b in bs}
    order = ["mixture", "opus", "flash", "pro", "sonnet"]
    bs = [by[k] for k in order]

    # headline table
    def row(label, fmt, pick, best="max", note=""):
        vals = [pick(b) for b in bs]
        nums = [v for v in vals if isinstance(v, (int, float))]
        win = (max(nums) if best == "max" else min(nums)) if nums else None
        lose = (min(nums) if best == "max" else max(nums)) if nums else None
        cells = []
        for v in vals:
            if v is None:
                cells.append('<td class="n" style="color:var(--dim)">—</td>')
                continue
            cls = "best" if v == win and len(set(nums)) > 1 else ("worst" if v == lose and len(set(nums)) > 1 else "")
            cells.append(f'<td class="n {cls}">{fmt(v)}</td>')
        return f"<tr><td>{label}{note}</td>{''.join(cells)}</tr>"

    head = "".join(f'<th style="text-align:right">{esc(b["label"])}</th>' for b in bs)
    shapes = "".join(f'<td class="n" style="color:var(--dim);font-size:.78rem">{esc(b["shape"])}</td>' for b in bs)
    prov = "".join(
        '<td class="n"><span class="pill %s">%s</span></td>'
        % (("p-mixed", "mixed dates") if len(b["dates"]) > 1 else ("p-clean", "one round"))
        for b in bs
    )

    rows = [
        f"<tr><td>shape</td>{shapes}</tr>",
        f"<tr><td>provenance</td>{prov}</tr>",
        row("<strong>completion</strong>", lambda v: f"{v:.2f}%", lambda b: b["completion"]),
        row("perfect scores", lambda v: f"{v}", lambda b: b["perfect"]),
        row("partial", lambda v: f"{v}", lambda b: b["partial"]),
        row("<strong>zeros</strong>", lambda v: f"{v}", lambda b: b["zeros"], best="min"),
        row("native rung", lambda v: f"{v:.0f}%", lambda b: b["native_pct"]),
        row("process measured", lambda v: f"{v} / 106", lambda b: b["process_measured"]),
        row("wall clock", lambda v: f"{v:.1f} h", lambda b: b["hours"], best="min"),
        row("cost", lambda v: f"${v:.4f}", lambda b: COST[b["key"]][0], best="min"),
    ]
    cost_notes = "".join(
        f'<tr><td class="id">{esc(b["label"])}</td><td>{esc(COST[b["key"]][1])}</td></tr>' for b in bs
    )

    # per-task, only where the leaderboard publishes a field mean
    trows = []
    for t in sorted(FIELD):
        cells = []
        for b in bs:
            s = b["per_task"].get(t)
            cells.append(f'<td class="n">{s*100:.0f}%</td>' if s is not None else '<td class="n">—</td>')
        m = by["mixture"]["per_task"].get(t)
        delta = (m * 100 - FIELD[t]) if m is not None else None
        dcls = "best" if delta and delta > 0 else "worst"
        trows.append(
            f'<tr><td class="id">{esc(t)}</td>{"".join(cells)}'
            f'<td class="n" style="color:var(--dim)">{FIELD[t]:.1f}%</td>'
            f'<td class="n {dcls}">{delta:+.0f}</td></tr>'
        )

    mix = by["mixture"]
    zeros_line = ", ".join(
        f'{esc(b["label"])} {b["zeros"]}' for b in bs
    )

    html = Template(PAGE).substitute(
        css=CSS, head=head, rows="".join(rows), cost_notes=cost_notes,
        trows="".join(trows), zeros_line=zeros_line,
        mix_completion=f'{mix["completion"]:.2f}',
        opus_completion=f'{by["opus"]["completion"]:.2f}',
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8", newline="\n")
    print(f"wrote {OUT} ({len(html)} bytes)")
    return 0


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Perpetum on Harness-Bench — five model backends</title>
<style>$css</style>
</head>
<body>
<div class="wrap">

<h1>Perpetum on Harness-Bench</h1>
<p class="sub">Five model backends over the same 106 tasks · 2026-08-10 · scores from each round's
result files, spend from Perpetum's journal</p>

<h2>The five rounds</h2>
<div class="tbl scroll">
<table>
<thead><tr><th>&nbsp;</th>$head</tr></thead>
<tbody>$rows</tbody>
</table>
</div>

<div class="note bad">
  <p><strong>Read the provenance row before the scores.</strong> These five rounds did not run against
  the same harness. Opus, Sonnet and Pro ran on a Perpetum build that predates this session's fixes;
  Flash and the mixture ran after them. So a difference between an early round and the mixture is a
  difference in <em>two</em> things at once, and the mixture's lead cannot be attributed to the model
  arrangement alone.</p>
  <p>Two directories also hold runs from more than one date. <strong>Sonnet is 92 original results
  plus 14 re-runs</strong> made after the fixes, which is why it reads 70.26% here against the 61.67%
  its own round produced — the re-runs replaced its worst tasks. <strong>Flash is 100 post-fix results
  plus 6 stale ones.</strong> Neither is a clean single round, and averaging over that silently is the
  mistake this project keeps catching.</p>
</div>

<h2>What the mixture is</h2>
<p class="lede">One model per role rather than one model for everything. Chains are best-first;
the coder's and verifier's chains share no link, so no failover can produce self-review.</p>
<div class="tbl scroll">
<table>
<thead><tr><th>role</th><th>chain</th><th>reasoning</th></tr></thead>
<tbody>
<tr><td class="id">planner</td><td class="id">opus &rarr; ds-pro</td><td>judgment, low volume</td></tr>
<tr><td class="id">coder</td><td class="id">opus &rarr; ds-fast</td><td>best measured completion, cheap native fallback</td></tr>
<tr><td class="id">verifier</td><td class="id">ds-pro &rarr; sonnet</td><td>a different family from the coder</td></tr>
<tr><td class="id">gatefixer</td><td class="id">ds-fast &rarr; sonnet</td><td>mechanical; native rung, pennies</td></tr>
<tr><td class="id">chat</td><td class="id">sonnet &rarr; ds-fast</td><td>interactive &mdash; latency over depth</td></tr>
<tr><td class="id">compactor</td><td class="id">ds-fast &rarr; sonnet</td><td>highest volume, cheapest metered</td></tr>
</tbody>
</table>
</div>

<h2>The result that is not a rounding difference</h2>
<div class="note good">
  <p><strong>Zeros, by backend: $zeros_line.</strong></p>
  <p>The mixture finished 106 tasks without a single zero. Completion at $mix_completion% against
  Opus's $opus_completion% is worth little on its own — run-to-run variance moved 53 of 106 tasks
  between two runs of identical code — but <em>zero zeros</em> is a different kind of claim. A zero is
  a task the harness abandoned, and abandoning nothing across a full suite is the property an
  unattended harness is actually judged on.</p>
  <p>The shape backs it up: the mixture has the same 25 perfect scores as Opus and more partials.
  It lands something everywhere rather than excelling narrowly and failing elsewhere.</p>
</div>

<h2>Against the public leaderboard</h2>
<p class="lede">Sixteen tasks where <code>harness-bench.ai/leaderboard.html</code> publishes a field
mean across seven harnesses and eight models. Comparing per task controls for difficulty; comparing
totals does not.</p>
<div class="tbl scroll">
<table>
<thead><tr><th>task</th>$head<th style="text-align:right">field</th><th style="text-align:right">mix &minus; field</th></tr></thead>
<tbody>$trows</tbody>
</table>
</div>
<div class="note">
  <p><strong>On those sixteen the mixture averages 91.8% against a field mean of 84.7%</strong> &mdash;
  ahead on thirteen. The leaderboard's best pair is Nanobot / GPT-5.4 at 81.3% combined, 85.1%
  completion; its best harness is Codex at 80.4% combined.</p>
  <p><strong>Our combined score is not comparable to theirs, and is inflated.</strong> The process
  rubric returned HTTP 429 for every task in every round, so <code>process_effective</code> silently
  defaults to <strong>1.0</strong> and combined collapses to completion. Every leaderboard entry
  carries a real process multiplier between 83% and 96%, which lowers theirs. Applying a realistic
  ~91% would put the mixture near 73% combined rather than 80%.</p>
  <p>A scored round that reports process as perfect because it could not measure it is exactly the
  unearned green this harness exists to refuse. It is the benchmark's defect rather than Perpetum's,
  and it is the first thing to fix before any of these numbers are quoted.</p>
</div>

<h2>Cost</h2>
<div class="tbl scroll">
<table>
<thead><tr><th>backend</th><th>how the figure was arrived at</th></tr></thead>
<tbody>$cost_notes</tbody>
</table>
</div>
<div class="note">
  <p>Pro's round recorded <strong>&#36;0.0000 across 1,205 priced calls</strong> because it ran before its
  prices were configured &mdash; the journal faithfully recorded what the config said. Reconstructing
  from journal tokens gives <strong>&#36;1.1882</strong>. The method is validated against Flash, where a
  measured figure exists: reconstruction returns <strong>&#36;0.6399</strong> against a measured
  <strong>&#36;0.6399</strong>, to four decimals.</p>
  <p>The mixture's &#36;0.4545 is its DeepSeek half only. Its Opus and Sonnet calls are subscription-billed
  and cost nothing per token, which also means the binding's money ceiling cannot see them &mdash; the
  real bound on those links is a rate limit <code>L-9</code> has no view of.</p>
</div>

<h2>What these rounds found in the harness</h2>
<p class="lede">The scores are the smaller half. Running a mixture exercised paths a single model never
touches, and three defects surfaced that single-model rounds had hidden.</p>
<div class="note bad">
  <p><strong><code>L-38</code> &mdash; the budget ceiling could not see the verifier.</strong>
  <code>self.spend</code> was incremented in one place, the coder's loop. The verifier calls a link too
  &mdash; <code>V-5</code> requires a different one &mdash; journalled its call with the price, and
  added nothing to the total. Measured on <code>002-exec</code>: perp reported
  <em>spent 596 tokens, &#36;0.000000</em> while its own journal held 3,132 output tokens and &#36;0.002266
  across seven priced calls.</p>
  <p>The reporting error is embarrassing; the budget error is the one that matters, because
  <code>L-9</code> exists so an unattended run stops at a ceiling rather than finding it on a bill.
  A single-model round hides it — the same call is missed, but it is the same cheap model and the
  error looks like rounding. Fixed: journalling and counting now happen in one place.</p>
</div>
<div class="note bad">
  <p><strong><code>T-37</code> &mdash; work done through <code>shell</code> is invisible.</strong>
  <code>record_touched</code> counts a call only if its tool is <code>write</code>, <code>patch</code>,
  <code>delete</code> or <code>apply</code>; both it and <code>progressed</code> decide from the
  <em>tool's name</em>, while <code>L-24</code> says progress is whether a call actually mutated the
  workspace. Found on the pure-Claude control at <code>002-exec</code> — a task named <em>Run Real
  Shell Commands In The Workspace</em>, so the shape is guaranteed rather than unlucky. The coder used
  shell redirection, <code>touched</code> stayed empty, the step ended <em>"read and reported, but
  changed nothing"</em>, perp exited non-zero — and the oracle scored the workspace <strong>1.00</strong>.</p>
  <p>Four things read <code>touched</code> and all four were wrong at once, including <code>G-3</code>'s
  staging, which means the work would not have been committed. This is the second time: the function's
  own comment records <code>apply</code> being left out with the same consequences. A list of blessed
  tool names is a defect that recurs whenever a tool is added.</p>
</div>
<div class="note">
  <p><strong>The results directory was named after one model.</strong> A mixture has no single "the"
  model, and the bench named its directory after whichever link answered last — a mixture round landed
  under <code>deepseek-v4-pro/</code> while its coder was Opus. Configs can now declare their own slug.</p>
  <p><strong>Five tasks had never run.</strong> <code>003</code>, <code>006</code>, <code>078</code>,
  <code>081</code> and <code>088</code> need a public URL for a loopback mock server and had failed at
  setup in every previous round. They need one environment variable, not a tunnel. All five ran here;
  <code>003</code>, <code>006</code> and <code>081</code> scored 1.00.</p>
</div>

<h2>What this does not show</h2>
<ul>
  <li><strong>The rounds are not controlled.</strong> Three ran on an older Perpetum. The mixture's
  lead over Opus is a difference in the model arrangement <em>and</em> in six requirements' worth of
  fixes, and nothing here separates them.</li>
  <li><strong>Two rounds' data is mixed</strong> — Sonnet and Flash both contain results from more than
  one date, marked in the provenance row.</li>
  <li><strong>Process is unmeasured everywhere.</strong> 0 of 106 in every round; the rubric 429s.</li>
  <li><strong>Native-rung percentages read 0% for the mixture</strong>, which is an artefact: turn
  records cover the coder's loop only, and the mixture's coder is a <code>claude-cli</code> link that
  can never reach the native rung. Its DeepSeek roles do, and no turn record says so.</li>
  <li><strong>Two tasks are scored on a tenth of themselves.</strong> <code>008</code> and
  <code>013</code> carry a 0.9 semantic weight whose judge also returns 429.</li>
  <li><strong>One round, each.</strong> Between two runs of identical code, 53 of 106 tasks moved and
  25 got worse. Differences under a few points are noise.</li>
</ul>

<footer>
Completion is the oracle's <code>outcome_score</code>, meaned over 106 tasks. Spend is summed from
Perpetum's journal, one record per call (<code>M-11</code>). Field means are from
<a href="https://www.harness-bench.ai/leaderboard.html">harness-bench.ai/leaderboard.html</a>,
which ranks on combined score across 7 harnesses and 8 model backends.
</footer>

</div>
</body>
</html>
"""

if __name__ == "__main__":
    raise SystemExit(main())
