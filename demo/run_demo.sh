#!/usr/bin/env bash
# 一键跑通 demo（零密钥）。用法：bash demo/run_demo.sh
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
QUORUM="${QUORUM:-quorum}"

cd "$HERE/.."   # 回到仓库根，quorum 才能 import
python3 demo/project/make.py
echo
# 事故一与事故二的**两道门禁**，都在「绿」，而材料是错的 —— 那正是那两个事故的性质：
#   gate.py        校验「预测里的 id 都能在答案里找到」→ 永远为真（缺的 59 条是缺失，不是多余）
#   metric_gate.py 只校验数字区块 → 正文被回填脚本擦光了它也不看
# 不拿 `|| true` 兜着：两道都**本该**是 0，哪天不是 0 了，demo 就该当场停。
# （2026-10-02 补：此前 demo 里只有 gate.py，而 README 却在解释「事故二的门禁为什么绿」——
#   那句话当时没有可执行的东西支撑，是散文。）
echo "--- 两道门禁（预期都绿，而材料是错的）---"
python3 demo/project/gate.py
python3 demo/project/metric_gate.py
echo
"$QUORUM" run    --config demo/review.yaml --all
echo
"$QUORUM" plate  --config demo/review.yaml --dispose
echo
"$QUORUM" verify --config demo/review.yaml --ledger demo/ledger_example.md || true
echo
echo "（verify 的退出码非零是**预期的**：示例台账里第 1 行是一个会失败的 ✅）"
