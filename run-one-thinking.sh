#!/usr/bin/env bash
# One task, eyes on the wire (M-47 verification step 2).
set -u
cd /mnt/d/repos/harness-bench || exit 1
export PYTHONPATH=src
python3 -m harnessbench.cli run-task --task 001-file \
  --harness perpetum-deepseek-thinking --mode live 2>&1 | tail -25
