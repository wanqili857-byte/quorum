Bash 被门禁挡住：`ls`/`cat`/`git`/`find` 能跑，但任何 `python3`（含 pytest、`quorum`）一律 "requires approval" 且未被批准。工单要求「每个数字自己重算 + 附命令输出」，没有执行权限就只能给静态结论 —— 那等于交一份不合格的作业。

三个选择，选一个我立刻继续：

1. **批准 Bash 执行**（推荐）：放行 `python3` / `.venv/bin/python`。我全程只读仓库、只写 `$TMPDIR`，不碰仓库内任何文件。
2. 明确说「只做静态审计」：我按源码逐条给结论，判定栏标注「静态复验（未执行）」。
3. 你自己跑我给的三条命令，把输出贴回来。

等你一句话。同时我先把不依赖执行的发现整理好了（已读完 `quorum/*.py` 全部 9 个模块、`tests/`、`demo/`、`templates/`、CI、工单）。预告三条已可从源码定死的：

- **COI 校验有洞**：`config.py:176` 的 `f != "unknown"` 让「都不写 family」的两条 primary 直接免检 —— 而 `family` 默认值就是 `unknown`。
- **`cross` 的结论照样进「跨模型族一致」**：`plate.py` 的 `Row`/`Cluster` 里根本没有 `role` 字段，README/CONTRACT 承诺的「cross 不计入跨模型族一致」在实现里不存在。
- **`check-leaks --self-test` 的主断言被自己过滤掉了**：`cli.py:155` 用 `if "样本" not in f` 过滤失败项，而内置规则失败的消息模板正好是「正则抓不到自己种的**样本**」—— 全部被滤掉，只剩误报检查。

第 2、3 条正好是工单 §2.C「门禁绿但材料错」在 quorum 自己身上的两个实例。
