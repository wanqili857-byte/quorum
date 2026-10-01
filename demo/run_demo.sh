#!/usr/bin/env bash
# 一键跑通 demo（零密钥）。用法：bash demo/run_demo.sh
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
QUORUM="${QUORUM:-quorum}"

cd "$HERE/.."   # 回到仓库根，quorum 才能 import
python3 demo/project/make.py
echo
"$QUORUM" run    --config demo/review.yaml --all
echo
"$QUORUM" plate  --config demo/review.yaml --dispose
echo
"$QUORUM" verify --config demo/review.yaml --ledger demo/ledger_example.md || true
echo
echo "（verify 的退出码非零是**预期的**：示例台账里第 1 行是一个会失败的 ✅）"
