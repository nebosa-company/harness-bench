"""A task that dies in setup leaves a row saying so.

Six tasks in one round wrote no result file at all, so the round's denominator
shrank without anyone choosing it. This exercises the two things that fix has to
get right: the row exists, and it is not a scored zero.

Run: python tools/check_setup_failure_row.py
"""
from __future__ import annotations

import json
import sys
import tempfile
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from harnessbench.models import AppConfig, TaskSpec  # noqa: E402
from harnessbench.runner import write_setup_failure  # noqa: E402

failures: list[str] = []


def check(condition: bool, why: str) -> None:
    if not condition:
        failures.append(why)


with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    app = AppConfig(
        project_root=root,
        data_dir=root / "data",
        tasks_dir=root / "tasks",
        results_dir=root / "data" / "results",
        work_root=root / "work",
    )
    task = TaskSpec(task_id="003-browser", title="the tunnel task that vanished")
    cfg = {"model": "deepseek-v4-flash", "adapter": "perpetum"}

    try:
        raise FileNotFoundError("cloudflared: not found on PATH")
    except FileNotFoundError as exc:
        out = write_setup_failure(
            app, task, "dsh-deepseek-flash", cfg, "live", exc, traceback.format_exc()
        )

    check(out.exists(), "no result file was written -- the task still vanishes")
    row = json.loads(out.read_text(encoding="utf-8"))

    # It is findable by the same id every other reader uses.
    check(row["task_id"] == "003-browser", f"wrong task_id: {row.get('task_id')}")

    # Recorded, and recorded as unrun rather than as a zero. A scored zero is a
    # claim about the harness; this task never reached its agent.
    check(row["setup_failed"] is True, "the row does not say the setup failed")
    check(
        row["scoring"]["combined_score"] is None,
        f"scored {row['scoring']['combined_score']} -- an unrun task is not a zero",
    )
    check(
        "cloudflared" in row["scoring"]["combined_unavailable"],
        f"the reason is not carried: {row['scoring'].get('combined_unavailable')}",
    )
    check("cloudflared" in row["setup_error"], "the error text is not carried")
    check("Traceback" in row["setup_traceback"], "the traceback is not carried")

    # And the shape a reader expects, present and honestly empty.
    for key in ("adapter_result", "oracle_result", "usage_summary", "elapsed_sec"):
        check(key in row, f"missing key a reader expects: {key}")

    # The file lands atomically, so no `.partial` is left behind.
    check(
        not list(out.parent.glob("*.partial")),
        "a .partial was left in the results directory",
    )

    # And it lands where a scored row would.
    #
    # This is the half that was missing, and the row above is why it was missed:
    # its config carries a top-level `model`, which is the case that works. A
    # multi-link config has none -- the models live inside `links` -- so the slug
    # fell through to `model_id`, the *harness entry name*. A reviewed round put
    # its four setup failures in
    # `results/perpetum-deepseek-reviewed/perpetum-deepseek-reviewed/` while its
    # 102 scored rows sat in `deepseek-v4-flash/`. Every assertion above passed
    # on that row. The round still shrank from 106 to 102, because a row a
    # collector cannot find is the hole this function exists to close.
    task2 = TaskSpec(task_id="042-api-schema-migration", title="a multi-link round's setup failure")
    multi = {
        "adapter": "perpetum",
        "result_slug": "deepseek-v4-flash",
        "links": {"deepseek": {"model": "deepseek-v4-flash"}, "ds-pro": {"model": "deepseek-v4-pro"}},
    }
    try:
        raise FileNotFoundError("cloudflared: not found on PATH")
    except FileNotFoundError as exc:
        out2 = write_setup_failure(
            app, task2, "perpetum-deepseek-reviewed", multi, "live", exc, traceback.format_exc()
        )

    check(
        out2.parent.name == "deepseek-v4-flash",
        f"a multi-link setup failure landed in {out2.parent.name!r}, not its result_slug",
    )
    check(
        out2.parent.name != "perpetum-deepseek-reviewed",
        "the row is filed under the harness id, where no collector reads",
    )

if failures:
    print("FAILED")
    for line in failures:
        print("  -", line)
    raise SystemExit(1)
print("ok: a setup failure leaves a row, and it is not a scored zero")
