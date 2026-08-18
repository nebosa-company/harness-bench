# The four-round comparison report

Builds `perpetum.io/docs/build/comparisson.html` — four HarnessBench rounds side
by side, every metric the result files can honestly support.

## Reproduce it

From the **repository root**, not from `tools/`:

```bash
python tools/collect_comparison.py && python tools/render_comparison.py
```

Roughly a minute, most of it in the collector. Deterministic: same inputs, same
page. No model is called at any point.

## The PDF

`render_comparison.py` carries a print stylesheet, so the page can be printed
without losing anything. That matters more than it sounds: every table lives in
an `overflow-x:auto` box, and on paper the overflow is simply cut off — a raw
print drops the two rightmost columns of every wide table with nothing to say
they were ever there. The print rules open those boxes, turn the page landscape,
force the light palette, keep background colours (the task map and the
value-stream bars are meaningless without them), and repeat table headers across
pages.

Any Chromium will do. With Edge, from the repository root:

    msedge.exe --headless=new --disable-gpu --no-pdf-header-footer
      --print-to-pdf="<repo>/perpetum.io/docs/build/comparisson.pdf"
      "file:///<repo>/perpetum.io/docs/build/comparisson.html"

all on one line — the binary lives under
`C:\Program Files (x86)\Microsoft\EdgeCore\<version>\msedge.exe`. Edge writes
registry warnings to stderr on a headless run; they are telemetry noise, not
failures. The PDF does not rebuild itself, so regenerate it whenever the HTML
changes.

## What is what

| file | role |
| --- | --- |
| `collect_comparison.py` | reads the rounds, writes `four-rounds.json` |
| `render_comparison.py` | reads `four-rounds.json`, writes the HTML |
| `four-rounds.json` | the handoff — one flat row per `(run, task)` |
| `task-domains.json` | task id → domain and human title, for the 106 tasks |

Same shape as `collect6.py` / `render6.py` / `six-backends.json`, and it borrows
that pair's per-MTok price table verbatim so the two reports price a round the
same way.

## Where the numbers come from

No single file holds all of it. The collector pulls from four places:

- **the result JSON** (`data_try6/results/<harness>/<model>/*.json`) — scoring,
  oracle checks, usage summary, elapsed time, adapter exit state
- **the adapter's stdout**, parsed out of the same JSON — the tool calls the
  model actually emitted, and the results that came back looking like failures
- **Perpetum's journal** (`<sandbox>/perpetum-state/.harness/journal.jsonl`) —
  latency, priced calls, charge, roles, refused reviews. dsh keeps no journal, so
  every metric derived from here is a dash in its column
- **the sandbox directory name** — stamped `…-YYYYMMDD-HHMMSS-<hash>` when the
  task started. This is the only reliable clock in the round: result-file mtimes
  lag over the WSL `/mnt/d` mount and a regrade rewrites them all.

Two consequences worth knowing before reading the page. The journal and the
adapter stdout live in **the sandbox**, not in the results tree — delete
`D:\harness-bench-work\sandbox` and tool calls, latency, priced calls, cost and
the wall clock all become dashes, while the scores keep working. And a round
still running is handled: the collector distinguishes a task **dropped** (below
the round's own frontier, no result file) from one **not yet run** (beyond it),
so an unfinished round is not charged for work it was never given.

## The four rounds

Registered at the top of `collect_comparison.py`. Adding or swapping one is a
`RUNS` entry plus a matching `IDENTITY` entry in the renderer.

| key | results directory | scoring pass |
| --- | --- | --- |
| `grok` | `perpetum-grok/unknown-api` | first |
| `pflash` | `perpetum-deepseek/deepseek-v4-flash` | first |
| `dsh` | `dsh-deepseek-flash/deepseek-v4-flash` | first |
| `opus` | `perpetum-opus/opus` | `.regraded.json` |

Opus reads the regraded files because its first pass had no proxy trace and
scored outcome only. The other three are first-pass. That mismatch is stated in
the report rather than hidden.

## What will not update itself

Everything numeric is computed at render time. Four blocks are hand-gathered
constants and will go stale if the rounds are re-run:

- **`IDENTITY`** (`render_comparison.py`) — harness versions, the model string on
  the wire, thinking mode, request parameters, round dates. None of this is in
  the result files: the versions came from `perp --version` and `git describe` in
  the dsh repo, the wire facts from reading captured request bodies under
  `usage-proxy/responses/`.
- **The machine section** — host and WSL2 specs, read off the machine once.
- **`PRICES` / `PRICE_OF`** — copied from `collect6.py`. If prices move there,
  move them here.
- **`task-domains.json`** — scraped once out of the built
  `perpetum-harness-bench.html`. If the suite gains a task, this needs
  regenerating or the task lands in `unclassified`.

The prose is also written, not generated. Figures interpolate into it, so the
numbers in a sentence stay right; the *claim* around them does not. If a
re-run reverses the standings, sentences like "dsh leads the suite" need editing
by hand.

## The statistical section

A Lean / Six Sigma reading of the same rounds, all of it derived — nothing new is
collected for it. Definitions, because each one is a choice:

- **DPMO / sigma level** — an oracle check is one pass/fail opportunity, which is
  the closest thing the suite has to a unit of conformance. Sigma uses the usual
  1.5-shift convention.
- **Rolled throughput yield** — adapter completed x oracle perfect x rubric
  perfect x security clean. The odds a task clears every gate with nothing to redo.
- **Cpk** — against a one-sided lower spec of 0.70, set in `LSL`. See the caveat
  in the report: the index assumes a roughly normal process and these scores are
  bounded and left-skewed, so only its conclusion is safe, not its value.
- **I-MR control limits** — mean +/- 2.66 x mean moving range, over tasks in id
  order. Points outside are named in the report rather than averaged away.
- **Process cycle efficiency** — summed per-call latency over lead time. Reads
  92-96%, which is inverted from a factory floor: nearly all the clock is the
  model thinking and the harness is 4-8% of it. Suppressed if it computes above
  100%, which would mean calls overlapped and the sum is not a duration.
- **Pareto** — points forfeited (1 - combined) per domain, summed across all four
  rounds, sorted, with a cumulative column.

`dsh` is a dash on everything latency-derived, PCE included: it keeps no journal
and the proxy log carries no timestamps.

## Two metrics that are not what they look like

**Failing tool results is a heuristic.** Neither harness flags a failed call. dsh
returns results as `role: tool` messages; Perpetum inlines them in the next user
turn inside `<<< name output >>>` fences. Each is read on its own terms — a
non-zero `[exit N]` for Perpetum, plus a shared marker list. Read them as
harness-internal rates, not a strict like-for-like.

**Tool calls needs two rows.** The proxy trace covers every metered link but not
`claude-cli`, which is a subprocess with no captured body. The journal covers
every Perpetum round but not dsh. Neither is complete; averaging them would
invent a number, so both are printed with dashes where they do not reach.
