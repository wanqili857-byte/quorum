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

SEVERITY_RE = re.compile(r"🔴|🟡|🟢|\[高\]|\[中\]|\[低\]")

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

    def summary(self) -> str:
        if self.blocked:
            return ("%dB · 审核员疑似**卡住**（未产出发现，输出里有环境/权限类措辞）· rc=%d · %ds"
                    % (self.size, self.rc, self.seconds))
        return ("%dB · 发现 %d 条（标记 %d）· 缺章节 %s · rc=%d · %ds"
                % (self.size, self.findings, self.marks,
                   self.missing_sections or "无", self.rc, self.seconds))


def evaluate(cfg: Config, text: str, rc: int, seconds: int) -> GateResult:
    """四道内容门。

    ⚠️ **数的是解析出来的发现条数，不是 emoji 出现次数。** 旧版数 emoji，于是
    「概述表里的 30 个 🔴 + 一句『最脆弱』+ 一堆句号」能凑出一份『合规』的空产出。
    标记数只作为附注保留在结果里。
    """
    rows = split_table_rows(text)
    # 只数**有实质内容**的发现：problem 列至少 8 个字符。
    # 旧版只堵死了 emoji 刷屏，没堵死「表里塞 30 行空话」——那同样是空产出。
    rows = [r for r in rows if len(r[2].strip()) >= 8]
    marks = len(SEVERITY_RE.findall(text))
    missing = [s for s in cfg.gates.require_sections if s not in text]
    passed = (len(text.encode()) >= cfg.gates.min_bytes
              and len(rows) >= cfg.gates.min_findings
              and not missing)
    low = text.lower()
    blocked = (not passed) and len(rows) == 0 and any(m.lower() in low for m in BLOCKED_MARKERS)
    return GateResult(passed, len(text.encode()), marks, missing, rc, seconds,
                      findings=len(rows), blocked=blocked)


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
    """已有非空结论 → 先留档，返回留档路径（空串表示无需留档）。"""
    if os.path.exists(path) and os.path.getsize(path) > 0:
        keep = "%s.%s.bak" % (path, datetime.now().strftime("%H%M%S"))
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
        "> 工单: `%s` · 模型族(声明): `%s` · 角色: `%s` · 通道: `%s`%s"
        % (cfg.brief, r.family, r.role, r.channel, (" · " + r.label) if r.label else ""),
        "> 方式: 独立进程 headless（干净上下文，与作者会话无共享记忆）",
        snapshot_line,
        "<!-- quorum:snapshot %s -->" % _snap_digest(snapshot_line),
    ]
    if extra:
        lines.append("> %s" % extra)
    lines += ["", "---", ""]
    return "\n".join(lines)


def atomic_write(path: str, text: str) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


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
    """若这行像表头则返回 {列名: 下标}，否则 {}。"""
    m: Dict[str, int] = {}
    for i, c in enumerate(cells):
        key = c.strip("*` ").strip()
        for want in COLUMN_NAMES:
            # 列名后面常带修饰（`严重度（🔴🟡🟢）`、`证据（命令/重算结果）`）——放宽到 +14
            if key.startswith(want) and len(key) <= len(want) + 14:
                m.setdefault(want, i)
    return m if len(m) >= 2 and "严重度" in m else {}


def _looks_like_header(cells: List[str]) -> bool:
    return bool(_header_map(cells))


def split_table_rows(text: str) -> List[Tuple[str, str, str, str]]:
    """从结论里抽出 (严重度, 位置, 问题, 证据)。交叉表与处置台账都用它。

    **按列名映射，不按位置**：输出契约规定的是列名（严重度/位置/问题/证据），
    审核员在左边加一列 `#` 是完全合理的写法——旧版按位置取，遇到这种写法会整份静默丢行。

    只认**表头含「严重度」的那张表**，避免把概述表也当成发现。
    """
    rows: List[Tuple[str, str, str, str]] = []
    in_table = False
    idx: Dict[str, int] = {}

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
        if not SEVERITY_RE.search(sev):
            continue
        rows.append((sev, pick(cells, "位置"), pick(cells, "问题"), pick(cells, "证据")))
    return rows


def severity_of(sev: str) -> int:
    if "🔴" in sev or "[高]" in sev:
        return 3
    if "🟡" in sev or "[中]" in sev:
        return 2
    return 1
