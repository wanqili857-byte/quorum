# 三轮自审的原始结论

三个真通道（kimi / qwen / codex），同一份工单 `../brief.md`，同一份材料。

| 轮 | 材料修订 | 拿到什么 |
|---|---|---|
| 1 | `033a3c0` | 3 份结论。抓到「契约写了、代码没做」类问题 9 条 |
| 2 | `fa06c78` | 抓到第一轮**修复本身**的问题（解析器、测试质量、边界） |
| 3 | `c0f0de9` | 抓到第二轮修复的残留 + 我自己的处置台账零断言 |

## ⚠️ 关于 round2 的缺件（如实说明）

`round2/` 里只有 qwen 一份。kimi 与 codex 的原始结论**被我的一条 shell 命令覆盖了**：

```bash
mv reviews/out/*.md reviews/out/round2/     # 第二轮的 kimi/codex 与第三轮同名 → 被覆盖
```

runner 本身有结论保护（已有非空结论先留档再原子落位），**但我的 shell 命令没有**。
这条已作为教训写进 `docs/LESSONS.md`——「工具保护了你，不代表你保护了自己」。

第二轮那两份的内容没有完整留存，只有交叉表的摘要（见下）。这是本轮唯一的实质性缺件。

## 各轮产出

- `round1/`：kimi(FAILED) · qwen · codex —— 那次 kimi 86 秒就退出、没产出东西，门禁正确拒收
- `round2/`：qwen（kimi/codex 缺失，原因见上）
- `round3/`：kimi · codex · qwen(FAILED) · `CROSS-TABLE.md`
  - 第三轮 qwen 交回的是一份**阻塞请求**（它的沙箱拒了 `python3`，它停下来问而不是硬凑弱结论）。
    门禁拒收了它，并且这正是「审核员卡住 ≠ 审核员交了个差结论」这条新识别的样本。

逐条处置在 [`../dispose.md`](../dispose.md)——**20 条带可执行断言**，`quorum verify` 会真跑。
