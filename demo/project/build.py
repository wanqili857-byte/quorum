#!/usr/bin/env python3
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
