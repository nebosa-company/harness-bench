"""Let the tunnel tasks use a real tunnel when one exists.

Two changes, in two places, for two different reasons.

`hooks.py` (x5) only ever recognised Cloudflare: `cloudflared` was the sole
auto-detected binary, and both URL-match branches required the literal string
`trycloudflare.com`, so a configured `HARNESSBENCH_TUNNEL_CMD` pointing at
anything else parsed its own output and then threw it away. This generalises the
match to a set of known tunnel hosts and adds `ngrok` to the auto-detected list.

`run_round.py` set the local-URL template unconditionally, which meant that
installing a tunnel changed nothing — the template takes the first branch and
the tunnel is never started. It now sets the template only when no tunnel binary
is present, so the fallback stays a fallback: real tunnel when one exists, local
URL when not, and never the setup failure that cost five tasks a round.

The explicit template still wins when a person sets it, because an explicit
override should win over auto-detection.
"""

from __future__ import annotations

import io
import pathlib
import re

TASKS = [
    "003-browser",
    "006-access-bilibili",
    "078-local-api-cursor-retry-ledger",
    "081-local-html-dom-form-extract",
    "088-api-contract-mock-client-compat",
]

OLD_RE = (
    '_TRYCLOUDFLARE_RE = re.compile(r"https://[-a-z0-9]+\\.trycloudflare\\.com", re.IGNORECASE)'
)
NEW_RE = '''# Hosts whose URL a tunnel is expected to print on stdout. Cloudflare was the
# only entry, and it was also hard-coded into both match branches below, so a
# `HARNESSBENCH_TUNNEL_CMD` pointing at any other provider discovered its own
# URL and then discarded it for failing the substring test.
_TUNNEL_HOSTS = ("trycloudflare.com", "ngrok-free.app", "ngrok.io", "ngrok.app", "loca.lt")
_TRYCLOUDFLARE_RE = re.compile(
    r"https://[-a-z0-9.]+\\.(?:" + "|".join(re.escape(h) for h in _TUNNEL_HOSTS) + r")",
    re.IGNORECASE,
)'''

OLD_DETECT = '''    tunnel_cmd = os.environ.get("HARNESSBENCH_TUNNEL_CMD", "").strip()
    if not tunnel_cmd and shutil.which("cloudflared"):
        tunnel_cmd = "cloudflared tunnel --url {local_url} --no-autoupdate"'''
NEW_DETECT = '''    tunnel_cmd = os.environ.get("HARNESSBENCH_TUNNEL_CMD", "").strip()
    if not tunnel_cmd and shutil.which("cloudflared"):
        tunnel_cmd = "cloudflared tunnel --url {local_url} --no-autoupdate"
    # `--log=stdout` is not optional: ngrok's default is a curses UI that never
    # writes the URL to stdout, so the reader below would time out on a tunnel
    # that came up perfectly.
    if not tunnel_cmd and shutil.which("ngrok"):
        tunnel_cmd = "ngrok http {local_url} --log=stdout"'''

OLD_MATCH = '''        cf_match = _TRYCLOUDFLARE_RE.search(line)
        if cf_match:
            return cf_match.group(0).rstrip("/"), proc
        match = _URL_RE.search(line)
        if match and "trycloudflare.com" in match.group(0).lower():
            return match.group(0).rstrip("/"), proc'''
NEW_MATCH = '''        cf_match = _TRYCLOUDFLARE_RE.search(line)
        if cf_match:
            return cf_match.group(0).rstrip("/"), proc
        match = _URL_RE.search(line)
        if match and any(h in match.group(0).lower() for h in _TUNNEL_HOSTS):
            return match.group(0).rstrip("/"), proc'''


def patch_hook(path: pathlib.Path) -> bool:
    t = io.open(path, encoding="utf-8").read()
    if "_TUNNEL_HOSTS" in t:
        return False
    for old, new in ((OLD_RE, NEW_RE), (OLD_DETECT, NEW_DETECT), (OLD_MATCH, NEW_MATCH)):
        if old not in t:
            raise SystemExit(f"{path}: anchor not found:\n{old[:80]}")
        t = t.replace(old, new, 1)
    io.open(path, "w", encoding="utf-8", newline="\n").write(t)
    return True


RUNNER_OLD = '''    env = dict(os.environ)
    env.setdefault("HARNESSBENCH_PUBLIC_URL_TEMPLATE", "{local_url}")'''
RUNNER_NEW = '''    env = dict(os.environ)
    # Only stand in for a tunnel when there is no tunnel. Setting this
    # unconditionally meant installing `cloudflared` changed nothing: the
    # template takes the first branch in the hook and the tunnel never starts.
    # A real tunnel exercises TLS, DNS and actual egress; the local URL exercises
    # none of them, and for a harness that fetches from another machine it would
    # not work at all. So prefer the real thing and keep the substitution as the
    # fallback that stops a missing binary from costing five tasks a round.
    tunnel = shutil.which("cloudflared") or shutil.which("ngrok")
    if tunnel:
        print(f"[run_round] tunnel available: {tunnel}", flush=True)
    else:
        env.setdefault("HARNESSBENCH_PUBLIC_URL_TEMPLATE", "{local_url}")'''


def patch_runner(path: pathlib.Path) -> bool:
    t = io.open(path, encoding="utf-8").read()
    if "tunnel available" in t:
        return False
    if RUNNER_OLD not in t:
        raise SystemExit(f"{path}: runner anchor not found")
    t = t.replace(RUNNER_OLD, RUNNER_NEW, 1)
    t = t.replace("import os\nimport subprocess", "import os\nimport shutil\nimport subprocess", 1)
    io.open(path, "w", encoding="utf-8", newline="\n").write(t)
    return True


def main() -> int:
    root = pathlib.Path(__file__).resolve().parent.parent
    for name in TASKS:
        p = root / "tasks" / name / "hooks.py"
        print(f"  {name:36} {'patched' if patch_hook(p) else 'already done'}")
    p = root / "tools" / "run_round.py"
    print(f"  {'run_round.py':36} {'patched' if patch_runner(p) else 'already done'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
