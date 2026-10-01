# demo · 处置台账（示例：故意造出四种判定）

> `quorum verify --config demo/review.yaml --ledger demo/ledger_example.md`
> 最要命的输出不是「失败」，是 **status=✅ 而 check 失败**——那说明台账在说谎。

| # | 置信度 | 严重度 | 位置 | 问题 | 处置 | check | status |
|---|---|---|---|---|---|---|---|
| 1 | 跨模型族一致 | 🔴 | `report.md`/`pred_old.jsonl` | 分母静默缩水 | 已改成「缺预测即中止」 | `python3 -c "import json;a={json.loads(l)['id'] for l in open('project/data/answers.jsonl')};b={json.loads(l)['id'] for l in open('project/data/pred_old.jsonl')};assert len(b)==len(a), 'pred 只覆盖 %d/%d'%(len(b),len(a))"` | ✅ |
| 2 | 单家独有 | 🟡 | `report.md` | 正文被掏空 | 已补正文与口径 | `grep -q METRICS project/report.md` | ✅ |
| 3 | 单家独有 | 🟡 | `build.py` | 切分不可复现 | 待办 | `grep -q 'sorted(' project/build.py` | ⬜ |
| 4 | 单家独有 | 🟢 | `gate.py` | 门禁语义与名字不符 | 改名 | | ✅ |
