#!/usr/bin/env python3
"""数据门禁。它检查的性质是「预测文件里出现的 id 都能在答案里找到」——永远为真，
因为多余的那 59 条是**缺失**而不是多余。读者以为它在保证「100 条都有预测」。"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ans = {json.loads(l)["id"] for l in open(os.path.join(HERE, "data", "answers.jsonl"))}
pred = {json.loads(l)["id"] for l in open(os.path.join(HERE, "data", "pred_old.jsonl"))}
extra = pred - ans
print("预测里的 id 都能在答案里找到" if not extra else "多出 %d 条" % len(extra))
sys.exit(0 if not extra else 1)
