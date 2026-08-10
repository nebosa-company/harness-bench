"""Exercise the tunnel fix on its own, away from the running calibration.

Three questions, in order of how much they matter:

1. **Does a silent tunnel still hang?** This is the defect that cost 44
   minutes. Forced with a command that prints nothing and does not exit —
   the shape an unauthenticated ngrok takes — and the fix is only real if
   this raises in about thirty seconds instead of never.
2. **Does a tunnel that fails fast still get reported?** A child that exits
   immediately must not be waited on for the full deadline.
3. **Does the happy path work?** cloudflared was installed and undiscoverable;
   finding it is only half the claim, and the other half is that the URL it
   prints is actually captured.

Runs on its own port, in its own temp directory, and tears down what it starts.
"""

import importlib.util
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HOOKS = Path("D:/repos/harness-bench/tasks/003-browser/hooks.py")

spec = importlib.util.spec_from_file_location("browser_hooks", HOOKS)
hooks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hooks)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def case(name: str):
    print(f"\n--- {name} ---")


results = []


# 1. The silent tunnel: the failure that started all this.
case("a tunnel that says nothing and does not exit")
os.environ["HARNESSBENCH_TUNNEL_CMD"] = (
    f'"{sys.executable}" -c "import time; time.sleep(600)"'
)
t0 = time.time()
try:
    url, proc = hooks._start_public_tunnel("http://127.0.0.1:9999")
    print(f"  UNEXPECTED: returned {url}")
    results.append(("silent tunnel", False, "returned a URL it could not have"))
except RuntimeError as exc:
    took = time.time() - t0
    ok = 25 <= took <= 45
    print(f"  raised after {took:.1f}s: {str(exc)[:70]}")
    print(f"  {'PASS' if ok else 'FAIL'} — before the fix this never returned")
    results.append(("silent tunnel", ok, f"{took:.1f}s"))
except Exception as exc:  # noqa: BLE001
    took = time.time() - t0
    print(f"  raised {type(exc).__name__} after {took:.1f}s: {exc}")
    results.append(("silent tunnel", False, type(exc).__name__))

# Leftover check: the child must not outlive the attempt.
time.sleep(1)
leftover = subprocess.run(
    ["powershell", "-NoProfile", "-Command",
     "(Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'time.sleep\\(600\\)' } | Measure-Object).Count"],
    capture_output=True, text=True,
).stdout.strip()
print(f"  orphaned children: {leftover} (terminate is followed by kill)")
results.append(("no orphan left behind", leftover in ("0", ""), leftover))


# 2. A tunnel that dies at once.
case("a tunnel that exits immediately")
os.environ["HARNESSBENCH_TUNNEL_CMD"] = f'"{sys.executable}" -c "raise SystemExit(1)"'
t0 = time.time()
try:
    url, proc = hooks._start_public_tunnel("http://127.0.0.1:9999")
    print(f"  UNEXPECTED: returned {url}")
    results.append(("fast failure", False, "returned a URL"))
except RuntimeError as exc:
    took = time.time() - t0
    ok = took < 10
    print(f"  raised after {took:.1f}s — {'PASS' if ok else 'FAIL'} (must not wait out the deadline)")
    results.append(("fast failure", ok, f"{took:.1f}s"))


# 3. The happy path, with a real server behind a real tunnel.
case("cloudflared, discovered and actually used")
del os.environ["HARNESSBENCH_TUNNEL_CMD"]
found = hooks._find_tunnel_binary("cloudflared")
print(f"  discovered at: {found}")
if not found:
    results.append(("cloudflared discovery", False, "not found"))
else:
    results.append(("cloudflared discovery", True, "found off-PATH"))
    root = Path(tempfile.mkdtemp(prefix="tunnel-test-"))
    (root / "index.html").write_text(
        "<!doctype html><title>tunnel check</title><p>ok</p>", encoding="utf-8"
    )
    port = free_port()
    server = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(port), "--directory", str(root)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    time.sleep(1.0)
    tunnel = None
    try:
        t0 = time.time()
        url, tunnel = hooks._start_public_tunnel(f"http://127.0.0.1:{port}")
        took = time.time() - t0
        print(f"  URL after {took:.1f}s: {url}")
        ok = bool(url) and "ngrok" not in (url or "")
        print(f"  {'PASS' if ok else 'FAIL'} — a cloudflared URL, not the fallback")
        results.append(("cloudflared happy path", ok, f"{took:.1f}s"))
    except Exception as exc:  # noqa: BLE001
        print(f"  raised: {str(exc)[:110]}")
        results.append(("cloudflared happy path", False, str(exc)[:40]))
    finally:
        for p in (tunnel, server):
            if p is not None:
                try:
                    p.terminate()
                    p.wait(timeout=5)
                except Exception:
                    try:
                        p.kill()
                    except Exception:
                        pass
        shutil.rmtree(root, ignore_errors=True)

print("\n" + "=" * 60)
for name, ok, detail in results:
    print(f"  {'PASS' if ok else 'FAIL'}  {name:28s} {detail}")
print("=" * 60)
raise SystemExit(0 if all(ok for _, ok, _ in results) else 1)
