#!/usr/bin/env python3
"""数字门禁 —— **事故二里的那个「绿」。**

它逐字节校验 `<!-- METRICS:START -->…<!-- METRICS:END -->` 区块里的数字对不对，
**区块之外的正文一个字都不看**。所以当回填脚本把纪要、口径、方法、局限整个擦光、
只剩一个数字块的时候，它**永远有理由绿**。

⚠️ 这个文件是 2026-10-02 补的（luna 在复核里发现）：`demo/README.md` 写着
「事故二 · 门禁绿材料错」并解释「门禁为什么绿：它逐字节校验的是数字区块」，
**而当时的 demo 里根本没有这个门禁** —— 只有一个 `gate.py`，那是事故一的那道
（校验预测 id 子集）。也就是说：事故二的**结果**能跑出来（报告确实只剩数字块），
但「门禁绿」那一步只是**散文**，读者验证不了。

按本项目的规矩，一句声称有护栏的注释比没有护栏更危险。所以补一个真的：

    python3 demo/project/metric_gate.py     # 退出码 0 = 绿（而材料是错的）

它是一道**真门禁**，不是道具：把区块里的数字改错，它会红。
它只是**管辖范围**划错了地方 —— 那才是事故二的性质。
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")


def main() -> int:
    rows = [json.loads(l) for l in open(os.path.join(DATA, "answers.jsonl"), encoding="utf-8")]
    pred = [json.loads(l) for l in open(os.path.join(DATA, "pred_old.jsonl"), encoding="utf-8")]
    expect = 100.0 * len(pred) / len(rows)          # 「覆盖率」——注意这正是事故一的错

    rep = open(os.path.join(HERE, "report.md"), encoding="utf-8").read()
    m = re.search(r"<!-- METRICS:START -->(.*?)<!-- METRICS:END -->", rep, re.S)
    if not m:
        print("✗ 数字区块不见了（本门禁只管这一块，区块没了它才红）")
        return 1

    block = m.group(1).strip()
    got = re.search(r"([\d.]+)%", block)
    if not got or abs(float(got.group(1)) - expect) > 0.05:
        print("✗ 数字区块里的数与重算不符：区块 %r，重算 %.1f%%" % (block, expect))
        return 1

    body_chars = len(re.sub(r"<!--.*?-->", "", rep, flags=re.S))
    print("✓ 数字区块正确（%.1f%%）" % expect)
    print("  ⚠️ 本门禁**不看区块之外的正文**。这份报告去掉注释后只有 %d 个字符——"
          "纪要、口径、方法、局限全都不在里面，而它照样是绿的。" % body_chars)
    print("  ↑ 这就是事故二：**门禁检查的性质，不是读者以为的那个性质。**")
    return 0


if __name__ == "__main__":
    sys.exit(main())
