# quorum · 独立复核结论 · kimi · 2026-10-01

> 工单: `brief.md` · 模型族: `moonshot` · 角色: `primary`
> 方式: 独立进程 headless（干净上下文，与作者会话无共享记忆）
> 材料快照：`git:a1333f5f2b9a`（git c0f0de930eec，工作区干净 + 材料树 tree:1fa5318a2f39（59 个文件））
<!-- quorum:snapshot git:a1333f5f2b9a -->
> 只读强度：未强制（NOT enforced（CLI 无沙箱开关；靠工单措辞 + 事后快照比对））

---
## 复核前置说明（必读）

**环境限制（影响证据强度，必须声明）**：本会话的权限层拒绝了所有解释器调用——`python3 -c`、`python3 <脚本>`、`pytest`、`.venv/bin/quorum`、`awk`、`jq`、`sed`、`join`、`xargs` 全部返回 "This command requires approval"；`sh -c`、`find -exec` 亦被拦。可用工具只剩 `cat/wc/cut/sort/uniq/grep/head/git/ls`。

旁证：上一轮审核员（`reviews/out/round2/quorum-findings-kimi.md` 正文首段）在同一环境里留下了同样一句话。所以这是环境性质，不是我的取舍。

**后果**：本文所有**数字**都由我自己用 shell 从数据文件重算（命令与输出见每行证据）；所有**代码路径**结论均由逐行阅读 + 行号定位推演得出，凡属推演我会写明。**我没有**亲自跑 `pytest` / `run_demo.sh` / `PYTHONHASHSEED` 双种子。凡引用前轮审核员"实测"的地方，我单独标注为转引。

---

## 第一节 · 声明复验总表

| 声明 | 我复验到什么 | 判定 |
|---|---|---|
| A1 审核员只读、结论由 runner 落盘（README:97-100） | **落盘侧成立**：结论只经 `gates.atomic_write`（`cli.py:102`）。**只读侧不成立为"保证"**：`claude-cli` 的 argv 无任何沙箱开关（`channels.py:78-82`），子进程 `cwd=repo` 且继承完整环境。更甚：`out_dir` 在被审 repo 内（`reviews/review.yaml:5` = `out`）且**不在 `sources` 里**，故审 2 号进程可覆写 1 号的结论文件，快照不覆盖该目录、plate 不再校验 | 🟡 存疑 |
| A2 内容优先于退出码 | **成立**：`evaluate` 的 `passed` 三项均不含 `rc`（`gates.py:56-59`），`rc` 只进 `extra` 注记（`cli.py:89-92`） | ✅ 复验通过 |
| A2' 四道门能挡住「空洞但形式合规」 | **不成立**。判据只有三条（bytes / 行数 / 子串章节），`marks` 不参与判定；`split_table_rows` 对 `位置·证据` 两列零校验，`问题` 列只要求 ≥8 字符（`gates.py:52-59`）。构造：5 行 `\| 🔴 \| 无 \| 占位占位占位占位 \| 无 \|` + 2000B 句号 + 一行「## 最脆弱」→ 三条件全过。且 `require_sections` 是**子串**判定，"本节没有任何最脆弱的一环"亦通过 | 🔴 不成立 |
| A3 临时文件 + 已有非空结论留档 + 原子落位 | **主路径成立**（`protect_existing` + `os.replace`）。**两条支路不设防**：① raw stderr 日志按「审核员-日期」命名且 `"wb"` 打开（`cli.py:61-62`+`config.py:111-114`+`gates.py:71`）→ 当天重跑同一审核员**截断上一份 raw**；② `--dispose <相对文件名>` 走 `os.makedirs(os.path.dirname("x.md"))` = `os.makedirs("")` → `FileNotFoundError` 未捕获（`cli.py:133-134`） | 🟡 存疑 |
| A4 密钥不进配置、不进命令行 | **argv 侧成立**：argv 只有 prompt/model；`--dry-run` 只打印 env 的**键名**（`cli.py:52-54`）。**两处削弱**：① 密钥经 `os.environ.copy()+update()` 进**子进程环境**（`gates.py:66-67`），同 uid 可读 `/proc/<pid>/environ`（macOS `ps -E`）；② 未设置变量的守卫只覆盖 `${VAR}` 形，`$VAR` 形不设防（`channels.py:57-60`） | 🟡 存疑 |
| A5 材料快照指纹能发现材料变化 | 工单描述的「>8MB 只计 (大小, mtime)」是 **fa06c78 的旧行为**；HEAD 已改为首尾各 64KB 取样哈希（`git diff fa06c78..HEAD -- quorum/snapshot.py`）。**四个现存洞**见第二节 F13/F14/F2 | 🟡 存疑 |
| A6 同 family 不得两个 primary | `load()` 是全仓唯一配置入口（四条命令都走它），role 已加枚举校验（`config.py:167-170`，HEAD 新增）。但 **`family` 是自由文本，与 channel/model 无任何绑定**，COI 校验的是标签不是来源 | 🟡 存疑 |
| A7 plate 只解析表头含「严重度」的表 | 门控本身按设计工作，但**列级解析会静默丢列**：`_header_map` 的 `len(key) <= len(want)+6` 把 `证据（命令/重算结果）`（11 字符 > 2+6）判出局 | 🔴 不成立 |
| A8 verify 四档判定 | 四档语义基本正确（`ledger.py:41-50`）。**但默认档**：全行无 check → 退出码 **0**（`ledger.py:131-137`）。作者自己的台账正是这个形状 | 🟡 存疑 |
| 工单 §1「quorum/\*.py 约 1200 行」 | `wc -l quorum/*.py` = **1579** | 🔴 不成立（工单自身） |
| README:41-42「demo 会把错的那条和另外两家对齐在同一簇」 | 按 `cluster()` 行序推演成立（详见 §B） | ✅ 复验通过（但无有效测试在守，见附录） |

---

## 第二节 · 逐条发现

| 严重度 | 位置 | 问题 | 证据（我怎么查出来的） | 建议 |
|---|---|---|---|---|
| 🔴 | `quorum/gates.py:185-193` | **模板自带的表头会让解析器静默丢掉整列。** `_header_map` 要求 `key.startswith(want) and len(key) <= len(want)+6`；`证据` 列名长 2，容差 8，而 `templates/brief.md:48` 与 `reviews/brief.md:97` 工单**规定**审核员写 `证据（命令/重算结果）` = 11 字符 → 该列永不入映射，`pick(cells,"证据")` 返回 `""` | `grep -n '^| 严重度' demo/canned/*.md templates/brief.md reviews/brief.md` → 工单模板与 `reviews/brief.md` 均为 `\| 证据（命令/重算结果） \|`；demo 夹具为 `\| 证据 \|`。`grep -n '^| *严重度' reviews/out/round2/quorum-findings-*.md` → **三家真结论（kimi:42 / codex:37 / qwen:42）全部使用长表头**。逐字计数：证据(2)+（(1)+命令(2)+/(1)+重算结果(4)+）(1)=11 > 8 | 列名匹配改为白名单前缀 + 明确容差分档；解析结束打印 `idx` 里实际映射到的列，未映射的列名**可见地**报出来 |
| 🔴 | `quorum/cli.py:45,92` + `quorum/plate.py:164-172,220-224` | **plate 的「材料快照不一致」告警在单次 `run --all` 里结构性不可触发。** `snap = snapshot.take(cfg)` 在循环**外**，三家结论头部抄的是同一份基线；`snap_after` 的差异只作为**正文散文**写进结论（`extra`），而 `plate.collect` 只认头部机器标记（`plate.py:167-169`），从不读那段散文 | 读 `cli.py:45`（循环外）→ `cli.py:101`（header 用 `snap`）→ `plate.py:167`（只取 `<!-- quorum:snapshot -->`）。因此"三家审的不是同一份材料"这个最危险的情形，恰恰是告警唯一不会响的情形 | 头部改记**本审核员自己的**前后双指纹（前/后各一枚）；plate 对"前≠后"单独出一档 🔴 |
| 🔴 | `reviews/out/round2/quorum-dispose.md` + `quorum/ledger.py:131-137` | **作者自己的处置台账 43 行、零条断言，`verify` 默认退出码 0。** 这正是 README 头条卖点（"抓台账说谎"）的反面 | `grep -c '^|'` → 45（1 表头 + 1 分隔 + **43 数据行**）；`grep -c '⬜'` → 44；`grep -c -F '\| \| \| ⬜ \|'` → **43**（说明 43 行的 `处置`/`check` 两格全空）。`ledger.py:42-43` 空 check 直接 `no-check`，`exit_code` 只在 LIE/error 或 `--strict` 时非零 | 把 `--strict` 设为默认、非 strict 改名 `--lenient`；CI 里加 `quorum verify --strict`（现在 `.github/workflows/ci.yml` 只有 `pytest -q` 和 `check-leaks .`，**没有 verify**） |
| 🔴 | `tests/test_quorum.py:309-310` | **两条不可能失败的断言。** e2e 断言 `"跨模型族一致" in text` 与 `"单家独有" in text`，而这两个串是 `render()` 固定「读法」样板的一部分，与簇的实际构成无关 | `grep -n '单家独有\|跨模型族一致' quorum/plate.py` → `plate.py:247-248` 两条样板行在**任何**输出里都出现。改簇逻辑后这两条断言依旧全绿 | 断言改为对 `plate.collect()/cluster()` 的结构化结果断言（簇数、成员、label），或断言 `quorum plate --json` 里的 `findings[*].confidence` |
| 🔴 | `quorum/cli.py:128-143` | **`plate --json --dispose` 的 stdout 不是合法 JSON**：JSON 先 `print`，随后 dispose 的两条人类可读消息也打到 stdout；且 `cli.py:142-143` 是 `if a.json and a.dispose: pass` 空分支——作者意识到了却没处理 | 读 `cli.py:128-143`。CONTRACT §三把 `quorum plate --json` 作为对外机器可读契约 | dispose 的消息一律走 `stderr`，或 `--json` 时把 dispose 结果并入 JSON 对象 |
| 🟡 | `quorum/plate.py:195-204` | **`match_reason` 会印错理由且相似度虚高 0.05。** `best.why` 用的是内层循环**泄漏出来的** `same_file`（属于最后比较过的那一对，不是胜出的那一簇）；`best_score` 已含 `+0.05` 加分却被当成原始相似度打印 | 读 `plate.py:191-204`：`same_file`/`sc` 在 `for other_idx in c.members` 内赋值，`best` 可能来自更早的簇 | 在确定 `best` 的同一次迭代里一并保存 `same_file`，并分列打印 `raw_sim` 与 `bonus` |
| 🟡 | `quorum/plate.py:108-110` 对 `plate.py:41-43` | **`disagreement` 的阈值落在作者自己标注的「同一条发现」区间内，因此该信号无法区分一致与否。** 阈值 `avg < 0.20` 报警，而同文件注释写明"同一条发现升到 **0.14–0.21**" | 逐字读 `plate.py:41-43` 与 `plate.py:108-110`。0.20 ∈ [0.14, 0.21] → 「三家一致」也可能印 ⚠️，而「一家归因错但共享大量词元」也可能压过 0.20 而不印 | 阈值必须落在 0.06 与 0.14 之间；或改用「簇内**最大**成对相似度」而非均值，并明确标注这是粗信号 |
| 🟡 | `quorum/leaks.py:106-140, 161-168` | **命中数被截断后当作总数打印。** `max_hits=5` 截断 `hits[name]`，`render` 打印 `len(items)` 并称「%d 处（最多显示 5）」→ 585 处会印成「5 处」。这与 `docs/LESSONS.md` 里「585 处用户名却打印『残留：无 ✓』」是同一形状 | 读 `leaks.py:135-137`（`if len(hits[pat.name]) < max_hits` 才 append）与 `leaks.py:166`（`len(items)`）。计数与展示共用同一个被截断的列表 | 单独维护 `count` 计数器，打印"共 N 处，展示前 5" |
| 🟡 | `quorum/leaks.py:26-41` + `quorum/cli.py:170-176` | **leak 扫描有静默盲区且不报告跳过。** `_is_text` 对 >4MB、含 NUL、非 UTF-8 的文件一律返回 False → 静默跳过；`scan` 逐**行**匹配（跨行拆开的路径/凭证漏检）；`--config` 读失败被 `except ConfigError: pass` 吞掉 → 退化为默认规则集，却仍打印「未发现任何命中。」并 exit 0 | 读 `leaks.py:26-41,127-133`；读 `cli.py:170-176`。输出里没有任何"跳过了 N 个文件"的字样 | 统计并打印跳过数；`--config` 失败必须非零退出（否则用户以为自定义规则生效了） |
| 🟡 | `quorum/cli.py:190-192` + `quorum/leaks.py:143-158` | **`--self-test` 证明的不是覆盖能力。** 不传目录时 `--self-test` 直接 `return 0`，并打印「全部规则都能抓到自己种的样本，且不误伤安全文本」——一句读起来像"已验证"的输出。且样本由作者自备，`rx.search(p.sample)` 只能证明"正则匹配我给它写的样本"，无法发现过窄的模式 | 读 `cli.py:182-192`（`if not a.dir: return 0`）与 `leaks.py:148-157`（反向测试只用一个字符串 `"the quick brown fox..."`）。例：`波浪线家目录` 要求尾随 `/` 且 `[A-Za-z0-9_\-]+`，`~user/x`、`~/我的目录/x` 均漏，而样本 `~/<用户名>/work/x.md` 照样通过 | 反向样本集要有对抗性（非 ASCII 家目录、无尾斜杠、`~user/` 形）；`--self-test` 无目录时应视为用法错误 |
| 🟡 | `quorum/gates.py:44-60` | **「四道门」实为三道**，`marks` 只记录不参与 `passed`（README:103、CONTRACT §四、`cli.py:90` 都写"四门/四道"）。同时 `min_bytes` 可被无意义填充满足（见第一节 A2'） | 读 `gates.py:55-59`：`passed` 只有 bytes / rows / missing 三项；`marks` 仅存进 `GateResult` | 删掉"四道"的说法，或把 `marks` 真正纳入判定 |
| 🟡 | `quorum/snapshot.py:66-77,96-118` + `reviews/review.yaml:7` | **`snapshot_exclude` 的三条配置全是惰性的。** ①无 glob 支持，`*.log` 形静默失效；②按路径**前缀**匹配，`__pycache__` 无法匹配 `quorum/__pycache__`；③`_tree` 走 `os.walk`，**完全不读 .gitignore**，于是 `sources` 内的构建产物照样入指纹。`reviews/review.yaml` 的 `["reviews/out", ".venv", "__pycache__"]`：前两条不在 sources 下，第三条对嵌套目录无效 | 读 `_excluded`（`rel == p or rel.startswith(p + os.sep)`）；`sources` = `["quorum","tests","demo","docs","templates","CONTRACT.md","README.md"]`（`reviews/review.yaml:6`）不含 `reviews/out`/`.venv`；`ls demo/out` 显示 `demo/out` 内有 3 份结论 + 9 个 `.bak` + `.raw/`，而 `demo` 在 sources 内、不在 exclude 内 | exclude 支持 glob 与 basename 两种语义，并在 `detail` 里打印"实际排除了 N 个路径"，排除 0 个要显眼 |
| 🟡 | `quorum/snapshot.py:55-63` 对 `:137-140` | **大文件取样的免责声明在最常见的场景里被丢掉。** `_tree` 把「其中 N 个 >8MB 按首尾各 64KB 取样」写进 `tree.detail`，随后 `take()` 在 git 分支**重建 `detail`**，`tree.detail` 被丢弃 | 读 `snapshot.py:55-63`（`detail = "git …+ 材料树 …"`，未引用 `tree.detail`）与 `:137-140`（唯一写免责声明的地方）。`reviews/out/round2/*.md` 头部实测为 `> 材料快照：git:12f07b0571c5（git fa06c7831851，工作区干净 + 材料树 tree:385084ff4c7c（59 个文件））`——无取样提示 | git 分支拼上 `tree.detail` 的取样段 |
| 🟡 | `quorum/snapshot.py:11` | **模块 docstring 与实现相反**：文档说大文件"只计 (大小, mtime)，不算内容"，实现是首尾 64KB 取样哈希；且文档写 `max_hash_bytes`，常量是 `MAX_HASH_BYTES` | `grep -n '只计\|max_hash_bytes\|MAX_HASH_BYTES' quorum/snapshot.py` → `:11` 旧说法，`:25/:125/:140` 新常量与新行为 | 同步 docstring |
| 🟡 | `quorum/channels.py:46-62` | **`${VAR}` 守卫有洞，且 `_FILE` 后缀是全量劫持。** ①`$VAR`（无花括号）未设置时 `expandvars` 原样返回，`v2 == v` 且 `"${" not in v` → **不报错**，子进程拿到字面量 `$VAR` 当 token；②`${A}${B}` 中 A 有值 B 无值 → `v2 != v` → **不报错**，token 里混进字面量 `${B}`；③任何以 `_FILE` 结尾的键都会被当密钥文件读，`SSL_CERT_FILE=/etc/ssl/cert.pem` 会被读成 PEM 内容塞进环境变量 | 读 `channels.py:55-61`：失败条件要求同时满足 `"$" in v2 and v2 == v and "${" in v` | 用"展开前后是否有未解析的 `$`"作判据；`_FILE` 改为显式白名单键名（如 `*_TOKEN_FILE`/`*_KEY_FILE`） |
| 🟡 | `quorum/gates.py:66-67` | 密钥进子进程环境（`os.environ.copy()` + `update(env)`），CONTRACT §一"密钥不进配置文件，也不进命令行参数（命令行会进 ps…）"只覆盖 argv，未覆盖同 uid 可读的环境 | 读 `gates.py:66-74` | 文档里把"同 uid 可读环境"写明；或对已知密钥键做 `env` 白名单 |
| 🟡 | `quorum/cli.py:61-62` + `quorum/config.py:111-114` | raw 日志 `stamp = "%Y-%m-%d"`，`run_with_timeout` 以 `"wb"` 打开 stderr → **当天第二次跑同一审核员，上一份 raw 被截断**。留档规则只覆盖"结论"，不覆盖 raw | 读 `cli.py:61-62`、`config.py:111-114`、`gates.py:71`。证据侧：`ls -la reviews/out/.raw` 每个审核员只有一份当天日志 | 沿用 `protect_existing`，或 stamp 精确到秒/HHMMSS |
| 🟡 | `quorum/cli.py:133-134` | `quorum plate --config x.yaml --dispose ledger.md`（裸文件名，按契约应相对 CWD 解析）→ `os.path.dirname("ledger.md") == ""` → `os.makedirs("", exist_ok=True)` 抛 `FileNotFoundError`，`main()` 只捕 `ConfigError`（`cli.py:243-245`），直接 traceback | 读 `cli.py:132-140` 与 `argparse` 的 `nargs="?"` 定义（`cli.py:218`） | `d = os.path.dirname(path); if d: os.makedirs(d, exist_ok=True)` |
| 🟡 | `demo/review.yaml:9-18` + `quorum/config.py:198-204` | **COI 校验的是标签，不是来源。** demo 三个审核员是**同一个通道、同一个脚本**（`argv: ["python3","channels/fake_reviewer.py"]`），只有 `FAKE_PERSONA` 与手写的 `family` 不同，却能产出"跨模型族一致 · 高置信"。同理，两个 reviewer 指向同一 `channel`（同 model）只要 `family:` 字符串不同即可全过 | 读 `demo/review.yaml:9-18`（`alpha/beta/gamma` 全部 `channel: fake`）；读 `config.py:198-208`（只比 `r.family` 字符串） | 加一条软校验：同一 `channel` + 同一 `model` 的多个 primary 给显眼告警；或要求 `family` 与 channel 的 `model` 建立映射表 |
| 🟡 | `quorum/plate.py:284-286` + `:228-230` | **位置列不转义竖线，而契约明确承诺 `\|`。** `dispose_skeleton` 只对 `problem` 做 `.replace("\|","\\\|")`，`location[:50]` 原样插入；`render` 的汇总行同样只转义 `headline()` | 读 `plate.py:228-230`（`c.rows[0].location[:50]` 未转义）与 `:284-286`。`ledger.parse` 依赖 `_split_row` 的列对齐（`ledger.py:57-61`），一格多一个竖线就会整行错列 | 两处 writer 都统一走一个 `_cell()` 转义函数 |
| 🟡 | `quorum/cli.py:63-65` + `quorum/plate.py:162-163` | 失败路径下 `protect_existing(out)` **已经**把上一次的好结论改名挪走，失败的 run 让 `out` 不存在 → `plate.collect` 静默跳过该审核员，只在表头留一句"缺：xxx" | 读 `cli.py:63-65`（先留档再跑）与 `plate.py:162-163`（空文本即跳过） | 失败时把 `.bak` 还原到 `out`，或让 plate 对"缺员"输出更显眼的一档 |
| 🟢 | `quorum/gates.py:237-242` | 死代码：`if not in_table: continue` 连续出现两次，第二次永不可达 | 读 `gates.py:237-242` | 删除 |
| 🟢 | `quorum/ledger.py:17` | `TODO_MARKS` 定义后从未使用 | `grep TODO_MARKS quorum/ledger.py` 仅命中定义行 | 删除，或真的用它区分 ⬜/❌/🚧 三档 |
| 🟢 | `README.md:76` / `CONTRACT.md:3` / `reviews/brief.md:27` | 体量说法不一致：`wc -l quorum/*.py` = **1579**（README"一千多行"✅）；工单写"约 1200 行"（✗）；作者 round-2 台账 row 16 记的是 1516（已过期） | `wc -l quorum/*.py` → 1579 total | 工单与台账里的硬数字改为现算或删掉 |
| 🟢 | `tests/test_quorum.py:35-44` | 弱断言：`cfg.repo == str(d.resolve()) or cfg.repo == str(d)` 两侧其实是同一路径的两种写法，`or` 是给 macOS `/var`↔`/private/var` 兜底的，实际几乎不区分任何行为 | 读测试源码 | 断言解析后的绝对路径 `os.path.realpath` 一致 |

### 第二节附 · §2.B 交叉表能被怎么打脸

**B-1 「该合的没合」**（结构性，不需实验）
- 合并的两个入口是 `(same_file and sc >= 0.07) or sc >= 0.10`（`plate.py:197`）。而 `_paths` 只保留 **basename**（`plate.py:30`），`PATH_RE` 只认 `py|md|json|jsonl|ya?ml|ipynb|sh|txt|toml|cfg`（`plate.py:23`）。于是一个 `.c` / `.bin` / 无扩展名的位置**连路径 token 都没有**，合并只能靠 0.10 的文字门槛；反过来，同一份数据在两个目录下（`train/data.jsonl` vs `test/data.jsonl`）会被当成同一个文件。**合并与否主要由"两位审核员是否恰好写了同一个文件名"决定，而不是由"说的是不是同一件事"决定。**
- 同一处缺陷被两家从两侧描述时（A 说 `report.md`、B 说 `metrics.py`）必然拆开——这是设计取舍，但工具没有把这种"因路径不同而拆开"的簇标出来，作者只能靠肉眼在 30+ 簇里找。

**B-2 「不该合的合了」**
- 簇的键**不含严重度**：🔴 与 🟢 只要同文件 + 7% 重叠即可同簇，`Cluster.severity` 取 `max`（`plate.py:125-127`）→ 一条 🟢 被提级成 🔴 汇报。
- **贪心 + 顺序依赖（可推演证明）**：设审核员 A 有 a1、a2（同文件），审核员 B 有 b1，且 `sim(b1,a1)=0.09`、`sim(b1,a2)=0.08`。若 A 的表里 a1 在前：b1 → 簇1（0.09+0.05=0.14 > 0.08+0.05=0.13）；若 a2 在前：b1 → 簇2。**同一批数据、只把 A 自己表里的两行对调，"跨模型族一致"就挂到了另一条结论上。** `cluster()` 是单趟贪心（`plate.py:188-208`），`score > best_score` 严格大于，平局由 `clusters` 的创建顺序决定。

**B-3 gamma 那条错的会不会进"高置信"簇？**
会。按 `collect` 的行序（reviewer 配置顺序 × 表内顺序）逐行推演：`alpha🔴`→C1；`alpha🟡`→C2（C1 已有 alpha）；`beta🔴`→C1（同 `report.md`，且 C1 不含 beta）；`beta🟡`（`build.py`，与 C2 不同文件、低相似）→C3；`gamma🔴`→C1（C1 不含 gamma，同文件）→ **C1 = {alpha🔴, beta🔴, gamma🔴}**；其余三条各自成簇。**总 5 簇**，与 e2e 期望的"跨模型族一致 + 单家独有 同时出现"一致。

- **label 是否误导**：`primary_families` 排除 cross（`plate.py:130-139`），C1 的 primary family 只有 vendor-a/vendor-b → "跨模型族一致 · 高置信"这句话本身**站得住**（gamma 是 cross）。
- **但汇总行误导**：汇总印的是 `"+".join(c.reviewers)` = `alpha+beta+gamma`（`plate.py:230`），读者数到三家；label 文案里没有一个字提示"仅 primary 计入"。而"一句话"取 `rows[0].problem` = alpha 的原话（`plate.py:152-153`），gamma 的错误归因被正确措辞盖住。
- **缓解措施够不够**：明细逐条列原话在，但 (a) 证据列在这份仓库的真实产物里**已经因 F1 全空**；(b) `disagreement` 的阈值落在同一条发现的相似度带里（F7），既可能误报也可能漏报。**结论：缓解措施不足以让读者发现"三家之一归因是错的"，需要人在明细里逐条读，而工具没有任何一处提示读者必须这么做。**

**B-4 「同一家的两条永远不合并」什么时候是错的**
1. **同一审核员把一件事拆成两行**（先写症状、后写根因；或既在"待复验声明"表又在"逐条发现"表写一遍）。规则假设"他自己分开写的就是两件事"（`plate.py:193` 注释），但它**没有去重**，也没有把两行标成"疑似同源"。
2. **更糟的连锁效应**：因为带该 reviewer 的簇会被跳过，他的重复行会**抢占**别家那条独占的匹配——例如 A 有 a1、a2（实为同一件事），B 有 b1（与 a2 更像）。贪心把它配到 a2 后，`a1` 变成"单家独有"。**结果是：一件真事同时产出一个"单家独有"（多余的复验负担）和一个"跨模型族一致"（配对对象还不是它的本意）。**
3. `dispose_skeleton` 按簇出行（`plate.py:283-286`）→ 台账里同一条缺陷出现两次，`verify` 也要跑两遍。

### 第二节附 · §2.C 在 quorum 自己身上找「门禁绿但材料错」（本轮增量）

作者的论断是：门禁检查的是**它自己定义的那个性质**，不是**读者以为的那个性质**。以下每一条都是这条论断在 quorum 自身上的实例：

1. **`gates.evaluate` 的绿 = "解析出了 ≥N 行含严重度标记的表行"**；读者读成"这份结论有 N 条真发现"。两个性质之间只有"8 字符"和"2000 字节"这两个极其廉价的桥（`gates.py:52-59`）。前轮 codex 已实测 `5 行 + 900 个句号 → PASSED=True`（转引 `reviews/out/round2/quorum-findings-codex.md:19`）；我按代码逐条核对三条件，构造同形产出确实全过。
2. **解析器的绿 = "表头第 0 格含「严重度」"**；读者读成"我的发现都被收进去了"。真相是**列会被静默丢**：工单模板自带的 `证据（命令/重算结果）` 因长度启发式被判出局（F1），三家真结论全部中招，而**没有任何一处输出提到这一点**。gate 不看证据列，所以照样全绿。
3. **`plate` 的「材料快照一致」= "三家结论头部抄了同一份基线"**；读者读成"三家审的是同一份材料"。`snap` 在循环外取一次（`cli.py:45`），这个告警因此**在单次 `run --all` 里不可能触发**（F2）。真正危险的情形——1 号审核员改写了材料，2/3 号审的是另一个状态——恰好是它唯一不会响的情形。
4. **「审核员只读」的唯一兜底是事后快照比对**（`channels.py:106` 自己这么写）；但比对结果只写进**结论正文的散文**（`cli.py:93-96`），而 `plate` 只消费头部机器标记（`plate.py:167-169`）。**控制措施产生了输出，却没有任何消费方**。且快照只覆盖 `sources`（`reviews/review.yaml:6` 就不含 `out/`、`.github/`、`examples/`、`LICENSE`），而结论文件正落在 `out/` 里——2 号审核员进程可以覆写 1 号的结论，快照看不见。
5. **`quorum verify` 的绿灯 = "没有一行 status=✅ 且 check 失败"**；读者读成"这个台账被验证过了"。当所有行都没填 check 时退出码是 **0**（F3 / `ledger.py:131-137`）。作者随仓发布的 `reviews/out/round2/quorum-dispose.md` 就是 43 行全空 check —— **这份仓库自带一份"通过"的、零验证的台账。**
6. **`check-leaks` 的绿灯 = "被跟踪的文本文件里，逐行正则没命中"**；读者读成"没有泄漏"。跳过条件（>4MB / NUL / 非 UTF-8）不打印，命中数被 `max_hits` 截断后当总数打印（F8），`--config` 失败被吞（F9）。这与 `docs/LESSONS.md` 里那个"三类形态的脱敏自检对着 585 处用户名打印『残留：无 ✓』"是**同一个形状**，只是这次是 quorum 自己。
7. **`--self-test` 的绿灯 = "每条规则能匹配作者给它写的样本"**；读者（和 README）读成"自检证明规则有效"。样本是作者自备的，过窄的正则照样通过（F10）；且不传目录时它扫描 0 个文件就直接 `return 0`。
8. **COI 的绿灯 = "primary 的 family 字符串互不相同"**；读者读成"这几家是不同厂商、盲区不重叠"。`family` 是自由文本，与 channel/model 无绑定（F19），demo 自己就是三个同通道同脚本的"三家"。
9. **e2e 的绿灯 = "输出里出现这两个词"**；读者读成"交叉表确实分辨出了一致与独有"。这两个词是固定样板（F4）。
10. **`--strict` 的存在本身就是一句自白**：作者知道默认档不证明什么，但 README 的头条示例、`run_demo.sh`、CI 走的都是**默认档**（`demo/run_demo.sh:14` 还加了 `|| true`）。

### 第二节附 · §2.D 反向证伪

**D1 LESSONS.md 的事故是否与规则对应**：逐条对着代码看，七条里六条对得上（内容优先于退出码 / 临时文件+留档 / 看门狗 / 快照进头部 / 自检从规则表派生 / 台账需断言——实现均在，且 `atomic_write`、`protect_existing`、`run_with_timeout`、`self_test`、`run_checks` 都能一一指到行号）。**一处夸大**：LESSONS 说"run 会在开始与结束时各取一次快照指纹，**写进结论头部**"——结束时那一次只在**不同**时才作为散文写进正文，且 git 模式下连大文件取样的免责声明都被丢掉（F14）。**一处错配**：`gates.evaluate` 的 docstring 自称"四道内容门"，实际 `passed` 只用三条，`marks` 不参与判定（F22/第一节 A2'）——规则讲的故事是"我们数了标记"，代码是"我们数了行数"。

**D2 demo 三个事故能否复现**（我实际算出的数字，未运行 make.py）：
- 事故一：`wc -l demo/project/data/answers.jsonl` = **100**，`pred_old.jsonl` = **41**；覆盖率 41/100 = **41.0%** ✅。准确率：把两文件按 `"` 切第 4/8 字段拼成 `id 标签` 后合并去重，`cat answers pred | cut -d'"' -f4,8 | wc -l` = **141**，`… | sort | uniq | wc -l` = **110** → 命中 **141−110 = 31** 条 → 31/41 = **75.61%**，对全集 31/100 = **31.0%** ✅。三个数字与 `demo/README.md` 逐位吻合，是**我自己重算的**。
- 事故二：`wc -c demo/project/report.md` = **101**；`cat` 全文只有 `# 评测报告` + METRICS 区块（区块外零正文）✅。
- 事故四（对照组门禁恒绿）：`cut -d'"' -f4 demo/project/data/pred_old.jsonl | sort -u | wc -l` = **41**，`head` = `q-000`，`tail` = `q-040`；answers 的 `tail` = `q-099` → `pred − ans = ∅` → `gate.py` 的 `sys.exit(0 if not extra else 1)` 恒为 0 ✅（结构上不可能红）。
- 事故三（PYTHONHASHSEED）：**我没能跑双种子**（见前置说明）。机制级核对：`demo/project/build.py:79-85` 是 `ids = {r["id"] for r in rows}` → `keys = list(ids)` → `rng.shuffle(keys)` → `dev = set(keys[:20])`；`list(set)` 的顺序由 `str.__hash__` 决定，而 CPython 默认 `PYTHONHASHSEED` 每进程随机化，故 `dev_ids` 必然随种子变。`Random(42)` 固定的是**洗牌算法**，洗的是**顺序已变的输入**。结论：机制成立，但我只做到"读代码 + 语言语义"这一级，**不是双种子实测**——这一条我按 🟡 计。

**D3 不可能失败的断言**：找到 **2 条**（另有 1 条弱断言）。
- `tests/test_quorum.py:309-310`：`assert "跨模型族一致" in text` / `assert "单家独有" in text` —— 两个串都在 `plate.py:247-248` 的固定"读法"样板里，与簇的实际构成无关。**F4。**
- `tests/test_quorum.py:112`：`assert "SECRET-VALUE" not in cfg_p.read_text()` —— 该文件是**测试自己**写入的，内容里只有密钥**路径**（`%s` % sec），断言在测试自己的写入上恒真，完全没碰被测的 `_resolve_env`。（作者 round-2 台账 row 11 已记，HEAD 未修。）
- `tests/test_quorum.py:44`：`assert cfg.repo == str(d.resolve()) or cfg.repo == str(d)` —— 弱断言，两侧同一路径。

**D4 check-leaks 能不能被绕过**：能，且有多条**不需要构造文件**的路径。
- 让扫描"通过"而实际失效：`quorum check-leaks --self-test`（不带目录）→ 打印"全部规则都能抓到自己种的样本，且不误伤安全文本"→ **exit 0**（`cli.py:190-192`）。扫描了 0 个文件。
- 让命中数看起来是 5：任何 >5 处的泄漏都印成"5 处（最多显示 5）"（`leaks.py:135-137,166`）。
- 让泄漏文件被跳过：把内容放到 >4MB 的文件、或带 BOM/NUL 的 UTF-16 文件（`_is_text` 三道门，`leaks.py:26-41`）——**不会打印任何"已跳过"**。
- 让自定义规则不生效而不报错：`--config` 指向一份坏 YAML → `except ConfigError: pass`（`cli.py:170-176`）→ 只剩默认规则，仍打印"未发现任何命中。"。
- 我自己做的正面核对：`git ls-files --cached --others --exclude-standard | tr '\n' '\0' | xargs -0 grep -nE '/Users/[A-Za-z0-9_.-]+|/home/[A-Za-z0-9_.-]+'` 只命中 `quorum/leaks.py:58`（即被 `FIXTURE_FILE` 豁免的那一行）→ 当前仓库在这条规则下**确实**是干净的。

### 第二节附 · §2.E 发布前风险

**现在能不能发布：不能，但差距不大。** 会让我反对发布的具体问题：
1. 工单模板自带的表头会打断自家解析器（F1）。这是"照文档做反而坏掉"的一类，公开后第一个使用者就会踩。
2. 仓库里自带的动作示范是一份 43 行零断言的台账，而默认 `verify` 对它打绿灯（F3）。发布出去等于把 README 的头条卖点自己证伪。
3. 承载这个卖点的 e2e 断言恒真（F4），CI 里又没有 `verify` 步骤，`run_demo.sh` 还 `|| true` 屏蔽退出码——**整个断言闭环没有任何一处被自动验证**。

**README「它不是什么」是否诚实**：基本诚实（"不保证审核员是对的"、"不是自动化裁判"、"单家独有必须人工复验"都写到了）。**该写而未写的三条**：① `claude-cli` 通道下"审核员只读"**不是控制措施**，事后快照只覆盖 `sources`、只写正文、且无消费方；② `verify` **默认档**对所有无断言台账返回 0，`--strict` 才进 CI；③ `family`/`model` 是配置里手写的标签，quorum 不校验实际应答的模型——本仓 `reviews/out/.raw/quorum-kimi-2026-10-01.log`（81 字节）全文只有 `[claude-code:unrecognized_model] {"model":"kimi-k2.7-code","query_source":"sdk"}`，同一形状的 qwen 日志 80 字节，而两次运行的 `quorum-review.log` 都记 `ok`。**CLI 不认识这个 model id，而流水线对这一事实零反应。**（我无法调 API 验证它是否回退到别的模型，所以只陈述"不识别 + 无校验"这个事实。）

**最容易被人挑毛病的三处**：① demo 的"三家"其实是同一个脚本印三份预设文件，`family` 是手写标签（`demo/review.yaml:9-18`）；② 自家台账 43 行 0 断言而 `verify` 绿灯；③ "四道门"实为三道 + 工单/台账/README 的体量数字互不一致（1579 / 约 1200 / 一千多）。

---

## 最脆弱的一环（前三）

1. **"发现条数"这一门的下游是同一个会静默丢列的解析器。** 门禁数的是解析出来的行数，解析器却会因表头长度启发式丢掉整列（F1）、因 `_looks_like_header` 吞掉数据行、因严重度不在 emoji 白名单里丢行——而**丢的过程零诊断**。绿灯为真，但它证明的不是"这份结论完整"，甚至不是"我读到了审核员写的每一行"。
2. **`verify` 默认档 = 全无断言时退出 0**（F3），而作者自己的 43 行台账正好是全无断言，CI 里也没有 `verify`，`run_demo.sh` 用 `|| true` 屏蔽。**"把 ✅ 变成可证伪的断言"这个核心承诺，在当前配置下的强制力为零。**
3. **"审核员只读"的唯一兜底（材料快照）有三重衰减**：基线只取一次使 plate 的告警结构性失效（F2）、耗时免责声明在 git 模式被丢（F14）、比对结果没有消费方（§C-4）。叠加"结论文件就落在被审 repo 内且不在 `sources` 里"，序号靠后的审核员可以覆写序号靠前的结论而无人察觉。

---

## 附录 · 我推翻的既有结论

**一、推翻工单自己的两处前提**
- 工单 §2.A.5 描述的"`(大小, mtime)` 取舍"是 **fa06c78 的旧实现**。`git diff fa06c78..HEAD -- quorum/snapshot.py` 显示 HEAD 已换成首尾各 64KB 的 `_sample_hash`。前轮 codex 的"两个 9MB 文件 digest 相同"与作者台账 row 4 因此**都已过期**（但**没被推翻掉全部风险**——担保声明在 git 模式被丢、exclude 无 glob，见 F13/F14）。
- 工单 §1 说 `quorum/*.py` "约 1200 行"。`wc -l quorum/*.py` = **1579**。

**二、推翻作者自己台账（`reviews/out/round2/quorum-dispose.md`）里已失效的 6 行**
以下在 `c0f0de9` 已修，台账却仍标 ⬜ —— 这是**反向的"台账未更新"（stale）**，恰好是 `ledger.py:48-49` 定义的那一档，而 `verify` 因为 check 列全空**连这一档都判不出来**：
- row 4（大文件按 mtime）→ 已改取样哈希（`snapshot.py:80-93`）
- row 5（`snapshot_exclude` 裸 startswith）→ 已改 `_excluded` 规范化比较（`snapshot.py:66-77`）；**但嵌套 `__pycache__` 仍无效**，此条只修了一半
- row 6（FAILED 产出被覆盖）→ 已加 `protect_existing`（`cli.py:106-107`）
- row 9（`tempfile.mktemp` 废弃）→ 已改 `mkstemp`（`cli.py:69-70`）
- row 14（`role` 无枚举校验）→ 已加校验（`config.py:167-170`）
- row 20（`test_e2e_material_change_is_flagged` 恒真）→ 测试已重写为真正制造材料变化（`tests/test_quorum.py:325-347`），此条**确实修好了**，我复验通过
- row 2（`--json` 丢 `disagreement`）→ 已补 `disagreement`/`primary_families`（`plate.py:269-270`）

**三、部分推翻作者对 row 18 的"修复"**
台账 row 18 记 `best.why` 的判断依据用错了变量。HEAD 把它从 `best_score > thr_text` 改成了 `same_file`（`plate.py:204`）——**但 `same_file` 是内层循环的泄漏变量**，属于"改了写法、没改性质"：`match_reason` 仍会印错理由，且 `best_score` 里的 `+0.05` 被当作原始相似度打印。**这条修复本身是新的 bug。**

**四、确认仍然活着、但结论被前轮低估的两条**
- row 11（`assert "SECRET-VALUE" not in cfg_p.read_text()` 恒真）与 row 22（`test_plate_snapshot_cannot_be_spoofed_by_body_text` 内联正则、从不调用 `plate.collect`）在 HEAD **依然成立**，我逐行复核。
- row 27（"模型族是配置字符串不是事实"）被列为 🟡，但它有**实物证据**：`reviews/out/.raw/quorum-kimi-2026-10-01.log` 全文 81 字节 = `[claude-code:unrecognized_model] …`，而 `reviews/out/quorum-review.log` 记 `kimi | ok`。**这一条应当升级为 🔴**：流水线对一个"CLI 不认识该模型"的事实完全无感，而整套置信度都建立在这个 model id 上。

**五、推翻 README 的一条隐含主张**
README:41-42 称 demo 的交叉表"让你看见同一处、不同结论"。**这一条按算法推演成立**（§B-3 给了逐行推演，且是 5 簇），但它**没有任何有效测试在守**——`test_e2e_demo_full_loop` 用来"证明"它的两条断言恒真（F4）。所以：声明为真，担保为假。
