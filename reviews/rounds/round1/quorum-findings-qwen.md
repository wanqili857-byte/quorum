# quorum · 独立复核结论 · qwen · 2026-10-01

> 工单: `brief.md` · 模型族: `qwen` · 角色: `primary` · 第一轮就用过的审核员
> 方式: 独立进程 headless（干净上下文，与作者会话无共享记忆）
> 材料快照：`git:033a3c067210`（git 仓库，工作区干净）
> ⚠️ **材料在审核期间发生变化**（git:033a3c067210 → git:033a3c067210+dirty:cf691a72cd09），结论可能对应中间的某个状态。

---
执行条件先说明：本会话的 Bash 权限门禁**拒绝执行任何 `python3`**（`python3 -c "print(1)"` 亦被拒），因此 `pytest`、`quorum run/plate/verify/check-leaks`、`cluster()` 实验、`PYTHONHASHSEED` 双种子**我一次都没跑成**。仓库内只读命令（`cat/ls/find/wc/grep/diff/sed/tr/paste/sort/uniq/expr`）与 `git` 可用。下文每条都标注了证据类型：【跑】=我执行的命令输出；【静态】=源码直读、未执行。**我没有把任何静态推理写成执行证据。**（`out/quorum-findings-kimi.FAILED-1230.md` 显示作者上一轮的真通道审核员撞的是同一堵墙。）

---

## 第一节 · 声明复验总表

| 声明 | 我复验到什么 | 判定 |
|---|---|---|
| A1 审核员只读、结论由 runner 落盘 | `codex-cli` 有 `-s read-only`（channels.py:85）**强制**；`claude-cli` 的 argv 只有 `claude -p <prompt> [--model M]`（channels.py:78-82），**没有任何只读/沙箱/工具白名单参数**。而作者真配置 `reviews/review.yaml` 的两个 primary 全走 `claude-cli`。只读性=工单措辞+外部 CLI 默认，quorum 本身没表达 | 🔴 不成立（就 claude-cli 而言） |
| A2 内容优先于退出码 / 四道内容门 | `evaluate`（gates.py:42-48）只有 3 个谓词，**不存在第 4 道「非空」门**（LESSONS.md 自称四道）。且 3 个谓词都可被「空洞但合规」的产出满足 | 🟡 存疑（可被满足，见 2-15） |
| A3 先临时文件、已有非空结论留档、原子落位 | `run` 路径做了（`protect_existing` + `atomic_write`）；**`plate --dispose` 没有**：cli.py:117 是裸 `open(path,"w")` —— 与 LESSONS.md 事故二的真因**同一个写法** | 🔴 不成立 |
| A4 密钥不进配置、不进命令行 | `X_FILE` 解析正确（channels.py:46-62），argv 干净，`--dry-run` 只打印键名。但密钥进**子进程环境**，macOS `ps -E`／Linux `/proc/<pid>/environ` 可读；`verify` 的 `bash -lc` 继承全量 env | 🟡 存疑（字面真、威胁模型不完整） |
| A5 材料快照指纹真能发现材料变化 | **git 仓库里 `sources` 与 `snapshot_exclude` 是死配置**：`take()` 在 `rev-parse HEAD` 成功时直接 return，`_tree()` 永不执行（snapshot.py:49-57）。且模式随环境静默翻转 | 🔴 不成立（对 git 仓库） |
| A6 同 family 不得有两个 primary，load() 报错 | 校验存在，但 `f != "unknown"` 把默认值排除（config.py:176），`family` 缺省即 `"unknown"`（config.py:145）→ **三个 primary 全不写 family 即可通过** | 🔴 不成立（硬约束名不副实） |
| A7 plate 只解析表头含「严重度」的表 | 实现是 `"严重度" in cells[0]`（gates.py:141）——**只认第 0 列**。换个写法整份结论被静默丢弃，而 `render` 的「已收结论」按文件是否存在判定（plate.py:172） | 🔴 不成立 |
| A8 verify 的四档语义 | 四档判定与代码一致（ledger.py:41-50）。默认下**全行无 check 的台账退出码 = 0**；`error` 档也返回 1，与 CONTRACT「LIE 是**唯一**不可接受的一档」措辞不符 | 🟡 存疑（0 是文档行为，但对 CI 无意义） |
| CONTRACT：cross 的结论不计入「跨模型族一致」 | **`role` 在 `plate.py` 与 `ledger.py` 里一次都没出现**（`grep -n "role"` 输出为空），`Row` 结构体无 role 字段。该规则**结构上无法实现** | 🔴 不成立 |
| demo 三个事故真能复现 | 事故二（正文被掏空）、事故三的**机制**成立；**事故一的数字不成立**（见 2-13） | 🔴 不成立（事故一） |
| README/CONTRACT「工具两百来行代码」 | `wc -l quorum/*.py` 合计 **1269 行** | 🔴 不成立 |
| brief「tests 20 个」 | `grep -c "^def test_"` = **21** | 🟢 |

---

## 第二节 · 逐条发现

| 严重度 | 位置 | 问题 | 证据 | 建议 |
|---|---|---|---|---|
| 🔴 | `quorum/cli.py:117` | **`plate --dispose` 原地截断处置台账**。`open(path,"w",...).write(...)`，既无 `protect_existing` 也无 `atomic_write`。默认路径就是 `out_dir/<project>-dispose.md`，即 `cfg.ledger` —— 用户填好的 `check`/`status`/`处置` 列被整份擦掉换成空骨架 | 【静态】cli.py:115-117；`demo/review.yaml` 的 `ledger: out/demo-dispose.md` 与骨架默认路径同一条。LESSONS.md 事故二自述真因正是「`open(p,"w")` 先截断」，此处同款代码复现 | 与 `run` 同等待遇：`protect_existing` → 临时文件 → `atomic_write` |
| 🔴 | `quorum/ledger.py:85-99` + `demo/ledger_example.md` | **`verify` 无法识别「装饰性断言」**——它只问「这条命令现在退 0 吗」，不问「把修复回滚它还退 0 吗」。作者自己的示例台账里就有两条装饰断言，其中一条产生**反向错判** | 【跑】第 2 行 `check: grep -q METRICS project/report.md`，`grep -c METRICS demo/project/report.md` = **2**（退出 0）→ 判 ✅ 已修；可 `wc -c demo/project/report.md` = **63**，`cat` 全文只有三行 METRICS 区块——正文一个字都没补。第 3 行 `check: grep -q 'sorted(' project/build.py` → `grep -n "sorted("` 只命中**第 13 行的 print**，病根第 7 行 `ids = {r["id"] for r in rows}` 原封不动 → 判 🟡「台账未更新（其实已经好了）」，而台账写的是「待办」——**判定与事实相反** | `check` 必须是**变异仍失败**的命令；或要求 `check` 里带一个「修复前失败」的见证 |
| 🔴 | `quorum/plate.py:104-116` | `Cluster.label()` 只看 `len(families)`，**不看 role**。`role: cross` 的审核员其 family 照常计入「跨模型族一致 · 高置信」 | 【跑】`grep -n "role" quorum/plate.py quorum/ledger.py` → 无输出。CONTRACT「cross 的结论不计入跨模型族一致」与代码直接冲突 | 实现 role 过滤，或删掉该契约句 |
| 🔴 | `quorum/config.py:145,176` | `family` 是配置里手写的自由字符串，是「跨模型族一致」与 COI 的**唯一依据**。COI 校验退化为「同一个人没有把同一个字符串写两遍」 | 【跑】`grep -n "role\|cross" quorum/plate.py` 空；【静态】`f != "unknown"` 排除默认值；`templates/review.yaml` 把 `codex-cli` 通道标成 `family: deepseek` —— 说明该字段无人校验、可任意填 | 至少校验 `channel.kind+model` 与 family 的一致性；或把「高置信」改名为「作者声明了 ≥2 个 family」 |
| 🔴 | `quorum/gates.py:43-47` | **门禁数的是「严重度标记个数」，不是「发现条数」。**标记出现在概述表里也算数 | 【跑】`grep -oE "🔴\|🟡\|🟢" demo/canned/alpha.md \| wc -l` = **3**，而 alpha 的发现行只有 **2** 行（第 2 行的 🔴 在第 1 节的复验总表里）。作者自己的日志 `demo/out/demo-review.log` 记的就是 `alpha \| ok \| 1212B · 严重度标记 3`。CONTRACT 又明说「概述表里的 🟡 不会被误当成一条发现」——plate 不误认，**门禁照样认** | 标记计数改为「只数严重度表内的行」——复用 `split_table_rows` |
| 🔴 | `quorum/gates.py:141` + `plate.py:172` | 表头「严重度」必须落在**第 0 列**。审核员写成 `\| # \| 严重度 \| 位置 \| … \|` 时整份结论**静默丢行**；同时 `render` 的「已收结论」只按 `os.path.exists` 判定，于是这份 0 贡献的结论**仍然显示为「已收」** | 【静态】gates.py:141 vs plate.py:172。两份真产出（`demo/out/demo-findings-*.md`）第 16 行都是 `\| 严重度 \| 位置 \| 问题 \| 证据 \| 建议 \|`，说明只要审核员加一列序号就会踩中 | 表头按「任一单元格含严重度」匹配；「已收结论」同时报出「解析到 N 条」 |
| 🔴 | `quorum/snapshot.py:49-57` | 在 **git 仓库**里 `sources` / `snapshot_exclude` **完全不生效**（`_tree()` 不可达）。同一个仓库，首个 commit 之前快照是 `tree:…`，之后变成 `git:HEAD`——**同一份材料、同一份配置，指纹算法随环境切换** | 【跑】`demo/out/demo-findings-alpha.md` 头部为 `> 材料快照：\`tree:288c0b049ac8\`（非 git，文件树指纹（10 个文件））`；`find demo/project demo/briefs demo/canned -type f \| wc -l` = **10**（我独立数出，与该行一致）；`git log --format='%h %ci'` 显示首次 commit 在 12:25:19，而该产物时间为 12:22——当时无 HEAD，故走 tree 分支 | git 模式也要把 `sources` 纳入（或至少在 git 模式下明确拒用这两个键，别让它们静默失效） |
| 🔴 | `quorum/plate.py:130-131` | 「材料快照一致」是从**审核员自己写的正文**里正则抠出来的（`材料快照：\`([^\`]+)\``，后匹配覆盖先匹配）。审核员只要在正文里写一行同格式文本，就能覆盖 runner 写在头部的真快照，从而**关掉 plate 的快照不一致告警** | 【跑】框架产出的头部格式见 `demo/out/demo-findings-alpha.md` 第 5 行；【静态】`collect()` 用 `re.finditer` 全篇扫描、循环赋值，末尾覆盖 | 快照改由 runner 落到独立 sidecar/`--json` 字段，不从正文回读 |
| 🔴 | `demo/project/report.md` + `demo/canned/{alpha,beta}.md` | **demo 事故一的数字不可复现。**报告里的 `41.0%` 与数据里任何一种算法都对不上 | 【跑】逐位对齐预测与答案：`paste -d' ' pred_old.jsonl answers.jsonl \| head -41 \| grep -oE '"(pred\|gold)": "[a-z]*"' \| tr -d '"' \| sed 's/^[a-z]*: //' \| paste -d' ' - - \| sort \| uniq -c` → `13 allow allow / 10 ask ask / 8 deny deny` + 10 组不一致 → **命中 31/41**；`expr 31 \* 1000 / 41` = **756‰（75.6%）**；若缺失按错算 `expr 31 \* 1000 / 100` = **310‰（31.0%）**。`41.0%` **只能**由 41/100（覆盖率）得到，不是任何口径的「严格命中」。而 alpha 写「用这 41 条重算恰好得 41.0，与区块逐位吻合」——**该证据句在数据上为假** | 让 `make.py` 从数据里真算一个准确率写进 report.md，否则这条「事故」是编的 |
| 🔴 | `demo/project/gate.py` / `demo/README.md` | demo 里**根本没有「数字能重算」这道门禁**，`gate.py` 只查「预测的 id ⊆ 答案的 id」。demo/README 却把事故一归因为「门禁检查的是这个数能不能算出来」——**这道门禁在 demo 里不存在** | 【跑】`cat demo/project/gate.py` 全文 11 行，只有 `extra = pred - ans` 一处判据；`demo/` 下无任何重算数字的脚本 | 补一个真的数字门禁进 demo，或把事故一改写成「无门禁时数字根本没人验」 |
| 🟡 | `quorum/gates.py:42-48` | 空洞但形式合规的产出可过门禁：≥2000 字节填充 + 5 个 `[中]`/🔴 + 全文任意位置出现子串「最脆弱」→ 全过，落成正式结论，且对交叉表贡献 0 条 | 【静态】三个谓词逐条对照：`len(text.encode()) >= 2000` ✓、`len(SEVERITY_RE.findall(text)) >= 5` ✓（`[中]` 也匹配）、`"最脆弱" not in text` 为假 ✓。`require_sections` 是全文子串匹配，不是章节位置匹配 | 加一道「必须解析出 ≥1 条发现行」的门 |
| 🔴 | `quorum/leaks.py:20-24,75-90` | `check-leaks` 的**可达性**没有门禁：只扫 `TEXT_EXT` 白名单里的扩展名，跳过 `SKIP_DIRS`。`.env/.csv/.log/.pem/.key/.xml/.sql/.bak` 一律不扫——**工具自己的原始转录 `out/.raw/*.log` 正好是 `.log`** | 【静态】leaks.py:20-24 列出扩展名，`.log` 不在其中；`ls out/.raw` = `quorum-kimi-2026-10-01.log`、`quorum-qwen-2026-10-01.log` | 白名单改黑名单 + 二进制嗅探；把默认忽略目录收窄到 `.git`/虚拟环境 |
| 🟡 | `quorum/channels.py:57-61` | 密钥进子进程环境；`verify` 的 `bash -lc` 又继承全量 env 并把台账里的任意字符串当 shell 执行 | 【静态】`subprocess.Popen(..., env=full_env)`（gates.py:57-61）、`subprocess.run(["bash","-lc", e.check], ...)`（ledger.py:92）。CONTRACT 给的威胁模型是「命令行会进 ps」，而 env 同样可被 `ps -E` 读出 | 文档里把 env 也写进威胁模型；`verify` 用 `bash -c` 且最小化 env |
| 🟡 | `quorum/gates.py:77-83` / `cli.py:56,92` | 「损坏一份已有结论比不产出更糟」只做了一半：留档动作发生在**跑之前**，若这一轮没过门禁，原来那份好结论已从规范路径消失（只剩 `.bak`），下游按 `out_path` 读的人会看到「没有结论」。另外 `.bak` 名只有 `HHMMSS`，同一秒内二次运行会 `shutil.move` 覆盖上一个备份 | 【跑】`ls demo/out` 可见 6 个 `.bak`，命名为 `…122254.bak`/`…122445.bak` 等秒级；【静态】`protect_existing` 在 `run_with_timeout` 之前调用（cli.py:56） | 留档移到「新结论确实落地之后」；`.bak` 加序号或毫秒 |
| 🟡 | `tests/test_quorum.py:70-77` | **恒真断言**：`assert "SECRET-VALUE" not in str(sec.parent / "review.yaml")` —— 断的是「某字符串不在一个**路径字符串**里」，而该路径下的文件测试根本没写过。这条断言任何实现下都不可能失败 | 【静态】`str(tmp_path/"review.yaml")` 是纯路径，不含密钥内容 | 改成真读文件：先 `load()` 那份临时配置，再断言文件正文里没有密钥 |
| 🟡 | `tests/test_quorum.py:213-215` | `assert "单家独有" in text` 的注释称「gamma 那条错误断言不该被算成一致」，但子串断言**无法区分** gamma 是否被并进第 1 簇；README 反而明说 gamma **会**被并进去。测试通过与否与它声称要守的性质无关 | 【跑】该断言只做全文子串匹配；【静态】`demo/out/demo-dispose.md` 第 1 行 = `跨模型族一致 · 高置信`，问题文本是 alpha 的措辞 | 断言改为「第 1 簇的 reviewers 集合」等可证伪的具体形状 |
| 🟡 | `README.md:76` / `CONTRACT.md:3` | 「工具本身只有两百来行」「工具是两百来行代码」 | 【跑】`wc -l quorum/*.py` 逐文件相加 = 6+111+222+180+160+122+127+240+101 = **1269** | 改成真实数字，或删掉这句自我描述 |
| 🟡 | `reviews/review.yaml:2,4` | 作者自用的真配置里 **工单路径不存在**。`repo: ..` 解析到仓库根，`brief: brief.md` 于是指向 `<仓库根>/brief.md` | 【跑】`ls brief.md` → `No such file or directory`；`ls reviews/brief.md` → 存在。工单实际躺在 `reviews/` 下 | `brief: reviews/brief.md`（或 `repo: .`）。顺带：`load()` 只校验键存在，从不校验路径可读——**没有任何门禁检查「输入」**，只检查「输出」 |
| 🟡 | `quorum/cli.py:115-116` | `quorum plate --config X --dispose myledger.md`（带文件名、无目录部分）会走 `os.makedirs(os.path.dirname("myledger.md"))` = `os.makedirs("")` → `FileNotFoundError` | 【静态】`argparse` 里 `--dispose` 是 `nargs="?"`（cli.py:191），传值即字符串；`os.path.dirname` 对无目录相对路径返回 `""` | 加 `if d: os.makedirs(d, exist_ok=True)` |
| 🟡 | `quorum/plate.py:137,141` | 阈值标定极薄：同文件阈值 0.07，跨文件 0.10，而同文件那条用的是 0.07——**比它自称的「不同条 ≤0.06」只高 0.01**。且标定样本未公开、无回归数据 | 【静态】plate.py:41-42 的自述与 137 行的签名对照 | 把标定样本与分数分布固化成测试，或改成可配置 + 输出每对候选的分数 |
| 🟢 | `quorum/snapshot.py:89-96` | 大文件（>8MB）只计 (大小, `int(mtime)`)：同尺寸 + 同秒内改动 → 指纹不变。取舍写进了 `detail`（仅当确有跳过时） | 【静态】`h.update(str(int(st.st_mtime)).encode())` | 至少把 mtime 提到纳秒，或在 detail 里常驻声明 |
| 🟢 | `quorum/plate.py:162` | `best.why` 记的是**最后一次**加入的匹配分数，且该分数含 `+0.05` 同文件加成——`match_reason` 里的「相似度」被系统性报高 0.05；单行簇 `why` 为空串 | 【静态】plate.py:155-162 | 只在严格更高时更新，且单独保留原始 `sc` |
| 🟢 | `quorum/cli.py:129-134` | 台账路径解析有三处回退（CWD → 配置目录 → repo），而 CONTRACT 写「路径语义（**唯一规则**，别猜）」 | 【静态】cli.py:128-134 | 要么统一语义，要么在 CONTRACT 里写明台账是例外 |

### 2.C · 在 quorum 自己身上找「门禁绿但材料错」（本节单列）

作者的论断是「门禁检查的是**它自己定义的那个性质**，不是**读者以为的那个性质**」。以下每一条都是 quorum 的绿灯**为真**、但它证明的事**不是**你以为的事。

1. **`check-leaks --self-test` 通过 ≠ 泄漏扫描有效（最强的一条）。**
   `self_test()`（leaks.py:96-111）只做两件事：把 `Pattern.sample` 这个**存在同一张规则表里的字符串**喂给该条的 `re.compile(p.regex)`，断言能匹配；再拿一句安全文本断言不误伤。它**从不调用 `scan()`**。
   于是：扩展名白名单漏掉的 `.env`、被 `SKIP_DIRS` 跳过的 `dist/`、被 `--ignore` 排除的文件——`--self-test` 一律报「全部规则都能抓到自己种的样本，且不误伤安全文本 ✓」。
   门禁定义的性质 =「每条正则认得我自己写下的那个样本」；读者以为的性质 =「泄漏扫描器是有效的」。**这正是 LESSONS.md 里「脱敏自检只查三类形态、对着 585 处用户名打印『残留：无 ✓』」的同一副骨架**——而 quorum 用来对付它的正是这条自检。

2. **`verify` 的 ✅ 检查的是「这条命令今天退 0」，不是「这个修复在库里」。**
   上文 2-2 已给出可执行反例：`grep -q METRICS` 退 0 而正文仍是 0 字。sell 点是「抓台账说谎」，但它把「装饰性断言」判成了 ✅。CONTRACT 自己写着「一份不能失败的检查等于装饰」——**quorum 没有任何机制能识别装饰**，而它的姊妹模块 `leaks` 偏偏有（种样本）。同一个仓库里，一个模块懂这个道理，另一个不懂。

3. **「跨模型族一致 · 高置信」检查的是「配置里出现了 ≥2 个不同 family 字符串」。**
   读者以为是「≥2 个独立模型谱系独立得出了同一结论」。`family` 是手写自由文本，无校验；`role` 被完全忽略；`codex-cli` 通道在模板里被标成另一个厂商的 family。把同一个模型起两次、写两个名字两个 family，即可产出「高置信」——**这个保证的强度等于配置作者的诚实度**。

4. **`min_severity_marks` 检查的是「🔴🟡🟢 出现几次」。**
   读者以为是「有几条发现」。可执行证据：alpha 的标记数 3、发现行数 2（第 1 节复验总表里的 🔴 被计入）。CONTRACT 专门承诺「概述表里的 🟡 不会被误当成一条发现」——**plate 守住了，门禁没守**。

5. **「已收结论：alpha, beta, gamma」检查的是「这三个文件存在」。**
   读者以为是「这三家的结论被解析进了这张表」。表头变一列即 0 条发现，而汇总行照旧显示三家齐全。

6. **「材料快照一致」检查的是「三份文本里最后出现的那串 `材料快照：\`…\`` 相同」。**
   读者以为是「三家审的是同一版材料」。而那串文本来自审核员的自由正文，审核员可写。

7. **`materials snapshot` 在 git 仓库里检查的是「HEAD + `git status --porcelain`」。**
   读者以为是「`sources` 列的文件没变」。两个后果：`sources`/`snapshot_exclude` 静默失效；且 `--porcelain` **折叠未跟踪目录**——【跑】`git status --porcelain` 只输出 `?? out/`，而 `out/` 下实际有 2 个文件、`out/.raw/` 还有 2 个。**未跟踪目录里改文件，指纹纹丝不动**，而工具自己的输出目录正好是未跟踪目录。

8. **COI 硬约束检查的是「同一个人没把同一个字符串写两遍」。**
   `family` 缺省为 `"unknown"` 且被排除在校验外——**把 `family` 全部删掉，任意多个 primary 全部放行**。CONTRACT 写的是「硬约束，不是建议」。

9. **`require_sections` 检查的是「全文含子串『最脆弱』」。**
   读者以为是「有『最脆弱的一环』这一节」。写在正文任意一句里即可。

10. **`--dry-run` 检查的是「argv 里没有密钥」。**
    读者以为是「这次运行不会把密钥暴露出去」。env 照常带密钥。

一句话：**这个工具有 8 处以上「绿灯为真、所指非实」，而 README 的「它不是什么」一节对这些只字未提。**

### 2.B · 交叉表能被怎么打脸

- **会被合进「跨模型族一致 · 高置信」吗——会。** 【跑】`cat demo/out/demo-dispose.md`：第 1 行就是 `跨模型族一致 · 高置信 | 🔴`，问题文本是 alpha 的措辞。gamma 那条（症状对、归因错）**确实在这一簇里**，且它的 `role: cross` 对 `label()` 毫无影响。汇总表因此给出的是**被一条已知错误断言抬高过的置信度**。
- **「逐条列原话」的缓解够不够——不够。** 该缓解只存在于 `plate` 的**明细**段落（plate.py:189-199）。**导出的处置台账没有这一列**：`dispose_skeleton` 只写 `c.headline()` = `rows[0].problem`（plate.py:118-119, 236-239），即**排序里第一个审核员的措辞**。台账才是下游真正被使用的工件——分歧在导出的那一刻就被抹掉了，只剩一个被抬高的置信度标签。
- **该合的没合（false split）**：`cluster()` 里 `if row.reviewer in c.reviewers: continue`（plate.py:151）以**审核员名字**为身份。同一模型挂两个名字即可绕过；而同一个审核员把同一根因写在两行（demo 里 alpha 的「分母缩水」与「正文被掏空」同属 `report.md`）**永远无法合并**，工具里也没有人工合并的入口。
- **不该合的合了（false merge）**：`_paths()` 只取**文件名**（plate.py:30 `m.rsplit("/",1)[-1]`）。`src/report.md` 与 `archive/report.md` 被判定「同文件」，门槛由 0.10 降到 0.07。任何两个不同目录里的同名文件都会触发这条折扣。
- **同一家永不合并这条规则错在哪**：它把「独立信源」等同于「审核员名字不同」。真正该判等的是 `channel + model`。现在只要在 `reviewers:` 里加一行同样的通道换个 `name` 和换个 `family`，两次同模型输出就构成「跨模型族一致 · 高置信」。（P0）

### 2.D · 反向证伪

- **LESSONS.md 的事故是不是事后编的故事**：事故二「`open(p,"w")` 先截断」在 `cli.py:117` **原样复现**——规则没有防住它自己的代码，这条至少是真的、且未被遵守。事故一「分母静默缩水」的机制在 demo 数据里成立（100 vs 41，【跑】`wc -l`），但**数字叙事不成立**（见 2-13）。「必须有超时看门狗」（gates.py:51-74）与「快照指纹」（snapshot.py）对应的事故我无法证伪也无法证实。
- **demo 三个事故能否真复现**：事故二 ✓（【跑】report.md 63 字节、仅 METRICS 区块）；事故三的**机制**✓（源码第 7 行确为 set），但其**证据形态**是 `sorted(dev)[:3]`——20 元素集合的 3 元素投影，两个不同的 dev 集合可以有相同的前三个 id。它「碰巧」不同，但展示的代理量并不能证明它要证明的东西（又一个「检查了代理性质」）。事故一 ✗。
- **PYTHONHASHSEED 双种子**：**未能执行**（`python3` 被权限门禁拒绝）。我能给的是静态结论：`ids = {r["id"] for r in rows}` 对 `str` 键的迭代顺序随进程哈希种子变化，`list(ids)` 顺序随之变化，固定种子的 `shuffle` 作用在不同顺序的输入上 → 输出集合不同。**这一条是推理，不是我的复现结果**，请按存疑处理。
- **永真断言**：`tests/test_quorum.py:77` 的 `"SECRET-VALUE" not in str(.../ "review.yaml")` —— 不可能失败（见 2-16）。另 `test_e2e_demo_full_loop:215` 的注释与断言不符（见 2-17）。
- **check-leaks 能否被绕过**：能，**靠扩展名与目录**：`.env`/`.csv`/`.log`/`.pem`/`.key`/`.xml`/`.sql`/`.bak` 不在 `TEXT_EXT`；`dist`/`build` 在 `SKIP_DIRS`。让 `--self-test` 通过而扫描失效的构造是平凡的：**新增一条规则并同时新增一个不在白名单里的载体文件**——自检只喂 `Pattern.sample`，永远看不到那个文件。我没有构造该文件（受只读约束），此处为源码直读。

---

## 最脆弱的一环（前三）

1. **`quorum verify` 无法区分「能失败的断言」与「装饰性断言」，而它自己的示例台账里就有两条装饰断言，其中一条产生反向错判。** 这是整个工具对外的核心卖点（「抓台账说谎」），却在作者自己交付的示例上失效；且反例只用 `grep`/`wc` 就能复现。姊妹模块 `leaks` 已经有「种样本证明能失败」的正确做法——不对称说明这不是能力问题，是这道门禁漏了。
2. **「跨模型族一致 · 高置信」的全部依据是一个无人校验的手写字符串 `family`，且 `role` 被实现层彻底忽略。** 保证强度 = 配置作者的诚实度；同模型双开即可伪造高置信，而 CONTRACT 承诺的 cross 不计入根本没写进代码。再叠加「导出的台账丢掉分歧、只留一个被抬高的标签」，误导链条是完整的。
3. **`plate --dispose` 原地截断处置台账，复刻 LESSONS.md 事故二的真因。** 一个把「不许原地覆盖」写进契约和文档的工具，在自己的第二条命令里就是 `open(path,"w")`。这一条的破坏是不可逆的（用户手写的 `check`/`status` 全部丢失）。

---

## 附录 · 我推翻的既有结论

1. **推翻 CONTRACT §一「同源模型可以当 cross，但它的结论不计入『跨模型族一致』」。** 站不住：`role` 在 `plate.py`/`ledger.py` 中零出现，`Row` 无该字段。规则结构上不可实现，而非实现有 bug。
2. **推翻 README/CONTRACT「工具两百来行代码」。** 站不住：`quorum/*.py` 共 1269 行（我逐文件相加）。
3. **推翻 demo/README 与 `canned/alpha.md`、`canned/beta.md` 中「用这 41 条重算恰好得 41.0，与区块逐位吻合」。** 站不住：逐位对齐后命中 31/41 = 75.6%；把缺失算错是 31.0%；`41.0%` 只是 41/100 的覆盖率。**这条「证据」在数据上是假的。**
4. **推翻 demo/README 中「事故一的门禁为什么绿：它检查的是『这个数字能不能从数据算出来』」。** 站不住：`demo/project/gate.py` 全文 11 行只做 id 包含判断，demo 里不存在任何重算数字的门禁。
5. **推翻 brief 工单自身的一处描述**：「直接调 `quorum/plate.py` 的 `cluster()` 做实验」——本会话 `python3` 被权限门禁拒绝，该实验未执行；本节 §2.B 的结论来自源码直读 + 工具既有产物的比对，**不是**调用 `cluster()` 的结果。请把 §2.B 的阈值相关判断按「静态」而非「复现」采信。
6. **推翻 README「它不是什么」一节的完备性**：该节只承认「不保证审核员对」与「不是自动化裁判」两类**概念**局限，对本文列出的 8 处「绿灯所指非实」、`family` 不可验证、`check` 不可验证、扫描器可达性、env 可见密钥、快照随环境切换——**全部未提**。

（本次复核未修改、未新建仓库内任何文件；`git status --porcelain` 仍为会话开始时的 `?? out/`。）
