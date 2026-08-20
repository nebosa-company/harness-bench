#!/usr/bin/env bash
# Start the reviewed round once the clean round finishes.
#
# Not concurrently, deliberately. The two rounds would not collide on ports --
# every task that binds one picks it as `base + random.randint(0, 2000)`, so
# the odds are about 1/2000 even when both rounds run the same task at the same
# moment. What they would share is the DeepSeek endpoint, and the reviewed
# round adds ds-pro traffic on top. A rate-limit storm would put false zeros
# into *both* rounds, including the clean one that is already an hour in and is
# the round the corrected headline depends on. Four saved hours is not worth
# contaminating it -- this whole plan exists because environmental failures got
# read as capability gaps.
#
# Waits on the Windows PID rather than a log line: the suite log already
# carries a "run-suite finished" line from an earlier 5-task run, so matching
# on that text would fire immediately.
set -u

WINPID="${1:?usage: run-reviewed-after.sh <winpid-of-running-suite>}"
cd /d/repos/harness-bench || exit 1

echo "[chain] waiting for the clean round (winpid $WINPID) to exit..."
while tasklist //FI "PID eq $WINPID" 2>/dev/null | grep -q "$WINPID"; do
    sleep 60
done
echo "[chain] clean round exited at $(date -u +%H:%M:%SZ)"

tail -3 data_try6/results/perpetum-deepseek-thinking-fixed/run-suite.log 2>/dev/null

echo "[chain] starting perpetum-deepseek-reviewed"
export PYTHONPATH=src
python -m harnessbench.cli run-suite \
    --harness perpetum-deepseek-reviewed --mode live 2>&1 | tail -40
echo "[chain] reviewed round exited $? at $(date -u +%H:%M:%SZ)"
