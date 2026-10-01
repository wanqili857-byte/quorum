#!/usr/bin/env python3
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
