# quorum · 独立复核结论 · codex · 2026-10-01

> 工单: `brief.md` · 模型族: `deepseek` · 角色: `cross`
> 方式: 独立进程 headless（干净上下文，与作者会话无共享记忆）
> 材料快照：`git:033a3c067210`（git 仓库，工作区干净）
> ⚠️ **材料在审核期间发生变化**（git:033a3c067210 → git:033a3c067210+dirty:cf691a72cd09），结论可能对应中间的某个状态。

---
## 第一节 · 声明复验总表

> **执行环境说明（影响证据类型，先声明）**：本会话是**只读沙箱**，且机器上**没有任何可写临时目录**（`open('/tmp/x','w')`、`tempfile.mkdtemp()` 均 `PermissionError: Operation not permitted`）。因此 `pytest`、`quorum run`、`plate --dispose`、`verify` 这几个**会落盘的 CLI** 我一个都没能端到端跑起来。替代做法：用 `.venv/bin/python -c` **在内存里调用 quorum 的每一个纯函数**（`gates.evaluate/split_table_rows`、`plate.collect/cluster/render`、`ledger.parse/run_checks/exit_code`、`config.load`、`snapshot.take`、`leaks.scan/self_test`），并直接从数据文件重算全部数字；`demo/project/build.py` 不需要落盘，我用 4 个 `PYTHONHASHSEED` 真跑了。下文除标注【静态】外，都是【跑】出来的。

| 声明 | 我复验到什么 | 判定 |
|---|---|---|
| A1 审核员只读、结论由 runner 落盘 | `codex-cli` 有 `-s read-only`（channels.py:85）；但 `claude-cli` 的 argv 只有 `claude -p <prompt> [--model M]`（channels.py:78-82），**没有任何沙箱/只读参数**。而作者真配置 `reviews/review.yaml` 的两个 primary（kimi/qwen）全走 claude-cli。只读=工单措辞+CLI 默认，quorum 没表达 | 🔴 |
| A2 内容优先于退出码 / 四门 | rc 确实被忽略（gates.py:42-48 不看 rc）✅；但**只有 3 个谓词**，没有独立第 4 道「非空」门；且空洞产出能过（见 2-7） | 🟡 |
| A3 先临时文件 · 已有非空先留档 · 原子落位 | `run` 满足（`protect_existing`+`atomic_write`）；**`plate --dispose` 是裸 `open(path,"w")`**（cli.py:117），无留档无原子，且默认写的就是 `cfg.ledger`（我算出两路径逐字符相同） | 🔴 |
| A4 密钥不进配置/命令行 | 配置只有路径、argv 无密钥（argv=`claude -p '<prompt>' --model kimi-k2.7-code`）✅；但 `_resolve_env` 把内容填进**子进程环境**，`ps -E`／`/proc/<pid>/environ` 可见 | 🟡 |
| A5 材料快照指纹真能发现材料变化 | **git 仓库里 `sources`/`snapshot_exclude` 是死配置**：`take()` 命中 HEAD 就 return，`_tree()` 永不执行；指纹=sha256(HEAD+porcelain)，与材料内容无关 | 🔴 |
| A6 同 family 不得两个 primary | 校验在，但 `f != "unknown"`（config.py:176）把默认值豁免——两条 primary 都不写 `family` 即通过 | 🔴 |
| A7 plate 只解析表头含「严重度」的表 | 实为 `"严重度" in cells[0]`——**只认第 0 列且要子串精确**；换写法整份结论被静默丢弃，而「已收结论」按文件是否存在判定 | 🔴 |
| A8 verify 四档语义 | 四档与代码一致✅；但**全行无 `check` 的台账默认退出码=0**；且 `error` 档也返回 1，与 CONTRACT「LIE 是**唯一**不可接受的一档」不符 | 🟡 |
| CONTRACT：`cross` 的结论不计入「跨模型族一致」 | `grep -n role quorum/plate.py quorum/ledger.py` **无输出**，`Row`/`Cluster` 无 role 字段——规则结构上不可能实现 | 🔴 |
| demo 三个事故真能复现 | 事故二（正文被掏空）、事故三（遍历 set→哈希随机）成立；**事故一的「41.0%」在数据里复算不出来** | 🔴 |
| README/CONTRACT「工具两百来行代码」 | `wc -l quorum/*.py` = **1269** | 🔴 |
| 工单自称「tests 20 个」 | `grep -c "^def test_"` = **21** | 🟡 |

## 第二节 · 逐条发现

（证据列即「我怎么查出来的」。）

| 严重度 | 位置 | 问题 | 证据 | 建议 |
|---|---|---|---|---|
| 🔴 | `quorum/cli.py:117` | **`plate --dispose` 原地截断处置台账**。裸 `open(path,"w")`，无 `protect_existing`、无 `atomic_write`。默认路径 `out_dir/<project>-dispose.md` 与 `demo/review.yaml` 的 `ledger: out/demo-dispose.md` 是**同一个文件** | 【跑】`load("demo/review.yaml")` 后 `os.path.abspath(out_dir/demo-dispose.md)==os.path.abspath(ledger)` → `True`。【静态】cli.py:115-117 与 LESSONS.md 事故二自述真因（`open(p,"w")` 先截断）是同一写法 | 与 `run` 同等待遇：`protect_existing`→临时文件→`atomic_write` |
| 🔴 | `demo/project/data/*.jsonl` ↔ `demo/project/report.md`、`demo/canned/alpha.md` | **demo 事故一的数字不成立**。报告写「严格命中 41.0%」。我从唯一事实源重算：答案 100 条、预测 41 条、交集 41 条、标签命中 **31** 条。即覆盖率 41/100=**41.0%**（正好等于那个数），命中率 31/41=**75.61%**，对全 100 条 31/100=**31.0%**。没有一种是 41.0% 的命中率 | 【跑】`sum(1 for i in inter if pm[i]==am[i])`=31；`round(100*hit/len(pred),4)`=75.6098。alpha.md 那句「用这 41 条重算恰好得 41.0，与区块逐位吻合」是**被这条工具用来抓「假证据」的假证据** | 让 `make.py` 的报表数字由数据算出（如直接写 75.6%），否则 demo 教的是错的 |
| 🔴 | `quorum/plate.py:104-116` | **`Cluster.label()` 只看 `len(families)`、不看 role**，`role: cross` 照常计入「跨模型族一致 · 高置信」 | 【跑】对 demo 现有结论 `collect`→`cluster`：簇 1 = `跨模型族一致 · 高置信`，families `[vendor-a,vendor-b,vendor-c]`，reviewers `[alpha,beta,gamma]`，why `同文件 + 相似度 0.26`。而 gamma 是 `role: cross`，且 `canned/gamma.md` 那条🔴是作者自认写错的 | 实现 role 过滤，或把标签改名为「作者声明 ≥2 个 family」 |
| 🔴 | `quorum/config.py:145,176` | **COI 校验有洞**：`family` 缺省值 `"unknown"`，校验条件 `f != "unknown"` 把它排除。三条 primary 全不写 `family` 即可全部通过「硬约束」 | 【跑】注入 YAML（两条 primary 不写 family）→ `load` 成功，得到 `[('a','unknown','primary'),('b','unknown','primary')]`；对照组显式 `family: same` → 抛 `ConfigError('COI：同一 family…')`。`family` 是唯一依据且是自由字符串（`templates/review.yaml` 把 codex-cli 标成 `family: deepseek`，无人校验） | 至少校验 `channel.kind+model`↔`family` 一致，或把「高置信」降级为「作者声明了 N 个 family」 |
| 🔴 | `quorum/snapshot.py:48-57` | **git 仓库里 `sources`/`snapshot_exclude` 完全失效**。`take()` 命中 `rev-parse HEAD` 即 return，`_tree()` 永不执行；digest = sha256(HEAD+`git status --porcelain`)，与材料字节无关 | 【跑】同一份 `demo/review.yaml`，把 `sources` 改成 `["definitely/not/here"]`、`snapshot_exclude` 改成 `["totally/bogus"]`，`snapshot.take()` 两次 digest **完全相同** = `git:033a3c067210+dirty:cf691a72cd09`，kind=`git`。而当前 porcelain 只有一行 `?? out/`——已列脏的文件再改内容，porcelain 不变→digest 不变 | 在 git 分支也把 `sources` 内容哈希并进 digest，或至少报出「指纹仅覆盖 HEAD+脏文件名单」 |
| 🔴 | `quorum/cli.py:154-162`（配 `leaks.self_test`） | **`--self-test` 的核心断言被自己过滤掉了**。`bad = [f for f in self_test(pats) if "样本" not in f]`，而「抓不到自己种的样本」的失败消息正好含「样本」→ 全部被滤除，只剩误报方向 | 【跑】给 `default_patterns` 追加一个永不匹配的规则，`leaks.self_test` 返回 `["坏规则：正则抓不到自己种的样本 'sample'"]`；套用 cli 的过滤后 = `[]` → 打印「**全部规则都能抓到自己种的样本**」（假话） | 不要用中文子串过滤；让 `self_test` 返回结构化结果 |
| 🔴 | `quorum/gates.py:42-48` | **门禁数的是「emoji 出现次数」不是「发现条数」**，概述表里的标记也算。作者自己的说法（概述表不会被误当成发现）只对 `plate` 成立 | 【跑】`SEVERITY_RE.findall`：alpha=3 但 `split_table_rows` 只 2 行；beta=3/2；gamma=3/3。构造一份无任何发现表、只有 `🔴🟡🟢`×30 + 一句「最脆弱」+ 1200 个「。」的产出（4013B）→ `evaluate(...).passed == True` | 标记计数改为只数 `split_table_rows` 命中行 |
| 🔴 | `quorum/leaks.py:20-24,74-78`、`.gitignore` | **`check-leaks` 可被文件类型绕过**：只扫 15 种扩展名，`.log/.bak/.env/无扩展名` 全不扫，`.git` 被跳过。**本仓库现在就有一份未被扫描的泄漏面** | 【跑】`main(["check-leaks","ROOT"])` → 「未发现任何命中」，退出 0；但我遍历全树套同一套正则，`out/.raw/quorum-codex-2026-10-01.log`（**177134 B**）命中 `~` **65 次**、`<示例密钥>`（第 1938 行）、本机用户名；只因为它在 `.log` 里而被跳过。`.gitignore` 忽略 `demo/out/` 但**不忽略 `out/`**（`git status` 显示 `?? out/`） | 扫描不再按扩展名白名单，改为按内容/文本探测；把 `out/` 加进 `.gitignore` |
| 🟡 | `quorum/plate.py:162` | **`match_reason` 会说谎**：`best.why = "同文件 + 相似度 ..." if best_score > thr_text else ...`——判据是**分数**不是 `same_file`。于是跨文件合并也会被标成「同文件」 | 【跑】构造两条措辞相同但位置不同文件的发现（`alpha.md` vs `beta.py`）→ 合并成 1 簇，`why="同文件 + 相似度 0.20"`，而 `_paths` 交集为空 | 用真实的 `same_file` 布尔来选措辞 |
| 🟡 | `quorum/gates.py:141`、`quorum/ledger.py:63` | **表头识别过窄且失败静默**。`plate` 只认第 0 列含「严重度」；`ledger` 的 check 列表头是**大小写敏感**的精确匹配 | 【跑】`split_table_rows`：正常表头→1 行；`严重程度`→**0 行**；`| Severity | File |…`→**0 行**。`ledger.parse`：表头 `Check`（大写 C）→ 解析出 **0 行**，无任何报错 | 解析失败要可见（告警/退出码），并放宽表头匹配 |
| 🟡 | `quorum/plate.py:137-168` | **该合的没合**：同一条发现、措辞不同 → 分数 0.0135，被拆成 2 簇 | 【跑】两条同指「分母缩水」但措辞不同（`报表分母与预测条数不一致` vs `分母被 continue 静默缩小`）→ `cluster` 返回 **2 簇**；`_weighted_jaccard`=0.0135 ≪ thr_text(0.10)。注释自称「同一条 0.14–0.21、不同条 ≤0.06」没有分离度（我上面 FP 例里不同条也到 0.20） | 承认阈值没有区分度，或改成需人工合并的候选推荐 |
| 🟡 | `quorum/ledger.py:121-127` | **全行无 `check` 的台账默认退出码=0**（只在 `--strict` 下才 1）。一份「24 行全 ✅、无一条断言」的台账在 CI（默认）里是绿的 | 【跑】解析 `| 1 | a | | ✅ |`×2 → verdicts `['no-check','no-check']`，`exit_code(v)=0`，`exit_code(v,strict=True)=1` | CI 默认用 strict，或把「无断言」并入非零 |
| 🟡 | `demo/ledger_example.md` 第 2/3 行 ↔ `quorum/ledger.py` | **`verify` 无法识别「装饰性断言」**：它只问「这条命令现在退 0 吗」，不问「把修复回滚它还退 0 吗」 | 【跑】第 2 行 `grep -q METRICS project/report.md`→rc0→判**✅ 已修**，而 `wc -c`=63B、正文一个字都没补；第 3 行 `grep -q 'sorted(' project/build.py`→rc0（只命中第 13 行的 `print`），病根第 7 行 `ids = {...}` 原封不动，却判成**「🟡 台账未更新（其实已经好了）」**（与事实相反） | 要求 `check` 提供变异见证，或文档里把「装饰断言」作为反例显式列出 |
| 🟡 | `quorum/snapshot.py:73,81,89-96` | 非 git 路径的两个洞：排除是**前缀匹配**（`out` 会吞掉 `outputs/`）；>8MB 文件只按 `(size, int(mtime))`，同秒同大小改动不可见 | 【跑】`"outputs/x.md".startswith("out")`→True、`"database/x".startswith("data")`→True。【静态】snapshot.py:95 `int(st.st_mtime)` 截到秒 | 排除匹配改用 `rel == x or rel.startswith(x+os.sep)` |
| 🟢 | `tests/test_quorum.py:70-77,230-235` | **两条「永远为真」的断言**：`assert "SECRET-VALUE" not in str(sec.parent/"review.yaml")` 检查的是一个从未被创建的文件路径；`test_e2e_material_change_is_flagged` 只断言正文含「材料快照」——头部永远含它，删掉变化检测代码该测试照样过 | 【静态+跑】`tests` 共 21 个 `def test_`、32 个 `assert`；这两条不可能失败 | 前者改成真的把密钥写进去再断言配置文本不含它；后者人为改材料后断言出现「材料在审核期间发生变化」 |
| 🟢 | `quorum/cli.py:62`、`gates.py:102-106`、`gates.py:77-83` | 工程细节：`tempfile.mktemp`（已弃用且有竞态）；`atomic_write` 的临时名固定为 `path+".tmp"`（并发会互踩）；`protect_existing` 的 `.bak` 名只有 `%H%M%S`（同秒两次运行会互覆盖） | 【静态】三处源码 | 用 `mkstemp`/`NamedTemporaryFile` 与带随机后缀的备份名 |

### 第二节附 · §2.C 在 quorum 自己身上找「门禁绿但材料错」的反例

作者的核心论断是「门禁检查的是它自己定义的那个性质，不是读者以为的那个性质」。**这个论断在 quorum 自己身上成立，且有多个实例**——工具宣称的保证，逐个都能被「形式合规但语义错」的输入骗过：

1. **`min_severity_marks`**：读者以为它在保证「有足够多发现问题」；它保证的是「文本里出现过足够多 emoji」。我构造的 4013B、90 个 emoji、**0 条发现**的产出门禁全绿（见 2-7）。
2. **`min_bytes`**：读者以为在保证「有实质内容」；它保证的是「字节数够」。填充字符即可。
3. **`require_sections: ["最脆弱"]`**：读者以为在保证「有那节内容」；它保证的是「这四个字出现在某处」。写在正文句子里也算。
4. **「材料快照指纹」**：读者以为它绑定材料内容；git 仓库里它绑定的是 `HEAD + 脏文件名单`，与材料字节无关，且**改 `sources` 也不改变它**（见 2-5）。
5. **「已收结论：alpha,beta,gamma」**：读者以为三家结论都进了表；它保证的是「这三个文件存在」（plate.py:172）。某家表头写成「严重程度」时，文件照样列进「已收结论」，但贡献 **0 行**且**无告警**，只要 >=1 家能解析，`plate` 就正常退出。
6. **`check-leaks --self-test`**：读者以为它在证明「每条规则都能抓到自己的样本」；它保证的只是「规则没误伤一句安全文本」——抓不到样本的失败被一行过滤吃掉（见 2-6）。这正是 LESSONS.md 自己吐槽的「一句读起来像已验证的输出」。
7. **`check-leaks`（无 `--self-test`）**：读者以为它在当「公开仓的守门人」；它保证的是「这 15 种扩展名里没有命中」。本仓库已有一份 177 KB 的 `.log` 含 `~`×65 却不被看（见 2-8）。
8. **`verify` 的 `check`**：读者以为「✅ 已修」被验证过；它保证的是「这条命令此刻退 0」。demo 自带两条装饰断言，一条给出假 ✅、一条给出假的「台账未更新」（见 2-13）。
9. **COI「硬约束」**：读者以为它在保证「两家审核员真的独立」；它保证的是「同一个人没有把同一个字符串写两遍」（见 2-4、2-3）。
10. **`Cluster.label()` 的「高置信」**：读者以为「跨模型族一致」= 不同厂商独立收敛；它保证的是「`families` 计数 ≥2」。`role: cross` 不清除、`family` 不校验，demo 里一条写错的 cross 结论照样进了「高置信」簇（见 2-3）。

一句话：**这个工具最核心的卖点——「你没办法在没验证过的情况下宣称某件事是对的而不被发现」——在它自己身上就不成立**；它把「可被发现」定义成了「作者写下的那个字符串出现了/那条命令退 0 了」。

## 最脆弱的一环（前三）

1. **「高置信」这个标签本身。** 它由作者手填的 `family` 字符串去重计数得出，`role: cross` 被结构性地忽略（`role` 在 `plate.py`/`ledger.py` 零引用），`family` 又没有任何一致性校验（模板里把 `codex-cli` 标成 `deepseek`）。我用 demo 的真实结论跑出：一条作者自认写错的 🔴，被汇总表列成「跨模型族一致 · 高置信 / alpha+beta+gamma」。读者看的是汇总表，「逐条列原话」的缓解只在明细里，属于事后补救而非门禁。
2. **泄漏门禁是装饰。** 核心自检被 `if "样本" not in f` 过滤掉（自检永远不会因「抓不到样本」而失败），扫描面又只有 15 种扩展名，真实仓库里已经存在一份未被扫描、含本机绝对路径 65 处的日志文件，而 `quorum check-leaks .`（也正是 CI 里唯一跑的那条）打印「未发现任何命中」。
3. **处置闭环可以被装饰性断言骗过。** `verify` 只问「现在退 0 吗」，不问「修复回滚后是否失败」；作者自己的示例台账里就有两条这样的 check，分别产生假 ✅ 和假「未更新」，而默认（非 `--strict`）下一份「全 ✅、无一条断言」的台账退出码是 0——最需要被审的那类吹牛，恰好是默认放行的。

## 附录 · 我推翻的既有结论

- **推翻 `demo/README.md` 与 `demo/canned/alpha.md` 的「用这 41 条重算恰好得 41.0，与区块逐位吻合」。** 从 `answers.jsonl`(100) + `pred_old.jsonl`(41) 复算：命中 31 条，31/41=**75.61%**，31/100=**31.0%**；41.0% 是**覆盖率**（41/100），不是命中率。demo 的头号事故，其数字本身就对不上——这条「假证据」恰好是该工具声称要抓的东西。
- **推翻 README「审核员只读、…审核员没有写权限，就不可能污染被审材料」。** 两个 primary 走的 `claude-cli` 通道 argv 里没有任何只读/沙箱参数（`claude -p <prompt> --model …`），只有 `codex-cli` 才有 `-s read-only`。只读性靠工单措辞，不靠 quorum。
- **推翻 CONTRACT「同源模型可以当 cross…它的结论不计入『跨模型族一致』」。** 实现里 `role` 一次都没被读；demo 的 cross（gamma）被计成第 3 个 family，直接进入「高置信」簇。
- **推翻 `docs/LESSONS.md`「四道内容门（体积 / 严重度标记 / 必需章节 / 非空）」。** `gates.evaluate` 只有 3 个谓词，「非空」被 `min_bytes` 吸收，不是独立一道门；而且三道门都不检查「是否存在发现表」。
- **推翻「材料快照指纹覆盖 `sources` 列出的路径」**——在 git 仓库这一前提下它是死配置（我改了 `sources`/`snapshot_exclude`，digest 不变）。
- **推翻 README/CONTRACT 反复出现的「工具本身只有两百来行代码」**：`wc -l quorum/*.py` = 1269。
- **推翻工单自己的小声明「tests 20 个」**：实为 21 个（`grep -c "^def test_"`）——顺带说明「跑通不等于通过」也要对测试数量本身生效。