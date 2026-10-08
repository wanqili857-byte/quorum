"""门禁：判一份审核结论「能不能算数」。

三条从实战里换来的规则（`docs/LESSONS.md` 有完整来龙去脉）：

1. **内容优先于退出码。** 进程退出码描述的是进程，不是材料。我们真实吃过：
   两份结构完整、内容齐全的结论因为收尾时收到 SIGTERM（rc=143）被判「失败」而改名。
2. **损坏一份已有结论，比不产出更糟。** 结论一律先写临时文件、四门全过再原子落位；
   已有非空结论先自动留档，绝不原地覆盖。（我们在测试看门狗时截断过一份真结论。）
3. **必须有超时看门狗。** 没有它，「审核员挂了」与「审核员还在想」在外部看起来完全一样。
   （我们真实吃过：一次连接死等，空跑 5 小时。）
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Tuple

from .config import Config

SEVERITY_RE = re.compile(r"🔴|🟠|🟡|🟢|\[严重\]|\[高\]|\[中\]|\[低\]")

# 严重度**单元格**专用的放宽版：这一格只可能是档位本身，所以允许**不带方括号**的中文档位。
#
# 为什么不直接放宽上面那个：`SEVERITY_RE` 还被用来在**全文**里数标记
# （`marks = len(SEVERITY_RE.findall(text))`，见「概述表凑合规」那条防线）。
# 往它里面加裸的「中」「高」，会把「中国」「集中」「提高」全算成严重度标记，
# 那条防线当场失效 —— 两个用途的精度要求相反，必须分开。
#
# 实测（quant 第 2 轮，2026-10-08）：工单写「严重度用 高/中/低 三档」，
# 三家就老老实实写裸的 `高`/`中`/`低`，于是 `SEVERITY_RE.search(sev)` 全不匹配，
# **11 行发现全被 `dropped_severity` 丢掉**（表头倒是认出来了）。同一个错第 1 轮也犯过。
SEVERITY_CELL_RE = re.compile(r"🔴|🟠|🟡|🟢|严重|高|中|低")

# 「审核员卡住了」与「审核员交了个差结论」在门禁看来长得一样，但处置完全不同：
# 前者要你解封权限/换通道再跑，后者要重写工单或换模型。这里给前者一个可识别的信号。
BLOCKED_MARKERS = ("requires approval", "need a decision", "需要你", "需要授权", "无法执行",
                   "permission denied", "command not allowed", "I cannot proceed",
                   "blocked", "sandbox")


@dataclass
class GateResult:
    passed: bool
    size: int
    marks: int
    missing_sections: List[str]
    rc: int
    seconds: int
    findings: int = 0
    blocked: bool = False
    hint: str = ""          # 未过门禁时的可操作诊断（「为什么是 0 条」）

    def summary(self) -> str:
        if self.blocked:
            return ("%dB · 审核员疑似**卡住**（未产出发现，输出里有环境/权限类措辞）· rc=%d · %ds"
                    % (self.size, self.rc, self.seconds))
        base = ("%dB · 发现 %d 条（标记 %d）· 缺章节 %s · rc=%d · %ds"
                % (self.size, self.findings, self.marks,
                   self.missing_sections or "无", self.rc, self.seconds))
        return base + ("　→ " + self.hint if self.hint else "")


def evaluate(cfg: Config, text: str, rc: int, seconds: int) -> GateResult:
    """四道内容门。

    ⚠️ **数的是解析出来的发现条数，不是 emoji 出现次数。** 旧版数 emoji，于是
    「概述表里的 30 个 🔴 + 一句『最脆弱』+ 一堆句号」能凑出一份『合规』的空产出。
    标记数只作为附注保留在结果里。
    """
    stats: Dict[str, int] = {}
    rows_all = split_table_rows(text, stats)
    dropped = stats.get("dropped_severity", 0)
    # 只数**有实质内容**的发现：problem 列至少 8 个字符。
    # 旧版只堵死了 emoji 刷屏，没堵死「表里塞 30 行空话」——那同样是空产出。
    rows_problem = [r for r in rows_all if len(r[2].strip()) >= 8]
    # ⚠️ **位置与证据列也必须有内容**（2026-10-02，luna 独立发现；kimi 的同类观察在同一处）。
    # 旧版只量「问题」列的长度，于是
    #     | 🔴 |  | 这一行的问题描述凑够了八个字 |  |
    # 是一张**能过门禁的空表**：没有任何可核实的东西，却拿走了绿灯。
    # 工单的硬约束写着「每条必须带『我怎么查出来的』」，而门禁从来没查过那一列——
    # 这正是这个工具反复讲的那件事：**门禁检查的是它自己定义的性质，不是读者以为的那个性质。**
    #
    # **但只在「那一列被认出来了」时才要求**：列名认不出来时位置列会整列为空，
    # 那种情形下丢发现是错的（缺的是信息，不是结论）——见 test_row_alias 的那条测试。
    _need_loc = bool(stats.get("has_位置"))
    _need_ev = bool(stats.get("has_证据"))
    rows = [r for r in rows_problem
            if (not _need_loc or r[1].strip()) and (not _need_ev or r[3].strip())]
    hollow = len(rows_problem) - len(rows)
    marks = len(SEVERITY_RE.findall(text))
    missing = [s for s in cfg.gates.require_sections if s not in text]
    passed = (len(text.encode()) >= cfg.gates.min_bytes
              and len(rows) >= cfg.gates.min_findings
              and not missing)
    low = text.lower()
    blocked = (not passed) and len(rows) == 0 and any(m.lower() in low for m in BLOCKED_MARKERS)
    # 0 条发现时，说清是**哪一种 0**——否则使用者只看到「发现 0 条」，
    # 不知道该怎么改（真实事故：审核员交了 21KB 有内容的结论，全是标题式，
    # 被解析成 0 条，整轮白跑）。
    hint = ""
    if not passed and not rows and not blocked:
        if rows_problem:
            hint = ("有严重度表、问题列也够长，但有 %d 行的**「位置」或「证据」列是空的**"
                    "——按空话处理。工单要求每条带「我怎么查出来的」" % hollow)
        elif rows_all:
            hint = "有严重度表，但每行「问题」列不足 8 字，按空话处理"
        elif "|" in text and "严重度" in text:
            hint = ("看着像严重度表却没解析出任何行——检查表头是否含「严重度」列、"
                    "以及是不是 Markdown 表格（分隔行要写 |---|）")
        elif "严重度" in text:
            # 真实事故：21KB 有内容的结论全写成 `### F1 · …`，被判 0 条整轮白跑
            hint = ("「严重度」出现在正文里但**不是表格**——门禁按列名解析 Markdown 表格，"
                    "标题式结论（`### F1 …`）会被判 0 条。工单的输出契约已写明要表格")
        else:
            hint = "未解析到任何发现行"
    # **过了门禁也要出声**：列名对不上不会让门禁失败，只会让交叉表的「位置」列
    # 静默变空——实测 25 行全空、零报错，而交叉表正是按位置对齐的，位置空了对齐
    # 就退化成纯文本相似度。hint 在 summary() 里只要非空就会打印，与过没过门禁无关。
    # **丢行必须可见**：严重度标记认不出时旧版静默跳过整行，于是「发现 8 条」
    # 可以其实是 17 条——工具少报一半还判 ok（canonbench 第二轮实测：工单写
    # 🔴/🟠/🟡/🟢，正则不认 🟠，46 条只进来 30 条）。这条与过没过门禁无关，
    # 所以放在 hint 里由 summary() 无条件打印。
    if dropped:
        warn2 = ("另有 %d 行看着是发现行，但严重度列没有可识别的标记，已丢弃"
                 "（认：%s）。门禁不受影响，但**条数与交叉表都少算了**"
                 % (dropped, SEVERITY_RE.pattern.replace("|", " / ")))
        hint = (hint + "；" + warn2) if hint else warn2
    if rows and not any(r[1] for r in rows):
        warn3 = ("发现 %d 条，但「位置」列全空——表头里那一列的名字没被认出来"
                 "（认：%s）。不挡门禁，但交叉表按位置对齐会退化"
                 % (len(rows), " / ".join(COLUMN_ALIASES["位置"])))
        hint = (hint + "；" + warn3) if hint else warn3
    if hollow and rows:
        warn4 = ("另有 %d 行的「位置」或「证据」列是空的，已按空话丢弃——"
                 "它们看着像发现，但没有任何可核实的东西" % hollow)
        hint = (hint + "；" + warn4) if hint else warn4
    return GateResult(passed, len(text.encode()), marks, missing, rc, seconds,
                      findings=len(rows), blocked=blocked, hint=hint)


def run_with_timeout(argv: List[str], env: Dict[str, str], timeout_s: int,
                     stdout_path: str, stderr_path: str, cwd: str = "") -> int:
    """起进程 + 看门狗。返回退出码（信号也算，由调用方判断是否影响「内容」）。

    ``cwd`` 一律传**项目根**：审核员的工作目录就是被审项目本身。
    （也顺带让配置里的相对路径与命令行参数在任何 CWD 下都成立。）"""
    full_env = os.environ.copy()
    full_env.update(env)
    with open(stdout_path, "wb") as so, open(stderr_path, "wb") as se:
        proc = subprocess.Popen(argv, stdout=so, stderr=se, stdin=subprocess.DEVNULL,
                                env=full_env, cwd=cwd or None)
        deadline = time.time() + timeout_s
        while proc.poll() is None:
            if time.time() > deadline:
                with open(stderr_path, "ab") as f:
                    f.write(("\n[看门狗] 超过 %ds 未返回，杀掉 pid %d\n" % (timeout_s, proc.pid)).encode())
                proc.kill()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    pass
                return -9
            time.sleep(0.5)
        return proc.returncode


def protect_existing(path: str) -> str:
    """已有非空结论 → 先留档，返回留档路径（空串表示无需留档）。

    ⚠️ 留档名带秒级时间戳，**同一个名字被占用时要往后找一个空的**（2026-10-02，luna 独立发现）。
    旧版直接 `shutil.move(path, keep)` —— 同一秒内对同一个 path 调用两次时，
    第二次的目标 `.bak` 已经存在，`shutil.move` 会**静默覆盖**掉第一份留档。
    也就是说：**用来防丢东西的那一步，自己会丢东西。**

    这不是纯理论：`run` 里失败产出的路径带 `%H%M%S`，而一个**立刻失败**的通道
    （凭据错、CLI 没装）在一秒内跑完两轮是可能的。留档是最后一道防线，
    它不该有一个「偏偏在最需要它的时候失效」的窗口。
    """
    if os.path.exists(path) and os.path.getsize(path) > 0:
        stamp = datetime.now().strftime("%H%M%S")
        keep = "%s.%s.bak" % (path, stamp)
        n = 1
        while os.path.exists(keep):          # 绝不覆盖已有留档
            n += 1
            keep = "%s.%s-%d.bak" % (path, stamp, n)
        shutil.move(path, keep)
        return keep
    return ""


def _snap_digest(snapshot_line: str) -> str:
    import re as _re
    m = _re.search(r"`([^`]+)`", snapshot_line or "")
    return m.group(1) if m else "unknown"


def header(cfg: Config, reviewer_name: str, snapshot_line: str, extra: str = "") -> str:
    r = cfg.reviewer(reviewer_name)
    lines = [
        "# %s · 独立复核结论 · %s · %s" % (cfg.project, reviewer_name, datetime.now().strftime("%Y-%m-%d")),
        "",
        # 两个来源轴都记进头部。vendor 是**声明**（工具验证不了），harness 是**事实**；
        # 事后有人要核对「这三家『不同源』到底是不是真的」，读这一行。
        "> 工单: `%s` · 模型来源(声明): `%s` · agent 框架: `%s` · 角色: `%s` · 通道: `%s`%s"
        % (cfg.brief, r.vendor, r.harness, r.role, r.channel,
           (" · " + r.label) if r.label else ""),
        "> 方式: 独立进程 headless（干净上下文，与作者会话无共享记忆）",
        snapshot_line,
        "<!-- quorum:snapshot %s -->" % _snap_digest(snapshot_line),
    ]
    if extra:
        lines.append("> %s" % extra)
    lines += ["", "---", ""]
    return "\n".join(lines)


_TMP_SEQ = 0        # 临时文件名的进程内序号，见 atomic_write


def atomic_write(path: str, text: str) -> None:
    """先写临时文件再 `os.replace` —— 中途崩了不会留下一份半截的结论。

    ⚠️ 临时名带 pid 与一个进程内计数器（2026-10-02，luna 独立发现旧版是固定的
    `path + ".tmp"`）。固定名在**同一路径被并发写**时会互相踩：两个写入者打开同一个
    临时文件、交叉写进去，`os.replace` 落位的是一份**两份内容交错**的文件——
    而那比没有结论更糟，因为它看起来是一份正常结论。
    """
    global _TMP_SEQ
    _TMP_SEQ += 1
    tmp = "%s.tmp.%d.%d" % (path, os.getpid(), _TMP_SEQ)
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):              # 写失败/替换失败时别留垃圾
            try:
                os.unlink(tmp)
            except OSError:
                pass


def log(cfg: Config, reviewer: str, result: GateResult, label: str) -> None:
    """记账：唯一入口。失败也要记（否则失败会从账上消失）。"""
    os.makedirs(cfg.out_dir_abs, exist_ok=True)
    with open(cfg.log_path(), "a", encoding="utf-8") as f:
        f.write("%s | %s | %s | %s | %s\n" % (
            datetime.now().strftime("%Y-%m-%d %H:%M"), cfg.project, reviewer,
            "ok" if result.passed else "FAILED", result.summary() + ((" | " + label) if label else "")
        ))


def read_text(path: str) -> str:
    if not os.path.exists(path):
        return ""
    return open(path, encoding="utf-8", errors="replace").read()


COLUMN_NAMES = ("严重度", "位置", "问题", "证据", "建议")

# 列名**别名**：契约规定的名字是「位置/证据」，但工单骨架是人写的，写法差别很大。
# 实测（canonbench 第二轮）：工单表头写的是
# `| # | 文件:行 | 问题 | 具体失败场景 | 严重度 | 怎么查出来的 |`，
# 于是 25 条发现的「位置」**全空且一声不吭**，交叉表按位置对齐直接退化。
# 这类写法是合理的——工具该认，不是让作者去改自己的习惯。
#
# 实测（quant 第 2 轮，2026-10-08）：工单表头写的是
# `| 严重度 | 声明编号 | 发现 | 我怎么查出来的——附可复跑命令 |`。
# `_header_map` 要求**至少两个**列名被认出（且含「严重度」），这三列当时一个都认不出
# ——「声明编号」「发现」不在表里，而「我怎么查出来的…」以「我」开头，
# 别名走 `startswith("怎么查出来的")` 也匹配不上。**于是只认出 1 列 → 判为不是表头
# → 整份 13KB 的审核被算成 0 条发现**，还打出「看着像严重度表却没解析出任何行」这种
# 指错方向的提示（提示让人去查「表头有没有严重度列」，而严重度那列一直是好的）。
# 「声明编号」映射到「位置」是有意的：交叉表按它对齐，同一编号（D1/D2…）的发现正好该并排。
COLUMN_ALIASES = {
    "严重度": ("严重度", "severity", "等级", "级别"),
    "位置": ("位置", "文件:行", "文件", "路径", "location", "file",
             "声明编号", "编号", "声明", "条目"),
    "问题": ("问题", "issue", "problem", "发现", "结论"),
    "证据": ("证据", "怎么查出来的", "查证", "复现", "命令", "evidence",
             "我怎么查出来的"),
    "建议": ("建议", "fix", "suggestion"),
}


def clip_cell(s: str, n: int) -> str:
    r"""把一段文本裁成 n 字符以内，用作 markdown 表格的单元格。

    两件事一起做，**顺序不能反**：

    1. 转义 `|` —— 否则它会变成列分隔符，把一行劈成两行。
    2. 裁断时**不许切进代码段** —— 若第 n 个字符正好落在一个反引号代码段内部，
       裁完就是**未闭合的反引号**；而 `_split_row` 按 markdown 规则把代码段内的
       `|` 当字面竖线，于是它一路吞掉后面的分隔符。

    真实事故：一条 headline 里 `` `--top `` 正好跨过第 100 个字符，生成出来的
    **8 列的行被切成 5 格**，`status` / `check` 落到别的格子里 —— 那一行明明填了 ✅，
    `verify` 却报「无断言」。看报告的人会以为是自己没填。
    """
    s = str(s or "").replace("|", "\\|")
    if len(s) <= n:
        return s
    t = s[:n]
    if t.count("`") % 2:                     # 截断点落在代码段内 → 回退到该代码段之前
        t = t[:t.rfind("`")]
    return t


def _split_row(line: str) -> List[str]:
    r"""按 markdown 规则切单元格：`\|` 是字面竖线，**反引号代码段内的 `|` 也不是分隔符**。

    踩过：审核员在单元格里内嵌了一张表格（``审核员写成 `| # | 严重度 | 位置 |` ``），
    朴素的 `split("|")` 把它切成一堆碎块，反而让这一行**看起来像表头**，
    于是列映射被冲掉、后面整段发现被静默丢弃。LLM 审核员很少会记得转义竖线。
    """
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|") and not body.endswith("\\|"):
        body = body[:-1]
    cells: List[str] = []
    buf: List[str] = []
    in_code = False
    i = 0
    while i < len(body):
        ch = body[i]
        if ch == "\\" and i + 1 < len(body):
            buf.append(body[i + 1])
            i += 2
            continue
        if ch == "`":
            in_code = not in_code
            buf.append(ch)
            i += 1
            continue
        if ch == "|" and not in_code:
            cells.append("".join(buf))
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    cells.append("".join(buf))
    return [c.strip() for c in cells]


def _header_map(cells: List[str]) -> Dict[str, int]:
    """若这行像表头则返回 {规范列名: 下标}，否则 {}。

    匹配走**别名表**（`COLUMN_ALIASES`），返回的键一律是规范名——
    下游 `pick(cells, "位置")` 因此不必知道审核员那列叫什么。
    """
    m: Dict[str, int] = {}
    for i, c in enumerate(cells):
        key = c.strip("*` ").strip()
        for canon, aliases in COLUMN_ALIASES.items():
            for want in aliases:
                # 列名后面常带修饰（`严重度（🔴🟡🟢）`、`证据（命令/重算结果）`）——放宽到 +14
                if key.startswith(want) and len(key) <= len(want) + 14:
                    m.setdefault(canon, i)
                    break
    return m if len(m) >= 2 and "严重度" in m else {}


def _looks_like_header(cells: List[str]) -> bool:
    return bool(_header_map(cells))


def split_table_rows(text: str, stats: Dict[str, int] = None) -> List[Tuple[str, str, str, str]]:
    """从结论里抽出 (严重度, 位置, 问题, 证据)。交叉表与处置台账都用它。

    **按列名映射，不按位置**：输出契约规定的是列名（严重度/位置/问题/证据），
    审核员在左边加一列 `#` 是完全合理的写法——旧版按位置取，遇到这种写法会整份静默丢行。

    只认**表头含「严重度」的那张表**，避免把概述表也当成发现。

    `stats` 传入字典时回填被丢弃的行数（`dropped_severity`）——**丢行必须能被看见**：
    实测（canonbench 第二轮）严重度正则不认 🟠，而工单明写「严重度用 🔴/🟠/🟡/🟢」，
    于是 46 条发现只解析出 30 条，其中一家 17 条只进了 8 条，**门禁照样判 ok**。
    工具少报一半而说自己 ok，比报错更糟。
    """
    rows: List[Tuple[str, str, str, str]] = []
    in_table = False
    idx: Dict[str, int] = {}
    dropped = 0

    def pick(cells: List[str], *names: str) -> str:
        for n in names:
            i = idx.get(n)
            if i is not None and i < len(cells):
                return cells[i]
        return ""

    for line in text.splitlines():
        s = line.strip()
        if not s.startswith("|"):
            in_table = False
            idx = {}
            continue
        cells = _split_row(line)
        if len(cells) < 3:
            continue
        # 表头判定必须**严**：至少两个列名，且该单元格本身很短。
        # 踩过：数据行里出现「严重度」三个字（例如正文引用了这个列名）会被误判成表头，
        # 于是列映射被冲掉、后面整段发现被静默丢弃（实测一份 23 条发现的结论只解析出 4 条）。
        if not in_table or _looks_like_header(cells):
            hdr = _header_map(cells)
            if hdr:
                in_table = True
                idx = hdr
                # ⚠️ 记下**哪些列名被认出来了**。调用方要拿它区分两件截然不同的事：
                #   「列名没认出来」→ 信息缺失，**发现不能丢**（见 test_row_alias 那条测试）
                #   「列认出来了、格子空着」→ 这一行是**空的**，不该算发现
                # 不区分的话，两种都会变成「位置为空」。2026-10-02 的处置里踩过这个坑：
                # 第一版直接按「位置/证据为空就丢」，把前者一起误伤了。
                if stats is not None:
                    for col in ("位置", "证据"):
                        if col in idx:
                            stats["has_" + col] = 1
                continue
        if not in_table:
            continue
        if set("".join(cells)) <= set("-: "):
            continue
        if not in_table:
            continue
        if "严重度" not in idx:
            continue
        sev = pick(cells, "严重度")
        if not SEVERITY_CELL_RE.search(sev):
            # 看着像发现行却没有可识别的严重度标记——**记数，别静默扔**
            if len(cells) >= 3 and any(c.strip() for c in cells[1:]):
                dropped += 1
            continue
        rows.append((sev, pick(cells, "位置"), pick(cells, "问题"), pick(cells, "证据")))
    if stats is not None:
        stats["dropped_severity"] = dropped
    return rows


def severity_of(sev: str) -> int:
    """档位 → 序数。带方括号的、emoji 的、**裸中文的**都认（见 SEVERITY_CELL_RE）。

    裸中文这条是 2026-10-08 补的：工单写「用 高/中/低」，审核员照写，而这里只认 `[高]`。
    判定顺序从高到低；「严重」与「高」同档。
    """
    s = sev or ""
    if "🔴" in s or "严重" in s or "高" in s:
        return 4
    if "🟠" in s:
        return 3
    if "🟡" in s or "中" in s:
        return 2
    return 1
