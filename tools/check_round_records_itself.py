"""A round records its own cost, and keeps its own log.

Item 6 of the four-round plan: the comparison report priced three of its four
columns from a table it held itself, and two suite logs were destroyed because
they lived in `/tmp`. Both make a property of the run into a property of
whoever reads it afterwards.

Run: python tools/check_round_records_itself.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from harnessbench.runner import price_usage  # noqa: E402

failures: list[str] = []


def check(ok: bool, why: str) -> None:
    if not ok:
        failures.append(why)


# The numbers from a real row, so the arithmetic is checked against something
# that actually happened rather than a round number.
def summary() -> dict:
    return {
        "available": True,
        "input_tokens": 674,
        "output_tokens": 331,
        "cache_read_tokens": 3968,
        "models": ["deepseek-v4-flash"],
    }


s = summary()
price_usage(s, "deepseek-v4-flash", {})
expected = round((3968 * 0.0028 + 674 * 0.14 + 331 * 0.28) / 1_000_000.0, 6)
check(s["cost_usd"] == expected, f"cost {s.get('cost_usd')} != {expected}")
check("default" in s["cost_basis"], f"the basis is not recorded: {s.get('cost_basis')}")

# A config price wins, and says it did.
s = summary()
price_usage(s, "deepseek-v4-flash", {"prices": {"deepseek-v4-flash": (1.0, 1.0, 1.0)}})
check(s["cost_usd"] == round((3968 + 674 + 331) / 1_000_000.0, 6), f"config price ignored: {s}")
check("config" in s["cost_basis"], f"the basis does not say config: {s.get('cost_basis')}")

# An unknown model is not priced at zero. A round that cost nothing and a round
# nobody could price must not share a number.
s = summary()
s["models"] = ["something-nobody-has-priced"]
price_usage(s, "something-nobody-has-priced", {})
check(s["cost_usd"] is None, f"an unpriceable round was priced {s.get('cost_usd')}")
check("no price on file" in s["cost_basis"], f"and does not say why: {s.get('cost_basis')}")

# The model that answered is the honest second guess when the configured name
# is not in the table -- a fallback link means those two differ.
s = summary()
price_usage(s, "a-name-not-in-the-table", {})
check(s["cost_usd"] == expected, f"the answering model was not used: {s}")
check("answered" in s["cost_basis"], f"and the row does not say so: {s.get('cost_basis')}")

# A summary that reports nothing is left alone rather than priced as zero.
s = {"available": False, "reason": "no proxy trace"}
price_usage(s, "deepseek-v4-flash", {})
check("cost_usd" not in s, "an unavailable summary was given a cost")

# 6c: the suite log lives beside the results, not in /tmp.
cli = (Path(__file__).resolve().parents[1] / "src" / "harnessbench" / "cli.py").read_text(
    encoding="utf-8"
)
check('"run-suite.log"' in cli, "run-suite does not open its own log")
check("app_cfg.results_dir / args.harness" in cli, "the log is not beside the results")
# Comments stripped: the fix is allowed to *explain* `/tmp`, and the first
# version of this check failed on its own rationale.
code = chr(10).join(l for l in cli.splitlines() if not l.lstrip().startswith("#"))
check("/tmp" not in code, "the cli still writes to /tmp")

if failures:
    print("FAILED")
    for line in failures:
        print("  -", line)
    raise SystemExit(1)
print("ok: the round prices itself, and logs beside its results")
