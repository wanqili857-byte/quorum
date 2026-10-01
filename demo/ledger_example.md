# demo · 处置台账（示例：故意造出四种判定）

> `quorum verify --config demo/review.yaml --ledger demo/ledger_example.md`
>
> 最要命的输出不是「失败」，是 **status=✅ 而 check 失败**——那说明台账在说谎。
>
> 写 `check` 的唯一标准：**如果这个修复被回滚，它会不会红？** 不会红就是装饰性断言。

| # | 置信度 | 严重度 | 位置 | 问题 | 处置 | check | status |
|---|---|---|---|---|---|---|---|
| 1 | 跨模型族一致 | 🔴 | `report.md`/`pred_old.jsonl` | 覆盖率被当成了准确率 | 已改成「缺预测即中止」 | `python3 -c "import json;a={json.loads(l)['id'] for l in open('project/data/answers.jsonl')};b={json.loads(l)['id'] for l in open('project/data/pred_old.jsonl')};assert len(b)==len(a), 'pred 只覆盖 %d/%d'%(len(b),len(a))"` | ✅ |
| 2 | 单家独有 | 🟡 | `report.md` | 正文被掏空 | 待办：补口径/方法/局限 | `python3 -c "import re;s=open('project/report.md').read();body=re.sub(r'<!-- METRICS:START -->.*?<!-- METRICS:END -->','',s,flags=re.S);assert len(body.strip())>200, '正文只剩 %d 字'%len(body.strip())"` | ⬜ |
| 3 | 单家独有 | 🟡 | `build.py` | 切分不可复现 | 待办：先 sorted 再 shuffle | `grep -q 'keys = sorted(' project/build.py` | ⬜ |
| 4 | 单家独有 | 🟢 | `gate.py` | 门禁语义与名字不符 | 改名 | | ✅ |

## 四档判定各是什么

| 行 | 预期判定 | 为什么 |
|---|---|---|
| 1 | 🔴 **台账说谎** | status 是 ✅，但断言说 pred 仍只覆盖 41/100 |
| 2 | ⬜ 未修 | 断言是**判别性**的（把正文掏空它会红），而正文确实还是空的 → 正确地报「未修」 |
| 3 | ⬜ 未修 | 判别的写法：`grep -q 'sorted(' ` 会被文件里无关的 `sorted(dev)` 满足（**装饰性**），
改成 `keys = sorted(` 才真的测到那处修复 |
| 4 | ⚪ 无断言 | 没填 `check` —— 那只是「作者说修好了」，不算修好 |

## 工具抓不到的那一类：装饰性断言

如果第 2 行改写成 `grep -q METRICS project/report.md`，它会**通过**——
因为报告里确实还有那个词。可它证明的不是「正文被补回来了」，掏空正文它照样通过。

**这类断言 `verify` 抓不到**：要判断「修复被回滚后它会不会红」，工具得知道修复前的状态。
所以这条写在 `CONTRACT.md` 里，靠人守。
