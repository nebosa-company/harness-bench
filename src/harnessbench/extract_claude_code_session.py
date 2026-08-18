"""Read a Claude Code session transcript into the shape the process rubric wants.

Claude Code authenticates against a subscription, so it is a subprocess rather
than an address and nothing can sit between it and the provider -- which is why
the usage proxy sees nothing and `extract_proxy_trace` has no `responses/` to
read. That was taken for a while to mean a subscription round cannot be scored.
It does not. Claude Code writes a complete transcript of every turn and tool
call to `~/.claude/projects/<slug>/<session-id>.jsonl`, and that file is a
richer record than the wire trace: it has the tool results too, not just the
requests that produced them.

So this is the same move `perpetum_journal` makes for Perpetum -- score the
harness from the log it already keeps, instead of from a proxy it cannot be
put behind -- and it emits the same structure `extract_proxy_trace` does, so
the rubric cannot tell which one it is reading.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def _blocks(content: Any) -> list[dict[str, Any]]:
    """Claude Code sends a bare string for simple turns and a list otherwise."""
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return [b for b in (content or []) if isinstance(b, dict)]


def uuid_for_session(session_id: str, round_index: int = 1) -> str:
    """The transcript name for a bench session id.

    Claude Code rejects a non-UUID `--session-id` outright, so the launcher
    passes a UUID5 derived from the bench id rather than the id itself. Deriving
    it -- here and there, from the same namespace and the same string -- rather
    than minting a random one is what lets the scorer find the transcript later
    with nothing having been recorded in between.
    """
    import uuid
    name = "harnessbench://" + session_id + "#" + str(round_index)
    return str(uuid.uuid5(uuid.NAMESPACE_URL, name))


def session_file(session_id: str, workspace: str | os.PathLike[str] | None = None,
                 root: Path | None = None) -> Path | None:
    """Find the transcript for a session id.

    The per-project directory is named after the workspace path with separators
    beaten into dashes, but that encoding is Claude Code's to change -- so the
    session id is searched for by name across every project rather than derived,
    and `workspace` only orders the search.
    """
    root = root or (Path.home() / ".claude" / "projects")
    if not root.is_dir():
        return None
    hit = sorted(root.glob(f"*/{session_id}.jsonl"))
    return hit[0] if hit else None


def session_file_for_workspace(workspace: Path, root: Path | None = None) -> list[Path]:
    """Find a transcript from the workspace it ran in.

    Claude Code names each project directory after the working directory, with
    the separators beaten into dashes. Rather than reproduce that encoding --
    which is Claude Code's to change -- this matches on the sandbox's own leaf
    name, which is unique per task run and appears verbatim inside it. The
    newest transcript in the matching directory wins, so a re-run of the same
    task is read rather than its predecessor.
    """
    root = root or (Path.home() / ".claude" / "projects")
    if not root.is_dir():
        return None
    leaf = Path(workspace).name
    stem = Path(workspace).parent.name if leaf == "workspace" else leaf
    if not stem:
        return None
    found: list[Path] = []
    for d in root.iterdir():
        if not d.is_dir() or stem not in d.name:
            continue
        found.extend(d.glob("*.jsonl"))
    # Oldest first: a multi-round task writes one transcript per round into the
    # same directory, and the rubric reads them as one run in the order they
    # happened. Returning only the newest scored the last round of a five-round
    # task as though it were the whole thing.
    return sorted(found, key=lambda f: f.stat().st_mtime)


def extract_claude_code_session(session_path: Path) -> dict[str, Any]:
    if not session_path or not Path(session_path).is_file():
        return {"session_file": str(session_path), "rounds": [], "totals": {},
                "error": "missing session transcript"}

    records: list[dict[str, Any]] = []
    for line in Path(session_path).read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # a transcript being appended to can end mid-line
    if not records:
        return {"session_file": str(session_path), "rounds": [], "totals": {},
                "error": "empty session transcript"}

    unified: list[dict[str, Any]] = []
    rounds: list[dict[str, Any]] = []
    totals = {"llm_rounds": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0}

    for rec in records:
        kind = rec.get("type")
        if kind not in ("user", "assistant"):
            continue  # titles, queue operations and other bookkeeping
        msg = rec.get("message") or {}
        blocks = _blocks(msg.get("content"))

        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        tool_calls = [
            {"name": b.get("name"), "arguments": b.get("input") or {}}
            for b in blocks if b.get("type") == "tool_use"
        ]
        agent = rec.get("agentName") or rec.get("agent") or "main"

        entry: dict[str, Any] = {"role": kind, "content": text, "agent": agent}
        if tool_calls:
            entry["tool_calls"] = tool_calls
        # A tool result arrives as a user turn with no text; keep it as the
        # result it is, so the rubric can see what came back rather than a blank.
        results = [b for b in blocks if b.get("type") == "tool_result"]
        if kind == "user" and results and not text:
            entry["content"] = "\n".join(
                b.get("content") if isinstance(b.get("content"), str)
                else json.dumps(b.get("content"), ensure_ascii=False)
                for b in results
            )
            entry["role"] = "tool"
        unified.append(entry)

        if kind != "assistant":
            continue

        u = msg.get("usage") or {}
        inp = int(u.get("input_tokens") or 0)
        out = int(u.get("output_tokens") or 0)
        cache_r = int(u.get("cache_read_input_tokens") or 0)
        cache_w = int(u.get("cache_creation_input_tokens") or 0)
        rounds.append({
            "response_file": rec.get("uuid") or "",
            "provider": "anthropic",
            # The transcript names the model on every assistant message. Carried
            # through because it is what prices the round and what names the
            # results directory -- without it a run lands under `unknown-api/`
            # and its cost reads `no price on file for ''`.
            "model": str(msg.get("model") or "").strip(),
            "agent": agent,
            "new_messages": [],
            "assistant_text": text,
            "tool_calls": tool_calls,
            "usage": {
                "input_tokens": inp,
                "output_tokens": out,
                "cache_read_tokens": cache_r,
                "cache_write_tokens": cache_w,
                "total_tokens": inp + out + cache_r + cache_w,
            },
        })
        totals["llm_rounds"] += 1
        totals["input_tokens"] += inp
        totals["output_tokens"] += out
        totals["total_tokens"] += inp + out + cache_r + cache_w

    return {
        "session_file": str(session_path),
        "extract_mode": "claude_code_session",
        "unified_transcript": unified,
        "rounds": rounds,
        "totals": totals,
    }
