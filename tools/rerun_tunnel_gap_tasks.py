"""Rerun the three tasks that failed the Sonnet A/B on infrastructure, not on
anything perp does.

`003-browser`, `006-access-bilibili` and `078-local-api-cursor-retry-ledger`
each start a `python3 -m http.server` on loopback and then look for a public
URL to hand the model, via `tasks/<id>/hooks.py::_start_public_tunnel`. With
no `cloudflared` on this machine and neither override set, that raises before
the task ever starts -- the same "needed one environment variable, not a
tunnel" gap `harness-bench-improvements.md` already names from round 1: perp
and the mock server are on the same machine, so the local loopback URL *is*
the public one to hand the model.

`HARNESSBENCH_PUBLIC_URL_TEMPLATE={local_url}` makes `_start_public_tunnel`
return the loopback URL unchanged instead of raising.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
os.environ.setdefault("HARNESSBENCH_PUBLIC_URL_TEMPLATE", "{local_url}")

from harnessbench.config import load_app_config, load_model_config
from harnessbench.runner import run_task
from harnessbench.tasks import load_tasks

from rerun_sonnet_signature import HARNESS, signature_facts  # noqa: E402

TASK_IDS = ["003-browser", "006-access-bilibili", "078-local-api-cursor-retry-ledger"]


def main() -> int:
    app_cfg = load_app_config()
    model_cfgs = load_model_config()
    tasks = load_tasks(app_cfg.tasks_dir)
    model_cfg = model_cfgs[HARNESS]

    merged_path = Path(__file__).resolve().parent / "rerun-sonnet-signature.json"
    results = json.loads(merged_path.read_text(encoding="utf-8")) if merged_path.is_file() else []

    for idx, task_id in enumerate(TASK_IDS, start=1):
        print(f"[{idx}/{len(TASK_IDS)}] {task_id}: starting ...", flush=True)
        t0 = time.time()
        try:
            result = run_task(app_cfg, tasks[task_id], HARNESS, model_cfg, "live", keep_workspace=True)
            elapsed = time.time() - t0
            scoring = result.scoring if isinstance(result.scoring, dict) else {}
            facts = signature_facts(result)
            row = {
                "task_id": task_id,
                "ok": True,
                "elapsed_sec": round(elapsed, 1),
                "sandbox": str(result.sandbox),
                "combined_score": scoring.get("combined_score"),
                **facts,
            }
            print(
                f"[{idx}/{len(TASK_IDS)}] {task_id}: combined_score={row['combined_score']!r} "
                f"turns={facts['turns']} calls={facts['calls']} "
                f"still_signature={facts['still_signature']} "
                f"injection_claim={facts['injection_claim_in_journal']} "
                f"elapsed={row['elapsed_sec']}s",
                flush=True,
            )
        except Exception as exc:  # noqa: BLE001 - throwaway driver
            elapsed = time.time() - t0
            row = {
                "task_id": task_id,
                "ok": False,
                "elapsed_sec": round(elapsed, 1),
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
            print(f"[{idx}/{len(TASK_IDS)}] {task_id}: FAILED {exc}", flush=True)

        results = [r for r in results if r["task_id"] != task_id] + [row]
        merged_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\nwrote {merged_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
