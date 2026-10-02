# 三轮自审的原始结论

> ## ⚠️ 更正（2026-10-02）：这三轮不是「三个来源」
>
> 配置里写着 kimi / qwen / codex 三个通道，**实际三条全部由同一个模型服务**。
> 两个 `claude-cli` 通道声明的 `ANTHROPIC_BASE_URL` / `ANTHROPIC_AUTH_TOKEN`
> **从未生效**——进程环境变量被 CLI 自己的用户级 settings 盖过，请求被送进本机代理，
> 由它按自己的 provider 路由。codex 那条没有被劫持，但它的 `request_model` 本来就与
> 实服务同名，**所以三条的实服务是同一个模型**。
>
> 真实的形状是 **1 个 vendor × 2 个 harness**（`claude-cli` / `codex-cli`），
> 不是「三个不同模型族」。**harness 那一轴是真的**；vendor 那一轴是假的。
>
> **发现本身保留**——它们是关于代码的，逐条对着源码核过，与谁审的无关。
> 作废的只是**置信度**那一列。原委与证据：[`../CORRECTIONS.md`](../CORRECTIONS.md)。

三个通道（kimi / qwen / codex）——**通道名属实，模型名不属实，见上**——
同一份工单 `../brief.md`，同一份材料。

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
