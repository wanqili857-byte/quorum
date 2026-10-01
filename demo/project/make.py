#!/usr/bin/env python3
"""生成 demo 项目——**情节是真的，数据全是编的**。

三个事故都来自真实复核里抓到的、性质不同的「静默错误」。三者的共同点是：
**门禁是绿的，材料是错的**——绿灯为真，但它证明的不是读者以为的事。

  事故一 · 分母静默缩水  数字能从数据文件「算出来」，但算的不是读者以为的那道题
  事故二 · 门禁绿材料错  数字区块一直是对的，区块外的正文被擦光了而没人发现
  事故三 · 切分非确定性  同参数重跑得到不同结果，因为遍历了 set

跑：python3 make.py
"""
import json
import os
import random

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
LABELS = ["allow", "ask", "deny"]


def main():
    os.makedirs(DATA, exist_ok=True)
    rng = random.Random(7)

    rows = [{"id": "q-%03d" % i, "gold": LABELS[i % 3]} for i in range(100)]
    with open(os.path.join(DATA, "answers.jsonl"), "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")

    # 事故一：预测只覆盖 41 条（旧版本跑的），而报表头写「100 条」。
    # 而 metrics() 里那句 `if p is None: continue` 会静默把分母缩到 41。
    with open(os.path.join(DATA, "pred_old.jsonl"), "w") as f:
        for r in rows[:41]:
            pred = r["gold"] if rng.random() < 0.6 else rng.choice(LABELS)
            f.write(json.dumps({"id": r["id"], "pred": pred}) + "\n")

    # 事故一（数字部分）：报告写「严格命中 41.0%」，而 41.0% 其实是**覆盖率**（41/100），
    # 不是准确率——准确率是 31/41 = 75.6%（对全部 100 条则是 31.0%）。
    # 作者把覆盖率当成了准确率，而**没有任何门禁**检查这件事。
    pred = [json.loads(l) for l in open(os.path.join(DATA, "pred_old.jsonl"))]
    gold = {r["id"]: r["gold"] for r in rows}
    covered = len(pred)
    hit = sum(1 for r in pred if gold.get(r["id"]) == r["pred"])
    coverage = 100.0 * covered / len(rows)
    acc_covered = 100.0 * hit / covered
    acc_all = 100.0 * hit / len(rows)

    # 事故二：报告的数字区块是对的，区块外的正文被「回填脚本」擦光了。
    # 真因：open(path, "w").write(replace(path, ...)) —— open(...,"w") 先截断，函数再读，读到空。
    with open(os.path.join(HERE, "report.md"), "w", encoding="utf-8") as f:
        f.write("# 评测报告\n\n<!-- METRICS:START -->\n"
                "严格命中 %.1f%%（held-out %d 条）\n" % (coverage, len(rows)) +
                "<!-- METRICS:END -->\n")

    # 复核用：把三个数都算出来（审核员据此复现事故一）
    with open(os.path.join(HERE, "metrics.py"), "w", encoding="utf-8") as f:
        f.write('''#!/usr/bin/env python3
"""重算报告里的数字。审核员用它复现事故一。"""
import json, os
HERE = os.path.dirname(os.path.abspath(__file__))
ans = {json.loads(l)["id"]: json.loads(l)["gold"]
       for l in open(os.path.join(HERE, "data", "answers.jsonl"))}
pred = [json.loads(l) for l in open(os.path.join(HERE, "data", "pred_old.jsonl"))]
hit = sum(1 for r in pred if ans.get(r["id"]) == r["pred"])
print("覆盖率（有预测的条数 / 全集）: %d/%d = %.1f%%" % (len(pred), len(ans), 100*len(pred)/len(ans)))
print("准确率（在有预测的那些上）  : %d/%d = %.1f%%" % (hit, len(pred), 100*hit/len(pred)))
print("准确率（把缺的算错，对全集）: %d/%d = %.1f%%" % (hit, len(ans), 100*hit/len(ans)))
''')

    # 事故三：切分时遍历 set，字符串哈希每进程随机化 → 同参数重跑结果不同。
    with open(os.path.join(HERE, "build.py"), "w", encoding="utf-8") as f:
        f.write('''#!/usr/bin/env python3
"""把 100 条按 8:2 切成 train/dev。**故意埋了事故三**：遍历 set。"""
import random, json, os

HERE = os.path.dirname(os.path.abspath(__file__))
rows = [json.loads(l) for l in open(os.path.join(HERE, "data", "answers.jsonl"))]
ids = {r["id"] for r in rows}          # ← set：迭代顺序随 PYTHONHASHSEED 变
rng = random.Random(42)                # 种子固定也没用，输入顺序本身就不固定
keys = list(ids)
rng.shuffle(keys)
dev = set(keys[:20])
print(json.dumps({"train": len([k for k in keys if k not in dev]), "dev": len(dev),
                  "dev_ids": sorted(dev)[:3]}))
''')

    # 事故四（对照组）：一个**检查了错误性质**的门禁。它全绿。
    with open(os.path.join(HERE, "gate.py"), "w", encoding="utf-8") as f:
        f.write('''#!/usr/bin/env python3
"""数据门禁。它检查的性质是「预测文件里出现的 id 都能在答案里找到」——永远为真，
因为多余的那 59 条是**缺失**而不是多余。读者以为它在保证「100 条都有预测」。"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ans = {json.loads(l)["id"] for l in open(os.path.join(HERE, "data", "answers.jsonl"))}
pred = {json.loads(l)["id"] for l in open(os.path.join(HERE, "data", "pred_old.jsonl"))}
extra = pred - ans
print("预测里的 id 都能在答案里找到" if not extra else "多出 %d 条" % len(extra))
sys.exit(0 if not extra else 1)
''')

    print("demo 项目已生成：")
    for p in ("data/answers.jsonl", "data/pred_old.jsonl", "report.md", "build.py", "gate.py"):
        print("  %s" % p)


if __name__ == "__main__":
    main()
