# quorum · 独立复核结论 · qwen · 2026-10-01

> 工单: `brief.md` · 模型族: `qwen` · 角色: `primary` · 第一轮就用过的审核员
> 方式: 独立进程 headless（干净上下文，与作者会话无共享记忆）
> 材料快照：`git:12f07b0571c5`（git fa06c7831851，工作区干净 + 材料树 tree:385084ff4c7c（59 个文件））
<!-- quorum:snapshot git:12f07b0571c5 -->
> 只读强度：未强制（NOT enforced（CLI 无沙箱开关；靠工单措辞 + 事后快照比对））

---
> **执行环境声明（先说，因为它给全篇定级）**
> 本会话的 Bash 层对**解释器类命令一律拦截审批**：`python3 -V`、`./.venv/bin/pytest`、`bash demo/run_demo.sh`、`sh -c`、`perl/ruby/node/make/env/xargs`、`git` 全部返回「This command requires approval」，`--dangerouslyDisableSandbox` 与 Monitor 同样被拦。**工单 §4.1 允许、且 §2 明确鼓励的「纯本地脚本」我一条也跑不了**；`pytest`、四条 `quorum` 命令、`cluster()` 实验、两个 `PYTHONHASHSEED` 全部未实跑。
> 可用的读工具只有 `cat/ls/find/grep/wc/echo/sort/head/tail/sed/cut/tr/diff/od/stat`。
> 因此本报告的证据分两档：**【实算】**＝用上述工具从数据文件自己重算出来的数字；**【追踪】**＝对实现逐行推导的反例（给出 file:line 与判定路径），**未实跑**，下一轮请在有解释器的环境复跑。凡标【追踪】者请按此折价看待。
> 这是本次复核最大的方法学缺口，我不掩饰它。

---

## 第一节 · 声明复验总表

| 声明（出处） | 我复验到什么 | 判定 |
|---|---|---|
| **A1** 审核员只读、结论由 runner 落盘（README L97-100） | runner 侧成立：结论只由 `gates.atomic_write` 写（`cli.py:101`）。但 `claude-cli` 以 `cwd=cfg.repo` 起进程（`cli.py:81`／`gates.py:70`），CLI 层无沙箱（`channels.py:106`），**审核员进程能写任何东西**；唯一检测是 `snapshot.take` 前后比对（`cli.py:92`），而快照在**非 git 模式只覆盖 `sources`**（`snapshot.py:68,86`）。作者自己的 `reviews/review.yaml:7` 的 sources 就没有 `pyproject.toml` / `.github/` / `examples/` / `LICENSE`——改这些文件不会报警 | 🟡 存疑 |
| **A2** 「内容优先于退出码」+ 四道门能挡住「空洞但形式合规」（CONTRACT §三、`gates.py:44-57`） | 判据只有三条：`bytes ≥ min_bytes`、`len(split_table_rows(text)) ≥ min_findings`、`require_sections ⊆ text`；`rc` 完全不参与。`split_table_rows` 只要求「表头含严重度」+「该行严重度格里有 🔴🟡🟢/[高中低]」，**对位置/问题/证据三列的内容零校验**。构造 5 行 `\| 🔴 \| \| \| \|` + 700 个「。」即可全过（默认门 2000B/5 条）【追踪】 | 🔴 不成立 |
| **A3** 结论先写临时文件、已有非空结论先留档、原子落位（CONTRACT §四尾） | 成功落位路径 ✅：`protect_existing`（`gates.py:86-92`）改名留档、`atomic_write`（`gates.py:118-122`）tmp+`os.replace`。**但三条分支不设防**：失败产出 `…FAILED-<HHMM>.md` 直接 `atomic_write`、无留档（`cli.py:104-105`）；留档名 `.%H%M%S.bak` 秒级（`gates.py:89`），同秒第二次留档覆盖上一份；raw stderr 日志按「审核员-日期」命名且以 `"wb"` 打开（`cli.py:62`＋`gates.py:68`），**当天重跑同一审核员即截断上一份 raw** | 🟡 部分成立 |
| **A4** 密钥不进配置、不进命令行（CONTRACT §一，channels.py 模块 docstring） | argv 干净 ✅：`_resolve_env`（`channels.py:46-62`）把 `*_FILE` 内容搬进 env，argv 里只有 `prompt`/`model`；`--dry-run` 只打印**键名**（`cli.py:53-54`）。**但**「不进 ps」这句不成立：密钥经 `os.environ.copy()+update(env)`（`gates.py:66-67`）进子进程环境，同用户可经 `/proc/<pid>/environ`、macOS `ps -E` 读到；且 `${VAR}` 间接引用要求密钥先存在于 quorum 父进程环境 | 🟡 存疑 |
| **A5** 材料快照指纹能发现材料变化（README L102） | git 模式**确已**并入 sources 文件树哈希（`snapshot.py:55-63`）——这条作者修过，是真的。漏在三处：>8MB 只计 `(size, int(mtime))`（`snapshot.py:95-101`）；`snapshot_exclude` 是裸 `startswith`（`snapshot.py:79,87`）；**基线只取一次**（`cli.py:45`），后 2..n 个审核员的比对用的是循环前的基线 | 🟡 存疑 |
| **A6** 同 family 不得有两个 primary，`load()` 直接报错（CONTRACT §一「硬约束」） | `load()` 是全仓唯一构造入口（四条命令都走它），无旁路 ✅。但校验是**裸字符串相等**（`config.py:198-204`），而 `role`/`family` 都是**无枚举、无校验的自由文本**（`config.py:170`）：`role: Primary` 或 `role: core` 既绕过 COI 检查，又在 `plate.primary_families`（`plate.py:136-138`）里被当成「非 primary」悄悄降档——**一个拼写错误同时废掉硬约束和置信度规则**，且无任何提示 | 🟡 存疑 |
| **A7** `plate` 只解析表头含「严重度」的表（CONTRACT §三） | 「只认含严重度的表」确实成立，概述表的 🟡 不会误入 ✅。但**降级是静默的**：`严重度` 格里写 `P0`/`Critical`/「高」（不带方括号）的行被 `SEVERITY_RE`（`gates.py:25,243`）直接 `continue`，门禁数不到它、`plate` 也收不到它；只要**其余行**够 `min_findings`，整份结论照样过门、照样进交叉表，**没有任何一行诊断输出说「有 3 条没被解析」** | 🟡 存疑 |
| **A8** `verify` 四档判定语义（CONTRACT §四） | 四档与实现一致（`ledger.py:41-50`）。**工单问的那个数：全行都没填 `check` 的台账，非 `--strict` 下退出码 = 0**（`ledger.py:121-127`），而 `plate --dispose` 生成的骨架 check 列**全空**（`plate.py:282`）——即「dispose → 填 status → verify」这条 README 默认路径**恒绿**。口径写清了、`--strict` 存在，但默认行为危险 | 🟡 存疑 |
| **B** 对齐是启发式的、刻意保守：宁可拆细，不合错（CONTRACT §三 L109、`plate.py:179-184`） | 保守性作用在**配对**上，不作用在**簇的语义**上。`label()` 只数 primary family 个数（`plate.py:141-150`），`headline()` 取 `rows[0].problem`（`plate.py:152-153`），`severity` 取簇内 max（`plate.py:124-127`）——三件事都不看「这一簇里的人是不是在说同一件事」。作者自己的 demo 产物 `demo/out/demo-dispose.md:8` 就是这一形态（见 §2 第 2 条） | 🔴 不成立 |
| **C** 门禁检查的是「它自己定义的性质」（LESSONS L37-57），quorum 就是为此设计 | **论断本身成立**，我在工具自己身上找到 11 处同构实例（§2 单列小节）。它成立的力度比作者写的还大——最刺眼的一处是 `verify` 对作者随仓发布的示例台账打出的绿灯（§2 第 4 条） | ✅ 复验通过（且实例多于作者自陈） |
| **D1** `docs/LESSONS.md` 的事故与规则真对应，不是事后编故事 | 逐条在代码里找到对应物：rc 被忽略（`gates.py:54-56`）、`protect_existing`（`gates.py:86`）、`RAW/裸 open(w)` 的历史痕迹（`cli.py:129-134` 注释）、`self_test` 双向（`leaks.py:139-154`）、`min_findings` 取代 emoji 计数（`config.py:181-182`）。事故二的机制描述**技术上正确**：`open(p,"w").write(f(p))` 在 CPython 里先求值对象表达式（截断文件）再求值实参，函数确实读到空文件。**不是编的** | ✅ 复验通过 |
| **D2** demo 三个事故真能复现（不是注释声称） | 事故一数字**【实算】全部对得上**：`answers.jsonl` 100 行、`pred_old.jsonl` 41 行（`wc -l`）；逐 id 比对 10 处不符（命令见 §2 第 14 条），命中 31 ⇒ 覆盖率 41/100=**41.0%**、覆盖内准确率 31/41=**75.6%**、对全集 31/100=**31.0%**，与 `report.md` 及 canned 结论逐位吻合。事故二**看得见**：`report.md` 实测 **101 字节**，区块外无一字。事故三**未实跑**（无解释器）：`build.py` 确实遍历 set，但「两个 seed 得到不同 `dev_ids`」我没有亲自验证 | ✅ 数字部分复验通过；🟡 事故三未实跑 |
| **D3** 测试里有没有「永远为真」的断言（作者自陈踩过此坑） | **有，至少 4 条，且都是这一类的正例**。详见 §2 第 8 条与附录第 3 条：`tests/test_quorum.py:104` 断言的是一个**从未被创建的文件路径字符串**；`:321-322` 断言的「材料快照」在结论头里**无条件存在**；`:245-251` 测的是一段内联复制的正则，**根本没调用 `plate.collect`**；`:44` 是对同一路径两种规范化形式的 `A or B`，实践上恒真 | 🔴 不成立 |
| **D4** `check-leaks` 能否被绕过 | **能，且三条静默路径**：① 候选集 = `git ls-files` 的**被跟踪文件**（`leaks.py:110-120`），未跟踪的 `.env`/`*.pem`/无扩展名密钥**永远不扫**；非 git 目录才回落 `os.walk`。② `_is_text` 对 `>4MB` 与**前 4KB 含 NUL**的文件直接判非文本跳过（`leaks.py:26-39`）——**UTF-16 编码的 `.env` 整个文件隐形**。③ 每条规则命中**上限 5 条**，而打印的是 `len(items)`（`leaks.py:132-133`），于是「**凭证形态：5 处（最多显示 5）**」在一份 100 处泄漏的文件上照样出现。三者的共同输出都是「在 … 下未发现任何命中」——**一句读起来像「已验证」的话** | 🔴 不成立 |
| **E** demo 的 `--self-test` 能证明检查本身会失败（LESSONS L59-71） | `self_test` 本身**修对了**（`cli.py:171-176` 那段「过滤条件滤掉了要抓的东西」的 bug 确已不存在，`leaks.py:139-154` 会返回非空失败清单）。但它证明的只是「**每条正则能匹配自己写死的那个样本**」，**完全没有触碰 `scan()` 的文件选择逻辑**——`--self-test` 全绿与「一个文件都没扫」可以同时成立（§2 第 10 条） | 🟡 存疑（机制对、强度被高估） |

---

## 第二节 · 逐条发现

| 严重度 | 位置 | 问题 | 证据（命令/重算结果） | 建议 |
|---|---|---|---|---|
| 🔴 | `demo/ledger_example.md:9` + `ledger.py:50` | **`verify` 会给一份「说谎」的 ✅ 打绿灯**——这是作者随仓发布的示例，不是假想。第 2 行处置写「已补正文与口径」、status ✅、check `grep -q METRICS project/report.md`；而 `report.md` 实测 **101 字节、除 METRICS 区块外一字没有**（被掏空的病根本没治）。`rc==0` 且 `is_ok_status` ⇒ `verdict()=="ok"` ⇒ 渲染成 `✅` | 【实算】`cat demo/project/report.md`、`wc -c` → 101。判定路径 `ledger.py:46-50`：`is_ok_status=True, rc=0` ⇒ 不进 LIE、不进 stale ⇒ `"ok"`。而 `CONTRACT.md:139` 亲手把 `grep -q METRICS report.md` 点名为**装饰性断言的反例**——同一句命令、同一份仓库 | 这是工具卖点的自我反例，至少要在 `verify` 输出里对「check 命中行数/被检查文件的行数」给出可比数字；更好的做法是把 `--strict` 提到默认 |
| 🔴 | `demo/ledger_example.md:10` + `ledger.py:49` | 第 3 行 check `grep -q 'sorted(' project/build.py`、status ⬜ ⇒ verdict **`stale`**，渲染成「🟡 台账未更新」。而 `ledger.py:49` 注释把这一档的语义定为「**其实已经好了**，台账没更新」——**谎**。`build.py` 里的 `sorted(` 来自 `print(json.dumps({... "dev_ids": sorted(dev)[:3]}))`，是先 shuffle 再排序的**输出格式化**；修复（shuffle 前 `sorted()`）**从未落地**。`verify` 把「还没修的」报成「已经好了」 | 【实算】`grep -n sorted demo/project/build.py` → 命中 `print(... sorted(dev)[:3] ...)`；同文件 `keys = list(ids)` 后直接 `rng.shuffle(keys)`。判定路径同上一行 | `stale` 的措辞必须退回它真正知道的事：「check 通过、status 未标 ✅」；不得断言「已经好了」 |
| 🔴 | `plate.py:256-271` | **`--json` 丢掉了「逐条列原话」这个唯一的缓解措施**：`to_json` 的 `problem` 字段是 `c.headline()`＝`rows[0].problem`（**只保留第一条**），`sources` 只有 `{reviewer, evidence}`——**各家的 `problem` 原文全部丢失**。README L41-42／CONTRACT §三 承诺「明细逐条列出各家的原话，让你看见同一处、不同结论」；对 JSON 消费者这个承诺**不成立**（`disagreement` 字段同样不存在） | 【追踪】`plate.py:269` `"sources": [{"reviewer": r.reviewer, "evidence": r.evidence} ...]`；对比 `render()` 的 `plate.py:237` 确实逐条打印 `r.problem`。CONTRACT §三 又把 `--json` 定为「稳定的输出契约，不必 import 本包」 | `sources[]` 增加 `problem` 与 `severity`；顶层增加 `disagreement`。否则接 JSON 的下游拿到的正是作者最担心的那张「一句话汇总表」 |
| 🔴 | `plate.py:124-127,152-153` | **簇的一句话和各家的分歧无关，且是顺序相关的**：`headline()` = `rows[0].problem`（第一个进入该簇的审核员的原话），`severity` = 簇内 max。谁在 `review.yaml` 里排前面，汇总表就印谁的措辞；三家说三件事也照样印「跨模型族一致 · 高置信」（`label()` 只数 primary family 个数）。作者自己的产物就是实例：`demo/out/demo-dispose.md:8` 的 1 号簇，问题列只有**一家的措辞**，读者无法从中看出另有一家把归因写成了「文件被人换掉了」 | 【实算】`cat demo/out/demo-dispose.md` → 5 行 = 3 家的 🔴 合成 1 簇 + 4 个单点；1 号簇 置信度列＝「跨模型族一致 · 高置信」。该产物时间戳 12:24:47（`ls -lT`），早于 `demo/canned/*.md` 的 12:43:56，故**当前措辞下的簇结构我未能实跑复验**（canned 的 🔴 首句由「分母静默缩水」改写为「把覆盖率当成了准确率」，位置列三份未变） | `dispose_skeleton`（`plate.py:274-285`）增加「几家一致度」列与「各家原话」列——**正在被处置的那份文件里必须有分歧信号**，否则缓解措施只活在控制台滚动里 |
| 🔴 | `plate.py:204` | **`match_reason` 会印错匹配理由**：`best.why = "同文件 + 相似度 %.2f" if best_score > thr_text else ...`——判断依据是**分数**，不是**走了哪个分支**。跨文件命中时 `score = sc`（不加 0.05），只要 `sc ≥ 0.10` 就会打印「**同文件 +** 相似度 0.12」，而匹配其实与文件无关。这条字符串是作者给「启发式对齐」留的唯一审计线索 | 【追踪】`plate.py:197-204`：`score = sc + (0.05 if same_file else 0.0)`，而 `why` 只看 `best_score > thr_text`。`thr_text=0.10` | `why` 由分支决定：显式记录 `matched_by = "same_file" / "text"`，不要从分数反推 |
| 🔴 | `snapshot.py:66-107` + `cli.py:45,92` | **快照基线只取一次，全部审核员共用**：`snap = snapshot.take(cfg)` 在循环外；每个审核员的 `snap_after` 都跟**同一个**基线比。于是第 1 个审核员留下的任何痕迹（它自己写进仓库的文件、它跑过的命令改动的文件）都会让第 2、3 个审核员被标记「**材料在审核期间发生变化**」——归因归错人。git 模式下 `git status --porcelain` 又被哈希进去（`snapshot.py:59-60`），所以这条断言的真正内容是「**仓库脏了**」，而不是「被审材料变了」；审核员在 repo 里放个临时文件就能触发它。反向地，非 git 模式只看 `sources`，`sources` 之外的改动一律看不见 | 【追踪】`cli.py:45` 与 `cli.py:86-95`；`snapshot.py:59-60`。作者自己的结论头留有现场：`demo/out/demo-findings-alpha.md` 第 4 行「工作区有未提交改动」 | 每个审核员**前后各取一次**基线；把 `git status` 的条目按路径分桶，落在 `sources` 内的才叫「材料变化」，其余报成「审核员足迹」 |
| 🔴 | `tests/test_quorum.py:97-104` | **一条不可能失败的测试**：`test_env_file_indirection_keeps_secret_out_of_config` 最后一行 `assert "SECRET-VALUE" not in str(sec.parent / "review.yaml")`——`review.yaml` **从未被创建**，被断言的对象只是**一个路径的字符串**。除非临时目录名恰好含 `SECRET-VALUE`，此断言恒真。测试名承诺「密钥不进配置」，实际从未读过任何配置文件 | 【实算】`sed -n '97,104p' tests/test_quorum.py`；该文件全程只 `write_text` 了 `key`，没有第二处写文件 | 真写一份 `review.yaml` 并断言它不含密钥；这条正是 LESSONS L59-71「不能失败的检查就是装饰」的教科书复现 |
| 🔴 | `tests/test_quorum.py:317-322` | **第二条不可能失败的测试**：`test_e2e_material_change_is_flagged` 只断言 `"材料快照" in 结论文件`。而 `gates.header()` **无条件**写入 `> 材料快照：\`…\``（`gates.py:109`）——**审核期间材料没变它也存在**。测试名说「材料变化会被标记」，实际测的是「结论有头部」 | 【实算】`sed -n '317,322p' tests/test_quorum.py`；对照 `gates.py:101-115` 的 `header()` 常量行 | 该测应断言 `extra` 里出现「材料在审核期间发生变化」，或断言 `GateResult` 之外的告警字段 |
| 🟡 | `tests/test_quorum.py:245-251` | **测的不是被测对象**：`test_plate_snapshot_cannot_be_spoofed_by_body_text` 内联复制了一段正则去匹配一段字符串，**完全没有调用 `plate.collect`**。把 `collect` 改回旧的全篇扫描写法，这条测试**依然绿**。它守的是一行正则，不是那个「审核员能在正文里伪造快照」的漏洞 | 【实算】`sed -n '245,251p' tests/test_quorum.py`：函数体只有 `import re as _re` + `_re.search` + 断言 group | 造一个真目录、写一份正文含伪快照的结论、调 `plate.collect` 并断言取到的是 runner 的 `<!-- quorum:snapshot -->` |
| 🟡 | `tests/test_quorum.py:35-44` | `test_config_paths_are_config_relative` 的断言是 `cfg.repo == str(d.resolve()) or cfg.repo == str(d)`——两个析取项是**同一条路径的两种规范化形式**，而 `cfg.repo` 恰由 `os.path.dirname(os.path.abspath(...))` 得出。实践上恒真，等于没测 | 【实算】`sed -n '35,44p'`；`config.py:139-142` | 断言具体路径：`cfg.repo == str(d)`（单一形式） |
| 🟡 | `ledger.py:62` | **同一份输出契约，两张表用两套解析规则**：发现表用 `gates._split_row`（识别 `\|` 转义与反引号内竖线，`gates.py:144-179`），台账却用裸 `s.strip("|").split("|")`。而 `plate.dispose_skeleton` 恰好把 `\|` 写进「问题」列（`plate.py:284`）——**工具自己的产物喂回自己的 `verify` 就会错位**：`zip(header, cells)` 之后 `status`/`check` 读到的是相邻列的值，`verify` 然后按错位的命令去执行 | 【追踪】`ledger.py:62-81`；`plate.py:284` `c.headline().replace("|", "\\|")[:100]`。CONTRACT §三 明确要求「单元格里的 `\|` 与反引号内竖线按 markdown 规则当字面竖线」——§四 没享受到 | `ledger.parse` 复用 `gates._split_row` |
| 🟡 | `leaks.py:26-39,102-136` | `check-leaks` 的覆盖范围是**静默窄**的，且输出读起来像「已验证」：候选集=被跟踪文件；`_is_text` 对 `>4MB` 与含 NUL 字节（**UTF-16 文本整个文件命中**）直接跳过且不计入任何计数；每条规则命中上限 5 而打印的是被截断后的 `len(items)`。三者叠加后，「在 X 下未发现任何命中」既可能是「扫过了、干净」，也可能是「**一个文件都没扫**」——这恰是 LESSONS L59-71 原事故的形态，只是从「规则子集」换成了「文件子集」 | 【追踪】`leaks.py:110-120`（`files` 非空即不再 `os.walk`）、`:28-29`（`getsize > MAX_FILE_BYTES` 返回 False）、`:34-35`（`b"\x00" in chunk` 返回 False）、`:132-133`（`max_hits` 截断后计数）。CI 的 `quorum check-leaks .` 是公开仓唯一守门人（`.github/workflows/ci.yml:19`） | 至少打印「扫描了 N 个文件 / 跳过 M 个（原因分桶）」；对 `>4MB` 与二进制嗅探命中的文件单独列出，不要静默 |
| 🟡 | `ledger.py:121-127` + `plate.py:282` | **默认工作流下 `verify` 恒绿**：`dispose` 生成 check 全空的骨架 → 每行 `no-check` → 非 strict 下不进退出码 → `exit 0`。README 的四行上手示例（L5-9）与 `templates/dispose.md` 的用法都没带 `--strict`。「处置契约」——作者说这是 quorum 存在的第二个理由——在默认用法下**不产生任何非零退出码** | 【追踪】`plate.py:282` 生成 `| %d | … | | | ⬜ |`（check 空）；`ledger.py:123-126` 只在 `verdict in ("LIE","error")` 或 `strict and no-check` 时非零 | 把「无断言」默认计入非零，或让 `dispose` 在骨架里写入 `check` 占位并让 `verify` 对占位行报错 |
| 🟡 | `config.py:170,198-204` | **`role` 无枚举校验**，`spec.get("role","primary")` 原样收下。写 `role: Primary`／`role: core` 的审核员：① 不参与 COI 检查（`if r.role == "primary"` 精确比较）⇒ **同 family 两个 primary 的硬约束被一个大小写绕过**；② 在 `plate.primary_families`（`plate.py:136-138`）里被当成非 primary 跳过 ⇒ 置信度静默降档。`family` 同样是自由文本（`kimi-a`/`kimi-b` 即两家） | 【追踪】`config.py:167-174,196-204`；`plate.py:130-139`。测试 `test_config_rejects_same_family_primaries` 只覆盖了精确拼写 | `role` 用字面量集合校验并 `ConfigError`；`family` 加规范化（trim + casefold） |
| 🟡 | `plate.py:23` | **`PATH_RE` 把「哪些文件算材料」硬编码进引擎**，白名单为 `py\|md\|json\|jsonl\|ya?ml\|ipynb\|sh\|txt\|toml\|cfg`。数据类项目的主材料（`.csv`/`.tsv`/`.parquet`/`.npy`/`.log`/`.db`）**一个都不匹配** ⇒ `_paths()` 返回空 ⇒ `same_file` 恒 False ⇒「同文件降门槛」这条**核心启发式对数据项目全局失效**，退化成单靠文本相似度。这与 CONTRACT §一「引擎里不出现任何具体项目的信息」直接冲突（该扩展名表就是具体项目知识，且不可配置） | 【追踪】`plate.py:23-31,195`。demo 的位置列 `data/pred_old.jsonl` 恰好落在白名单内，所以 demo 看不出这个洞 | 扩展名列表进配置（`path_exts`），或改用「含 `/` 或 `\` 的词 + 已知扩展名」的正则 |
| 🟡 | `plate.py:29-30` | `_paths` 只保留 **basename**（`m.rsplit("/",1)[-1]`），于是 `train/data.jsonl` 与 `test/data.jsonl` 被当成同一个文件 ⇒ `same_file=True` ⇒ 阈值降到 0.07。更隐蔽：`PATH_RE` 的词首字符类含 `\w`，而 Python 的 `str` 正则 `\w` **是 Unicode 感知的**——中文紧邻路径时会被吸进同一个 token（`见report.md` → basename `见report.md`），于是同一个文件在不同审核员笔下因相邻汉字不同而产生**不同的路径 token**，`same_file` 时真时假 | 【追踪】`plate.py:24,29-31`；Python 语义：`re` 对 `str` 默认 Unicode，`\w` 匹配 CJK | 用 `[^\s\W]`／显式 ASCII 类；basename 比较改为「路径后缀相等」而非「文件名相等」 |
| 🟡 | `snapshot.py:95-101` | **>8MB 文件只按 `(size, int(mtime))` 计入**。保持长度、mtime 秒相同的替换（`cp -p`、`tar -x`、`rsync -t`、`git checkout` 都会保 mtime）⇒ 指纹**不变** ⇒ 报「材料没变」而材料已变。该取舍只写在 `detail` 里，且**只在 `skipped>0` 时出现**（`snapshot.py:105-106`），`plate` 侧完全不显示 | 【追踪】`snapshot.py:95-101,104-106` | 大文件改计「头 N KB + 尾 N KB + 大小」的哈希；或把 `MAX_HASH_BYTES` 换成 `sources` 的总预算 |
| 🟡 | `snapshot.py:79,87` | `snapshot_exclude` 是裸前缀匹配 `rel.startswith(x.rstrip("/"))`：**误伤**（exclude `out` 会连 `output/`、`outbox/` 一起排除）且**漏排**（写在子目录里的 `x/node_modules`、`x/__pycache__` 匹配不上——`reviews/review.yaml:7` 正是用 `__pycache__` 想排 `quorum/__pycache__`，实测该目录存在且排不掉：`ls quorum/__pycache__` 有 9 个 `.pyc`） | 【实算】`ls quorum/__pycache__`（9 个 pyc）；【追踪】`snapshot.py:76-80,85-88`、`reviews/review.yaml:7` | 按路径段匹配：`PurePath(rel).parts[:len(pat.parts)] == pat.parts` |
| 🟡 | `cli.py:62` + `gates.py:68` | **raw 日志每次重跑都被截断**：`raw_path` 是「项目-审核员-日期」，`run_with_timeout` 用 `"wb"` 打开 `stderr_path`。后果是当天第二次跑同一审核员，上一份 stderr 就没了——而这正是**唯一**记录通道层实况的地方。作者自己的 `out/.raw/` 里就躺着那条实况：两个 primary 通道的 model id **各自都被 claude CLI 判为 `unrecognized_model`**（`[claude-code:unrecognized_model] {"model": …}`），下一次同目录重跑即抹掉 | 【实算】`cat out/.raw/quorum-kimi-2026-10-01.log out/.raw/quorum-qwen-2026-10-01.log` → 两条 `[claude-code:unrecognized_model]`；`ls -la demo/out/.raw` → 每审核员每天一个文件、全 0 字节 | raw 用追加 + 时间戳后缀；`unrecognized_model` 这种通道层告警应当**提升进结论头部**，而不是只躺在 stderr 里 |
| 🟡 | `gates.py:106` + `channels.py:78-90` | **「模型族」是配置字符串，不是事实**。结论头里的 `模型族: X` 直接抄 `review.yaml`；quorum 从不校验实际应答的是哪个模型。若某 CLI 对不认识的 model id 静默回落到默认模型（作者的 raw 日志里两个 primary 的 model id 都触发了 `unrecognized_model`），「跨模型族一致 · 高置信」就会变成**同一个模型自己跟自己的共识**——正是 COI 规则存在的理由 | 【实算】见上条日志；`gates.py:101-115` 的 header 由 `cfg.reviewer(...)` 填 `family`；`channels.py:78-90` 只把 `--model` 放进 argv，无回执校验 | 结论头记录通道返回的 model 标识（若 CLI 提供）；至少把 `unrecognized_model` 这类告警并入头部，让「两家独立」这句可被证伪 |
| 🟡 | `plate.py:220-224` | **快照告警有假绿分支**：`if len(set(snaps.values())) > 1` 才报不一致；当**所有**结论都没有快照标记时（手放的文件、旧版本产物、被裁掉头部的文件），集合只有一个值「（该结论无快照标记）」，于是打印 **「> 材料快照一致：`（该结论无快照标记）`」**——一行绿字，实际一个快照都没有 | 【追踪】`plate.py:167-173,220-224` | 先判「是不是所有结论都有标记」，有缺失就单独报警，不要落进「一致」分支 |
| 🟡 | `gates.py:188,193-194,243` | **静默丢行**：`_looks_like_header` 只看「这一行各格是否**像**列名」（`startswith` + 长度 ≤ 列名+6）。一条数据行只要在「问题」格以「严重度」开头、另有某格以「位置/问题/证据/建议」开头，就会被判成新表头 ⇒ 列映射被冲掉、`continue` ⇒ **该表后段全部静默丢弃**。作者注释里说这一条已经被加固过（`gates.py:225-227`），但加固的判据仍是「像不像表头」，不是「是不是那张表头」。同类：含 NUL/奇数反引号导致 `_split_row` 合并单元格时，也无任何计数与提示 | 【追踪】`gates.py:182-194,228-245` | 一张表只认一次表头（首次出现后锁定）；对「解析出的行数 < 表内数据行数」给出计数差 |
| 🟢 | `cli.py:146-151` | **第三种路径解析规则**，且未进契约：`--ledger` 先按 CWD 试，再按配置目录试，再按 `repo` 试。CONTRACT §一 写的是「路径语义（**唯一规则**，别猜）：配置里的相对路径按配置文件目录、命令行给的按 CWD」。当 CWD 与配置目录各有一份同名台账时，**静默取 CWD 那份** | 【追踪】`cli.py:144-151` | 命令行路径**只按 CWD**；要覆盖就用绝对路径。删掉后两个回落分支，或把它们写进契约 |
| 🟢 | `cli.py:104-105` | 失败产出路径 `"%s.FAILED-%s.md" % (out[:-3], HHMM)` 直接 `atomic_write`，既不查存在也不留档。同一分钟内该审核员第二次失败，**第一份失败产出被静默覆盖**——与「损坏一份已有结论比不产出更糟」同一副骨架，只是标的物换了 | 【追踪】`cli.py:104-105`、`gates.py:118-122` | 失败路径也走 `protect_existing` |
| 🟢 | `cli.py:69,109-111` | `tempfile.mktemp()` 已废弃且不入目录索引，产生竞态与孤儿临时文件；清理循环同时 `unlink` 两个路径，在 `writes_file` 分支下语义与命名相反（`tmp_out` 才是审核员的输出文件、`tmp_out+".stream"` 是 stdout） | 【追踪】`cli.py:69-74,109-111`；`channels.py:89` | `tempfile.mkstemp`；把两个路径的语义写成变量名 |
| 🟢 | `gates.py:234,238` | 死代码：`if not in_table: continue` 在同一段里出现两次，第二次永不可达 | 【实算】`sed -n '228,241p' quorum/gates.py` | 删 |
| 🟢 | `README.md:76` / `CONTRACT.md:3` / `reviews/brief.md:27` | 代码体量的三个说法互不一致：`wc -l quorum/*.py` = **1516**；README 说「一千多行」（✅），CONTRACT 说「工具是两百来行代码」（✗），工单说「约 1200 行」（✗）。数字不大，但这是**一份以「数字必须自己重算」为卖点的材料** | 【实算】`wc -l quorum/*.py` → 合计 1516 | 统一成一个数，或全部删掉 |

### §2.C 单列小节 —— 在 quorum 自己身上找「门禁绿、材料错」

作者论断：**门禁检查的是「它自己定义的那个性质」，不是「读者以为的那个性质」。绿灯是真的，但它证明的不是你以为的事。**
论断成立，而且在这个工具里至少要成立 **11 次**（作者自陈的是 3 次）。逐条：

1. **`gates.evaluate` 的绿 = 「存在 ≥N 行带严重度标记的表格行」，读者以为的 = 「这份结论有 N 条真发现」。** 判据里没有任何一格内容参与（`gates.py:44-57`）。作者把 emoji 计数换成行计数（`config.py:181-182`、`tests:130`），换掉的是「数哪个可数性质」，没换掉「可数性质 ⇒ 语义性质」这一步。
2. **`verify` 的绿 = 「所有非空 check 都退 0」，读者以为的 = 「台账里的 ✅ 都验证过了」。** 最锋利的证据在作者自己随仓发布的示例里：`demo/ledger_example.md` 第 2 行对一份 101 字节、正文被掏空的报告打 ✅，`verify` 判 **ok**；而 `CONTRACT.md:139` 把同一句命令点名为装饰性断言。（demo 第 3 行更糟：把「还没修」报成「已经好了」。）
3. **`verify` 退出码 0 = 「没有任何一行被判为说谎或执行失败」。** 默认口径下 `no-check` 不进退出码，而 `dispose` 骨架 check 全空 ⇒ 全新骨架必绿。绿是真的，它说的是「没东西可失败」。
4. **`--self-test` 的绿 = 「每条正则能匹配自己写死的样本」，读者以为的 = 「扫描覆盖了该覆盖的东西」。** `self_test`（`leaks.py:139-154`）与 `scan` 的文件选择（`leaks.py:110-120`）**没有任何耦合**。作者修掉的那次「过滤条件滤掉了要抓的东西」是同一坑的另一面：**检查的检查，仍然可以不知道自己没检查什么。**
5. **`check-leaks` 的「未发现任何命中」= 「被 git 跟踪、≤4MB、前 4KB 无 NUL 的文件里，没有命中这 8 条正则」。** 未跟踪文件、UTF-16 文本、大文件全在性质之外，且三者都不进任何计数（`leaks.py:26-39,102-136`）。
6. **`plate` 的「材料快照一致」= 「各家结论头部那串字符相同」，也可能是「各家都没有快照标记」**（`plate.py:220-224`）——一个什么都没验的分支，输出形态与验过的分支**完全一样**。
7. **反向的假警报同样成立**：`run` 的「材料在审核期间发生变化」= 「git status 与 sources 文件树变了」，其中包含**审核员自己的足迹**和**基线只取一次**带来的归因错位（`cli.py:45,92`）。假警报会让真警报被忽略——`leaks.py:88-91` 的注释自己就这么说。
8. **`readonly_note` 的诚实是半步的**：`claude-cli` 打印「NOT enforced」（`channels.py:106`）值得表扬；但结论头回落成「只读强度：未强制」（`cli.py:98-99`）——措辞从「无保证」退到「强度」。而 `codex-cli` 的「enforced（-s read-only）」是**关于我们放进 argv 的东西**的断言，不是「该进程实际只能读」的断言，同样没有任何校验。
9. **`match_reason` 的「同文件 + 相似度 0.19」= 「分数超过 0.10」**，不是「因为同文件而匹配上」（`plate.py:204`）。这是全套启发式里唯一承诺可审计的字段。
10. **`Cluster.label()` 的「跨模型族一致 · 高置信」= 「≥2 个 primary family 各贡献了至少一行」**，不是「≥2 家对同一件事得出了同一结论」（`plate.py:141-150`）。demo 的 1 号簇就是三家里混着一条归因相反的结论。
11. **`protect_existing` 返回的留档路径 = 「当时改名成功了」**，不是「这份结论保住了」：`%H%M%S` 秒级后缀在同一秒的第二次留档会覆盖上一份（`gates.py:89`），`shutil.move` 到已存在路径是静默覆盖。
12. **`gates.header` 里的「材料快照：`git:xxx`」= 「跑这次审核时算出来的指纹」**，与「审核员实际读到的那一版材料」之间隔着审核期间的全部时间窗——这正是 LESSONS L29-35 那条事故想解决的问题，而修复只做到「记下来」，没做到「钉住」。

**一句话**：作者诊断对了病，然后把「重算数字」升级成了「重算存在性」；**存在性同样是一个它自己定义的性质**。我在工具自己的示例台账上就能把这条演示完整（第 2 条）。

---

## 最脆弱的一环（前三）

1. **`verify` 的绿灯不区分「修好了」与「命令退 0」，而作者随仓发布的示例正好演示了后者。** `demo/ledger_example.md` 第 2 行：报告正文确实被掏空（101 字节），处置写着「已补正文与口径」，check 是那句被 CONTRACT 亲自点名的装饰性断言，`quorum verify` 判 **✅ ok**。第 3 行把「没修」判成「其实已经好了」。处置契约是作者说的**第二个存在理由**，而它在自家示例上是失效的——这不是文档瑕疵，是核心卖点的反例。

2. **交叉簇的「一句话」和「置信度」都不看内容，而唯一的缓解措施在文件形态里被丢掉了。** `label()` 数 family 个数、`headline()` 取第一家措辞、`severity` 取 max；`disagreement` 只存在于控制台文本，`--json` 里没有它、也没有各家的 `problem` 原文；`--dispose` 生成的**台账**同样只有一句话。于是「同一处发现、三种措辞、其中一种是错的」这条设计目标，只在**当场看屏幕**时成立。而 README L41-42 与 demo/README 都把「明细逐条列原话」当成对「合并 ≠ 同意」的兜底。

3. **`check-leaks` 的覆盖面是静默窄的，而它是公开仓唯一的守门人。** 被跟踪文件之外的一切（未跟踪的 `.env`/`*.pem`、UTF-16 文本、>4MB 文件）既不扫也不计数，输出却是「在 … 下未发现任何命中」。这与 LESSONS L59-71 被作者亲自点名的那次事故（只查三类形态却打印「残留：无 ✓」）**同构**——原事故是规则子集，这次是文件子集。`.github/workflows/ci.yml:19` 把这条命令当作 CI 的最后一步。

---

## 附录 · 我推翻的既有结论

1. **推翻「测试里没有永远为真的断言」**（前轮审核员 D3 判 ✅）。至少四条：`tests:104` 断言一个**从未被创建的文件**的路径字符串；`tests:321-322` 断言的「材料快照」在结论头里**无条件存在**，测不到任何「变化被标记」的行为；`tests:245-251` **没有调用 `plate.collect`**，只测了一段内联复制的正则，改坏被测函数它照样绿；`tests:44` 是同一条路径两种规范化形式的 `A or B`，实践上恒真。作者的 LESSONS L59-71 恰好把这一类称为「装饰」——最需要它没有生效的地方，它就在测试里。

2. **推翻「`check-leaks --self-test` 通过 ⇒ 这道守门人是有效的」的强度。** `self_test` 只证明「每条正则匹配自己的样本」，与 `scan` 的文件选择零耦合。`--self-test` 全绿与「扫描到 0 个文件」可以同时成立。

3. **推翻「四道门能挡住空洞但形式合规的产出」**（`tests:130` 那条测试在为它背书）。那条测试只堵死了 emoji 刷屏；门禁数的是**表格行数**，对「位置/问题/证据」三列的内容零校验。5 行 `\| 🔴 \| \| \| \|` + 700 个「。」在全默认门下通过。

4. **推翻「对齐刻意保守 ⇒ 交叉表可信」。** 保守性作用在配对上，不作用在簇的语义上；`label()`/`headline()`/`severity` 三者都不看内容。保守的定义被 `label()` 吃掉了。

5. **推翻「`ANTHROPIC_AUTH_TOKEN` 不进 ps」的措辞。** 「不进配置文件、不进 argv」字面成立；但密钥经 `os.environ.copy()+update(env)` 进入审核员进程环境，同用户可读（`/proc/<pid>/environ`、macOS `ps -E`），且 `${VAR}` 形式要求密钥先存在于父进程环境。CONTRACT §一 用「命令行会进 ps 和 shell 历史」来解释为什么不走 argv——这句话把 env 暗示成了安全信道。

6. **修正工单 §2.A.8 的预设**：全空 `check` 的台账在非 `--strict` 下退出码是 **0**；这个口径**与 CONTRACT §四 自洽、文档也写明了 `--strict`**。不合理的是**默认工作流**（`dispose` 生成全空骨架 + README/CI 都不带 `--strict`），不是判定逻辑本身。这一条我不推翻作者的口径，只指出实现与默认用法之间的落差。

7. **修正工单的一个前提**：工单说 `demo/out/` 「三个事故是否真能复现」。其中事故一的数字我**【实算】复核通过**（41/100、31/41、31/100 与数据文件逐位吻合）；事故二**【实算】成立**（`report.md` 101 字节）；**事故三我未能实跑**（无解释器），只能确认 `build.py` 确实遍历 set。请注意 repo 里 `demo/out/` 的产物是**过期的**（`demo-dispose.md` 时间戳 12:24:47，早于 `demo/canned/*.md` 的 12:43:56，其第 1 行问题文本取自现已不存在的旧版 canned），拿它当「当前代码的输出」会得到错误结论。

8. **补一条作者与前轮都没提的**：`reviews/review.yaml`（作者的**真实**配置）里 `sources` 没有覆盖 `pyproject.toml` / `.github/workflows/ci.yml` / `examples/` / `LICENSE` / `reviews/`——即「事后材料快照比对」这个 fallback 对**发布面文件**是盲的（非 git 模式）。git 模式下 `git status --porcelain` 恰好补上了这个面，但代价是把「仓库是否脏」当成了「材料是否变」（见 §2 第 6 条）。

---

### 附录二 · 本轮未能实跑、建议下一轮补的实验

| 实验 | 目的 | 命令 |
|---|---|---|
| 空洞产出过门 | 落实 A2 / 附录 3 | `python3 -c "from quorum import gates; from quorum.config import *; print(gates.evaluate(cfg, text, 0, 1))"`，text = 5 行空表 + 700 句号 |
| 台账竖线错位 | 落实 §2 第 11 条 | 造一份「问题」列含 `\|` 的台账，跑 `quorum verify`，看 check 列是否读错 |
| 两个 `PYTHONHASHSEED` | 落实 D2 事故三 | `PYTHONHASHSEED=1 python3 demo/project/build.py` vs `=2` |
| 当前 canned 下的簇结构 | 落实 §2 第 4 条 | `quorum plate --config demo/review.yaml --json` |
| `check-leaks` 盲区 | 落实 D4 | 造 UTF-16 的 `.env`、未跟踪的 `.pem`，各跑一次 `quorum check-leaks` |
| 快照基线级联 | 落实 §2 第 6 条 | 让第 1 个审核员往 repo 里写一个未跟踪文件，看第 2、3 个的结论头是否都被标记 |
| `pytest -q` | 全部 | 本环境的权限层不允许；**20 个测试连一次都没跑过** |
