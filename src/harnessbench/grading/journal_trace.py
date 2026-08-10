"""Build a process trace from Perpetum's journal when the wire cannot be read.

The process rubric grades a *usage-proxy* trace: the HTTP traffic between the
harness and its models, captured by a proxy sitting on the wire. That works for
an OpenAI-compatible link and cannot work for a `claude-cli` link, which is a
subprocess rather than an address — there is no wire to sit on. Three of six
Harness-Bench rounds therefore failed with `no proxy trace: missing responses/`
before the rubric was even attempted, and no rubric backend could have changed
that.

The journal is the other record of the same run, and for grading *process* it is
arguably the better one. A proxy sees the messages; the journal sees what the
loop decided and why — the step it was working on, the requirement it served,
the intent it stated before acting, whether the outcome was green, which link
answered, the verdict of the independent review, the gate transcripts, the
degradation decisions. That is closer to what the three process dimensions
actually ask about than a replay of prompt text.

The trace this produces is deliberately shaped like the proxy's so the rubric,
the payload truncation and the scoring path all stay unchanged.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

JOURNAL = ("perpetum-state", ".harness", "journal.jsonl")


def _records(sandbox: Path) -> list[dict[str, Any]]:
    path = sandbox.joinpath(*JOURNAL)
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            # A half-written last line is a torn write, not a corrupt journal —
            # take what parsed and carry on.
            continue
    return out


def _line(record: dict[str, Any]) -> str:
    """One journal record as a line the rubric can read."""
    bits: list[str] = []
    if step := record.get("step"):
        bits.append(f"[{step}]")
    if role := record.get("role"):
        link = record.get("link") or "?"
        model = record.get("model") or "?"
        bits.append(f"{role} via {link}/{model}")
    ok = record.get("ok")
    if ok is False:
        bits.append("FAILED")
    bits.append(str(record.get("summary") or ""))
    text = " ".join(b for b in bits if b)

    # The detail is where the evidence lives — a gate transcript, an error, the
    # verdict of a review. Kept, because a process grade with the evidence
    # removed is a grade of the summaries.
    detail = record.get("detail")
    if isinstance(detail, str) and detail.strip():
        text += "\n" + detail.strip()
    return text


def extract_journal_trace(sandbox: Path) -> dict[str, Any]:
    """A proxy-shaped trace built from the journal.

    Returns the same keys `extract_proxy_trace_incremental` returns, including
    `error` when there is nothing to read — a journal that does not exist is not
    an empty process, and reporting it as one would be the same unearned green
    the whole scoring path was just fixed to stop producing.
    """
    sandbox = Path(sandbox)
    records = _records(sandbox)
    if not records:
        return {
            "proxy_dir": str(sandbox.joinpath(*JOURNAL)),
            "rounds": [],
            "totals": {},
            "error": "no journal to read",
        }

    unified: list[dict[str, Any]] = []
    rounds: list[dict[str, Any]] = []
    calls = 0
    tokens_in = 0
    tokens_out = 0

    for record in records:
        text = _line(record)
        if not text.strip():
            continue
        # An intent is the loop saying what it is about to do; an outcome is what
        # happened. Mapped to user/assistant so the rubric reads a conversation
        # rather than a log, which is the shape its prompt expects.
        role = "user" if record.get("kind") == "intent" else "assistant"
        unified.append({"role": role, "provider": "perpetum-journal", "content": text})

        if record.get("link"):
            calls += 1
            tokens_in += (record.get("cache_hit") or 0) + (record.get("cache_miss") or 0)
            tokens_out += record.get("output_tokens") or 0
            rounds.append({
                "response_file": f"journal:{record.get('step', '?')}",
                "provider": record.get("link") or "perpetum",
                "new_messages": [],
                "assistant_text": text,
                "tool_calls": [],
                "usage": {
                    "input_tokens": (record.get("cache_hit") or 0) + (record.get("cache_miss") or 0),
                    "output_tokens": record.get("output_tokens") or 0,
                },
            })

    return {
        "proxy_dir": str(sandbox.joinpath(*JOURNAL)),
        "extract_mode": "perpetum_journal",
        "unified_transcript": unified,
        "rounds": rounds,
        "totals": {
            "llm_rounds": calls,
            "input_tokens": tokens_in,
            "output_tokens": tokens_out,
        },
    }
