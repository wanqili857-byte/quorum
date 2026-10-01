# quorum · 多模型交叉审计

**让几个不同厂商的模型互相挑错，把「审核」从一次性动作变成可证伪的回归。**

```bash
quorum run    --config review.yaml --all     # 起独立进程审核（干净上下文）
quorum plate  --config review.yaml --dispose # 交叉表：一致 / 独有 · 导出处置台账
quorum verify --config review.yaml           # 跑台账里的断言 → 抓「台账说谎」
quorum check-leaks .                         # 泄漏自检（公开仓的守门人）
```

---

## 为什么需要它

单个模型审自己的同类工作，最大的问题是**它的错你发现不了**。换个模型审能补上——但换了模型之后，
你面对的是一堆自由文本的「发现」，而你没有任何机制判断哪条可信。

真实发生过的一幕：三个审核员里有一个断言「在役权重其实是上一版」，语气肯定、附了命令；
**是另一个审核员用逐字节 `cmp` 把它推翻了**。只用一个审核员，这条假发现就会被当成真的去改。

还有更贵的一幕：**审核员的「✅ 已修」没有人验证**。某一轮复核的全部价值就在于去审上一轮的 ✅，
结果相当一部分站不住。台账越厚，这个缺口越大。

quorum 针对的就是这两件事：**交叉**（谁说的、几家说、是不是同一个模型族）与**可执行断言**
（`check` 列跑不过的 ✅ 就是台账在说谎）。

## 30 秒上手（不需要任何 API key）

仓库自带一个 demo，三个「事故」都是真实情节的合成版：

```bash
pip install -e '.[dev]'
python3 demo/project/make.py
quorum run   --config demo/review.yaml --all
quorum plate --config demo/review.yaml
quorum verify --config demo/review.yaml --ledger demo/ledger_example.md
```

demo 里的三个审核员走**桩通道**（打印预设结论），所以整个过程零密钥、零网络。
其中一个审核员的结论是**错的**——`quorum plate` 会把它和其他两家的正确结论对齐在同一簇，
并在明细里逐条列出各家的原话，让你看见「同一处、不同结论」。

## 真实使用

```yaml
# review.yaml
project: my-project
repo: .                       # 相对本文件解析，换 CWD 结果不变
brief: reviews/brief.md       # 工单：自包含，审核员没有前轮记忆
out_dir: reviews/out
ledger: reviews/dispose.md    # 处置台账（verify 读它）
sources: ["src", "data", "reports"]     # 材料快照指纹覆盖这些路径

channels:
  ark:                                    # 任何 Anthropic 兼容端点都能接
    kind: claude-cli
    model: kimi-k2.7-code
    env:
      ANTHROPIC_BASE_URL: https://ark.cn-beijing.volces.com/api/coding
      ANTHROPIC_AUTH_TOKEN_FILE: ~/.config/ark_key   # 密钥只给路径，内容不进配置
  codex:
    kind: codex-cli

reviewers:
  - {name: kimi,  channel: ark,   family: moonshot, role: primary}
  - {name: qwen,  channel: ark,   family: qwen,     role: primary}
  - {name: codex, channel: codex, family: deepseek, role: cross}
```

`family` 是 COI 规则的载体：**同一 family 不能有两个 primary**——同源模型看不出同源的盲区。
配置违反这条会直接报错。

## 四条契约

引擎一千多行（`wc -l quorum/*.py` 现算），读到这儿你大概已经能猜到它长什么样——**真正起作用的是下面这四条契约**：
它们写死在 `CONTRACT.md` 里，也写死在模板里。

| 契约 | 约束什么 |
|---|---|
| **配置** | 一个 `review.yaml` 描述「审什么、谁来审、门禁多严」。**引擎里不出现任何具体项目的信息** |
| **工单** | 自包含、**按「声明」而不是「文件」组织**、必须留一节让审核员反驳作者的方法学结论 |
| **输出** | 严重度表（每条带「我怎么查出来的」）+ 最脆弱一环 + 附录「推翻了什么」 |
| **处置** | 台账每行可挂一条 `check` 断言；`verify` 跑它 |

## 它不是什么

- **不是「多跑几个模型」的包装。** 价值在交叉与可证伪，不在并发。单个模型 + 人审在很多场景更划算。
- **不保证审核员是对的。** 交叉能提高信噪比，不能消除错误。`plate` 的输出里「单家独有」**必须人工复验**。
- **不是自动化裁判。** 它给你一张对齐好的表和一套可跑的断言，判断仍然是你的。
- **什么时候不该用**：材料里没有**可复算的事实源**时，多模型只会互相抄——先让材料可复算，再谈交叉审计。

## 设计上刻意做的选择

- **只走 CLI，不提供 import API。** 需要编程接入就消费 `quorum plate --json`（稳定的输出契约），
  这样上层不必跟版本绑定，非 Python 项目也能用。也不做 MCP——那只是给 CLI 套一层生命周期。
- **审核员只读、结论由 runner 落盘。** 结论由 runner 写，审核员进程不碰材料。
  注意：`codex-cli` 能在 CLI 层**强制**只读（`-s read-only`），`claude-cli` 不能——
  后者只能靠工单措辞 + **事后材料快照比对**兜底。`run` 会把只读强度打印出来并记进结论头部，
  不让「审核员只读」变成一个没人验证的假设。
- **内容优先于退出码。** 退出码描述的是进程，不是材料。完整结论不该因为收尾信号被作废。
- **材料快照指纹进结论头部。** 「这份结论审的是哪一版」必须能被回答；各家快照不一致时 `plate` 直接报警。
- **结论先写临时文件、四门全过再原子落位**，已有非空结论先留档——损坏一份已有结论比不产出更糟。

## 这个仓库自己就是一次用例

quorum 被它自己审过三轮 —— 三个真通道（kimi / qwen / codex），40+ 条发现，逐条处置。
这不是营销话术，材料和台账都在仓库里：

| 位置 | 是什么 |
|---|---|
| `reviews/brief.md` | 自审工单（按「声明」组织，不是按文件） |
| `reviews/review.yaml` | 真通道配置（三个不同模型族） |
| `reviews/out/round*/` | 三轮的原始结论 + 交叉表 |
| `reviews/dispose.md` | 处置台账，**20 条带可执行断言** |

跑一下：

```bash
quorum verify --config reviews/review.yaml     # 20 条断言，全部会真跑
```

三轮里抓到的都是「作者看不见自己」的那一类，摘三条最有代表性的：

- `plate --dispose` 是裸 `open(path,"w")`，而默认路径正好是**用户填好的台账**——
  同一个写法就写在 `docs/LESSONS.md` 的「事故二」里，作者写了教训却没检查自己的代码。
- `check-leaks --self-test` 的过滤条件恰好滤掉了它要抓的失败
  （失败消息含「样本」，而代码写的是 `if "样本" not in f`）——
  **「检查能不能失败」的检查，自己不能失败**。
- `CONTRACT.md` 写着「cross 的结论不计入跨模型族一致」，而 `role` 在两个模块里**从未被读取**。

## 文档

- [`CONTRACT.md`](CONTRACT.md) —— 四条契约的正典（想接进自己流程，读这份）
- [`docs/LESSONS.md`](docs/LESSONS.md) —— 每条硬规则背后的**真实事故**
- [`demo/README.md`](demo/README.md) —— 三个事故的说明

## 许可

MIT
