"""A/B rerun of the 13 Sonnet three-turn-signature tasks against the fixed perp.exe.

Not general-purpose: `run-suite` only takes contiguous ranges, and these 13 task
ids are scattered across the numeric ordering, so this is the throwaway driver
for one specific check. Sequential, not parallel — `perpetum-sonnet` runs the
`claude` CLI as a subprocess, and the earlier full-suite runs were sequential
for the same reason.

Fixes under test: L-36 (prompted rung repair quotes the format), S-22 (the
continuation rule moved out of the results turn), T-36 (glob/grep answer
without a repository). 003-browser and 006-access-bilibili are left in even
though T-34 also touches them (fetch is now Auto for the allowlisted mock
server) -- if the parser diagnosis is right, T-34 alone should not be enough to
fix 003 or 006's *protocol-abandonment* half, only the fetch-refusal half.
"""

from __future__ import annotations

import io
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from harnessbench.config import load_app_config, load_model_config
from harnessbench.runner import run_task
from harnessbench.tasks import load_tasks

TASK_IDS = [
    "003-browser",
    "006-access-bilibili",
    "008-image-recognize",
    "010-office-docs",
    "011-code-debug",
    "018-provider-failover-audit",
    "021-batch-rename-transform",
    "022-local-rest-api-summary",
    "033-offline-knowledge-qa",
    "035-conflicting-source-resolution",
    "038-research-brief-synthesis",
    "047-code-review-risk-report",
    "078-local-api-cursor-retry-ledger",
    "096-offline-knowledge-qa-insufficient-evidence",
]

HARNESS = "perpetum-sonnet"


def signature_facts(result) -> dict:
    """Same derivation `tools/collect.py::load_runs` uses, read straight off the
    freshly returned result instead of a re-parsed results JSON file."""
    oracle = result.oracle_result or {}
    score = oracle.get("outcome_score")
    score = score if isinstance(score, (int, float)) else 0.0
    report = (result.adapter_result.metadata or {}).get("report") or {}
    turns_list = report.get("turns") or []
    turns = len(turns_list)
    calls = sum(t.get("calls", 0) for t in turns_list)

    sandbox = Path(result.sandbox)
    journal = sandbox / "perpetum-state" / ".harness" / "journal.jsonl"
    injection_claim = False
    if journal.is_file():
        txt = journal.read_text(encoding="utf-8", errors="replace")
        injection_claim = "prompt injection" in txt.lower()

    return {
        "combined_score": score,
        "turns": turns,
        "calls": calls,
        "still_signature": score == 0.0 and turns == 3 and calls == 1,
        "injection_claim_in_journal": injection_claim,
    }


def main() -> int:
    app_cfg = load_app_config()
    model_cfgs = load_model_config()
    tasks = load_tasks(app_cfg.tasks_dir)
    model_cfg = model_cfgs[HARNESS]

    out_path = Path(__file__).resolve().parent / "rerun-sonnet-signature.json"
    results = []
    if out_path.is_file():
        results = json.loads(out_path.read_text(encoding="utf-8"))
    done_ids = {r["task_id"] for r in results if r.get("ok")}

    for idx, task_id in enumerate(TASK_IDS, start=1):
        if task_id in done_ids:
            print(f"[{idx}/{len(TASK_IDS)}] {task_id}: already done, skipping", flush=True)
            continue
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
        except Exception as exc:  # noqa: BLE001 - this is a throwaway driver, not the harness
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
        out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\nwrote {out_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
