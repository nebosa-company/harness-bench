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

    python tools/run_round.py <harness-id> [--from-num N] [--to-num N]
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    harness = sys.argv[1]
    extra = sys.argv[2:]

    env = dict(os.environ)
    env.setdefault("HARNESSBENCH_PUBLIC_URL_TEMPLATE", "{local_url}")
    env["PYTHONPATH"] = str(ROOT / "src")
    env["PYTHONIOENCODING"] = "utf-8"

    cmd = [sys.executable, "-m", "harnessbench.cli", "run-suite",
           "--harness", harness, "--mode", "live", *extra]
    print(f"[run_round] {harness} · public-url template "
          f"{env['HARNESSBENCH_PUBLIC_URL_TEMPLATE']!r}", flush=True)
    return subprocess.run(cmd, cwd=ROOT, env=env, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
