# quorum · 自审处置台账

> 三轮自审（kimi / qwen / codex，真通道）共提出 40+ 条。这里列的是**有断言的那部分**。
>
> 每条 `check` 的标准：**把这个修复回滚，它会不会红？** 不会红的不写进来。
> `quorum verify --config reviews/review.yaml` 会全部跑一遍。
>
> 这份台账本身就是对第三轮那条批评（「作者自己的台账零条断言，verify 恒绿」）的处置。

| # | 置信度 | 严重度 | 位置 | 问题 | 处置 | check | status |
|---|---|---|---|---|---|---|---|
| 1 | 跨模型族一致 | 🔴 | `cli.py` dispose | `plate --dispose` 裸 `open(path,"w")`，会原地截断用户填好的台账 | 改为 `protect_existing` + `atomic_write` | `pytest -q tests/test_quorum.py::test_dispose_protects_existing_ledger` | ✅ |
| 2 | 跨模型族一致 | 🔴 | `plate.py` | CONTRACT 说 cross 不计入「跨模型族一致」，代码里 `role` 从未被读 | `Cluster.primary_families` 只看 primary | `pytest -q tests/test_quorum.py::test_plate_ignores_cross_role_for_confidence` | ✅ |
| 3 | 跨模型族一致 | 🔴 | `config.py` | `family` 缺省 `"unknown"` 被 COI 校验豁免 → 三个 primary 不写 family 即可全过 | 缺 family 直接报错 | `pytest -q tests/test_quorum.py::test_config_requires_explicit_family` | ✅ |
| 4 | 跨模型族一致 | 🔴 | `leaks.py` | 只扫 `git ls-files` 跟踪文件 → 未跟踪但即将提交的 `.env` 不扫 | 加 `--others --exclude-standard` | `grep -q -- '--others' quorum/leaks.py` | ✅ |
| 5 | 跨模型族一致 | 🔴 | `ledger.py` | 台账用裸 `split("\|")`，与发现表两个切分器 | 复用 `gates._split_row` | `grep -q '_split_row' quorum/ledger.py` | ✅ |
| 6 | 跨模型族一致 | 🔴 | `gates.py` | 门禁数 emoji 出现次数而不是发现条数 | 数解析出的发现行，且要求 problem ≥ 8 字 | `pytest -q tests/test_quorum.py::test_gate_counts_findings_not_emoji_spam` | ✅ |
| 7 | 跨模型族一致 | 🟡 | `gates.py` | 表头「严重度」必须落第 0 列；数据行提到这三个字会被误判成表头 | 按列名映射 + 收紧表头判定 | `pytest -q tests/test_quorum.py::test_severity_column_need_not_be_first` | ✅ |
| 8 | 跨模型族一致 | 🟡 | `snapshot.py` | >8MB 文件只按 (size, mtime) → 同长度同 mtime 的替换隐形 | 首尾各 64KB 取样哈希 | `grep -q '_sample_hash' quorum/snapshot.py` | ✅ |
| 9 | 跨模型族一致 | 🟡 | `snapshot.py` | `snapshot_exclude` 裸 `startswith`、不支持 glob、根目录层永不匹配 | `_excluded()` 统一判定 + fnmatch | `grep -q 'fnmatch' quorum/snapshot.py` | ✅ |
| 10 | 跨模型族一致 | 🟢 | `cli.py` | `tempfile.mktemp()` 已废弃且产生竞态与孤儿文件 | 换 `mkstemp` | `! grep -q 'mktemp(' quorum/cli.py` | ✅ |
| 11 | 含交叉 · 中置信 | 🔴 | `cli.py` `leaks` | `--self-test` 的过滤条件恰好滤掉了它要抓的失败 | 去掉字符串过滤 | `pytest -q tests/test_quorum.py::test_cli_self_test_can_actually_fail` | ✅ |
| 12 | 含交叉 · 中置信 | 🔴 | `tests/` | 两条**不可能失败**的断言（断言不存在的文件、断言 runner 总会写的串） | 改成真能失败 | `pytest -q tests/test_quorum.py::test_e2e_material_change_is_flagged tests/test_quorum.py::test_env_file_indirection_keeps_secret_out_of_config` | ✅ |
| 13 | 含交叉 · 中置信 | 🔴 | `demo/` | demo 事故一的 41.0% 复现不出来 | 改为「覆盖率被当成准确率」，并加 `metrics.py` | `python3 demo/project/metrics.py \| grep -q '41.0%'` | ✅ |
| 14 | 含交叉 · 中置信 | 🟡 | `plate.py` | `--json` 丢掉了 `disagreement` 与 `primary_families` | 补进输出契约 | `grep -q '"disagreement"' quorum/plate.py` | ✅ |
| 15 | 含交叉 · 中置信 | 🟡 | `plate.py` | `disagreement` 阈值 0.20 落在「同一条发现」的相似度区间内 → 信号无效 | 提到 0.30 并写明标定依据 | `grep -q '平均相似度 %.2f < 0.30' quorum/plate.py` | ✅ |
| 16 | 含交叉 · 中置信 | 🟡 | `plate.py` | `match_reason` 用了内层循环泄漏出来的 `same_file` | 显式记录 `best_same_file` | `grep -q 'best_same_file' quorum/plate.py` | ✅ |
| 17 | 单家独有 | 🟢 | `demo/ledger_example.md` | 示例台账里的 check 是**装饰性**的（掏空正文照样通过） | 换成判别性断言，并写清工具抓不到这一类 | `pytest -q tests/test_quorum.py::test_demo_ledger_reports_the_expected_verdicts` | ✅ |
| 18 | 单家独有 | 🟢 | `README.md` `CONTRACT.md` | 代码体量的说法互不一致，且写死了会漂的数字 | 改成不写死 | `! grep -qE '两百来行\|引擎约 [0-9]+ 行' README.md CONTRACT.md` | ✅ |
| 19 | 单家独有 | 🟡 | `cli.py` `gates.py` | 「审核员卡住了」与「交了个差结论」在门禁看来一样 | 加 blocked 识别与针对性提示 | `grep -q 'BLOCKED_MARKERS' quorum/gates.py` | ✅ |
| 20 | — | — | `demo/review.yaml` | COI 校验的是标签不是来源（三个「不同族」实际同一个通道） | 无法自动识别，改为**把通道名记进结论头部**并在 CONTRACT 写明 | `grep -q '模型族(声明)' quorum/gates.py` | ✅ |

## 写这份台账时自己踩的坑（留档）

第一版里有三条 `check` 写成了「**文件里不该出现某个字符串**」：

```
! grep -q '"unknown"' quorum/config.py
! grep -q '"样本" not in f' quorum/cli.py
! grep -q 'grep -q METRICS' demo/ledger_example.md
```

跑 `verify` 时三条全红。但它们不是「修复失效」，而是**断言写错了**——
那三个字符串分别躺在 `Reviewer` 的默认值、**我解释这个修复的注释**、
以及 demo 台账里**说明这是反面例子**的段落里。

这跟台账要防的「装饰性断言」是同一族毛病：**测的不是那件事**。
现在三条都换成行为断言（真的构造出场景，看它会不会失败）。

## 没写进本表的部分

三轮合计 40+ 条里，有些是**已确认但选择不修**、或**无法用断言表达**的：

| 项 | 为什么不修 |
|---|---|
| `claude-cli` 无法在 CLI 层强制只读 | 上游 CLI 没有沙箱开关。已改为：运行时打印只读强度 + 写进结论头部 + 事后材料快照比对兜底 |
| `family` 无法验证真伪 | 这是**声明字段**，工具无法知道两个通道背后是不是同一个模型。已写进 CONTRACT，并记录通道名供人事后核对 |
| 装饰性断言无法自动识别 | 判它需要知道「修复前的状态」。写在 CONTRACT 里，靠人守 |
| 审核员沙箱能力差异 | 不同会话的权限不同（同一家的 qwen 两次跑，一次能跑 python 一次不能）。已加 blocked 识别，但无法预防 |
