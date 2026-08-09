from __future__ import annotations

import os
import random
import re
import shlex
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any


_URL_RE = re.compile(r"https?://[^\s\"')]+")
# Hosts whose URL a tunnel is expected to print on stdout. Cloudflare was the
# only entry, and it was also hard-coded into both match branches below, so a
# `HARNESSBENCH_TUNNEL_CMD` pointing at any other provider discovered its own
# URL and then discarded it for failing the substring test.
_TUNNEL_HOSTS = ("trycloudflare.com", "ngrok-free.app", "ngrok.io", "ngrok.app", "loca.lt")
_TRYCLOUDFLARE_RE = re.compile(
    r"https://[-a-z0-9.]+\.(?:" + "|".join(re.escape(h) for h in _TUNNEL_HOSTS) + r")",
    re.IGNORECASE,
)


def _start_public_tunnel(local_url: str) -> tuple[str | None, subprocess.Popen[str] | None]:
    public_url_template = os.environ.get("HARNESSBENCH_PUBLIC_URL_TEMPLATE", "").strip()
    if public_url_template:
        return public_url_template.format(local_url=local_url).rstrip("/"), None

    tunnel_cmd = os.environ.get("HARNESSBENCH_TUNNEL_CMD", "").strip()
    if not tunnel_cmd and shutil.which("cloudflared"):
        tunnel_cmd = "cloudflared tunnel --url {local_url} --no-autoupdate"
    # `--log=stdout` is not optional: ngrok's default is a curses UI that never
    # writes the URL to stdout, so the reader below would time out on a tunnel
    # that came up perfectly.
    if not tunnel_cmd and shutil.which("ngrok"):
        tunnel_cmd = "ngrok http {local_url} --log=stdout"
    if not tunnel_cmd:
        raise RuntimeError(
            "no public mock URL configured: install cloudflared or set "
            "HARNESSBENCH_PUBLIC_URL_TEMPLATE / HARNESSBENCH_TUNNEL_CMD"
        )

    rendered = tunnel_cmd.format(local_url=local_url)
    proc = subprocess.Popen(
        shlex.split(rendered),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    deadline = time.time() + 15.0
    captured: list[str] = []
    while time.time() < deadline:
        if proc.poll() is not None:
            break
        line = proc.stdout.readline() if proc.stdout else ""
        if not line:
            time.sleep(0.1)
            continue
        captured.append(line.rstrip("\n"))
        cf_match = _TRYCLOUDFLARE_RE.search(line)
        if cf_match:
            return cf_match.group(0).rstrip("/"), proc
        match = _URL_RE.search(line)
        if match and any(h in match.group(0).lower() for h in _TUNNEL_HOSTS):
            return match.group(0).rstrip("/"), proc

    try:
        proc.terminate()
    except OSError:
        pass
    raise RuntimeError(
        "failed to discover public tunnel URL from HARNESSBENCH_TUNNEL_CMD output: "
        + " | ".join(captured[-5:])
    )


def prepare_runtime(runtime: dict[str, Any]) -> dict[str, Any]:
    workspace = Path(runtime["workspace"])
    port = 32000 + random.randint(0, 2000)
    www = workspace / "www"
    proc = subprocess.Popen(
        ["python3", "-m", "http.server", str(port), "--directory", str(www)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(0.3)
    local_page = f"http://127.0.0.1:{port}/"
    try:
        public_page, tunnel_proc = _start_public_tunnel(local_page.rstrip("/"))
    except Exception:
        try:
            proc.terminate()
        except OSError:
            pass
        raise
    mock_page = public_page + "/"
    return {
        "MOCK_PAGE": mock_page,
        "server_pid": proc.pid,
        "tunnel_pid": tunnel_proc.pid if tunnel_proc else 0,
    }


def cleanup_runtime(runtime: dict[str, Any], state: dict[str, Any]) -> None:
    import os

    for key in ("tunnel_pid", "server_pid"):
        pid = int(state.get(key, 0) or 0)
        if pid <= 0:
            continue
        try:
            os.kill(pid, 15)
        except OSError:
            pass
