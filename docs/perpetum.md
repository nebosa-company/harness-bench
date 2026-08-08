# Perpetum under HarnessBench

Perpetum (`perp`) is a loop harness rather than a chat agent, and the adapter is
mostly the work of translating between the two shapes.

Every other harness in this bench takes a prompt and a working directory.
Perpetum takes neither. It takes a **requirement id it can find on the record**,
resolves a **role** to a **link**, and drives the model against that requirement
under a journal, a budget, a permission classifier and a gate. Work that is not
on the record is not built — that refusal is the harness, not a setting.

So one bench task becomes one bound workspace, one minted requirement, and one
`perp run --requirement`.

## What the adapter does per task

| Step | Why |
|---|---|
| `perp init --root <workspace>` | Writes `.harness/` — binding, links, requirements, vision |
| Sets `gate.test` in the binding | `perp init` leaves it commented out and the harness refuses to run without it. A benchmark task is graded by the oracle, so the gate is a real command that is trivially green rather than a second, competing definition of done |
| Writes `.harness/links.md` | From `links` / `roles` in the harness config, or copied verbatim from `user_config` |
| Appends one row to the requirements source | `R-1` for round 1, `R-2` for round 2, and so on. This is the only place ids are minted, which is Perpetum's own rule |
| `perp run --requirement R-n --brief <prompt>` | The bench prompt is the brief; the task title is the requirement text |
| Moves `.harness/` out of the workspace | The oracle grades the workspace. A harness that leaves its own bookkeeping there is being graded on files the task never asked for. Everything is kept, under `sandbox/perpetum-state/` |

Multi-round tasks (`007-session-memory` and the rest of the long-running
autonomy set) restore `.harness/` before the next round, so one journal spans
every round of the task.

## Configuration

```jsonc
"perpetum-deepseek": {
  "adapter": "perpetum",
  "command": "perp",                  // or an absolute path to the binary
  "timeout_sec": 1800,
  "links": {
    "deepseek": {
      "kind": "deepseek",             // lmstudio · lmlink · ollama · vllm · openai
                                      // · anthropic · deepseek · grok
                                      // · openai-compat · claude-cli
      "model": "deepseek-v4-flash",
      "auth_env": "DEEPSEEK_API_KEY", // the variable's *name*, never its value
      "price": { "cache_hit": 0.0028, "cache_miss": 0.14, "output": 0.28 }
    }
  },
  "roles": { "coder": "deepseek", "chat": "deepseek", "verifier": "deepseek" },
  "use_usage_proxy": true,
  "budget": { "cycle_money": 1.00, "batch_money": 1.00 },
  "map_budget": 0
}
```

Any other scalar under a link passes straight through as
`link.<name>.<key> = <value>`, so `concurrency`, `privacy`, `device` and
anything Perpetum learns later need no adapter change. A role may name a chain
(`"coder": ["here", "deepseek"]`), which is the point of roles: the first
healthy, eligible link wins.

Other keys: `local_only` (no cloud link may answer), `verbose`, `cycle`,
`stage`, `gate`, `keep_harness_in_workspace`, `user_config` (a `links.md` copied
verbatim, for role chains the inline form cannot express).

The declared `auth_env` variable has to be set in the environment the bench runs
in. Perpetum fails a link whose credential is unset before it connects, which is
deliberate.

## The usage proxy has to stream

**This is the one thing that will bite anyone extending the adapter.**

The bench proxy reads each upstream response to completion before answering it.
For a harness that only reads the final message that is invisible. Perpetum
fails over a link that says nothing for twenty seconds (`M-23`), counted from
the **first** token — and through a buffering proxy the first token arrives when
the last one does.

Measured on `021-batch-rename-transform`: two calls returned in 2.1s and 5.5s,
the third generated for longer than twenty seconds, and the run was recorded as

> blocked: no link answered … said nothing for 20s — failed over rather than
> waited on (`M-23`)

for a link that had answered normally. That is proxy latency being scored as
Perpetum's behaviour.

`usage_proxy.py` now relays server-sent events as they arrive for any route
whose meta carries `"stream": true`, which the perpetum adapter sets and nothing
else does. No other harness's timing changes. With it on, the same task runs 28
turns and 54 tool calls to a normal finish.

Setting `use_usage_proxy: false` bypasses the proxy entirely. Usage is then read
out of Perpetum's journal instead — which carries cache-hit, cache-miss, output
tokens, latency and charge per call, more than the proxy sees — but
`usage-proxy/responses/` is what the process rubric reads, so the process score
is skipped and the task can only be scored on outcome.

## Reading a result

`adapter_result.metadata.report` carries Perpetum's own account of the run,
parsed from its stdout:

```json
{
  "turns": [{"rung": "native", "calls": 8, "link": "deepseek"}],
  "tokens": 264787,
  "seconds": 421.0,
  "money_usd": 0.0198,
  "stopped": "the backlog is exhausted"
}
```

`stopped` is worth reading on every failure. Perpetum stops for one of exactly
three named reasons — the backlog is exhausted, the batch is blocked, or a
budget parked it — and the blocked ones say what blocked them. `rung` is which
step of the tool-call degradation ladder the reply parsed at, which is a harness
property no outcome score exposes.

The full journal is at `sandbox/perpetum-state/.harness/journal.jsonl`, and
`perp explain <id>` will render the evidence chain from it after the fact.

## Known result: cross-round memory

`007-session-memory` scores 0.25 and reproduces. Round 1 accepts the passphrase
and writes `phase1_done.txt`; round 2 returns zero tool calls and writes
nothing.

This is a real property, not an adapter defect. Perpetum's memory across process
lifetimes is the journal on disk, and each `perp run --requirement` builds the
model's context from the item and its own tool results — the journal is not
replayed into it. A benchmark task that says "recall it using multi-turn
conversation memory only" is asking for the one thing this harness deliberately
does not keep in a context window.

`perp chat` is the conversational surface whose turns are journalled on both
sides. Routing rounds through `perp chat --once` would be a different mapping of
the same task, and a fair one to add — but it is a different harness
configuration, not a fix, and it should be scored as one.
