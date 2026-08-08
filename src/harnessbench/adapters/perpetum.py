from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from harnessbench.adapters.base import BaseAdapter
from harnessbench.models import AdapterRunContext, AdapterRunResult
from harnessbench.usage_proxy import register_routes

# Perpetum's per-kind default endpoints (perp-core/src/link.rs::default_base_url).
# A link that names `base_url` wins over the default, which is what lets the
# usage proxy sit in front of a cloud link without Perpetum knowing.
DEFAULT_BASE_URL = {
    "lmstudio": "http://localhost:1234",
    "ollama": "http://localhost:11434",
    "vllm": "http://localhost:8000",
    "openai": "https://api.openai.com",
    "anthropic": "https://api.anthropic.com",
    "deepseek": "https://api.deepseek.com",
    "grok": "https://api.x.ai",
}

# Kinds that are not an address: an LM Link peer is selected on the host, and a
# `claude-cli` link is a subprocess. Neither can be proxied.
UNADDRESSED_KINDS = {"lmlink", "claude-cli"}

# Perpetum keeps its own state under `.harness/` in the workspace root, because
# the tool host is rooted there and the model may not write outside it. The
# oracle grades the workspace, so the scaffolding is moved out before grading
# and moved back in for the next round of a multi-round task.
HARNESS_DIR = ".harness"

# Beyond this the brief goes in a file instead of on the command line. Every
# task in the suite is well under it today; this is insurance against a Windows
# command line, not a routine path.
MAX_BRIEF_CHARS = 8000

# Perpetum's routes ask the bench proxy to relay server-sent events rather than
# buffer them, and that is a measurement decision rather than a preference.
#
# The proxy reads each upstream response to completion before answering. For a
# harness that only reads the final message that is invisible; Perpetum fails
# over a link that says nothing for twenty seconds (`M-23`), counted from the
# *first* token — which through a buffering proxy is the last one. Measured on
# 021-batch-rename-transform: two calls at 2.1s and 5.5s succeeded, the third
# generated for longer than twenty seconds, and the batch was recorded as
# blocked on a link that had answered. That is proxy latency scored as
# Perpetum's behaviour.
#
# `stream` on the route fixes it without touching any other harness's timing.
# Going through the proxy is still worth it: `usage-proxy/responses/` is what
# the process rubric reads, and a run without it can only be scored on outcome.
USE_PROXY_DEFAULT = True

_SPEND = re.compile(
    r"spent\s+(?P<tokens>[\d,]+)\s+tokens,\s*(?P<seconds>[\d.]+)s,\s*\$(?P<money>[\d.]+)"
)
_TURN = re.compile(r"turn:\s*(?P<rung>\S+)\s+rung,\s*(?P<calls>\d+)\s+calls,\s*via\s+(?P<link>\S+)")


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _resolve_project_path(raw: str | Path) -> Path:
    p = Path(os.path.expanduser(str(raw)))
    if not p.is_absolute():
        p = _project_root() / p
    return p.resolve()


def _links_block(
    links: dict[str, Any],
    roles: dict[str, Any],
    proxy_base_url: str = "",
    proxy_routes_file: Path | None = None,
) -> str:
    """Render `.harness/links.md` and return it with the proxied upstreams.

    Perpetum reads the fenced ``perp-links`` block and nothing else in the file,
    so the prose around it is for whoever opens the sandbox afterwards.
    """
    if not links:
        raise ValueError("perpetum adapter requires model_config.links (or model_config.user_config)")

    routes: dict[str, dict[str, str]] = {}
    lines: list[str] = []

    for name, raw in links.items():
        cfg = dict(raw or {})
        kind = str(cfg.pop("kind", "")).strip()
        if not kind:
            raise ValueError(f"link `{name}` has no kind")
        price = cfg.pop("price", None) or cfg.pop("prices", None) or {}

        base_url = str(cfg.pop("base_url", "") or "").strip()
        upstream = base_url or DEFAULT_BASE_URL.get(kind, "")
        if proxy_base_url and proxy_routes_file is not None and kind not in UNADDRESSED_KINDS and upstream:
            prefix = f"/perpetum/{name}"
            routes[prefix] = {
                "framework": "perpetum",
                "provider": name,
                "upstream": upstream,
                "stream": True,
            }
            base_url = f"{proxy_base_url.rstrip('/')}{prefix}"

        lines.append(f"link.{name}.kind = {kind}")
        if base_url:
            lines.append(f"link.{name}.base_url = {base_url}")
        for key, value in cfg.items():
            if value is None or value == "":
                continue
            lines.append(f"link.{name}.{key} = {value}")
        for field, value in dict(price).items():
            lines.append(f"price.{name}.{field} = {value}")
        lines.append("")

    for role, chain in (roles or {}).items():
        target = ", ".join(str(x) for x in chain) if isinstance(chain, list) else str(chain)
        lines.append(f"role.{role} = {target}")

    if routes:
        register_routes(proxy_routes_file, routes)

    body = "\n".join(lines).strip()
    text = (
        "# Links\n\n"
        "Written by HarnessBench's perpetum adapter for one benchmark task. A\n"
        "cloud link's `base_url` points at the bench usage proxy so tokens are\n"
        "counted the same way they are for every other harness.\n\n"
        f"```perp-links\n{body}\n```\n"
    )
    return text


def _patch_binding(path: Path, gate: str, budget: dict[str, Any], map_budget: Any) -> None:
    """Turn the scaffold `perp init` writes into one that will actually run.

    `perp init` leaves `gate.test` commented out on purpose — the harness
    refuses to run until a project says what "working" means. A benchmark task
    is graded by the oracle rather than by a gate, so the gate here is a real
    command that is trivially green: it satisfies the binding without adding a
    second, competing definition of done.
    """
    text = path.read_text(encoding="utf-8")
    text = text.replace("# gate.test  = <your test command>", f"gate.test = {gate}")

    replacements = {
        "budget.cycle.money": budget.get("cycle_money"),
        "budget.cycle.seconds": budget.get("cycle_seconds"),
        "budget.batch.money": budget.get("batch_money"),
        "budget.batch.seconds": budget.get("batch_seconds"),
    }
    for key, value in replacements.items():
        if value is None:
            continue
        text = re.sub(rf"(?m)^{re.escape(key)}\s*=.*$", f"{key} = {value}", text)

    if map_budget is not None:
        text = text.replace("```perp-binding\n", f"```perp-binding\nmap.budget = {map_budget}\n", 1)

    path.write_text(text, encoding="utf-8")


def _mint_requirement(path: Path, title: str) -> str:
    """Append one row to the requirements source and return the id it minted.

    Ids are minted here and nowhere else, which is Perpetum's own rule: `perp
    run --requirement` refuses an id that is not on the record. One id per
    round, so a two-round task leaves a journal that says which round did what.
    """
    text = path.read_text(encoding="utf-8")
    # The scaffold ships a placeholder row; drop it rather than work around it.
    text = re.sub(r"(?m)^\|\s*`R-1`\s*\|\s*Replace this row\..*$\n?", "", text)

    row_at = [m for m in re.finditer(r"(?m)^\|\s*`R-(\d+)`\s*\|.*$\n?", text)]
    used = {int(m.group(1)) for m in row_at}
    rid = f"R-{max(used) + 1 if used else 1}"
    row = f"| `{rid}` | {title.replace('|', '/').strip()} |\n"

    if row_at:
        at = row_at[-1].end()
    else:
        header = re.search(r"(?m)^\|\s*-+\s*\|\s*-+\s*\|.*$\n?", text)
        if header is None:
            text = text.rstrip("\n") + "\n\n| id | Requirement |\n|---|---|\n"
            at = len(text)
        else:
            at = header.end()
    path.write_text(text[:at] + row + text[at:], encoding="utf-8")
    return rid


def _long_path(path: Path) -> str:
    """A Windows path that is not subject to the 260-character `MAX_PATH` limit.

    Sandbox names carry the task id, the harness id and a timestamp, and a task
    id in this suite runs to 45 characters. Nothing here is long by choice — the
    total just crosses the limit for the longest-named tasks, and did: seven of
    them lost a finished run to `FileNotFoundError` on a 331-character path.
    """
    if os.name != "nt":
        return str(path)
    resolved = str(path.resolve())
    return resolved if resolved.startswith("\\\\?\\") else "\\\\?\\" + resolved


def _usage_from_journal(journal: Path, out: Path) -> int:
    """Translate Perpetum's journal into the session file the bench collects.

    Every model call is journalled as an outcome record carrying its role, link,
    model, cache-hit and cache-miss split, output tokens and charge (`M-11`).
    That is the same accounting the usage proxy would have reconstructed from
    the wire, so a run that skips the proxy is not a run with no numbers.

    ``cache_miss`` maps to ``input`` and ``cache_hit`` to ``cacheRead``, which
    is the split the proxy reports: prompt tokens *not* already held by the
    provider, counted apart from the ones that were.
    """
    if not journal.is_file():
        return 0
    rows: list[dict[str, Any]] = []
    for line in journal.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict) or "output_tokens" not in record:
            continue
        cache_hit = int(record.get("cache_hit", 0) or 0)
        cache_miss = int(record.get("cache_miss", 0) or 0)
        output = int(record.get("output_tokens", 0) or 0)
        charge = float(record.get("charge", 0) or 0)
        rows.append(
            {
                "message": {
                    "provider": str(record.get("link", "")),
                    "model": str(record.get("model", "")),
                    "role": str(record.get("role", "")),
                    "latency_ms": record.get("latency_ms"),
                    "usage": {
                        "input": cache_miss,
                        "output": output,
                        "cacheRead": cache_hit,
                        "cacheWrite": 0,
                        "totalTokens": cache_hit + cache_miss + output,
                        "cost": {"total": charge},
                    },
                }
            }
        )
    if not rows:
        return 0
    out.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n"
    with open(_long_path(out), "w", encoding="utf-8") as fh:
        fh.write(body)
    return len(rows)


def _kill_tree(pid: int) -> None:
    """Kill a process and everything it spawned."""
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            check=False,
            timeout=60,
        )
    else:
        os.killpg(os.getpgid(pid), 9)


def _run(cmd: list[str], cwd: Path, env: dict[str, str], timeout: int) -> tuple[str, str, int]:
    """Run `perp` under a timeout that is actually enforced.

    `subprocess.run(timeout=...)` kills the direct child and then drains its
    pipes — and a `claude-cli` link's grandchildren inherit the write end of
    those pipes. Killing `perp` alone leaves them holding it open, so the drain
    blocks and the timeout does not fire until they happen to exit on their own.

    Measured on 074-education-grading-feedback: a 2400s timeout returned after
    **14,088 seconds**, having already recorded the link failure at the four
    minute mark. Nearly four hours of a suite run spent waiting on a pipe.

    So: kill the tree, then bound the drain too.
    """
    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
        return stdout, stderr, proc.returncode
    except subprocess.TimeoutExpired:
        _kill_tree(proc.pid)
        try:
            stdout, stderr = proc.communicate(timeout=60)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = "", ""
        return stdout or "", f"{stderr or ''}\nperp timed out after {timeout}s", -1


def _parse_report(stdout: str) -> dict[str, Any]:
    report: dict[str, Any] = {"turns": []}
    spend = _SPEND.search(stdout)
    if spend:
        report["tokens"] = int(spend.group("tokens").replace(",", ""))
        report["seconds"] = float(spend.group("seconds"))
        report["money_usd"] = float(spend.group("money"))
    for turn in _TURN.finditer(stdout):
        report["turns"].append(
            {"rung": turn.group("rung"), "calls": int(turn.group("calls")), "link": turn.group("link")}
        )
    for line in stdout.splitlines():
        if "stopped:" in line:
            report["stopped"] = line.split("stopped:", 1)[1].strip()
            break
    return report


class PerpetumAdapter(BaseAdapter):
    """Run Perpetum (`perp`) over one HarnessBench task.

    Perpetum is a loop harness rather than a chat agent: it does not take a
    prompt, it takes a requirement id it can find on the record, and it drives
    a model against it under a journal, a budget and a permission classifier.
    So one bench task becomes one bound workspace, one minted requirement, and
    one `perp run --requirement`.
    """

    name = "perpetum"

    def run(self, ctx: AdapterRunContext) -> AdapterRunResult:
        command = str(ctx.model_config.get("command") or "perp")
        workspace = ctx.workspace.resolve()
        stash = ctx.sandbox / "perpetum-state"
        harness = workspace / HARNESS_DIR

        first_round = not (stash / HARNESS_DIR).is_dir()
        if first_round:
            init = self._init(command, workspace, ctx)
            if init is not None:
                return init
        else:
            # A later round of a multi-round task: the journal is the harness's
            # memory across process lifetimes, so it comes back rather than
            # being rebuilt. This is the one place Perpetum's design shows up
            # in the adapter — nothing lives only in a context window.
            shutil.move(str(stash / HARNESS_DIR), str(harness))

        requirements = harness / "requirements" / "requirements.md"
        rid = _mint_requirement(requirements, ctx.task.title or ctx.task.task_id)

        brief = ctx.prompt
        brief_file = None
        if len(brief) > MAX_BRIEF_CHARS:
            brief_file = harness / f"brief-{rid}.md"
            brief_file.write_text(ctx.prompt, encoding="utf-8")
            brief = (
                f"Your task is written in `{HARNESS_DIR}/{brief_file.name}`. "
                "Read that file first, then do exactly what it says."
            )

        cmd = [
            command,
            "run",
            "--root",
            str(workspace),
            "--requirement",
            rid,
            "--brief",
            brief,
            "--cycle",
            str(ctx.model_config.get("cycle", 1)),
            "--stage",
            str(ctx.model_config.get("stage", "D")),
        ]
        if ctx.model_config.get("local_only"):
            cmd.append("--local-only")
        if ctx.model_config.get("verbose"):
            cmd.append("--verbose")

        env = os.environ.copy()
        env.update(ctx.env)
        env["HOME"] = str(ctx.sandbox)
        env["WORKSPACE"] = str(workspace)

        stdout, stderr, returncode = _run(cmd, workspace, env, ctx.timeout_sec)

        metadata: dict[str, Any] = {
            "returncode": returncode,
            "requirement": rid,
            "workspace": str(workspace),
            "harness_dir": str(stash / HARNESS_DIR),
            "brief_file": str(brief_file) if brief_file else "",
            "report": _parse_report(stdout),
        }
        keep = bool(ctx.model_config.get("keep_harness_in_workspace"))
        metadata.update(self._stash(harness, stash, keep=keep))

        # `state_dir` is what runner._collect_usage_summary looks under when the
        # proxy saw nothing, which is the normal case for an unaddressed link.
        #
        # It points at a directory holding exactly one `.jsonl` and a fixed
        # short name, not at the stash: the collector's last resort is the
        # newest `*.jsonl` anywhere underneath, and pointing it at the stash
        # would leave that choice racing Perpetum's own `journal.jsonl`. The
        # fixed name also keeps the path off the session id, which carries the
        # task id twice over and is what overflowed `MAX_PATH`.
        #
        # Wrapped, because this is bookkeeping written *after* the work is done:
        # a run that finished and was graded must not be thrown away over the
        # file that records what it cost.
        journal = (harness if keep else stash / HARNESS_DIR) / "journal.jsonl"
        usage_root = stash / "usage"
        try:
            metadata["model_calls"] = _usage_from_journal(journal, usage_root / "sessions" / "usage.jsonl")
            metadata["state_dir"] = str(usage_root)
        except OSError as exc:
            metadata["usage_error"] = str(exc)

        return AdapterRunResult(
            ok=returncode == 0,
            command=cmd,
            stdout=stdout,
            stderr=stderr,
            metadata=metadata,
        )

    def _init(self, command: str, workspace: Path, ctx: AdapterRunContext) -> AdapterRunResult | None:
        """Bind the workspace. Returns a failed result, or None when bound."""
        env = os.environ.copy()
        env.update(ctx.env)
        env["HOME"] = str(ctx.sandbox)
        try:
            init = subprocess.run(
                [command, "init", "--root", str(workspace)],
                cwd=str(workspace),
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=120,
                env=env,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return AdapterRunResult(ok=False, stderr=f"perp init failed: {exc}")
        if init.returncode != 0:
            return AdapterRunResult(
                ok=False,
                command=[command, "init", "--root", str(workspace)],
                stdout=init.stdout,
                stderr=init.stderr,
                metadata={"returncode": init.returncode},
            )

        harness = workspace / HARNESS_DIR
        gate = str(ctx.model_config.get("gate") or f"{sys.executable} -c pass")
        budget = dict(ctx.model_config.get("budget") or {})
        budget.setdefault("cycle_money", 1.00)
        budget.setdefault("batch_money", 1.00)
        # Wall-clock is HarnessBench's to enforce, so Perpetum's own clock is set
        # wide enough that the two do not race and every harness gets the same
        # budget the bench gave it.
        budget.setdefault("cycle_seconds", ctx.timeout_sec)
        budget.setdefault("batch_seconds", ctx.timeout_sec)
        _patch_binding(harness / "binding.md", gate, budget, ctx.model_config.get("map_budget"))

        user_config = ctx.model_config.get("user_config")
        if user_config:
            source = _resolve_project_path(str(user_config))
            if not source.is_file():
                return AdapterRunResult(ok=False, stderr=f"missing Perpetum links config: {source}")
            (harness / "links.md").write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        else:
            proxy = bool(ctx.model_config.get("use_usage_proxy", USE_PROXY_DEFAULT))
            text = _links_block(
                dict(ctx.model_config.get("links") or {}),
                dict(ctx.model_config.get("roles") or {}),
                proxy_base_url=str(ctx.env.get("HARNESSBENCH_LLM_PROXY_URL") or "") if proxy else "",
                proxy_routes_file=(
                    Path(ctx.env["HARNESSBENCH_LLM_PROXY_ROUTES"])
                    if proxy and ctx.env.get("HARNESSBENCH_LLM_PROXY_ROUTES")
                    else None
                ),
            )
            (harness / "links.md").write_text(text, encoding="utf-8")
        return None

    def _stash(self, harness: Path, stash: Path, keep: bool) -> dict[str, Any]:
        """Move `.harness/` out of the graded workspace, keeping the journal.

        The oracle scores the workspace, and a harness that leaves its own
        bookkeeping there is being graded on files the task never asked for.
        Everything is kept — under the sandbox, beside the other run artifacts.
        """
        out: dict[str, Any] = {}
        journal = harness / "journal.jsonl"
        if journal.is_file():
            out["records"] = sum(1 for line in journal.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip())
        if keep or not harness.is_dir():
            return out
        stash.mkdir(parents=True, exist_ok=True)
        target = stash / HARNESS_DIR
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        try:
            shutil.move(str(harness), str(target))
        except OSError as exc:
            out["stash_error"] = str(exc)
        return out
