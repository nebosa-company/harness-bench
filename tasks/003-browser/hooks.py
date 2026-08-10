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


# Where a tunnel binary actually lives when it is not on PATH.
#
# cloudflared installs to Program Files and does not add itself, so
# `shutil.which` says no and the caller falls through to whatever is next —
# which is how a working cloudflared lost to an unauthenticated ngrok and hung
# the suite. Looking in the obvious places is cheaper than the failure.
_TUNNEL_BINARY_HINTS = (
    r"C:\Program Files (x86)\cloudflared\cloudflared.exe",
    r"C:\Program Files\cloudflared\cloudflared.exe",
    "/usr/local/bin/cloudflared",
    "/usr/bin/cloudflared",
    "/opt/homebrew/bin/cloudflared",
)


def _find_tunnel_binary(name: str) -> str | None:
    """`shutil.which`, then the places installers actually use."""
    found = shutil.which(name)
    if found:
        return found
    for hint in _TUNNEL_BINARY_HINTS:
        if Path(hint).name.lower().startswith(name.lower()) and Path(hint).is_file():
            return hint
    return None


def _read_lines_without_blocking_forever(proc, deadline):
    """Yield the child's stdout lines until `deadline`, whatever the child does.

    `readline()` blocks, so a deadline loop built on it is only a deadline while
    the child keeps talking. A child that goes quiet without exiting — an
    unauthenticated ngrok is exactly this — parks the caller forever. Measured:
    a calibration run stopped for 44 minutes on one task, the runner holding 3.2
    seconds of CPU, until the tunnel was killed by hand.

    A daemon thread does the blocking read and a queue carries the lines back,
    so the timeout belongs to the reader rather than to the writer's goodwill.
    """
    import queue
    import threading

    lines: "queue.Queue[str]" = queue.Queue()

    def pump():
        try:
            for line in iter(proc.stdout.readline, ""):
                lines.put(line)
        except Exception:
            pass
        finally:
            lines.put("")  # the child closed its output

    threading.Thread(target=pump, daemon=True).start()

    while time.time() < deadline:
        try:
            line = lines.get(timeout=0.25)
        except queue.Empty:
            if proc.poll() is not None:
                return
            continue
        if not line:
            return
        yield line


def _start_public_tunnel(local_url: str) -> tuple[str | None, subprocess.Popen[str] | None]:
    public_url_template = os.environ.get("HARNESSBENCH_PUBLIC_URL_TEMPLATE", "").strip()
    if public_url_template:
        return public_url_template.format(local_url=local_url).rstrip("/"), None

    tunnel_cmd = os.environ.get("HARNESSBENCH_TUNNEL_CMD", "").strip()
    cloudflared = _find_tunnel_binary("cloudflared")
    if not tunnel_cmd and cloudflared:
        tunnel_cmd = f'"{cloudflared}" tunnel --url {{local_url}} --no-autoupdate'
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

    # 30 seconds, and it is now a real bound rather than one that holds only
    # while the child keeps writing.
    deadline = time.time() + 30.0
    captured: list[str] = []
    for line in _read_lines_without_blocking_forever(proc, deadline):
        captured.append(line.rstrip("\n"))
        cf_match = _TRYCLOUDFLARE_RE.search(line)
        if cf_match:
            return cf_match.group(0).rstrip("/"), proc
        match = _URL_RE.search(line)
        if match and any(h in match.group(0).lower() for h in _TUNNEL_HOSTS):
            return match.group(0).rstrip("/"), proc

    try:
        proc.terminate()
        proc.wait(timeout=5)
    except Exception:
        # `terminate` is a request. A tunnel that ignores it would outlive the
        # run and hold its port, so the second ask is not a request.
        try:
            proc.kill()
        except Exception:
            pass
    raise RuntimeError(
        "failed to discover public tunnel URL from HARNESSBENCH_TUNNEL_CMD output: "
        + " | ".join(captured[-5:])
    )


def prepare_runtime(runtime: dict[str, Any]) -> dict[str, Any]:
    workspace = Path(runtime["workspace"])
    port = 31000 + random.randint(0, 2000)
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
    return {
        "MOCK_PAGE": public_page + "/",
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
