"""Run a full suite round with the environment a local run actually needs.

Exists because a round was started without it and lost five tasks. The
tunnel-dependent tasks — 003, 006, 078, 081, 088 — stand up a mock server on
loopback and then look for a *public* URL to hand the model, via each task's
`hooks.py::_start_public_tunnel`. With no `cloudflared` and no override they
raise before the task begins.

They need one environment variable, not a tunnel: the server is on loopback and
the harness under test runs on the same machine, so the local URL *is* the URL
to hand it. Setting it here rather than in a shell means the next round cannot
be started without it by someone who did not know to.

    python tools/run_round.py <harness-id> [--tunnel] [--from-num N] [--to-num N]
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


# `PATH` in an already-running shell predates anything installed since it
# started — cloudflared was installed into `C:\Program Files (x86)\cloudflared`
# and on the machine `PATH`, and `shutil.which` in this process still could not
# see it. Checking the install locations as well means "I installed it" and "the
# tool finds it" stop being different questions.
_TUNNEL_DIRS = [
    r"C:\Program Files (x86)\cloudflared",
    r"C:\Program Files\cloudflared",
    os.path.expandvars(r"%ProgramData%\chocolatey\bin"),
    os.path.expanduser(r"~\scoop\shims"),
]


def _find_tunnel() -> str | None:
    """cloudflared first: it needs no account, and ngrok without an authtoken
    opens no tunnel while still answering `which`."""
    for exe in ("cloudflared", "ngrok"):
        found = shutil.which(exe)
        if found:
            return found
        for d in _TUNNEL_DIRS:
            cand = Path(d) / f"{exe}.exe"
            if cand.is_file():
                return str(cand)
    return None


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    harness = sys.argv[1]
    extra = sys.argv[2:]

    env = dict(os.environ)
    # A real tunnel exercises TLS, DNS and actual egress; the local URL exercises
    # none of them, and for a harness that fetched from another machine it would
    # not work at all. So a real tunnel is worth having — but it is **opt-in**,
    # not auto-detected.
    #
    # Auto-detection was written first and was wrong. Presence on `PATH` is not
    # evidence a tunnel works: `ngrok` was on this machine's `PATH` and had no
    # authtoken, so `ngrok http` never printed a URL and never exited. Detection
    # would have suppressed the fallback and returned all five tasks to the
    # setup failure that cost them a round — the exact regression this script
    # exists to prevent. An installed binary is a claim; a working tunnel is a
    # measurement, and only the second one may switch off a fallback.
    if "--tunnel" in extra:
        extra = [a for a in extra if a != "--tunnel"]
        which = _find_tunnel()
        if not which:
            print("[run_round] --tunnel: no cloudflared or ngrok found", flush=True)
            return 2
        env["HARNESSBENCH_TUNNEL_CMD"] = (
            f'"{which}" tunnel --url {{local_url}} --no-autoupdate'
            if "cloudflared" in which.lower()
            else f'"{which}" http {{local_url}} --log=stdout'
        )
        print(f"[run_round] --tunnel: deferring to {which} (tasks fail if it "
              f"cannot open a tunnel)", flush=True)
    else:
        env.setdefault("HARNESSBENCH_PUBLIC_URL_TEMPLATE", "{local_url}")
    # The process rubric defaulted to OpenAI, and that account's credits ran
    # out: every task in five consecutive rounds came back `HTTP 429
    # insufficient_quota / credit_balance_exhausted`. It reads as throttling and
    # is not — no backoff would have helped, which is why it was 106/106 rather
    # than intermittent. DeepSeek speaks the same Chat Completions shape and is
    # already paid for, so the grader has a working backend by default.
    #
    # Setting it here rather than in a shell is the same reasoning as the
    # public-URL template above: a round that silently grades nothing is worse
    # than one that fails loudly, and neither should depend on remembering.
    if not env.get("RUBRIC_API_KEY") and env.get("DEEPSEEK_API_KEY"):
        env["RUBRIC_API_KEY"] = env["DEEPSEEK_API_KEY"]
        env.setdefault("RUBRIC_BASE_URL", "https://api.deepseek.com/v1")
        env.setdefault("RUBRIC_MODEL", "deepseek-chat")
        print(f"[run_round] rubric backend: {env['RUBRIC_MODEL']} "
              f"@ {env['RUBRIC_BASE_URL']}", flush=True)
    elif not env.get("RUBRIC_API_KEY"):
        print("[run_round] WARNING: no RUBRIC_API_KEY and no DEEPSEEK_API_KEY — "
              "process will be unmeasured and combined_score will be null",
              flush=True)

    env["PYTHONPATH"] = str(ROOT / "src")
    env["PYTHONIOENCODING"] = "utf-8"

    cmd = [sys.executable, "-m", "harnessbench.cli", "run-suite",
           "--harness", harness, "--mode", "live", *extra]
    print(f"[run_round] {harness} · public-url template "
          f"{env['HARNESSBENCH_PUBLIC_URL_TEMPLATE']!r}", flush=True)
    return subprocess.run(cmd, cwd=ROOT, env=env, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
